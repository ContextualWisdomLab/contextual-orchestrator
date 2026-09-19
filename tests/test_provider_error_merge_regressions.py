"""Merge-result regressions for provider taxonomy and trace evidence."""

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
