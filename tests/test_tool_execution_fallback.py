"""Tool execution fallback policy and orchestration integration tests."""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.orchestrator import ModelClient
from contextual_orchestrator.server import SecurityConfig, build_server
from contextual_orchestrator.tool_fallback import (
    ToolExecutionError,
    ToolFallbackAction,
    ToolFallbackStoppedError,
    ToolFailureKind,
    classify_tool_failure,
)


@pytest.mark.parametrize(
    ("error", "expected_kind", "expected_action"),
    [
        (
            RuntimeError("Tool execute_command not found in agent strix"),
            ToolFailureKind.TOOL_NOT_FOUND,
            ToolFallbackAction.FAILOVER_AGENT,
        ),
        (
            RuntimeError("unknown tool: execute_command"),
            ToolFailureKind.TOOL_NOT_FOUND,
            ToolFallbackAction.FAILOVER_AGENT,
        ),
        (
            RuntimeError("MCP tool server unavailable"),
            ToolFailureKind.TOOL_UNAVAILABLE,
            ToolFallbackAction.FAILOVER_AGENT,
        ),
        (
            RuntimeError("tool arguments failed schema validation"),
            ToolFailureKind.INVALID_ARGUMENTS,
            ToolFallbackAction.FAIL_CLOSED,
        ),
        (
            PermissionError("tool permission denied"),
            ToolFailureKind.PERMISSION_DENIED,
            ToolFallbackAction.FAIL_CLOSED,
        ),
        (
            RuntimeError("sandbox denied by policy"),
            ToolFailureKind.POLICY_BLOCKED,
            ToolFallbackAction.FAIL_CLOSED,
        ),
        (
            RuntimeError("too many requests from tool service"),
            ToolFailureKind.RATE_LIMITED,
            ToolFallbackAction.FAILOVER_AGENT,
        ),
        (
            RuntimeError("tool command returned non-zero exit status 2"),
            ToolFailureKind.EXECUTION_FAILED,
            ToolFallbackAction.FAIL_CLOSED,
        ),
        (
            RuntimeError("provider produced an unfamiliar failure"),
            ToolFailureKind.UNKNOWN,
            ToolFallbackAction.FAILOVER_AGENT,
        ),
    ],
)
def test_text_failures_map_to_bounded_actions(
    error: BaseException,
    expected_kind: ToolFailureKind,
    expected_action: ToolFallbackAction,
) -> None:
    decision = classify_tool_failure(error)
    assert decision.kind is expected_kind
    assert decision.action is expected_action
    assert decision.reason_code == f"tool_failure.{expected_kind.value}.{expected_action.value}"


def test_wrapped_missing_tool_error_is_classified_from_cause_chain() -> None:
    cause = RuntimeError("Tool execute_command not found in agent strix")
    wrapper = RuntimeError("agent invocation failed")
    wrapper.__cause__ = cause
    decision = classify_tool_failure(wrapper)
    assert decision.kind is ToolFailureKind.TOOL_NOT_FOUND
    assert decision.action is ToolFallbackAction.FAILOVER_AGENT


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("tool timed out"),
        socket.timeout("tool deadline exceeded"),
        urllib.error.URLError("tool connection reset"),
    ],
)
def test_transient_idempotent_tool_failures_retry_same_agent(error: BaseException) -> None:
    decision = classify_tool_failure(error, idempotent=True)
    assert decision.action is ToolFallbackAction.RETRY_SAME_AGENT
    assert decision.retry_safe is True
    assert decision.circuit_failure is True


def test_non_idempotent_timeout_fails_closed_for_ambiguous_outcome() -> None:
    decision = classify_tool_failure(TimeoutError("tool timed out"), idempotent=False)
    assert decision.kind is ToolFailureKind.AMBIGUOUS_OUTCOME
    assert decision.observed_kind is ToolFailureKind.TIMEOUT
    assert decision.action is ToolFallbackAction.FAIL_CLOSED
    assert decision.retry_safe is False
    assert decision.circuit_failure is False


def test_explicit_unknown_outcome_overrides_other_structured_failure_metadata() -> None:
    error = ToolExecutionError(
        "connection reset after dispatch",
        tool_name="send_message",
        kind=ToolFailureKind.TRANSPORT_ERROR,
        idempotent=True,
        outcome_unknown=True,
    )
    decision = classify_tool_failure(error)
    assert decision.kind is ToolFailureKind.AMBIGUOUS_OUTCOME
    assert decision.observed_kind is ToolFailureKind.TRANSPORT_ERROR
    assert decision.action is ToolFallbackAction.FAIL_CLOSED


def test_structured_idempotent_execution_failure_can_fail_over() -> None:
    error = ToolExecutionError(
        "command failed",
        tool_name="inspect_repository",
        kind=ToolFailureKind.EXECUTION_FAILED,
        idempotent=True,
    )
    decision = classify_tool_failure(error)
    assert decision.action is ToolFallbackAction.FAILOVER_AGENT
    assert decision.retry_safe is False


def test_tool_execution_error_rejects_invalid_metadata() -> None:
    with pytest.raises(ValueError, match="tool_name"):
        ToolExecutionError("bad", tool_name="")
    with pytest.raises(TypeError, match="kind"):
        ToolExecutionError("bad", tool_name="run_command", kind="timeout")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="idempotent"):
        ToolExecutionError(
            "bad",
            tool_name="run_command",
            idempotent="yes",  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match="outcome_unknown"):
        ToolExecutionError(
            "bad",
            tool_name="run_command",
            outcome_unknown="maybe",  # type: ignore[arg-type]
        )


def test_classifier_requires_explicit_boolean_idempotency() -> None:
    with pytest.raises(TypeError, match="idempotent"):
        classify_tool_failure(RuntimeError("tool failed"), idempotent=1)  # type: ignore[arg-type]


def test_generic_provider_timeout_is_not_misclassified_as_tool_replay() -> None:
    cause = TimeoutError("provider read timeout")
    wrapper = RuntimeError("provider request failed")
    wrapper.__cause__ = cause
    decision = classify_tool_failure(wrapper)
    assert decision.kind is ToolFailureKind.UNKNOWN
    assert decision.action is ToolFallbackAction.FAILOVER_AGENT


class _ScriptedToolClient(ModelClient):
    """Return or raise scripted outcomes by agent id."""

    def __init__(self, scripts: dict[str, list[object]]) -> None:
        super().__init__(max_retries=0)
        self.scripts = {agent_id: list(outcomes) for agent_id, outcomes in scripts.items()}
        self.calls: list[str] = []

    def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
        del messages, temperature
        self.calls.append(agent.id)
        outcome = self.scripts[agent.id].pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return str(outcome)


def _orchestrator(
    client: ModelClient,
    *,
    tool_retry_attempts: int = 1,
    tool_retry_backoff_seconds: float = 0.0,
) -> TaskOrchestrator:
    agents = [
        ModelAgent("primary_worker", "mock", tags=("reasoning", "writing"), priority=5),
        ModelAgent("backup_worker", "mock", tags=("reasoning", "writing"), priority=1),
    ]
    return TaskOrchestrator(
        agents,
        client=client,
        tool_retry_attempts=tool_retry_attempts,
        tool_retry_backoff_seconds=tool_retry_backoff_seconds,
    )


def test_exact_strix_missing_tool_failure_falls_back_to_backup_agent() -> None:
    client = _ScriptedToolClient(
        {
            "primary_worker": [RuntimeError("Tool execute_command not found in agent strix")],
            "backup_worker": ["recovered"],
        }
    )
    orchestrator = _orchestrator(client)
    result = orchestrator.route_once([{"role": "user", "content": "scan this repository"}])
    assert result["answer"] == "recovered"
    assert result["trace"][0]["served_agent_id"] == "backup_worker"
    assert result["trace"][0]["failover_from"] == "primary_worker"
    assert client.calls == ["primary_worker", "backup_worker"]
    event = orchestrator.list_recent_audit_events()[0]
    assert event["event_type"] == "tool_fallback_decision"
    assert event["event_detail"] == {
        "agent_id": "primary_worker",
        "action": "failover_agent",
        "failure_kind": "tool_not_found",
        "reason_code": "tool_failure.tool_not_found.failover_agent",
        "retry_attempt": 0,
    }


def test_idempotent_timeout_retries_same_agent_before_failover() -> None:
    client = _ScriptedToolClient(
        {
            "primary_worker": [
                ToolExecutionError(
                    "read timed out",
                    tool_name="inspect_repository",
                    kind=ToolFailureKind.TIMEOUT,
                    idempotent=True,
                ),
                "primary recovered",
            ],
            "backup_worker": ["unused"],
        }
    )
    orchestrator = _orchestrator(client, tool_retry_attempts=1)
    result = orchestrator.route_once([{"role": "user", "content": "inspect repository"}])
    assert result["answer"] == "primary recovered"
    assert "served_agent_id" not in result["trace"][0]
    assert client.calls == ["primary_worker", "primary_worker"]
    assert orchestrator._circuit == {}


def test_exhausted_safe_retry_then_fails_over_once() -> None:
    timeout = ToolExecutionError(
        "read timed out",
        tool_name="inspect_repository",
        kind=ToolFailureKind.TIMEOUT,
        idempotent=True,
    )
    client = _ScriptedToolClient(
        {
            "primary_worker": [timeout, timeout],
            "backup_worker": ["backup recovered"],
        }
    )
    orchestrator = _orchestrator(client, tool_retry_attempts=1)
    result = orchestrator.route_once([{"role": "user", "content": "inspect repository"}])
    assert result["answer"] == "backup recovered"
    assert client.calls == ["primary_worker", "primary_worker", "backup_worker"]
    events = list(reversed(orchestrator.list_recent_audit_events()))
    assert [event["event_detail"]["action"] for event in events] == [
        "retry_same_agent",
        "failover_agent",
    ]
    assert events[-1]["event_detail"]["reason_code"] == (
        "tool_failure.timeout.failover_agent"
    )


def test_non_idempotent_ambiguous_failure_stops_without_backup_or_secret_leak() -> None:
    client = _ScriptedToolClient(
        {
            "primary_worker": [
                ToolExecutionError(
                    "request may have completed token=super-secret-value",
                    tool_name="send_message",
                    kind=ToolFailureKind.TRANSPORT_ERROR,
                    outcome_unknown=True,
                )
            ],
            "backup_worker": ["must not run"],
        }
    )
    orchestrator = _orchestrator(client)
    with pytest.raises(ToolFallbackStoppedError) as raised:
        orchestrator.route_once([{"role": "user", "content": "send this message"}])
    assert raised.value.decision.kind is ToolFailureKind.AMBIGUOUS_OUTCOME
    assert raised.value.agent_id == "primary_worker"
    assert "super-secret-value" not in str(raised.value)
    assert client.calls == ["primary_worker"]
    event_detail = orchestrator.list_recent_audit_events()[0]["event_detail"]
    assert event_detail["failure_kind"] == "ambiguous_outcome"
    assert event_detail["observed_failure_kind"] == "transport_error"


def test_invalid_arguments_stop_without_poisoning_agent_circuit() -> None:
    client = _ScriptedToolClient(
        {
            "primary_worker": [
                ToolExecutionError(
                    "schema validation failed",
                    tool_name="execute_command",
                    kind=ToolFailureKind.INVALID_ARGUMENTS,
                )
            ],
            "backup_worker": ["must not run"],
        }
    )
    orchestrator = _orchestrator(client)
    with pytest.raises(ToolFallbackStoppedError):
        orchestrator.route_once([{"role": "user", "content": "run malformed command"}])
    assert orchestrator._circuit == {}
    assert client.calls == ["primary_worker"]


@pytest.mark.parametrize("value", [-1, True, 1.5, "1"])
def test_tool_retry_attempts_requires_nonnegative_integer(value: object) -> None:
    client = _ScriptedToolClient({"primary_worker": ["unused"], "backup_worker": ["unused"]})
    with pytest.raises(ValueError, match="tool_retry_attempts"):
        _orchestrator(client, tool_retry_attempts=value)  # type: ignore[arg-type]


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://tool.example/run", code, "error", None, None)


@pytest.mark.parametrize(
    ("code", "expected_kind"),
    [
        (429, ToolFailureKind.RATE_LIMITED),
        (408, ToolFailureKind.TIMEOUT),
        (504, ToolFailureKind.TIMEOUT),
        (502, ToolFailureKind.TRANSPORT_ERROR),
        (503, ToolFailureKind.TRANSPORT_ERROR),
        (400, ToolFailureKind.INVALID_ARGUMENTS),
    ],
)
def test_http_tool_failures_are_classified_by_status(
    code: int,
    expected_kind: ToolFailureKind,
) -> None:
    decision = classify_tool_failure(_http_error(code), idempotent=True)
    assert decision.kind is expected_kind


def test_idempotent_rate_limit_retries_same_agent() -> None:
    error = ToolExecutionError(
        "rate limited",
        tool_name="inspect_repository",
        kind=ToolFailureKind.RATE_LIMITED,
        idempotent=True,
    )
    decision = classify_tool_failure(error)
    assert decision.action is ToolFallbackAction.RETRY_SAME_AGENT
    assert decision.retry_safe is True


def test_unstructured_ambiguous_outcome_fails_closed() -> None:
    decision = classify_tool_failure(RuntimeError("request may have completed"))
    assert decision.kind is ToolFailureKind.AMBIGUOUS_OUTCOME
    assert decision.action is ToolFallbackAction.FAIL_CLOSED


def test_generic_provider_failure_preserves_legacy_cross_agent_failover() -> None:
    client = _ScriptedToolClient(
        {
            "primary_worker": [RuntimeError("provider unavailable")],
            "backup_worker": ["legacy recovered"],
        }
    )
    result = _orchestrator(client).route_once(
        [{"role": "user", "content": "ordinary route"}]
    )
    assert result["answer"] == "legacy recovered"
    assert client.calls == ["primary_worker", "backup_worker"]


def test_all_generic_provider_failures_keep_existing_terminal_error_shape() -> None:
    client = _ScriptedToolClient(
        {
            "primary_worker": [RuntimeError("primary down")],
            "backup_worker": [RuntimeError("backup down")],
        }
    )
    with pytest.raises(RuntimeError, match="all 2 candidate agents failed for role=worker"):
        _orchestrator(client).route_once(
            [{"role": "user", "content": "ordinary route"}]
        )


def test_unrecognized_tool_specific_failure_keeps_legacy_agent_failover() -> None:
    decision = classify_tool_failure(RuntimeError("tool emitted an odd failure"))
    assert decision.kind is ToolFailureKind.UNKNOWN
    assert decision.action is ToolFallbackAction.FAILOVER_AGENT

@pytest.mark.parametrize(
    ("code", "expected_kind", "expected_action"),
    [
        (400, ToolFailureKind.INVALID_ARGUMENTS, ToolFallbackAction.FAIL_CLOSED),
        (401, ToolFailureKind.PERMISSION_DENIED, ToolFallbackAction.FAIL_CLOSED),
        (403, ToolFailureKind.PERMISSION_DENIED, ToolFallbackAction.FAIL_CLOSED),
        (404, ToolFailureKind.TOOL_NOT_FOUND, ToolFallbackAction.FAILOVER_AGENT),
        (405, ToolFailureKind.TOOL_UNAVAILABLE, ToolFallbackAction.FAILOVER_AGENT),
        (406, ToolFailureKind.INVALID_ARGUMENTS, ToolFallbackAction.FAIL_CLOSED),
        (407, ToolFailureKind.PERMISSION_DENIED, ToolFallbackAction.FAIL_CLOSED),
        (408, ToolFailureKind.TIMEOUT, ToolFallbackAction.RETRY_SAME_AGENT),
        (409, ToolFailureKind.EXECUTION_FAILED, ToolFallbackAction.FAILOVER_AGENT),
        (410, ToolFailureKind.TOOL_UNAVAILABLE, ToolFallbackAction.FAILOVER_AGENT),
        (411, ToolFailureKind.INVALID_ARGUMENTS, ToolFallbackAction.FAIL_CLOSED),
        (412, ToolFailureKind.INVALID_ARGUMENTS, ToolFallbackAction.FAIL_CLOSED),
        (413, ToolFailureKind.INVALID_ARGUMENTS, ToolFallbackAction.FAIL_CLOSED),
        (414, ToolFailureKind.INVALID_ARGUMENTS, ToolFallbackAction.FAIL_CLOSED),
        (415, ToolFailureKind.INVALID_ARGUMENTS, ToolFallbackAction.FAIL_CLOSED),
        (416, ToolFailureKind.INVALID_ARGUMENTS, ToolFallbackAction.FAIL_CLOSED),
        (417, ToolFailureKind.INVALID_ARGUMENTS, ToolFallbackAction.FAIL_CLOSED),
        (422, ToolFailureKind.INVALID_ARGUMENTS, ToolFallbackAction.FAIL_CLOSED),
        (423, ToolFailureKind.POLICY_BLOCKED, ToolFallbackAction.FAIL_CLOSED),
        (424, ToolFailureKind.EXECUTION_FAILED, ToolFallbackAction.FAILOVER_AGENT),
        (425, ToolFailureKind.TRANSPORT_ERROR, ToolFallbackAction.RETRY_SAME_AGENT),
        (426, ToolFailureKind.TOOL_UNAVAILABLE, ToolFallbackAction.FAILOVER_AGENT),
        (428, ToolFailureKind.INVALID_ARGUMENTS, ToolFallbackAction.FAIL_CLOSED),
        (429, ToolFailureKind.RATE_LIMITED, ToolFallbackAction.RETRY_SAME_AGENT),
        (431, ToolFailureKind.INVALID_ARGUMENTS, ToolFallbackAction.FAIL_CLOSED),
        (451, ToolFailureKind.POLICY_BLOCKED, ToolFallbackAction.FAIL_CLOSED),
        (500, ToolFailureKind.EXECUTION_FAILED, ToolFallbackAction.FAILOVER_AGENT),
        (501, ToolFailureKind.TOOL_UNAVAILABLE, ToolFallbackAction.FAILOVER_AGENT),
        (502, ToolFailureKind.TRANSPORT_ERROR, ToolFallbackAction.RETRY_SAME_AGENT),
        (503, ToolFailureKind.TRANSPORT_ERROR, ToolFallbackAction.RETRY_SAME_AGENT),
        (504, ToolFailureKind.TIMEOUT, ToolFallbackAction.RETRY_SAME_AGENT),
        (507, ToolFailureKind.TRANSPORT_ERROR, ToolFallbackAction.RETRY_SAME_AGENT),
        (508, ToolFailureKind.EXECUTION_FAILED, ToolFallbackAction.FAILOVER_AGENT),
        (511, ToolFailureKind.PERMISSION_DENIED, ToolFallbackAction.FAIL_CLOSED),
        (505, ToolFailureKind.UNKNOWN, ToolFallbackAction.FAILOVER_AGENT),
    ],
)
def test_http_tool_statuses_map_to_safe_actions(
    code: int,
    expected_kind: ToolFailureKind,
    expected_action: ToolFallbackAction,
) -> None:
    decision = classify_tool_failure(_http_error(code), idempotent=True)
    assert decision.kind is expected_kind
    assert decision.action is expected_action


def test_wrapped_http_permission_error_fails_closed() -> None:
    wrapper = RuntimeError("agent invocation failed")
    wrapper.__cause__ = _http_error(403)
    decision = classify_tool_failure(wrapper, idempotent=True)
    assert decision.kind is ToolFailureKind.PERMISSION_DENIED
    assert decision.action is ToolFallbackAction.FAIL_CLOSED


def test_non_idempotent_http_execution_error_fails_closed() -> None:
    decision = classify_tool_failure(_http_error(500), idempotent=False)
    assert decision.kind is ToolFailureKind.EXECUTION_FAILED
    assert decision.action is ToolFallbackAction.FAIL_CLOSED


@pytest.mark.parametrize("code", [502, 503, 504])
def test_non_idempotent_http_transport_uncertainty_fails_closed(code: int) -> None:
    decision = classify_tool_failure(_http_error(code), idempotent=False)
    assert decision.kind is ToolFailureKind.AMBIGUOUS_OUTCOME
    assert decision.action is ToolFallbackAction.FAIL_CLOSED


def test_exception_cause_cycle_is_bounded() -> None:
    error = RuntimeError("provider failure")
    error.__cause__ = error
    decision = classify_tool_failure(error)
    assert decision.kind is ToolFailureKind.UNKNOWN
    assert decision.action is ToolFallbackAction.FAILOVER_AGENT


def test_tool_marker_beyond_eight_exception_links_is_ignored() -> None:
    root = RuntimeError("outer provider failure")
    current = root
    for index in range(7):
        following = RuntimeError(f"wrapper {index}")
        current.__cause__ = following
        current = following
    current.__cause__ = RuntimeError(
        "Tool execute_command not found in agent strix"
    )
    decision = classify_tool_failure(root)
    assert decision.kind is ToolFailureKind.UNKNOWN
    assert decision.action is ToolFallbackAction.FAILOVER_AGENT


def test_provider_auth_failure_without_tool_evidence_keeps_provider_failover() -> None:
    cause = urllib.error.HTTPError(
        "https://provider.example/v1/chat/completions",
        401,
        "Unauthorized",
        {},
        None,
    )
    wrapper = RuntimeError("provider request failed")
    wrapper.__cause__ = cause
    decision = classify_tool_failure(wrapper)
    assert decision.kind is ToolFailureKind.UNKNOWN
    assert decision.action is ToolFallbackAction.FAILOVER_AGENT


def test_idempotent_retries_wait_with_exponential_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    delays: list[float] = []
    monkeypatch.setattr(
        "contextual_orchestrator.orchestrator.time.sleep",
        delays.append,
    )
    first = ToolExecutionError(
        "read timed out",
        tool_name="inspect_repository",
        kind=ToolFailureKind.TIMEOUT,
        idempotent=True,
    )
    second = ToolExecutionError(
        "read timed out again",
        tool_name="inspect_repository",
        kind=ToolFailureKind.TIMEOUT,
        idempotent=True,
    )
    client = _ScriptedToolClient(
        {
            "primary_worker": [first, second, "recovered"],
            "backup_worker": ["unused"],
        }
    )
    orchestrator = _orchestrator(
        client,
        tool_retry_attempts=2,
        tool_retry_backoff_seconds=0.25,
    )
    result = orchestrator.route_once(
        [{"role": "user", "content": "inspect repository"}]
    )
    assert result["answer"] == "recovered"
    assert delays == [0.25, 0.5]


@pytest.mark.parametrize(
    "value",
    [-0.1, True, float("inf"), float("-inf"), float("nan"), "0.1"],
)
def test_tool_retry_backoff_requires_finite_nonnegative_number(value: object) -> None:
    client = _ScriptedToolClient(
        {"primary_worker": ["unused"], "backup_worker": ["unused"]}
    )
    with pytest.raises(ValueError, match="tool_retry_backoff_seconds"):
        _orchestrator(
            client,
            tool_retry_backoff_seconds=value,  # type: ignore[arg-type]
        )


def _post_fallback_json(
    port: int,
    payload: dict[str, object],
) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "authorization": "Bearer secret_token",
            "content-type": "application/json",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def test_http_fail_closed_tool_error_has_dedicated_contract() -> None:
    error = ToolExecutionError(
        "request may have completed token=must-not-leak",
        tool_name="send_message",
        kind=ToolFailureKind.TRANSPORT_ERROR,
        outcome_unknown=True,
    )
    client = _ScriptedToolClient(
        {
            "primary_worker": [error],
            "backup_worker": ["must not run"],
        }
    )
    orchestrator = _orchestrator(client)
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token="secret_token"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post_fallback_json(
            server.server_address[1],
            {
                "model": "mock",
                "mode": "route",
                "messages": [{"role": "user", "content": "send this message"}],
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 409
    error_body = body["error"]
    assert error_body["code"] == "tool_execution_stopped"
    assert error_body["detail"]["failure_kind"] == "ambiguous_outcome"
    assert error_body["detail"]["observed_failure_kind"] == "transport_error"
    assert "must-not-leak" not in json.dumps(body)


class _StoppedStreamingClient(ModelClient):
    """Raise a structured fail-closed decision from the live stream path."""

    def stream_chat(self, agent: ModelAgent, messages: list, **kwargs: object):  # type: ignore[override]
        del messages, kwargs
        decision = classify_tool_failure(
            ToolExecutionError(
                "request may have completed token=must-not-leak",
                tool_name="send_message",
                kind=ToolFailureKind.TRANSPORT_ERROR,
                outcome_unknown=True,
            )
        )
        raise ToolFallbackStoppedError(agent.id, decision)
        yield ""  # pragma: no cover


def test_stream_fail_closed_tool_error_emits_structured_sse() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent("primary_worker", "mock", tags=("reasoning", "writing"))],
        client=_StoppedStreamingClient(max_retries=0),
    )
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token="secret_token"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
        data=json.dumps(
            {
                "model": "mock",
                "mode": "route",
                "stream": True,
                "messages": [{"role": "user", "content": "send this message"}],
            }
        ).encode("utf-8"),
        headers={
            "authorization": "Bearer secret_token",
            "content-type": "application/json",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            status = response.status
            body = response.read().decode("utf-8")
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200
    assert '"code": "tool_execution_stopped"' in body
    assert '"failure_kind": "ambiguous_outcome"' in body
    assert '"observed_failure_kind": "transport_error"' in body
    assert '"finish_reason": "error"' in body
    assert "data: [DONE]" in body
    assert "must-not-leak" not in body
