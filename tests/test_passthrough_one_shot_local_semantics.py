"""Regression coverage for one-shot passthrough transport semantics."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import io
import socket
from unittest.mock import patch
import urllib.error

import pytest

from contextual_orchestrator import ModelAgent
from contextual_orchestrator.orchestrator import ModelClient


def _local_agent() -> ModelAgent:
    """Build one authenticated loopback gateway agent."""
    return ModelAgent(
        "local_gateway_agent",
        "local-model",
        base_url="local://127.0.0.1:8080/v1",
        local_credential_key="LOCAL_GATEWAY_TOKEN",
    )


def _chat_response(content: str = "local answer") -> dict[str, object]:
    """Return one minimal OpenAI-compatible chat response."""
    return {
        "id": "chatcmpl-one-shot",
        "object": "chat.completion",
        "created": 1,
        "model": "local-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 1,
            "completion_tokens": 2,
            "total_tokens": 3,
        },
    }


def test_one_shot_local_responses_preserves_translation_and_concurrency_slot() -> None:
    """One-shot failover must retain the provider-neutral local Responses adapter."""
    client = ModelClient(max_retries=4, local_concurrency=3)
    agent = _local_agent()
    request = {
        "model": "local-model",
        "input": "summarize the incident",
        "metadata": {"tenant": "tenant-one"},
    }
    original = deepcopy(request)
    sent: list[tuple[str, dict[str, object]]] = []
    slots: list[tuple[str, int, int]] = []

    @contextmanager
    def local_slot(
        slot_agent: ModelAgent,
        capacity: int,
        timeout: int,
    ):
        slots.append((slot_agent.id, capacity, timeout))
        yield

    def send_raw(
        sent_agent: ModelAgent,
        endpoint: str,
        payload: dict[str, object],
        _destination: object,
    ) -> dict[str, object]:
        assert sent_agent is agent
        sent.append((endpoint, deepcopy(payload)))
        return _chat_response()

    with (
        patch.object(
            client,
            "_validate_provider",
            return_value=(socket.AF_INET, ("127.0.0.1", 8080)),
        ),
        patch.object(client, "_send_raw", side_effect=send_raw),
        patch(
            "contextual_orchestrator.orchestrator._local_provider_slot",
            side_effect=local_slot,
        ),
        client.request_settings(max_output_tokens=73),
    ):
        result = client.proxy_send_once(agent, "responses", request)

    assert request == original
    assert slots == [(agent.id, 3, client.timeout)]
    assert len(sent) == 1
    endpoint, payload = sent[0]
    assert endpoint == "chat/completions"
    assert payload["model"] == "local-model"
    assert payload["stream"] is False
    assert payload["max_tokens"] == 73
    assert payload["messages"] == [
        {"role": "user", "content": "summarize the incident"}
    ]
    assert result["object"] == "response"
    assert result["output_text"] == "local answer"
    assert result["metadata"] == {"tenant": "tenant-one"}


@pytest.mark.parametrize(
    ("requested_max_tokens", "expected_max_tokens"), [(None, 57), (11, 11)]
)
def test_one_shot_local_chat_still_uses_model_switch_concurrency_slot(
    requested_max_tokens: int | None,
    expected_max_tokens: int,
) -> None:
    """Removing same-model retries must not bypass local model-switch coordination."""
    client = ModelClient(max_retries=5, local_concurrency=2, max_output_tokens=57)
    agent = _local_agent()
    payload = {
        "model": "local-model",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": False,
    }
    if requested_max_tokens is not None:
        payload["max_tokens"] = requested_max_tokens
    original = deepcopy(payload)
    slots: list[tuple[str, int, int]] = []
    sends: list[tuple[str, dict[str, object]]] = []

    @contextmanager
    def local_slot(
        slot_agent: ModelAgent,
        capacity: int,
        timeout: int,
    ):
        slots.append((slot_agent.id, capacity, timeout))
        yield

    def send_raw(
        _agent: ModelAgent,
        endpoint: str,
        sent_payload: dict[str, object],
        _destination: object,
    ) -> dict[str, object]:
        sends.append((endpoint, deepcopy(sent_payload)))
        return _chat_response("hello")

    with (
        patch.object(
            client,
            "_validate_provider",
            return_value=(socket.AF_INET, ("127.0.0.1", 8080)),
        ),
        patch.object(client, "_send_raw", side_effect=send_raw),
        patch(
            "contextual_orchestrator.orchestrator._local_provider_slot",
            side_effect=local_slot,
        ),
    ):
        result = client.proxy_send_once(agent, "chat/completions", payload)

    assert result["object"] == "chat.completion"
    assert slots == [(agent.id, 2, client.timeout)]
    assert sends == [
        ("chat/completions", {**payload, "max_tokens": expected_max_tokens})
    ]
    assert payload == original


def test_one_shot_remote_passthrough_never_enters_same_agent_retry_wrapper() -> None:
    """A candidate attempt is exactly one raw provider request."""
    client = ModelClient(max_retries=7)
    agent = ModelAgent(
        "remote_provider_agent",
        "remote-model",
        base_url="https://provider.example/v1",
        credential_key="REMOTE_PROVIDER_KEY",
    )
    rate_limit = urllib.error.HTTPError(
        "https://provider.example/v1/chat/completions",
        429,
        "rate limited",
        None,
        None,
    )

    with (
        patch.object(
            client,
            "_validate_provider",
            return_value=(socket.AF_INET, ("93.184.216.34", 443)),
        ),
        patch.object(client, "_send_raw", side_effect=rate_limit) as send_raw,
    ):
        with pytest.raises(urllib.error.HTTPError) as caught:
            client.proxy_send_once(
                agent,
                "chat/completions",
                {
                    "model": "remote-model",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": False,
                },
            )

    assert caught.value is rate_limit
    send_raw.assert_called_once()


def test_one_shot_passthrough_keeps_optional_temperature_negotiation() -> None:
    """Capability negotiation removes only temperature without transient replay."""

    client = ModelClient(max_retries=7)
    agent = ModelAgent(
        "remote_provider_agent",
        "remote-model",
        base_url="https://provider.example/v1",
        credential_key="REMOTE_PROVIDER_KEY",
    )
    unsupported = urllib.error.HTTPError(
        "https://provider.example/v1/responses",
        400,
        "bad request",
        None,
        io.BytesIO(
            b"Unsupported value: 'temperature' does not support 0.2; only the default is supported"
        ),
    )
    sent: list[dict[str, object]] = []

    def send_raw(
        _agent: ModelAgent,
        _endpoint: str,
        payload: dict[str, object],
        _destination: object,
    ) -> dict[str, object]:
        sent.append(deepcopy(payload))
        if len(sent) == 1:
            raise unsupported
        return _chat_response("negotiated")

    with (
        patch.object(
            client,
            "_validate_provider",
            return_value=(socket.AF_INET, ("93.184.216.34", 443)),
        ),
        patch.object(client, "_send_raw", side_effect=send_raw),
    ):
        result = client.proxy_send_once(
            agent,
            "responses",
            {
                "model": "remote-model",
                "input": "hello",
                "temperature": 0.2,
            },
        )

    assert result["object"] == "chat.completion"
    assert sent[0]["temperature"] == 0.2
    assert "temperature" not in sent[1]
