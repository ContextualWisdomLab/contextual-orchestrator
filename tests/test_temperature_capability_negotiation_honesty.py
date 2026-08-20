"""Regressions for bounded, evidence-preserving temperature negotiation."""

from __future__ import annotations

import io
import json
import socket
import urllib.error

import pytest

from contextual_orchestrator import ModelAgent
from contextual_orchestrator.orchestrator import (
    ModelClient,
    _temperature_capability_rejection,
)


def _http_error(status: int, message: str) -> urllib.error.HTTPError:
    body = json.dumps({"error": {"message": message}}).encode("utf-8")
    return urllib.error.HTTPError(
        "https://provider.example/v1/chat/completions",
        status,
        "provider error",
        {},
        io.BytesIO(body),
    )


def test_invalid_temperature_range_is_not_negotiated_as_missing_capability() -> None:
    """A bad caller value must remain a 4xx instead of being silently removed."""
    error = _http_error(400, "temperature is not allowed to be greater than 1")

    assert not _temperature_capability_rejection(error)


def test_azure_default_only_temperature_is_negotiated() -> None:
    """Azure's default-only diagnostic proves the optional field is unsupported."""
    error = _http_error(
        400,
        "AzureException BadRequestError - Unsupported value: 'temperature' does not "
        "support 0.2 with this model. Only the default (1) value is supported.",
    )

    assert _temperature_capability_rejection(error)


def test_non_negotiated_error_body_remains_available_to_the_caller() -> None:
    """Capability inspection must not consume evidence from an unrelated 4xx."""
    expected = json.dumps(
        {"error": {"message": "invalid temperature value"}}
    ).encode("utf-8")
    error = urllib.error.HTTPError(
        "https://provider.example/v1/chat/completions",
        400,
        "provider error",
        {},
        io.BytesIO(expected),
    )

    assert not _temperature_capability_rejection(error)
    assert error.read() == expected


class _Response:
    """Minimal context-managed JSON response for transport tests."""

    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def test_transient_retry_after_negotiation_keeps_temperature_omitted(monkeypatch) -> None:
    """Once unsupported is proven, later transient retries must use the negotiated payload."""
    client = ModelClient(max_retries=1, retry_backoff=0.0)
    agent = ModelAgent(
        "provider_agent",
        "restricted-model",
        base_url="https://provider.example/v1",
    )
    sent_payloads: list[dict[str, object]] = []

    def open_provider(request, _destination=None, **_kwargs):
        sent_payloads.append(json.loads(request.data.decode("utf-8")))
        if len(sent_payloads) == 1:
            raise _http_error(422, "temperature is not supported for this deployment")
        if len(sent_payloads) == 2:
            raise _http_error(503, "temporarily unavailable")
        return _Response(
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "recovered"}}
                ]
            }
        )

    monkeypatch.setattr(client, "_open_provider", open_provider)
    monkeypatch.setattr(client, "_sleep", lambda _delay: None)

    result = client._send_with_retry(
        agent,
        {"model": agent.model, "messages": [], "temperature": 0.2},
        (socket.AF_INET, ("93.184.216.34", 443)),
    )

    assert result == "recovered"
    assert ["temperature" in payload for payload in sent_payloads] == [
        True,
        False,
        False,
    ]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
