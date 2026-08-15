from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement target, found {count}")
    target.write_text(text.replace(old, new), encoding="utf-8")


# Preserve the original failure kind when replay safety normalizes a decision to
# ambiguous_outcome, and centralize exhausted-retry failover construction.
replace_once(
    "contextual_orchestrator/tool_fallback.py",
    '''    retry_safe: bool
    circuit_failure: bool
''',
    '''    retry_safe: bool
    circuit_failure: bool
    observed_kind: ToolFailureKind | None = None
''',
)
replace_once(
    "contextual_orchestrator/tool_fallback.py",
    '''def _decision(
    kind: ToolFailureKind,
    action: ToolFallbackAction,
    *,
    retry_safe: bool = False,
    circuit_failure: bool = False,
) -> ToolFailureDecision:
    """Build a decision with a stable machine-readable reason code."""
    return ToolFailureDecision(
        kind=kind,
        action=action,
        reason_code=f"tool_failure.{kind.value}.{action.value}",
        retry_safe=retry_safe,
        circuit_failure=circuit_failure,
    )
''',
    '''def _decision(
    kind: ToolFailureKind,
    action: ToolFallbackAction,
    *,
    retry_safe: bool = False,
    circuit_failure: bool = False,
    observed_kind: ToolFailureKind | None = None,
) -> ToolFailureDecision:
    """Build a decision with a stable machine-readable reason code."""
    return ToolFailureDecision(
        kind=kind,
        action=action,
        reason_code=f"tool_failure.{kind.value}.{action.value}",
        retry_safe=retry_safe,
        circuit_failure=circuit_failure,
        observed_kind=observed_kind or kind,
    )


def downgrade_to_failover(decision: ToolFailureDecision) -> ToolFailureDecision:
    """Convert an exhausted safe retry to canonical sequential failover."""
    return _decision(
        decision.kind,
        ToolFallbackAction.FAILOVER_AGENT,
        circuit_failure=decision.circuit_failure,
        observed_kind=decision.observed_kind or decision.kind,
    )
''',
)
replace_once(
    "contextual_orchestrator/tool_fallback.py",
    '''    if isinstance(error, PermissionError) or _contains_any(
        text,
        ("permission denied", "access denied", "unauthorized", "forbidden"),
    ):
        return ToolFailureKind.PERMISSION_DENIED
    if _contains_any(
        text,
        (
            "denied by policy",
            "policy blocked",
            "blocked by policy",
            "sandbox denied",
            "approval required",
        ),
    ):
        return ToolFailureKind.POLICY_BLOCKED
    if _contains_any(
        text,
        (
            "invalid tool arguments",
            "invalid arguments",
            "malformed arguments",
            "missing required argument",
            "schema validation",
        ),
    ):
        return ToolFailureKind.INVALID_ARGUMENTS
    if not _looks_tool_related(error, text):
        return ToolFailureKind.UNKNOWN
''',
    '''    if not _looks_tool_related(error, text):
        return ToolFailureKind.UNKNOWN
    if isinstance(error, PermissionError) or _contains_any(
        text,
        ("permission denied", "access denied", "unauthorized", "forbidden"),
    ):
        return ToolFailureKind.PERMISSION_DENIED
    if _contains_any(
        text,
        (
            "denied by policy",
            "policy blocked",
            "blocked by policy",
            "sandbox denied",
            "approval required",
        ),
    ):
        return ToolFailureKind.POLICY_BLOCKED
    if _contains_any(
        text,
        (
            "invalid tool arguments",
            "invalid arguments",
            "malformed arguments",
            "missing required argument",
            "schema validation",
        ),
    ):
        return ToolFailureKind.INVALID_ARGUMENTS
''',
)
replace_once(
    "contextual_orchestrator/tool_fallback.py",
    '''    if isinstance(error, ToolExecutionError):
        if error.outcome_unknown:
            kind = ToolFailureKind.AMBIGUOUS_OUTCOME
        else:
            kind = error.kind
        effective_idempotent = error.idempotent
    else:
        kind = _classify_unstructured(error)
        effective_idempotent = idempotent

    if kind is ToolFailureKind.AMBIGUOUS_OUTCOME:
        return _decision(kind, ToolFallbackAction.FAIL_CLOSED)
''',
    '''    if isinstance(error, ToolExecutionError):
        observed_kind = error.kind
        if error.outcome_unknown:
            kind = ToolFailureKind.AMBIGUOUS_OUTCOME
        else:
            kind = error.kind
        effective_idempotent = error.idempotent
    else:
        kind = _classify_unstructured(error)
        observed_kind = kind
        effective_idempotent = idempotent

    if kind is ToolFailureKind.AMBIGUOUS_OUTCOME:
        return _decision(
            kind,
            ToolFallbackAction.FAIL_CLOSED,
            observed_kind=observed_kind,
        )
''',
)
replace_once(
    "contextual_orchestrator/tool_fallback.py",
    '''        return _decision(
            ToolFailureKind.AMBIGUOUS_OUTCOME,
            ToolFallbackAction.FAIL_CLOSED,
        )
''',
    '''        return _decision(
            ToolFailureKind.AMBIGUOUS_OUTCOME,
            ToolFallbackAction.FAIL_CLOSED,
            observed_kind=kind,
        )
''',
)

# Add bounded exponential backoff and reuse the canonical decision builder after
# retry exhaustion. Keep audit schema secret-free while retaining observed cause.
replace_once(
    "contextual_orchestrator/orchestrator.py",
    "import json\nimport os\n",
    "import json\nimport math\nimport os\n",
)
replace_once(
    "contextual_orchestrator/orchestrator.py",
    '''    ToolFailureDecision,
    classify_tool_failure,
)''',
    '''    ToolFailureDecision,
    classify_tool_failure,
    downgrade_to_failover,
)''',
)
replace_once(
    "contextual_orchestrator/orchestrator.py",
    '''        cache_max_entries: int = 256,
        tool_retry_attempts: int = 1,
    ) -> None:
''',
    '''        cache_max_entries: int = 256,
        tool_retry_attempts: int = 1,
        tool_retry_backoff_seconds: float = 0.25,
    ) -> None:
''',
)
replace_once(
    "contextual_orchestrator/orchestrator.py",
    '''        self.tool_retry_attempts = tool_retry_attempts
        self.policy = OrchestrationPolicy()
''',
    '''        self.tool_retry_attempts = tool_retry_attempts
        if (
            isinstance(tool_retry_backoff_seconds, bool)
            or not isinstance(tool_retry_backoff_seconds, (int, float))
            or not math.isfinite(float(tool_retry_backoff_seconds))
            or tool_retry_backoff_seconds < 0
        ):
            raise ValueError(
                "tool_retry_backoff_seconds must be a finite nonnegative number"
            )
        self.tool_retry_backoff_seconds = float(tool_retry_backoff_seconds)
        self.policy = OrchestrationPolicy()
''',
)
replace_once(
    "contextual_orchestrator/orchestrator.py",
    '''                        retry_attempt += 1
                        self._record_tool_fallback(agent.id, decision, retry_attempt)
                        continue
                    if action is ToolFallbackAction.RETRY_SAME_AGENT:
                        action = ToolFallbackAction.FAILOVER_AGENT
                        decision = replace(
                            decision,
                            action=action,
                            reason_code=(
                                f"tool_failure.{decision.kind.value}.{action.value}"
                            ),
                            retry_safe=False,
                        )
''',
    '''                        retry_attempt += 1
                        self._record_tool_fallback(agent.id, decision, retry_attempt)
                        if self.tool_retry_backoff_seconds:
                            retry_delay = min(
                                self.tool_retry_backoff_seconds
                                * (2.0 ** min(retry_attempt - 1, 16)),
                                30.0,
                            )
                            time.sleep(retry_delay)
                        continue
                    if action is ToolFallbackAction.RETRY_SAME_AGENT:
                        decision = downgrade_to_failover(decision)
                        action = decision.action
''',
)
replace_once(
    "contextual_orchestrator/orchestrator.py",
    '''        self._append_audit_event(
            "tool_fallback_decision",
            {
                "agent_id": agent_id,
                "action": decision.action.value,
                "failure_kind": decision.kind.value,
                "reason_code": decision.reason_code,
                "retry_attempt": retry_attempt,
            },
        )
''',
    '''        event_detail = {
            "agent_id": agent_id,
            "action": decision.action.value,
            "failure_kind": decision.kind.value,
            "reason_code": decision.reason_code,
            "retry_attempt": retry_attempt,
        }
        observed_kind = decision.observed_kind or decision.kind
        if observed_kind is not decision.kind:
            event_detail["observed_failure_kind"] = observed_kind.value
        self._append_audit_event("tool_fallback_decision", event_detail)
''',
)

# Give fail-closed tool execution a dedicated HTTP/SSE contract rather than a
# generic internal_error or an unstructured finish_reason-only stream ending.
replace_once(
    "contextual_orchestrator/server.py",
    ''')

# OpenAI request params forwarded verbatim to the provider on passthrough.
''',
    ''')
from .tool_fallback import ToolFallbackStoppedError

# OpenAI request params forwarded verbatim to the provider on passthrough.
''',
)
replace_once(
    "contextual_orchestrator/server.py",
    '''def _coerce_json(payload: bytes) -> dict[str, Any]:
''',
    '''TOOL_FALLBACK_STOPPED_STATUS = 409
TOOL_FALLBACK_STOPPED_CODE = "tool_execution_stopped"
TOOL_FALLBACK_STOPPED_MESSAGE = (
    "tool execution stopped because no safe retry or failover was available"
)


def _tool_fallback_error_detail(error: ToolFallbackStoppedError) -> dict[str, Any]:
    """Return secret-free structured evidence for one fail-closed tool decision."""
    decision = error.decision
    detail = {
        "action": decision.action.value,
        "failure_kind": decision.kind.value,
        "reason_code": decision.reason_code,
    }
    observed_kind = decision.observed_kind or decision.kind
    if observed_kind is not decision.kind:
        detail["observed_failure_kind"] = observed_kind.value
    return detail


def _coerce_json(payload: bytes) -> dict[str, Any]:
''',
)
replace_once(
    "contextual_orchestrator/server.py",
    '''            except BudgetExceededError as exc:
                self._send_error(429, "budget_exceeded", str(exc), exc.detail)
''',
    '''            except ToolFallbackStoppedError as exc:
                self._send_error(
                    TOOL_FALLBACK_STOPPED_STATUS,
                    TOOL_FALLBACK_STOPPED_CODE,
                    TOOL_FALLBACK_STOPPED_MESSAGE,
                    _tool_fallback_error_detail(exc),
                )
            except BudgetExceededError as exc:
                self._send_error(429, "budget_exceeded", str(exc), exc.detail)
''',
)
replace_once(
    "contextual_orchestrator/server.py",
    '''                except Exception:  # noqa: BLE001 - headers already sent; surface as a terminal error frame
                    self._write_sse(frame({}, finish="error"))
''',
    '''                except ToolFallbackStoppedError as exc:
                    detail = {
                        "request_id": uuid.uuid4().hex,
                        **_tool_fallback_error_detail(exc),
                    }
                    payload = _error_payload(
                        TOOL_FALLBACK_STOPPED_CODE,
                        TOOL_FALLBACK_STOPPED_MESSAGE,
                        detail,
                    )
                    self._write_sse(
                        f"data: {json.dumps(payload, ensure_ascii=False)}\\n\\n"
                    )
                    self._write_sse(frame({}, finish="error"))
                except Exception:  # noqa: BLE001 - headers already sent; surface as a terminal error frame
                    self._write_sse(frame({}, finish="error"))
''',
)

# Clarify the exact idempotency matrix and bounded retry pacing.
replace_once(
    "docs/adr/0001-tool-execution-fallback-policy.md",
    '''| `rate_limited` | retry if idempotent, otherwise fail over | A rejected request can use another endpoint; explicit idempotency permits one bounded local retry. |
| `timeout` / `transport_error` | retry only if explicitly idempotent | A non-idempotent request can have an ambiguous outcome. |
''',
    '''| `rate_limited` | bounded retry then fail over if idempotent; otherwise fail over | A rejected request can use another endpoint; explicit idempotency permits bounded local retry. |
| `timeout` / `transport_error` | bounded retry then fail over if explicitly idempotent; otherwise `fail_closed` as `ambiguous_outcome` | A non-idempotent request may already have produced a side effect. |
''',
)
replace_once(
    "docs/adr/0001-tool-execution-fallback-policy.md",
    '''| `execution_failed` | fail over only if explicitly idempotent | A state-changing command must not be duplicated. |
| `ambiguous_outcome` | `fail_closed` | The system cannot prove whether a side effect occurred. |
''',
    '''| `execution_failed` | fail over if explicitly idempotent; otherwise `fail_closed` | A state-changing command must not be duplicated. |
| `ambiguous_outcome` / `outcome_unknown` | always `fail_closed` | The system cannot prove whether a side effect occurred. |
''',
)
replace_once(
    "docs/doctoring/TOOL_EXECUTION_FALLBACKS.md",
    '''| Stop when a non-idempotent result might already have occurred | RFC 9110 §9.2.2 | Timeout/transport uncertainty maps to `ambiguous_outcome`. |
''',
    '''| Stop when a non-idempotent result might already have occurred | RFC 9110 §9.2.2 | Non-idempotent timeout/transport uncertainty and `outcome_unknown` map to `ambiguous_outcome` + `fail_closed`; non-idempotent execution failure also fails closed. |
''',
)
replace_once(
    "docs/tool_execution_fallbacks.md",
    '''`TaskOrchestrator(..., tool_retry_attempts=1)` permits one same-agent retry when the classifier marks the operation `retry_safe`. Set the value to `0` to disable same-agent retries while retaining safe cross-agent fallback. Boolean, negative, non-integer, and fractional values are rejected.
''',
    '''`TaskOrchestrator(..., tool_retry_attempts=1, tool_retry_backoff_seconds=0.25)` permits one same-agent retry when the classifier marks the operation `retry_safe`. Retries wait with bounded exponential backoff, capped at 30 seconds. Set `tool_retry_attempts=0` to disable same-agent retries; tests may set the backoff to `0`. Invalid retry counts and negative, non-finite, boolean, or non-numeric backoff values are rejected.
''',
)
replace_once(
    "docs/tool_execution_fallbacks.md",
    '''No prompt, tool argument, output, credential, provider response, or exception text is recorded.
''',
    '''When a timeout or transport failure is normalized to `ambiguous_outcome`, the event additionally records `observed_failure_kind` so operators can distinguish the original cause without retaining raw exception text.

No prompt, tool argument, output, credential, provider response, or exception text is recorded.
''',
)
replace_once(
    "CHANGELOG.md",
    '''- Agent invocation now retries explicitly idempotent transient tool failures within a bounded per-agent budget.
''',
    '''- Agent invocation now retries explicitly idempotent transient tool failures with bounded exponential backoff within a per-agent budget.
- Fail-closed tool decisions now have dedicated JSON and SSE error contracts, and preserve the observed failure kind in secret-free audit evidence.
''',
)

# Regression tests: request pacing, provider/tool distinction, observed cause,
# canonical reason codes, and HTTP/SSE fail-closed behavior.
replace_once(
    "tests/test_tool_execution_fallback.py",
    '''import socket
import urllib.error

import pytest
''',
    '''import json
import socket
import threading
import urllib.error
import urllib.request

import pytest
''',
)
replace_once(
    "tests/test_tool_execution_fallback.py",
    '''from contextual_orchestrator.tool_fallback import (
''',
    '''from contextual_orchestrator.server import SecurityConfig, build_server
from contextual_orchestrator.tool_fallback import (
''',
)
replace_once(
    "tests/test_tool_execution_fallback.py",
    '''            PermissionError("permission denied"),
''',
    '''            PermissionError("tool permission denied"),
''',
)
replace_once(
    "tests/test_tool_execution_fallback.py",
    '''    tool_retry_attempts: int = 1,
) -> TaskOrchestrator:
''',
    '''    tool_retry_attempts: int = 1,
    tool_retry_backoff_seconds: float = 0.0,
) -> TaskOrchestrator:
''',
)
replace_once(
    "tests/test_tool_execution_fallback.py",
    '''        tool_retry_attempts=tool_retry_attempts,
    )
''',
    '''        tool_retry_attempts=tool_retry_attempts,
        tool_retry_backoff_seconds=tool_retry_backoff_seconds,
    )
''',
)
replace_once(
    "tests/test_tool_execution_fallback.py",
    '''    assert decision.kind is ToolFailureKind.AMBIGUOUS_OUTCOME
    assert decision.action is ToolFallbackAction.FAIL_CLOSED
    assert decision.retry_safe is False
''',
    '''    assert decision.kind is ToolFailureKind.AMBIGUOUS_OUTCOME
    assert decision.observed_kind is ToolFailureKind.TIMEOUT
    assert decision.action is ToolFallbackAction.FAIL_CLOSED
    assert decision.retry_safe is False
''',
)
replace_once(
    "tests/test_tool_execution_fallback.py",
    '''    assert decision.kind is ToolFailureKind.AMBIGUOUS_OUTCOME
    assert decision.action is ToolFallbackAction.FAIL_CLOSED


def test_structured_idempotent_execution_failure_can_fail_over() -> None:
''',
    '''    assert decision.kind is ToolFailureKind.AMBIGUOUS_OUTCOME
    assert decision.observed_kind is ToolFailureKind.TRANSPORT_ERROR
    assert decision.action is ToolFallbackAction.FAIL_CLOSED


def test_structured_idempotent_execution_failure_can_fail_over() -> None:
''',
)
replace_once(
    "tests/test_tool_execution_fallback.py",
    '''    assert [event["event_detail"]["action"] for event in events] == [
        "retry_same_agent",
        "failover_agent",
    ]
''',
    '''    assert [event["event_detail"]["action"] for event in events] == [
        "retry_same_agent",
        "failover_agent",
    ]
    assert events[-1]["event_detail"]["reason_code"] == (
        "tool_failure.timeout.failover_agent"
    )
''',
)
replace_once(
    "tests/test_tool_execution_fallback.py",
    '''    assert "super-secret-value" not in str(raised.value)
    assert client.calls == ["primary_worker"]
''',
    '''    assert "super-secret-value" not in str(raised.value)
    assert client.calls == ["primary_worker"]
    event_detail = orchestrator.list_recent_audit_events()[0]["event_detail"]
    assert event_detail["failure_kind"] == "ambiguous_outcome"
    assert event_detail["observed_failure_kind"] == "transport_error"
''',
)

appendix = r'''


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
'''

tests_path = Path("tests/test_tool_execution_fallback.py")
tests_text = tests_path.read_text(encoding="utf-8")
if "test_provider_auth_failure_without_tool_evidence_keeps_provider_failover" in tests_text:
    raise SystemExit("review-fix tests already exist")
tests_path.write_text(
    tests_text.rstrip() + appendix.rstrip() + "\n",
    encoding="utf-8",
)
