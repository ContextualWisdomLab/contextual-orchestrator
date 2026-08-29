"""One-shot exact-head repair for PR #879 taxonomy and trace evidence."""

from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    """Replace one reviewed block or stop without modifying the branch."""
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one replacement in {path}; found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    """Apply request-size, redaction, and shared batch-latency contracts."""
    replace_once(
        "contextual_orchestrator/provider_errors.py",
        "import json as _json\nimport socket\n",
        "import json as _json\nimport re as _re\nimport socket\n",
    )
    replace_once(
        "contextual_orchestrator/provider_errors.py",
        '''#: Maximum provider response bytes inspected for one caller-safe diagnostic.
MAX_PROVIDER_ERROR_BODY_BYTES = 65_536

#: Upstream HTTP status -> ``(client_status, error_code, retryable)`` surface.
''',
        '''#: Maximum provider response bytes inspected for one caller-safe diagnostic.
MAX_PROVIDER_ERROR_BODY_BYTES = 65_536

#: Provider-controlled text containing any likely secret, request content, URL,
#: or network address is discarded wholesale. Partial masking is unsafe because
#: adjacent diagnostic text can still identify credentials or private topology.
_SENSITIVE_PROVIDER_MESSAGE = _re.compile(
    r"(?ix)(?:"
    r"https?://|"
    r"(?:^|[^0-9])(?:[0-9]{1,3}\\.){3}[0-9]{1,3}(?:[^0-9]|$)|"
    r"\\b(?:api[_ -]?key|authorization|bearer|password|secret|token|prompt|input|messages?)\\b"
    r")"
)

#: Upstream HTTP status -> ``(client_status, error_code, retryable)`` surface.
''',
    )
    replace_once(
        "contextual_orchestrator/provider_errors.py",
        '''    ).strip()
    return collapsed[:MAX_SAFE_MESSAGE_CHARS] or None
''',
        '''    ).strip()
    collapsed = collapsed[:MAX_SAFE_MESSAGE_CHARS]
    if not collapsed or _SENSITIVE_PROVIDER_MESSAGE.search(collapsed):
        return None
    return collapsed
''',
    )
    replace_once(
        "contextual_orchestrator/orchestrator.py",
        '''class ProviderRequestTooLargeError(RuntimeError):
    """Raised after every eligible provider rejects the request as too large."""
''',
        '''class ProviderRequestTooLargeError(ProviderUpstreamError):
    """Preserve request-size taxonomy across transport and telemetry boundaries."""

    def __init__(
        self,
        message: str,
        *,
        agent_id: str = "",
        model: str = "",
        provider_status: int | None = None,
        transport: str = "chat",
    ) -> None:
        super().__init__(
            agent_id=agent_id,
            model=model,
            error_code="request_too_large",
            message=message,
            client_status=413,
            provider_status=provider_status,
            retryable=False,
            transport=transport,
        )
''',
    )

    orchestrator = Path("contextual_orchestrator/orchestrator.py")
    text = orchestrator.read_text(encoding="utf-8")
    old_raise = '''            raise ProviderRequestTooLargeError("provider request body is too large") from None
'''
    if text.count(old_raise) != 2:
        raise SystemExit(f"expected two direct request-size raises; found {text.count(old_raise)}")
    chat_raise = '''            raise ProviderRequestTooLargeError(
                "provider request body is too large",
                agent_id=agent.id,
                model=agent.model,
                provider_status=last_error.code,
                transport="chat",
            ) from None
'''
    passthrough_raise = '''            raise ProviderRequestTooLargeError(
                "provider request body is too large",
                agent_id=agent.id,
                model=agent.model,
                provider_status=last_error.code,
                transport="passthrough",
            ) from None
'''
    text = text.replace(old_raise, chat_raise, 1).replace(old_raise, passthrough_raise, 1)
    orchestrator.write_text(text, encoding="utf-8")

    replace_once(
        "contextual_orchestrator/orchestrator.py",
        '''        answers: dict[int, dict[str, Any]] = {}
        for agent_id, requests in requests_by_agent.items():
            effort_profile = self._role_effort_profile("worker")
            batch = (
                self.client.batch_chat(
                    agents_by_id[agent_id], requests, effort_profile=effort_profile
                )
                if effort_profile is not None
                else self.client.batch_chat(agents_by_id[agent_id], requests)
            )
            results = _validate_batch_results(requests, batch)
''',
        '''        answers: dict[int, dict[str, Any]] = {}
        batch_latency_ms_by_agent: dict[str, float] = {}
        for agent_id, requests in requests_by_agent.items():
            effort_profile = self._role_effort_profile("worker")
            batch_started_at = time.perf_counter()
            batch = (
                self.client.batch_chat(
                    agents_by_id[agent_id], requests, effort_profile=effort_profile
                )
                if effort_profile is not None
                else self.client.batch_chat(agents_by_id[agent_id], requests)
            )
            # One provider batch call covers every request in this group. Record
            # its shared elapsed time on each trace row without claiming
            # unavailable per-request timing precision.
            batch_latency_ms_by_agent[agent_id] = round(
                (time.perf_counter() - batch_started_at) * 1000,
                2,
            )
            results = _validate_batch_results(requests, batch)
''',
    )
    replace_once(
        "contextual_orchestrator/orchestrator.py",
        '''                "provider": agent.provider_name or self._infer_provider_name(agent.base_url),
                "subtask": "Direct route (batched)", "access": [], "output": result["content"],
''',
        '''                "provider": agent.provider_name or self._infer_provider_name(agent.base_url),
                "latency_ms": batch_latency_ms_by_agent[agent.id],
                "subtask": "Direct route (batched)", "access": [], "output": result["content"],
''',
    )
    replace_once(
        "tests/test_provider_error_taxonomy.py",
        '''    plain_string = safe_provider_message(_body_http_error(400, {"error": "invalid api key"}))
    assert plain_string == "invalid api key"
''',
        '''    plain_string = safe_provider_message(_body_http_error(400, {"error": "invalid api key"}))
    assert plain_string is None
''',
    )

    taxonomy_tests = Path("tests/test_provider_error_taxonomy.py")
    taxonomy_text = taxonomy_tests.read_text(encoding="utf-8")
    security_test = '''

def test_safe_message_discards_sensitive_provider_diagnostics() -> None:
    """Credentials, request content, URLs, and private topology never reach callers."""
    diagnostics = (
        "authorization: Bearer provider-secret-value",
        "prompt=private customer message",
        "request failed at http://10.0.0.9/internal",
        "token=abc123456789012345",
    )
    for diagnostic in diagnostics:
        error = _body_http_error(400, {"error": {"message": diagnostic}})
        assert safe_provider_message(error) is None
        classified = classify_provider_failure(error, agent_id="a", model="m")
        assert diagnostic not in str(classified)
        assert str(classified) == "provider rejected the request with HTTP 400"
'''
    if "test_safe_message_discards_sensitive_provider_diagnostics" in taxonomy_text:
        raise SystemExit("sensitive-provider-message regression already exists")
    taxonomy_tests.write_text(taxonomy_text + security_test, encoding="utf-8")

    regression = Path("tests/test_provider_error_merge_regressions.py")
    if regression.exists():
        raise SystemExit(f"{regression} already exists")
    regression.write_text(
        '''"""Merge-result regressions for provider taxonomy and trace evidence."""

from __future__ import annotations

from contextlib import AbstractContextManager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import contextual_orchestrator.orchestrator as orchestrator_module
import contextual_orchestrator.telemetry as telemetry_module
from contextual_orchestrator.orchestrator import (
    ModelAgent,
    ProviderRequestTooLargeError,
    TaskOrchestrator,
)
from contextual_orchestrator.telemetry import traced


class _SpanContext(AbstractContextManager):
    def __init__(self, span: MagicMock) -> None:
        self._span = span

    def __enter__(self) -> MagicMock:
        return self._span

    def __exit__(self, exc_type, exc, traceback) -> bool:
        del exc_type, exc, traceback
        return False


class _Tracer:
    def __init__(self, span: MagicMock) -> None:
        self._span = span

    def start_as_current_span(self, *_args, **_kwargs) -> _SpanContext:
        return _SpanContext(self._span)


class _Trace:
    def __init__(self, span: MagicMock) -> None:
        self._span = span

    def get_tracer(self, _name: str) -> _Tracer:
        return _Tracer(self._span)


@pytest.mark.parametrize("transport", ["chat", "passthrough"])
def test_traced_preserves_request_too_large_taxonomy(monkeypatch, transport: str) -> None:
    """HTTP 413 remains request_too_large with its upstream status on every transport."""
    span = MagicMock()
    monkeypatch.setattr(telemetry_module, "trace", _Trace(span))
    monkeypatch.setattr(telemetry_module, "Status", lambda code: code)
    monkeypatch.setattr(telemetry_module, "StatusCode", SimpleNamespace(ERROR="error"))
    failure = ProviderRequestTooLargeError(
        "provider request body is too large",
        agent_id="worker_agent",
        model="model-x",
        provider_status=413,
        transport=transport,
    )

    with pytest.raises(ProviderRequestTooLargeError):
        with traced(f"{transport} model-x"):
            raise failure

    span.set_attribute.assert_any_call("error.type", "request_too_large")
    span.set_attribute.assert_any_call(
        "contextual_orchestrator.provider_status_code", 413
    )


def test_batch_trace_uses_one_honest_shared_provider_duration(monkeypatch) -> None:
    """Every result in one provider batch reports the same measured batch duration."""
    agent = ModelAgent("batch_agent", "batch-model", provider_name="provider-x")
    orchestrator = TaskOrchestrator([agent])

    def batch_chat(_agent, requests, **_kwargs):
        return {
            custom_id: {"content": f"answer:{custom_id}"}
            for custom_id in requests
        }

    monkeypatch.setattr(orchestrator.client, "batch_chat", batch_chat)
    with patch.object(
        orchestrator_module.time,
        "perf_counter",
        side_effect=[10.0, 10.25],
    ):
        records = orchestrator.batch_route(["one", "two"])

    assert [record["trace"][0]["latency_ms"] for record in records] == [250.0, 250.0]
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
