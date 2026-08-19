"""Provider protocol translation is explicit and model selection stays upstream."""

from __future__ import annotations

import io
import urllib.error
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent  # noqa: E402
from contextual_orchestrator.credentials import register_credential  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402
from contextual_orchestrator.provider_protocol import (  # noqa: E402
    chat_to_responses_payload,
    responses_to_chat_response,
    responses_text,
)


def test_chat_payload_maps_system_to_responses_developer_and_omits_blank_model() -> None:
    payload = chat_to_responses_payload(
        {
            "model": "",
            "messages": [
                {"role": "system", "content": "evidence only"},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "read"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,x"}},
                    ],
                },
            ],
            "max_tokens": 1024,
        },
        2048,
    )

    assert "model" not in payload
    assert payload["input"][0]["role"] == "developer"
    assert payload["input"][1]["content"][0] == {"type": "input_text", "text": "read"}
    assert payload["input"][1]["content"][1]["type"] == "input_image"
    assert payload["max_output_tokens"] == 1024


def test_responses_text_and_chat_adapter_preserve_output_and_usage() -> None:
    response = {
        "id": "resp_test",
        "model": "provider-selected",
        "output": [{"content": [{"type": "output_text", "text": "answer"}]}],
        "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
    }

    assert responses_text(response) == "answer"
    adapted = responses_to_chat_response(response, {})
    assert adapted["choices"][0]["message"]["content"] == "answer"
    assert adapted["usage"]["total_tokens"] == 5


def test_model_client_uses_responses_protocol_without_model_override() -> None:
    client = ModelClient()
    agent = ModelAgent(
        "responses_agent",
        base_url="https://provider.example/v1",
        provider_protocol="responses",
    )
    calls: list[tuple[str, dict]] = []

    def send(_agent, endpoint, payload, _destination=None, _timeout=None):
        calls.append((endpoint, payload))
        return {"output_text": "ok", "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}

    client._send_provider_json = send  # type: ignore[method-assign]
    assert client._send(agent, {"messages": [{"role": "system", "content": "rules"}]}) == "ok"
    assert calls[0][0] == "responses"
    assert "model" not in calls[0][1]
    assert calls[0][1]["input"][0]["role"] == "developer"


def test_auto_protocol_falls_back_only_when_chat_endpoint_is_unsupported() -> None:
    client = ModelClient()
    agent = ModelAgent("auto_agent", "", "https://provider.example/v1")
    calls: list[str] = []
    error = urllib.error.HTTPError(
        "https://provider.example/v1/chat/completions", 404, "not found", {}, io.BytesIO(b"")
    )

    def send(_agent, endpoint, payload, _destination=None, _timeout=None):
        calls.append(endpoint)
        if endpoint == "chat/completions":
            raise error
        return {"output_text": "fallback"}

    client._send_provider_json = send  # type: ignore[method-assign]
    assert client._send(agent, {"messages": [{"role": "user", "content": "question"}]}) == "fallback"
    assert calls == ["chat/completions", "responses"]


def test_auto_protocol_retries_without_temperature_after_provider_capability_rejection() -> None:
    client = ModelClient()
    agent = ModelAgent("auto_agent", "gpt-reasoning", "https://provider.example/v1")
    calls: list[dict] = []
    error = urllib.error.HTTPError(
        "https://provider.example/v1/chat/completions", 400, "bad request", {}, io.BytesIO(b"{}")
    )

    def send(_agent, endpoint, payload, _destination=None, _timeout=None):
        assert endpoint == "chat/completions"
        calls.append(payload)
        if "temperature" in payload:
            raise error
        return {"choices": [{"message": {"content": "ok"}}]}

    client._send_provider_json = send  # type: ignore[method-assign]
    assert client._send(agent, {"messages": [{"role": "user", "content": "question"}], "temperature": 0.2}) == "ok"
    assert calls[0]["temperature"] == 0.2
    assert "temperature" not in calls[1]


def test_proxy_send_auto_falls_back_from_chat_to_responses_for_multimodal_capability() -> None:
    client = ModelClient()
    register_credential("OPENAI_API_KEY", "test-provider-key")
    agent = ModelAgent("auto_agent", "vision-model", "https://provider.example/v1")
    calls: list[tuple[str, dict]] = []
    provider_error = urllib.error.HTTPError(
        "https://provider.example/v1/chat/completions", 400, "bad request", {}, io.BytesIO(b"{}")
    )

    def send(_agent, endpoint, payload, _destination=None, _timeout=None):
        calls.append((endpoint, payload))
        if endpoint == "chat/completions":
            raise RuntimeError("provider request failed") from provider_error
        return {
            "id": "resp_test",
            "model": "vision-model",
            "output_text": "region result",
            "usage": {"input_tokens": 2, "output_tokens": 2, "total_tokens": 4},
        }

    client._validate_provider = lambda _agent: (2, ("127.0.0.1", 443))  # type: ignore[method-assign]
    client._send_raw_with_retry = send  # type: ignore[method-assign]
    result = client.proxy_send(
        agent,
        "chat/completions",
        {
            "model": "vision-model",
            "messages": [
                {"role": "system", "content": "extract visible evidence"},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "describe this"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,x"}},
                    ],
                },
            ],
        },
    )

    assert [endpoint for endpoint, _payload in calls] == ["chat/completions", "responses"]
    assert calls[1][1]["input"][0]["role"] == "developer"
    assert calls[1][1]["input"][1]["content"][1]["type"] == "input_image"
    assert result["choices"][0]["message"]["content"] == "region result"


def test_provider_protocol_rejects_unknown_values() -> None:
    with pytest.raises(ValueError):
        ModelAgent("bad_agent", provider_protocol="xml")
