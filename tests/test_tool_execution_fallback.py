"""Tool execution fallback policy and orchestration integration tests."""

from __future__ import annotations

import socket
import urllib.error

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.orchestrator import ModelClient
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
            PermissionError("permission denied"),
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
) -> TaskOrchestrator:
    agents = [
        ModelAgent("primary_worker", "mock", tags=("reasoning", "writing"), priority=5),
        ModelAgent("backup_worker", "mock", tags=("reasoning", "writing"), priority=1),
    ]
    return TaskOrchestrator(
        agents,
        client=client,
        tool_retry_attempts=tool_retry_attempts,
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
        (400, ToolFailureKind.UNKNOWN),
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
