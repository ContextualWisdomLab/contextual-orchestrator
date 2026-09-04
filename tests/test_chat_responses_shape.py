"""Bidirectional chat<->responses shape translation and API-version tests.

Covers: the four pure translation functions on realistic OpenAI-documented
payloads (multi-turn messages, tool calls, streaming-adjacent controls); the
shape-capability tag helpers' default and declared behavior; end-to-end
``ModelClient.proxy_send`` routing (a chat-shaped request served by a
Responses-only-declared agent and the mirror direction, plus proof the
default preserves today's plain-passthrough behavior for an untagged
agent); and the per-provider API-version mechanism (header injection, query
injection, and isolation between providers).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402
from contextual_orchestrator.chat_responses_shape import (  # noqa: E402
    agent_supports_chat_completions,
    agent_supports_responses,
    chat_request_to_responses_request,
    chat_response_to_responses_response,
    responses_request_to_chat_request,
    responses_response_to_chat_response,
)
from contextual_orchestrator.provider_api_version import ProviderApiVersion  # noqa: E402


class _Response:
    """A minimal stand-in for the ``http.client`` response ``_open_provider`` returns."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


# ---------------------------------------------------------------------------
# Pure-function translation: realistic, representative fixtures
# ---------------------------------------------------------------------------

CHAT_REQUEST_FIXTURE = {
    "model": "worker-model",
    "messages": [
        {"role": "system", "content": "Be concise."},
        {"role": "user", "content": "What is the weather in Paris?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
            }],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "18C, cloudy"},
        {"role": "user", "content": "Thanks -- and in one sentence?"},
    ],
    "temperature": 0.2,
    "max_tokens": 300,
    "tools": [{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Look up current weather",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
        },
    }],
    "tool_choice": "auto",
}


def test_chat_request_to_responses_request_maps_multiturn_and_tool_calls() -> None:
    translated = chat_request_to_responses_request(CHAT_REQUEST_FIXTURE)

    assert translated["model"] == "worker-model"
    assert translated["max_output_tokens"] == 300
    assert translated["input"][0] == {
        "type": "message",
        "role": "system",
        "content": [{"type": "input_text", "text": "Be concise."}],
    }
    assert translated["input"][1] == {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "What is the weather in Paris?"}],
    }
    assert translated["input"][2] == {
        "type": "function_call",
        "call_id": "call_1",
        "name": "get_weather",
        "arguments": '{"city": "Paris"}',
    }
    assert translated["input"][3] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "18C, cloudy",
    }
    assert translated["input"][4]["role"] == "user"
    assert translated["tools"] == [{
        "type": "function",
        "name": "get_weather",
        "description": "Look up current weather",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
    }]


def test_chat_request_to_responses_preserves_assistant_text_before_tool_calls() -> None:
    translated = chat_request_to_responses_request({
        "messages": [{
            "role": "assistant",
            "content": "I will look that up.",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "lookup", "arguments": "{}"},
            }],
        }],
    })

    assert [item["type"] for item in translated["input"]] == ["message", "function_call"]


def test_chat_request_to_responses_preserves_supported_controls_only() -> None:
    translated = chat_request_to_responses_request({
        "messages": [{"role": "user", "content": "hi"}],
        "store": True,
        "service_tier": "flex",
        "reasoning": {"effort": "high"},
        "stop": ["END"],
        "seed": 7,
        "presence_penalty": 0.2,
        "frequency_penalty": 0.3,
        "logit_bias": {"1": 1},
        "logprobs": True,
    })

    assert translated["store"] is True
    assert translated["service_tier"] == "flex"
    assert translated["reasoning"] == {"effort": "high"}
    for unsupported in (
        "stop", "seed", "presence_penalty", "frequency_penalty", "logit_bias", "logprobs",
    ):
        assert unsupported not in translated


@pytest.mark.parametrize("control", ["modalities", "prediction"])
def test_chat_request_to_responses_rejects_unrepresentable_controls(control: str) -> None:
    with pytest.raises(ValueError, match=control):
        chat_request_to_responses_request({
            "messages": [{"role": "user", "content": "hi"}],
            control: (
                ["text"]
                if control == "modalities"
                else {"type": "content", "content": "x"}
            ),
        })


def test_chat_request_responses_request_round_trips_message_text() -> None:
    """Text content and tool-call/tool-result linkage survive the round trip.

    Message *count* need not match: a chat assistant turn's tool_calls
    become that many separate Responses function_call items (see this
    module's docstring), so the round trip is checked on text content and
    call/output linkage, not on structural identity.
    """
    responses_shaped = chat_request_to_responses_request(CHAT_REQUEST_FIXTURE)
    back = responses_request_to_chat_request(responses_shaped)

    original_texts = [
        (m["role"], m["content"])
        for m in CHAT_REQUEST_FIXTURE["messages"]
        if isinstance(m.get("content"), str) and m["content"]
    ]
    round_tripped_texts = [
        (m["role"], m["content"])
        for m in back["messages"]
        if isinstance(m.get("content"), str) and m["content"]
    ]
    assert round_tripped_texts == original_texts
    tool_call_message = next(m for m in back["messages"] if m.get("tool_calls"))
    assert tool_call_message["tool_calls"][0]["function"]["name"] == "get_weather"
    tool_result_message = next(m for m in back["messages"] if m.get("role") == "tool")
    assert tool_result_message["content"] == "18C, cloudy"
    assert tool_result_message["tool_call_id"] == "call_1"


RESPONSES_REQUEST_FIXTURE = {
    "model": "worker-model",
    "instructions": "Be concise.",
    "input": [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Hi there"}],
        },
    ],
    "max_output_tokens": 200,
    "tools": [{"type": "function", "name": "lookup", "parameters": {"type": "object"}}],
    "tool_choice": {"type": "function", "name": "lookup"},
}


def test_responses_request_to_chat_request_maps_instructions_and_tools() -> None:
    translated = responses_request_to_chat_request(RESPONSES_REQUEST_FIXTURE)

    assert translated["messages"][0] == {"role": "system", "content": "Be concise."}
    assert translated["messages"][1] == {"role": "user", "content": "Hi there"}
    assert translated["max_tokens"] == 200
    assert translated["tools"] == [{
        "type": "function",
        "function": {"name": "lookup", "parameters": {"type": "object"}},
    }]
    assert translated["tool_choice"] == {"type": "function", "function": {"name": "lookup"}}


def test_responses_request_to_chat_request_round_trips_back() -> None:
    chat_shaped = responses_request_to_chat_request(RESPONSES_REQUEST_FIXTURE)
    back = chat_request_to_responses_request(chat_shaped)

    assert back["model"] == "worker-model"
    assert back["max_output_tokens"] == 200
    assert back["input"][0] == {
        "type": "message",
        "role": "system",
        "content": [{"type": "input_text", "text": "Be concise."}],
    }
    assert back["input"][1]["role"] == "user"
    assert back["tools"][0]["name"] == "lookup"


def test_responses_request_to_chat_request_rejects_unsupported_item_type() -> None:
    """Built-in Responses tool-use primitives have no chat equivalent (honest failure)."""
    with pytest.raises(ValueError, match="unsupported Responses input item"):
        responses_request_to_chat_request({"input": [{"type": "web_search_call"}]})


def test_responses_request_to_chat_request_rejects_file_id_image() -> None:
    with pytest.raises(ValueError, match="file_id"):
        responses_request_to_chat_request({
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_image", "file_id": "file_123"},
            ]}],
        })


def test_tool_and_tool_choice_alternate_shapes_are_preserved() -> None:
    flat = {"type": "function", "name": "lookup", "parameters": {"type": "object"}}
    nested = {"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}

    assert chat_request_to_responses_request({
        "tools": [flat], "tool_choice": {"type": "function", "name": "lookup"},
    })["tools"] == [flat]
    assert responses_request_to_chat_request({
        "tools": [nested],
        "tool_choice": {"type": "function", "function": {"name": "lookup"}},
    })["tools"] == [nested]


def test_chat_request_to_responses_request_maps_image_content() -> None:
    payload = {
        "model": "vision-model",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "What is in this image?"},
                {"type": "image_url", "image_url": {"url": "https://example.test/cat.png"}},
            ],
        }],
    }
    translated = chat_request_to_responses_request(payload)

    # Responses' input_image takes image_url as a bare URL string (unlike
    # Chat Completions' nested {"url": ...} object) -- see
    # test_chat_request_to_responses_request_flattens_image_url_object for
    # the dedicated regression test.
    assert translated["input"][0]["content"] == [
        {"type": "input_text", "text": "What is in this image?"},
        {"type": "input_image", "image_url": "https://example.test/cat.png"},
    ]


@pytest.mark.parametrize(
    ("response_format", "expected_text_format"),
    [
        ({"type": "json_object"}, {"type": "json_object"}),
        (
            {"type": "json_schema", "json_schema": {"name": "answer", "schema": {"type": "object"}}},
            {"type": "json_schema", "name": "answer", "schema": {"type": "object"}},
        ),
    ],
)
def test_chat_request_to_responses_request_maps_response_format(
    response_format: dict, expected_text_format: dict
) -> None:
    payload = {
        "model": "worker-model",
        "messages": [{"role": "user", "content": "hi"}],
        "response_format": response_format,
    }
    translated = chat_request_to_responses_request(payload)

    assert translated["text"]["format"] == expected_text_format


# ---------------------------------------------------------------------------
# Response translation
# ---------------------------------------------------------------------------

CHAT_RESPONSE_FIXTURE = {
    "id": "chatcmpl-abc",
    "model": "worker-model",
    "created": 1000,
    "choices": [{
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_9",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'},
            }],
        },
        "finish_reason": "tool_calls",
    }],
    "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
}


def test_chat_response_to_responses_response_preserves_tool_call_and_usage() -> None:
    translated = chat_response_to_responses_response(CHAT_RESPONSE_FIXTURE, {"model": "worker-model"})

    assert translated["object"] == "response"
    function_calls = [item for item in translated["output"] if item["type"] == "function_call"]
    assert function_calls[0]["name"] == "get_weather"
    assert function_calls[0]["arguments"] == '{"city":"Paris"}'
    assert translated["usage"] == {"input_tokens": 12, "output_tokens": 5, "total_tokens": 17}


def test_responses_response_to_chat_response_round_trips() -> None:
    responses_shaped = chat_response_to_responses_response(CHAT_RESPONSE_FIXTURE, {"model": "worker-model"})
    back = responses_response_to_chat_response(responses_shaped, {"model": "worker-model"})

    message = back["choices"][0]["message"]
    assert message["tool_calls"][0]["function"]["name"] == "get_weather"
    assert message["tool_calls"][0]["function"]["arguments"] == '{"city":"Paris"}'
    assert back["choices"][0]["finish_reason"] == "tool_calls"
    assert back["usage"] == {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17}


def test_responses_response_to_chat_response_maps_incomplete_status_to_length() -> None:
    data = {
        "id": "resp_x",
        "model": "m",
        "created_at": 1,
        "output": [{
            "type": "message",
            "content": [{"type": "output_text", "text": "partial"}],
        }],
        "status": "incomplete",
        "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
    }
    back = responses_response_to_chat_response(data, {"model": "m"})

    assert back["choices"][0]["finish_reason"] == "length"
    assert back["choices"][0]["message"]["content"] == "partial"
    assert back["id"] == "chatcmpl_x"


def test_responses_response_maps_content_filter_finish_reason() -> None:
    back = responses_response_to_chat_response({
        "status": "incomplete",
        "incomplete_details": {"reason": "content_filter"},
        "output": [],
    }, {"model": "m"})
    assert back["choices"][0]["finish_reason"] == "content_filter"


# ---------------------------------------------------------------------------
# Shape-capability tag helper defaults
# ---------------------------------------------------------------------------

def test_shape_capability_defaults_to_passthrough_for_both_shapes() -> None:
    """No tags means unproven, not incompatible -- today's passthrough default."""
    assert agent_supports_chat_completions(()) is True
    assert agent_supports_responses(()) is True


def test_shape_capability_declares_chat_completions_only() -> None:
    tags = ("api:chat_completions_only",)
    assert agent_supports_chat_completions(tags) is True
    assert agent_supports_responses(tags) is False


def test_shape_capability_declares_responses_only() -> None:
    tags = ("api:responses_only",)
    assert agent_supports_responses(tags) is True
    assert agent_supports_chat_completions(tags) is False


def test_shape_capability_rejects_conflicting_exclusivity_tags() -> None:
    tags = ("api:chat_completions_only", "api:responses_only")
    with pytest.raises(ValueError, match="conflicting API shape tags"):
        agent_supports_responses(tags)
    with pytest.raises(ValueError, match="conflicting API shape tags"):
        agent_supports_chat_completions(tags)


# ---------------------------------------------------------------------------
# End-to-end ModelClient.proxy_send behavioral tests
# ---------------------------------------------------------------------------

def test_untagged_remote_agent_gets_plain_passthrough_for_responses() -> None:
    """The default preserves today's behavior: no translation, no guessing."""
    agent = ModelAgent(
        "plain_remote_agent",
        "gpt-remote",
        base_url="https://provider.example.test/v1",
        provider_name="openai",
    )
    client = ModelClient(max_retries=0)
    with patch.object(client, "_validate_provider", return_value=None), patch.object(
        client, "_send_raw_with_retry", return_value={"id": "resp_1", "object": "response"},
    ) as send:
        result = client.proxy_send(agent, "responses", {"model": "gpt-remote", "input": "Hello"})

    assert send.call_args.args[1] == "responses"
    assert send.call_args.args[2] == {"model": "gpt-remote", "input": "Hello"}
    assert result == {"id": "resp_1", "object": "response"}


def test_chat_shaped_request_routed_to_responses_only_agent_translates_both_ways() -> None:
    """A caller sends chat shape; the selected agent is proven Responses-only."""
    agent = ModelAgent(
        "responses_only_agent",
        "responses-model",
        base_url="https://responses-only.example.test/v1",
        tags=("api:responses_only",),
    )
    client = ModelClient(max_retries=0)
    with patch.object(client, "_validate_provider", return_value=None), patch.object(
        client,
        "_send_raw_with_retry",
        return_value={
            "id": "resp_xyz",
            "object": "response",
            "created_at": 500,
            "model": "responses-model",
            "output": [{
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Paris is sunny.", "annotations": []}],
            }],
            "output_text": "Paris is sunny.",
            "status": "completed",
            "usage": {"input_tokens": 4, "output_tokens": 3, "total_tokens": 7},
        },
    ) as send:
        result = client.proxy_send(
            agent,
            "chat/completions",
            {
                "model": "responses-model",
                "messages": [{"role": "user", "content": "Weather in Paris?"}],
            },
        )

    # The upstream call actually hit the responses endpoint in responses shape.
    assert send.call_args.args[1] == "responses"
    forwarded = send.call_args.args[2]
    assert "messages" not in forwarded
    assert forwarded["input"] == [{
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "Weather in Paris?"}],
    }]

    # The caller gets back chat shape.
    assert result["object"] == "chat.completion"
    assert result["choices"][0]["message"]["content"] == "Paris is sunny."
    assert result["usage"] == {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7}


def test_responses_shaped_request_routed_to_chat_completions_only_agent_translates_both_ways() -> None:
    """The mirror direction: a remote (non-local) agent proven Chat-Completions-only."""
    agent = ModelAgent(
        "chat_only_agent",
        "chat-only-model",
        base_url="https://chat-only.example.test/v1",
        tags=("api:chat_completions_only",),
    )
    client = ModelClient(max_retries=0)
    with patch.object(client, "_validate_provider", return_value=None), patch.object(
        client,
        "_send_raw_with_retry",
        return_value={
            "id": "chatcmpl-1",
            "model": "chat-only-model",
            "created": 10,
            "choices": [{
                "message": {"role": "assistant", "content": "Hi there"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        },
    ) as send:
        result = client.proxy_send(agent, "responses", {"model": "chat-only-model", "input": "Hello"})

    assert send.call_args.args[1] == "chat/completions"
    assert send.call_args.args[2]["messages"] == [{"role": "user", "content": "Hello"}]
    assert result["object"] == "response"
    assert result["output_text"] == "Hi there"


def test_chat_only_endpoint_rejects_file_id_image_before_provider_egress() -> None:
    agent = ModelAgent(
        "chat_only_agent",
        "chat-only-model",
        base_url="https://chat-only.example.test/v1",
        tags=("api:chat_completions_only",),
    )
    client = ModelClient(max_retries=0)
    with patch.object(client, "_validate_provider", return_value=None), patch.object(
        client, "_send_raw_with_retry",
    ) as send, pytest.raises(ValueError, match="file_id"):
        client.proxy_send(agent, "responses", {
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_image", "file_id": "file_123"},
            ]}],
        })
    send.assert_not_called()


def test_responses_only_endpoint_preserves_flat_tool_shape_and_controls() -> None:
    agent = ModelAgent(
        "responses_only_agent",
        "responses-model",
        base_url="https://responses-only.example.test/v1",
        tags=("api:responses_only",),
    )
    client = ModelClient(max_retries=0)
    with patch.object(client, "_validate_provider", return_value=None), patch.object(
        client,
        "_send_raw_with_retry",
        return_value={"status": "completed", "output": []},
    ) as send:
        client.proxy_send(agent, "chat/completions", {
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [{"type": "function", "name": "lookup", "parameters": {}}],
            "tool_choice": {"type": "function", "name": "lookup"},
            "store": True,
            "service_tier": "flex",
            "reasoning": {"effort": "high"},
        })

    forwarded = send.call_args.args[2]
    assert forwarded["tools"][0]["name"] == "lookup"
    assert forwarded["tool_choice"] == {"type": "function", "name": "lookup"}
    assert forwarded["store"] is True
    assert forwarded["service_tier"] == "flex"
    assert forwarded["reasoning"] == {"effort": "high"}


def test_chat_only_endpoint_preserves_nested_tool_shape() -> None:
    agent = ModelAgent(
        "chat_only_agent",
        "chat-only-model",
        base_url="https://chat-only.example.test/v1",
        tags=("api:chat_completions_only",),
    )
    client = ModelClient(max_retries=0)
    with patch.object(client, "_validate_provider", return_value=None), patch.object(
        client,
        "_send_raw_with_retry",
        return_value={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        },
    ) as send:
        client.proxy_send(agent, "responses", {
            "input": "hi",
            "tools": [{
                "type": "function",
                "function": {"name": "lookup", "parameters": {}},
            }],
            "tool_choice": {"type": "function", "function": {"name": "lookup"}},
        })

    forwarded = send.call_args.args[2]
    assert forwarded["tools"][0]["function"]["name"] == "lookup"
    assert forwarded["tool_choice"] == {
        "type": "function", "function": {"name": "lookup"},
    }


def test_endpoint_rejects_conflicting_exclusivity_tags_before_provider_egress() -> None:
    agent = ModelAgent(
        "conflicting_agent",
        "model",
        base_url="https://provider.example.test/v1",
        tags=("api:chat_completions_only", "api:responses_only"),
    )
    client = ModelClient(max_retries=0)
    with patch.object(client, "_validate_provider", return_value=None), patch.object(
        client, "_send_raw_with_retry",
    ) as send, pytest.raises(ValueError, match="conflicting API shape tags"):
        client.proxy_send(agent, "responses", {"input": "hi"})
    send.assert_not_called()


# ---------------------------------------------------------------------------
# Per-provider API-version mechanism
# ---------------------------------------------------------------------------

def test_declared_header_version_is_injected_on_every_request() -> None:
    agent = ModelAgent(
        "versioned_header_agent",
        "model-x",
        base_url="mlx://127.0.0.1:8080/v1",
        provider_name="test_header_provider",
    )
    client = ModelClient(max_retries=0)
    seen = []

    def open_provider(request, _destination=None):
        seen.append(request)
        return _Response({"choices": [{"message": {"content": "OK"}}]})

    version = ProviderApiVersion(header_name="anthropic-version", value="2023-06-01")
    with patch(
        "contextual_orchestrator.orchestrator.api_version_for",
        side_effect=lambda name: version if name == "test_header_provider" else None,
    ), patch.object(client, "_open_provider", side_effect=open_provider):
        client.chat(agent, [{"role": "user", "content": "ping"}])

    assert seen[0].get_header("Anthropic-version") == "2023-06-01"


def test_declared_header_version_is_injected_on_local_model_registry_probe() -> None:
    """Readiness must authenticate the versioned registry request like inference."""
    agent = ModelAgent(
        "versioned_probe_agent",
        "model-x",
        base_url="mlx://127.0.0.1:8080/v1",
        provider_name="test_header_provider",
    )
    client = ModelClient(max_retries=0)
    seen = []

    def open_provider(request, _destination=None, timeout=None):
        """Capture registry and inference requests with valid fixture responses."""
        seen.append(request)
        if request.full_url.endswith("/models"):
            return _Response({"data": [{"id": "model-x"}]})
        return _Response({"choices": [{"message": {"content": "OK"}}]})

    version = ProviderApiVersion(header_name="anthropic-version", value="2023-06-01")
    with patch(
        "contextual_orchestrator.orchestrator.api_version_for",
        side_effect=lambda name: version if name == "test_header_provider" else None,
    ), patch.object(client, "_open_provider", side_effect=open_provider):
        result = client.probe(agent)

    assert result["status"] == "ready"
    assert len(seen) == 2
    assert seen[0].get_header("Anthropic-version") == "2023-06-01"
    assert seen[1].get_header("Anthropic-version") == "2023-06-01"


def test_declared_query_param_version_is_appended_to_the_url() -> None:
    agent = ModelAgent(
        "versioned_query_agent",
        "model-y",
        base_url="mlx://127.0.0.1:8080/v1",
        provider_name="test_query_provider",
    )
    client = ModelClient(max_retries=0)
    seen = []

    def open_provider(request, _destination=None):
        seen.append(request)
        return _Response({"choices": [{"message": {"content": "OK"}}]})

    version = ProviderApiVersion(query_param_name="api-version", value="2024-10-21")
    with patch(
        "contextual_orchestrator.orchestrator.api_version_for",
        side_effect=lambda name: version if name == "test_query_provider" else None,
    ), patch.object(client, "_open_provider", side_effect=open_provider):
        client.chat(agent, [{"role": "user", "content": "ping"}])

    assert seen[0].full_url == "http://127.0.0.1:8080/v1/chat/completions?api-version=2024-10-21"


def test_undeclared_provider_sends_no_version_and_never_leaks_anothers() -> None:
    """A provider absent from the registry is unaffected -- and another
    provider's declared version never leaks onto its requests."""
    plain_agent = ModelAgent(
        "plain_agent",
        "model-z",
        base_url="mlx://127.0.0.1:8080/v1",
        provider_name="plain_provider",
    )
    client = ModelClient(max_retries=0)
    seen = []

    def open_provider(request, _destination=None):
        seen.append(request)
        return _Response({"choices": [{"message": {"content": "OK"}}]})

    versioned = ProviderApiVersion(header_name="anthropic-version", value="2023-06-01")
    with patch(
        "contextual_orchestrator.orchestrator.api_version_for",
        side_effect=lambda name: versioned if name == "some_other_provider" else None,
    ), patch.object(client, "_open_provider", side_effect=open_provider):
        client.chat(plain_agent, [{"role": "user", "content": "ping"}])

    assert seen[0].full_url == "http://127.0.0.1:8080/v1/chat/completions"
    assert seen[0].get_header("Anthropic-version") is None


def test_provider_api_version_requires_header_or_query_param() -> None:
    with pytest.raises(ValueError, match="header_name or query_param_name"):
        ProviderApiVersion(value="1.0")


def test_provider_api_version_requires_non_empty_value() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        ProviderApiVersion(header_name="x-version")


def test_api_version_for_returns_none_for_unregistered_or_empty_provider_name() -> None:
    from contextual_orchestrator.provider_api_version import api_version_for

    assert api_version_for("") is None
    assert api_version_for("nonexistent_provider_xyz") is None


def test_apply_query_param_replaces_rather_than_duplicates_existing_param() -> None:
    from contextual_orchestrator.provider_api_version import apply_query_param

    version = ProviderApiVersion(query_param_name="api-version", value="2024-10-21")
    url = apply_query_param("https://example.test/v1/chat?api-version=old&foo=bar", version)

    assert url == "https://example.test/v1/chat?api-version=2024-10-21&foo=bar"


def test_apply_header_and_query_param_are_no_ops_for_none_version() -> None:
    from contextual_orchestrator.provider_api_version import apply_header, apply_query_param

    headers: dict[str, str] = {}
    apply_header(headers, None)
    assert headers == {}
    assert apply_query_param("https://example.test/v1/chat", None) == "https://example.test/v1/chat"


# ---------------------------------------------------------------------------
# Internal worker request shape: synchronous chat remains fail-closed while
# stream_chat translates live Responses SSE through the shared transport.
# ---------------------------------------------------------------------------

def test_chat_raises_for_responses_only_agent_instead_of_silent_wrong_shape() -> None:
    agent = ModelAgent(
        "responses_only_worker",
        "responses-model",
        base_url="https://responses-only.example.test/v1",
        tags=("api:responses_only",),
    )
    client = ModelClient(max_retries=0)
    with pytest.raises(ValueError, match="api:responses_only"):
        client.chat(agent, [{"role": "user", "content": "hi"}])


def test_stream_chat_translates_for_responses_only_agent() -> None:
    agent = ModelAgent(
        "responses_only_worker",
        "responses-model",
        base_url="https://responses-only.example.test/v1",
        tags=("api:responses_only",),
    )
    client = ModelClient(max_retries=0)
    with patch.object(client, "_validate_provider", return_value=None), patch.object(
        client, "_stream_send", return_value=iter(("one", " two")),
    ) as send:
        assert list(client.stream_chat(agent, [{"role": "user", "content": "hi"}])) == [
            "one", " two",
        ]

    forwarded = send.call_args.args[1]
    assert send.call_args.kwargs == {"endpoint": "responses", "response_shape": "responses"}
    assert "messages" not in forwarded
    assert forwarded["input"][0]["content"] == [{"type": "input_text", "text": "hi"}]
    assert forwarded["stream"] is True


def test_probe_uses_responses_endpoint_for_responses_only_agent() -> None:
    agent = ModelAgent(
        "responses_only_worker",
        "responses-model",
        base_url="https://responses-only.example.test/v1",
        tags=("api:responses_only",),
    )
    client = ModelClient(max_retries=0)
    with patch.object(client, "_validate_provider", return_value=None), patch.object(
        client, "_send_raw", return_value={
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "OK"}]}],
        },
    ) as send:
        result = client.probe(agent)
    assert result["status"] == "ready"
    assert send.call_args.args[1] == "responses"
    assert send.call_args.args[2]["input"] == "Reply with exactly OK."


def test_batch_chat_raises_for_responses_only_agent_instead_of_silent_wrong_shape() -> None:
    """ModelClient.batch_chat() shares chat()/stream_chat()'s gap: it always
    submits Chat Completions shape to the provider's Batch API with no
    translation branch of its own, so it must fail closed for a
    responses_only agent instead of being silently rejected upstream."""
    agent = ModelAgent(
        "responses_only_worker",
        "responses-model",
        base_url="https://responses-only.example.test/v1",
        tags=("api:responses_only",),
    )
    client = ModelClient(max_retries=0)
    with pytest.raises(ValueError, match="api:responses_only"):
        client.batch_chat(agent, {"one": [{"role": "user", "content": "hi"}]})


def test_chat_request_to_responses_request_prefers_max_completion_tokens() -> None:
    """max_completion_tokens is the current field name; it must not be silently
    dropped in favor of the deprecated max_tokens when both/either is present."""
    only_new_field = chat_request_to_responses_request({
        "model": "m", "messages": [{"role": "user", "content": "hi"}],
        "max_completion_tokens": 111,
    })
    assert only_new_field["max_output_tokens"] == 111

    both_fields = chat_request_to_responses_request({
        "model": "m", "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 50, "max_completion_tokens": 222,
    })
    assert both_fields["max_output_tokens"] == 222


def test_chat_request_to_responses_request_flattens_image_url_object() -> None:
    """Chat's image_url is {"url", "detail"}; real Responses-API providers need
    input_image.image_url as a bare URL string with detail as a sibling field."""
    payload = {
        "model": "vision-model",
        "messages": [{
            "role": "user",
            "content": [{
                "type": "image_url",
                "image_url": {"url": "https://example.test/cat.png", "detail": "high"},
            }],
        }],
    }
    translated = chat_request_to_responses_request(payload)
    image_item = translated["input"][0]["content"][0]
    assert image_item == {
        "type": "input_image",
        "image_url": "https://example.test/cat.png",
        "detail": "high",
    }


def test_chat_still_works_for_chat_completions_only_and_untagged_agents() -> None:
    """Guard against over-broadly blocking chat() for every tagged agent."""
    client = ModelClient(max_retries=0)
    for tags in ((), ("api:chat_completions_only",)):
        agent = ModelAgent(
            "chat_capable_worker",
            "some-model",
            base_url="mock://local",
            tags=tags,
        )
        # mock:// short-circuits before any shape concern; reaching it proves
        # the new guard didn't reject an agent that may legitimately serve
        # Chat Completions shape.
        assert client.chat(agent, [{"role": "user", "content": "hi"}])
