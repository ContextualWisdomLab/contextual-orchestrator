"""Output budget defaults to the selected model's published ceiling.

The gateway must not impose an arbitrary fixed ``max_tokens`` cap that truncates
a model's own long-form output. When no caller, request, client, or model
metadata ceiling is known, the field is omitted so the provider default governs
instead of a hidden constant.
"""

from __future__ import annotations

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
