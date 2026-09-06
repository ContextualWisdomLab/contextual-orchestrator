"""Regression contracts for request-size failover attempt telemetry."""

from __future__ import annotations

import urllib.error

from contextual_orchestrator import ModelAgent, TaskOrchestrator


def _request_too_large_http_error() -> urllib.error.HTTPError:
    """Return a provider HTTP 413 without response-body diagnostics."""
    return urllib.error.HTTPError(
        "https://provider.example/chat/completions",
        413,
        "Payload Too Large",
        None,
        None,
    )


def _attempt_record(exc: Exception) -> dict[str, object]:
    """Build the telemetry record through the production helper."""
    orchestrator = TaskOrchestrator.__new__(TaskOrchestrator)
    agent = ModelAgent(
        "provider_worker",
        "provider-model",
        base_url="https://provider.example/v1",
        api_key_env="",
        credential_key="",
    )
    return orchestrator._failover_attempt_record(agent, exc, None, 0)


def _assert_request_too_large(record: dict[str, object]) -> None:
    """Require the stable request-size taxonomy and provider status."""
    assert record["error_code"] == "request_too_large"
    assert record["provider_status"] == 413
    assert record["retryable"] is False


def test_raw_http_413_attempt_keeps_request_size_taxonomy() -> None:
    """A directly raised provider 413 must not degrade to ``unknown``."""
    _assert_request_too_large(_attempt_record(_request_too_large_http_error()))


def test_wrapped_http_413_attempt_keeps_request_size_taxonomy() -> None:
    """The bounded exception-chain recognition used by failover must reach telemetry."""
    wrapped = RuntimeError("provider transport wrapper")
    wrapped.__cause__ = _request_too_large_http_error()

    _assert_request_too_large(_attempt_record(wrapped))
