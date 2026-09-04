from unittest.mock import patch

import pytest

from contextual_orchestrator.model_discovery import (
    PROVIDER_MODEL_SOURCES,
    _parse_openai_compatible,
)
from contextual_orchestrator.orchestrator import ModelAgent, ModelClient
from contextual_orchestrator.provider_catalog_store import provider_account_id


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.payload


def _agent(model: str) -> ModelAgent:
    return ModelAgent(
        id="opencode_go_model",
        model=model,
        base_url="https://opencode.ai/zen/go/v1",
        provider_name="opencode_go",
    )


def test_go_source_reuses_zen_credential_but_has_independent_identity() -> None:
    sources = {source.provider_name: source for source in PROVIDER_MODEL_SOURCES}
    assert (
        sources["opencode_go"].credential_name
        == sources["opencode_zen"].credential_name
    )
    assert sources["opencode_go"].list_url == "https://opencode.ai/zen/go/v1/models"
    assert provider_account_id(sources["opencode_go"]) != provider_account_id(
        sources["opencode_zen"]
    )
    discovered = _parse_openai_compatible(
        {"data": [{"id": "minimax-m3"}, {"id": "undocumented"}]}, sources["opencode_go"]
    )
    assert [model.model_id for model in discovered] == ["minimax-m3"]
    assert discovered[0].provider_name == "opencode_go"


@pytest.mark.parametrize(
    ("model", "native_endpoint"),
    [
        ("glm-5.3", "chat/completions"),
        ("grok-4.6", "responses"),
        ("minimax-m3", "messages"),
    ],
)
def test_go_chat_converts_to_documented_native_endpoint(
    model: str, native_endpoint: str
) -> None:
    client = ModelClient(allowed_provider_hosts={"opencode.ai"})
    if native_endpoint == "chat/completions":
        upstream = {
            "id": "chat",
            "model": model,
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {},
        }
    elif native_endpoint == "responses":
        upstream = {
            "id": "resp",
            "model": model,
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "ok"}]}
            ],
            "usage": {},
        }
    else:
        upstream = {
            "id": "msg",
            "model": model,
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
            "usage": {},
        }
    with (
        patch.object(client, "_validate_provider", return_value=None),
        patch.object(client, "_send_raw_with_retry", return_value=upstream) as send,
    ):
        result = client.proxy_send(
            _agent(model),
            "chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 8,
            },
        )
    assert result["choices"][0]["message"]["content"] == "ok"
    assert send.call_args.args[1] == native_endpoint
    if native_endpoint == "messages":
        assert send.call_args.args[2]["messages"] == [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]}
        ]


def test_go_messages_tool_calls_round_trip_to_responses() -> None:
    client = ModelClient(allowed_provider_hosts={"opencode.ai"})
    upstream = {
        "id": "msg",
        "model": "minimax-m3",
        "content": [
            {"type": "tool_use", "id": "call_1", "name": "lookup", "input": {"q": "x"}}
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 3, "output_tokens": 2},
    }
    with (
        patch.object(client, "_validate_provider", return_value=None),
        patch.object(client, "_send_raw_with_retry", return_value=upstream),
    ):
        result = client.proxy_send(
            _agent("minimax-m3"),
            "responses",
            {
                "model": "minimax-m3",
                "input": "find x",
                "tools": [
                    {
                        "type": "function",
                        "name": "lookup",
                        "parameters": {"type": "object"},
                    }
                ],
            },
        )
    assert result["output"][0]["type"] == "function_call"
    assert result["output"][0]["name"] == "lookup"
    assert result["usage"] == {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}


def test_go_messages_conversion_fails_closed_on_images() -> None:
    client = ModelClient(allowed_provider_hosts={"opencode.ai"})
    with patch.object(client, "_validate_provider", return_value=None):
        with pytest.raises(ValueError, match="text content only"):
            client.proxy_send(
                _agent("minimax-m3"),
                "chat/completions",
                {
                    "model": "minimax-m3",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": "https://example.com/x.png"},
                                }
                            ],
                        }
                    ],
                },
            )


def test_internal_chat_uses_messages_conversion() -> None:
    client = ModelClient()
    response = _Response(
        b'{"id":"msg","model":"minimax-m3","content":[{"type":"text","text":"ok"}],"stop_reason":"end_turn","usage":{"input_tokens":1,"output_tokens":1}}'
    )
    with patch.object(client, "_open_provider", return_value=response) as opened:
        result = client._send(
            _agent("minimax-m3"),
            {
                "model": "minimax-m3",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 8,
            },
        )
    assert result == "ok"
    assert opened.call_args.args[0].full_url.endswith("/messages")
    assert client.take_usage() == {
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "total_tokens": 2,
    }
