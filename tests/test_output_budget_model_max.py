"""Output budget defaults to the selected model's published ceiling.

The gateway must not impose an arbitrary fixed ``max_tokens`` cap that truncates
a model's own long-form output. When no caller, request, client, or model
metadata ceiling is known, the field is omitted so the provider default governs
instead of a hidden constant.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from contextual_orchestrator import ModelAgent
from contextual_orchestrator import orchestrator as orchestrator_module
from contextual_orchestrator.orchestrator import ModelClient, ProviderRequestTooLargeError
from contextual_orchestrator.token_counting import NativeExactTokenCounter


def _remote_agent(**overrides) -> ModelAgent:
    fields = dict(
        id="remote_agent",
        model="remote-chat-model",
        base_url="https://api.example/v1",
        credential_key="REMOTE_API_KEY",
    )
    fields.update(overrides)
    return ModelAgent(**fields)


def _patched_credentials():
    """Bypass KV credential resolution so only payload shaping is under test."""
    return patch.multiple(
        orchestrator_module,
        _provider_credential=lambda _agent: "test-key",
        _provider_credential_name=lambda _agent: None,
    )


def _sent_chat_payload(client: ModelClient, agent: ModelAgent, messages=None) -> dict:
    captured: dict = {}

    def fake_send(_agent, payload, _destination=None, **_kwargs):
        captured["payload"] = payload
        return "ok"

    with patch.object(client, "_validate_provider", return_value=None), _patched_credentials(), patch.object(
        client, "_send_with_retry", side_effect=fake_send
    ):
        client.chat(agent, messages or [{"role": "user", "content": "hi"}])
    return captured["payload"]


def test_client_default_has_no_fixed_output_cap() -> None:
    assert ModelClient().max_output_tokens is None


def test_invalid_client_cap_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_output_tokens"):
        ModelClient(max_output_tokens=0)
    with pytest.raises(ValueError, match="max_output_tokens"):
        ModelClient(max_output_tokens=True)


def test_chat_resolves_agent_published_ceiling() -> None:
    client = ModelClient()
    payload = _sent_chat_payload(client, _remote_agent(max_output_tokens=32768))
    assert payload["max_tokens"] == 32768


def test_chat_omits_cap_when_nothing_known() -> None:
    client = ModelClient()
    payload = _sent_chat_payload(client, _remote_agent())
    assert "max_tokens" not in payload


def test_chat_explicit_client_cap_wins_over_agent_ceiling() -> None:
    client = ModelClient(max_output_tokens=4096)
    payload = _sent_chat_payload(client, _remote_agent(max_output_tokens=32768))
    assert payload["max_tokens"] == 4096


def test_chat_request_scoped_cap_wins() -> None:
    client = ModelClient()
    agent = _remote_agent(max_output_tokens=32768)
    captured: dict = {}

    def fake_send(_agent, payload, _destination=None, **_kwargs):
        captured["payload"] = payload
        return "ok"

    with patch.object(client, "_validate_provider", return_value=None), _patched_credentials(), patch.object(
        client, "_send_with_retry", side_effect=fake_send
    ):
        with client.request_settings(max_output_tokens=777):
            client.chat(agent, [{"role": "user", "content": "hi"}])
    assert captured["payload"]["max_tokens"] == 777


def test_effective_resolution_order() -> None:
    client = ModelClient()
    agent = _remote_agent(max_output_tokens=32768)
    assert client.effective_max_output_tokens(agent) == 32768
    assert client.effective_max_output_tokens(None) is None
    explicit = ModelClient(max_output_tokens=100)
    assert explicit.effective_max_output_tokens(agent) == 100


def test_apply_effort_profile_without_profile_does_not_inject_constant() -> None:
    client = ModelClient()
    payload = client.apply_effort_profile(_remote_agent(), {"model": "m"}, None)
    assert "max_tokens" not in payload


def test_apply_effort_profile_without_profile_uses_agent_ceiling() -> None:
    client = ModelClient()
    payload = client.apply_effort_profile(
        _remote_agent(max_output_tokens=8192), {"model": "m"}, None
    )
    assert payload["max_tokens"] == 8192


def test_responses_surface_omits_cap_when_unknown() -> None:
    client = ModelClient()
    payload = client.apply_effort_profile(
        _remote_agent(), {"model": "m"}, None, api_surface="responses"
    )
    assert "max_tokens" not in payload
    assert "max_output_tokens" not in payload


def test_responses_surface_maps_resolved_ceiling() -> None:
    client = ModelClient()
    payload = client.apply_effort_profile(
        _remote_agent(max_output_tokens=8192),
        {"model": "m"},
        None,
        api_surface="responses",
    )
    assert payload["max_output_tokens"] == 8192
    assert "max_tokens" not in payload


def test_stream_chat_resolves_agent_ceiling() -> None:
    client = ModelClient()
    agent = _remote_agent(max_output_tokens=16384)
    captured: dict = {}

    def fake_stream(_agent, payload, _destination=None):
        captured["payload"] = payload
        return iter(())

    with patch.object(client, "_validate_provider", return_value=None), _patched_credentials(), patch.object(
        client, "_stream_send", side_effect=fake_stream
    ):
        list(client.stream_chat(agent, [{"role": "user", "content": "hi"}]))
    assert captured["payload"]["max_tokens"] == 16384


def test_stream_chat_omits_cap_when_unknown() -> None:
    client = ModelClient()
    captured: dict = {}

    def fake_stream(_agent, payload, _destination=None):
        captured["payload"] = payload
        return iter(())

    with patch.object(client, "_validate_provider", return_value=None), _patched_credentials(), patch.object(
        client, "_stream_send", side_effect=fake_stream
    ):
        list(client.stream_chat(_remote_agent(), [{"role": "user", "content": "hi"}]))
    assert "max_tokens" not in captured["payload"]


def test_local_proxy_still_supplies_resolved_cap() -> None:
    client = ModelClient()
    agent = _remote_agent(
        base_url="mlx://127.0.0.1:59351/v1", max_output_tokens=4096
    )
    captured: dict = {}

    def fake_send_raw(_agent, _endpoint, payload, _destination=None, **_kwargs):
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "ok"}}]}

    with patch.object(client, "_validate_provider", return_value=None), _patched_credentials(), patch.object(
        client, "_send_raw_with_retry", side_effect=fake_send_raw
    ):
        client.proxy_send(agent, "chat/completions", {"model": agent.model})
    assert captured["payload"]["max_tokens"] == 4096


def test_local_proxy_omits_cap_when_nothing_known() -> None:
    """A local server with no known ceiling must not receive the removed constant."""
    client = ModelClient()
    agent = _remote_agent(base_url="local://127.0.0.1:59351/v1")
    captured: dict = {}

    def fake_send_raw(_agent, _endpoint, payload, _destination=None, **_kwargs):
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "ok"}}]}

    with patch.object(client, "_validate_provider", return_value=None), _patched_credentials(), patch.object(
        client, "_send_raw_with_retry", side_effect=fake_send_raw
    ):
        client.proxy_send(agent, "chat/completions", {"model": agent.model})
    assert "max_tokens" not in captured["payload"]


_VERIFIED_MODEL = "gpt-4o-2024-08-06"


def _word_count_native_module():
    """A deterministic stand-in for the optional native tokenizer extension."""
    return type(
        "_StubNativeModule",
        (),
        {
            "count_cl100k": staticmethod(lambda text: len(text.split())),
            "count_o200k": staticmethod(lambda text: len(text.split())),
            "pack_cl100k": staticmethod(lambda *_args: ([], [])),
        },
    )()


def _stub_native_token_counter() -> NativeExactTokenCounter:
    return NativeExactTokenCounter(_word_count_native_module())


def test_shared_context_budget_sent_when_no_caller_budget_and_all_inputs_known() -> None:
    """One message: 3 (tokens_per_message) + role(1) + content(2) + priming(3) = 9."""
    client = ModelClient(token_counter=_stub_native_token_counter())
    agent = _remote_agent(model=_VERIFIED_MODEL, max_output_tokens=50, context_window=20)
    payload = _sent_chat_payload(
        client, agent, messages=[{"role": "user", "content": "hello there"}]
    )
    # remaining = 20 - 9 = 11; ceiling = min(50, 11) = 11.
    assert payload["max_tokens"] == 11
    assert client.take_shared_context_budget() == {
        "context_window": 20,
        "prompt_tokens": 9,
        "output_ceiling": 11,
        "source": "exact",
    }


def test_shared_context_budget_rejects_explicit_caller_budget_over_remaining() -> None:
    client = ModelClient(token_counter=_stub_native_token_counter())
    agent = _remote_agent(model=_VERIFIED_MODEL, max_output_tokens=50, context_window=20)
    with patch.object(client, "_validate_provider", return_value=None), _patched_credentials(), patch.object(
        client, "_send_with_retry"
    ) as fake_send:
        with client.request_settings(max_output_tokens=15):  # remaining is 11
            with pytest.raises(ProviderRequestTooLargeError) as excinfo:
                client.chat(agent, [{"role": "user", "content": "hello there"}])
    fake_send.assert_not_called()
    message = str(excinfo.value)
    assert "context_window=20" in message
    assert "prompt_tokens=9" in message
    assert "requested_output_tokens=15" in message
    assert client.take_shared_context_budget() is None


def test_shared_context_budget_absent_when_context_window_is_unknown() -> None:
    client = ModelClient(token_counter=_stub_native_token_counter())
    agent = _remote_agent(model=_VERIFIED_MODEL, max_output_tokens=50)
    payload = _sent_chat_payload(
        client, agent, messages=[{"role": "user", "content": "hello there"}]
    )
    assert payload["max_tokens"] == 50
    assert client.take_shared_context_budget() is None


def test_shared_context_budget_absent_when_message_count_is_unavailable_for_tools() -> None:
    client = ModelClient(token_counter=_stub_native_token_counter())
    agent = _remote_agent(model=_VERIFIED_MODEL, max_output_tokens=50, context_window=20)
    with patch.object(client, "_validate_provider", return_value=None), _patched_credentials(), patch.object(
        client, "_send_with_retry"
    ) as fake_send:
        with client.request_settings(tools=[{"type": "function", "function": {"name": "noop"}}]):
            client.chat(agent, [{"role": "user", "content": "hello there"}])
    assert fake_send.call_args[0][1]["max_tokens"] == 50
    assert client.take_shared_context_budget() is None


def test_shared_context_budget_rejects_when_remaining_is_below_one() -> None:
    client = ModelClient(token_counter=_stub_native_token_counter())
    agent = _remote_agent(model=_VERIFIED_MODEL, max_output_tokens=50, context_window=5)
    with patch.object(client, "_validate_provider", return_value=None), _patched_credentials(), patch.object(
        client, "_send_with_retry"
    ) as fake_send:
        with pytest.raises(ProviderRequestTooLargeError) as excinfo:
            client.chat(agent, [{"role": "user", "content": "hello there"}])
    fake_send.assert_not_called()
    message = str(excinfo.value)
    assert "context_window=5" in message
    assert "prompt_tokens=9" in message
    assert client.take_shared_context_budget() is None


# -- Streaming send path (_stream_send) -- issue #1157 shared-context follow-up --
# Mirrors the chat() a-d matrix above, applied directly at _stream_send's own
# catalog-clamp site (the exact site the task requires), using the same
# _open_provider capture pattern as
# test_orchestrator_client_boundaries.py::test_stream_send_clamps_known_provider_output_ceiling.


class _StreamResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def __iter__(self):
        return iter(self._lines)


def _streaming_verified_agent(**overrides) -> ModelAgent:
    fields = dict(
        id="stream_remote_agent",
        model=_VERIFIED_MODEL,
        base_url="https://stream.example/v1",
        credential_key="STREAM_API_KEY",
    )
    fields.update(overrides)
    return ModelAgent(**fields)


def _sent_stream_send_payload(client: ModelClient, agent: ModelAgent, payload: dict) -> dict:
    seen_payload: dict = {}
    lines = [b'data: {"choices":[{"delta":{"content":"ok"}}]}', b"data: [DONE]"]

    def open_provider(request, destination=None, timeout=None):
        del destination, timeout
        seen_payload.update(json.loads(request.data.decode("utf-8")))
        return _StreamResponse(lines)

    with patch.object(client, "_open_provider", side_effect=open_provider):
        assert list(client._stream_send(agent, payload)) == ["ok"]
    return seen_payload


def test_stream_send_shared_context_budget_sent_when_no_caller_budget_and_all_inputs_known() -> None:
    """(a) No caller budget, all inputs known: outbound payload and evidence both apply."""
    client = ModelClient(token_counter=_stub_native_token_counter())
    agent = _streaming_verified_agent(max_output_tokens=50, context_window=20)
    payload = _sent_stream_send_payload(
        client,
        agent,
        {"model": agent.model, "messages": [{"role": "user", "content": "hello there"}]},
    )
    # remaining = 20 - 9 = 11; ceiling = min(50, 11) = 11.
    assert payload["max_tokens"] == 11
    assert client.take_shared_context_budget() == {
        "context_window": 20,
        "prompt_tokens": 9,
        "output_ceiling": 11,
        "source": "exact",
    }


def test_stream_send_shared_context_budget_rejects_explicit_caller_budget_over_remaining() -> None:
    """(b) Explicit caller budget over remaining: raise before any provider bytes."""
    client = ModelClient(token_counter=_stub_native_token_counter())
    agent = _streaming_verified_agent(max_output_tokens=50, context_window=20)
    with patch.object(client, "_open_provider") as fake_open:
        # Mirrors chat()'s own "explicit" seam: the request-scoped budget,
        # not whatever catalog default stream_chat() already stuffed into
        # payload["max_tokens"] before _stream_send runs.
        with client.request_settings(max_output_tokens=15):  # remaining is 11
            with pytest.raises(ProviderRequestTooLargeError) as excinfo:
                list(
                    client._stream_send(
                        agent,
                        {
                            "model": agent.model,
                            "messages": [{"role": "user", "content": "hello there"}],
                        },
                    )
                )
    fake_open.assert_not_called()
    message = str(excinfo.value)
    assert "context_window=20" in message
    assert "prompt_tokens=9" in message
    assert "requested_output_tokens=15" in message
    assert client.take_shared_context_budget() is None


def test_stream_send_shared_context_budget_absent_when_message_count_is_unavailable_for_tools() -> None:
    """(c) Unavailable count (tools present): payload unchanged, no evidence."""
    client = ModelClient(token_counter=_stub_native_token_counter())
    agent = _streaming_verified_agent(max_output_tokens=50, context_window=20)
    payload = _sent_stream_send_payload(
        client,
        agent,
        {
            "model": agent.model,
            "messages": [{"role": "user", "content": "hello there"}],
            "max_tokens": 50,
            "tools": [{"type": "function", "function": {"name": "noop"}}],
        },
    )
    assert payload["max_tokens"] == 50
    assert client.take_shared_context_budget() is None


def test_stream_send_shared_context_budget_rejects_when_remaining_is_below_one() -> None:
    """(d) remaining < 1: explicit error naming the prompt size, before any bytes."""
    client = ModelClient(token_counter=_stub_native_token_counter())
    agent = _streaming_verified_agent(max_output_tokens=50, context_window=5)
    with patch.object(client, "_open_provider") as fake_open:
        with pytest.raises(ProviderRequestTooLargeError) as excinfo:
            list(
                client._stream_send(
                    agent,
                    {
                        "model": agent.model,
                        "messages": [{"role": "user", "content": "hello there"}],
                    },
                )
            )
    fake_open.assert_not_called()
    message = str(excinfo.value)
    assert "context_window=5" in message
    assert "prompt_tokens=9" in message
    assert client.take_shared_context_budget() is None


# -- Passthrough/local-proxy send path (_proxy_send) -- issue #1157 follow-up --


def _sent_proxy_payload(client: ModelClient, agent: ModelAgent, body: dict) -> dict:
    captured: dict = {}

    def fake_send_raw(_agent, _endpoint, payload, _destination=None, **_kwargs):
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "ok"}}]}

    with patch.object(client, "_validate_provider", return_value=None), _patched_credentials(), patch.object(
        client, "_send_raw_with_retry", side_effect=fake_send_raw
    ):
        client.proxy_send(agent, "chat/completions", body)
    return captured["payload"]


def test_proxy_shared_context_budget_sent_when_no_caller_budget_and_all_inputs_known() -> None:
    """(a) No caller budget, all inputs known: outbound passthrough body and evidence both apply."""
    client = ModelClient(token_counter=_stub_native_token_counter())
    agent = _remote_agent(model=_VERIFIED_MODEL, max_output_tokens=50, context_window=20)
    payload = _sent_proxy_payload(
        client,
        agent,
        {"model": agent.model, "messages": [{"role": "user", "content": "hello there"}]},
    )
    assert payload["max_tokens"] == 11
    assert client.take_shared_context_budget() == {
        "context_window": 20,
        "prompt_tokens": 9,
        "output_ceiling": 11,
        "source": "exact",
    }


def test_proxy_shared_context_budget_rejects_explicit_caller_budget_over_remaining() -> None:
    """(b) Explicit caller max_tokens over remaining: raise before any provider send."""
    client = ModelClient(token_counter=_stub_native_token_counter())
    agent = _remote_agent(model=_VERIFIED_MODEL, max_output_tokens=50, context_window=20)
    with patch.object(client, "_validate_provider", return_value=None), _patched_credentials(), patch.object(
        client, "_send_raw_with_retry"
    ) as fake_send_raw:
        with pytest.raises(ProviderRequestTooLargeError) as excinfo:
            client.proxy_send(
                agent,
                "chat/completions",
                {
                    "model": agent.model,
                    "messages": [{"role": "user", "content": "hello there"}],
                    "max_tokens": 15,  # remaining is 11
                },
            )
    fake_send_raw.assert_not_called()
    message = str(excinfo.value)
    assert "context_window=20" in message
    assert "prompt_tokens=9" in message
    assert "requested_output_tokens=15" in message
    assert client.take_shared_context_budget() is None


def test_proxy_shared_context_budget_absent_when_messages_are_not_exact_countable() -> None:
    """(c) A Responses-shaped body (no 'messages') leaves no room for a decision."""
    client = ModelClient(token_counter=_stub_native_token_counter())
    agent = _remote_agent(model=_VERIFIED_MODEL, max_output_tokens=50, context_window=20)
    payload = _sent_proxy_payload(
        client, agent, {"model": agent.model, "input": "hello there"}
    )
    assert "max_tokens" not in payload
    assert client.take_shared_context_budget() is None


def test_proxy_shared_context_budget_rejects_when_remaining_is_below_one() -> None:
    """(d) remaining < 1: explicit error naming the prompt size, before any provider send."""
    client = ModelClient(token_counter=_stub_native_token_counter())
    agent = _remote_agent(model=_VERIFIED_MODEL, max_output_tokens=50, context_window=5)
    with patch.object(client, "_validate_provider", return_value=None), _patched_credentials(), patch.object(
        client, "_send_raw_with_retry"
    ) as fake_send_raw:
        with pytest.raises(ProviderRequestTooLargeError) as excinfo:
            client.proxy_send(
                agent,
                "chat/completions",
                {"model": agent.model, "messages": [{"role": "user", "content": "hello there"}]},
            )
    fake_send_raw.assert_not_called()
    message = str(excinfo.value)
    assert "context_window=5" in message
    assert "prompt_tokens=9" in message
    assert client.take_shared_context_budget() is None
