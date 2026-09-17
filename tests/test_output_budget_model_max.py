"""Output budget defaults to the selected model's published ceiling.

The gateway must not impose an arbitrary fixed ``max_tokens`` cap that truncates
a model's own long-form output. When no caller, request, client, or model
metadata ceiling is known, the field is omitted so the provider default governs
instead of a hidden constant.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest.mock import patch

import pytest

from contextual_orchestrator import ModelAgent
from contextual_orchestrator import orchestrator as orchestrator_module
from contextual_orchestrator.endpoint_race import EndpointEquivalenceContract
from contextual_orchestrator.orchestrator import (
    ModelClient,
    ProviderRequestTooLargeError,
    TaskOrchestrator,
    chat_completion_response,
)
from contextual_orchestrator.server import SecurityConfig, build_server
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

# -- output-budget clamp evidence (issue #1169 / ADR 0130) --------------------
#
# ``_clamp_agent_token_budget`` silently rewrites an explicit caller budget
# down to the agent's published ceiling with no way for the caller to tell.
# ``_clamp_agent_token_budget_with_evidence`` performs the same clamp but also
# records, on this thread, what was requested and what was actually applied so
# the orchestration trace and the OpenAI-shaped response can say so honestly.


@contextmanager
def _fake_open_provider(*_args: Any, **_kwargs: Any):
    """Stand in for a provider HTTP response carrying one assistant message."""

    class _FakeResponse:
        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")

    yield _FakeResponse()


def test_clamp_evidence_records_requested_and_effective_tokens_when_clamped() -> None:
    agent = _remote_agent(max_output_tokens=64)
    client = ModelClient()
    payload = {"max_tokens": 256}

    clamped = client._clamp_agent_token_budget_with_evidence(agent, payload)

    assert clamped == {"max_tokens": 64}
    assert client.take_output_budget() == {
        "requested_output_tokens": 256,
        "effective_output_tokens": 64,
        "output_budget_clamped": True,
    }
    # Evidence is consumed exactly once, mirroring take_usage()/take_assistant_message().
    assert client.take_output_budget() is None


def test_clamp_evidence_reports_unclamped_when_within_ceiling() -> None:
    agent = _remote_agent(max_output_tokens=64)
    client = ModelClient()
    payload = {"max_tokens": 32}

    clamped = client._clamp_agent_token_budget_with_evidence(agent, payload)

    assert clamped == {"max_tokens": 32}
    assert client.take_output_budget() == {
        "requested_output_tokens": 32,
        "effective_output_tokens": 32,
        "output_budget_clamped": False,
    }


def test_clamp_evidence_absent_without_an_explicit_budget_field() -> None:
    agent = _remote_agent(max_output_tokens=64)
    client = ModelClient()

    clamped = client._clamp_agent_token_budget_with_evidence(agent, {"model": agent.model})

    assert clamped == {"model": agent.model}
    assert client.take_output_budget() is None


def test_chat_end_to_end_records_clamp_evidence_on_explicit_request() -> None:
    """A real ``chat()`` call whose request-scoped budget exceeds the agent
    ceiling must leave clamp evidence for the caller to read afterward."""
    client = ModelClient()
    agent = _remote_agent(max_output_tokens=64)
    with patch.object(client, "_validate_provider", return_value=None), _patched_credentials(), patch.object(
        client, "_open_provider", side_effect=_fake_open_provider
    ):
        with client.request_settings(max_output_tokens=256):
            client.chat(agent, [{"role": "user", "content": "hi"}])
    assert client.take_output_budget() == {
        "requested_output_tokens": 256,
        "effective_output_tokens": 64,
        "output_budget_clamped": True,
    }


def test_chat_end_to_end_omits_clamp_when_request_fits() -> None:
    client = ModelClient()
    agent = _remote_agent(max_output_tokens=256)
    with patch.object(client, "_validate_provider", return_value=None), _patched_credentials(), patch.object(
        client, "_open_provider", side_effect=_fake_open_provider
    ):
        client.chat(agent, [{"role": "user", "content": "hi"}])
    assert client.take_output_budget() == {
        "requested_output_tokens": 256,
        "effective_output_tokens": 256,
        "output_budget_clamped": False,
    }


class _ClampedBudgetClient:
    """Duck-typed ``ModelClient`` stub whose one call always reports fixed clamp evidence.

    Matches the existing duck-typed test clients in
    ``tests/test_actions_model_fallback.py``: ``TaskOrchestrator._invoke`` only
    calls ``take_usage``/``take_assistant_message``/``take_output_budget``
    through ``hasattr`` guards, so a minimal stub is enough to prove the
    orchestrator threads the evidence from the client into the trace row and
    the top-level result it returns.
    """

    def __init__(self, requested: int, effective: int, clamped: bool) -> None:
        self._budget = {
            "requested_output_tokens": requested,
            "effective_output_tokens": effective,
            "output_budget_clamped": clamped,
        }

    def request_settings_snapshot(self) -> dict[str, Any]:
        return {
            "temperature": None,
            "top_p": None,
            "presence_penalty": None,
            "frequency_penalty": None,
        }

    @contextmanager
    def request_settings(self, **overrides: Any):
        del overrides
        yield

    def chat(self, agent: ModelAgent, messages: list, **kwargs: Any) -> str:
        del agent, messages, kwargs
        return "the answer"

    def take_usage(self) -> None:
        return None

    def take_assistant_message(self) -> None:
        return None

    def take_output_budget(self) -> dict[str, Any]:
        return dict(self._budget)


def test_route_trace_and_response_surface_clamp_evidence_when_clamped() -> None:
    agent = _remote_agent(id="worker_agent", max_output_tokens=64)
    client = _ClampedBudgetClient(requested=256, effective=64, clamped=True)
    orchestrator = TaskOrchestrator([agent], client=client)

    result = orchestrator.complete([{"role": "user", "content": "hi"}], mode="route")

    trace_row = result["trace"][-1]
    assert trace_row["requested_output_tokens"] == 256
    assert trace_row["effective_output_tokens"] == 64
    assert trace_row["output_budget_clamped"] is True
    assert result["requested_output_tokens"] == 256
    assert result["effective_output_tokens"] == 64
    assert result["output_budget_clamped"] is True

    response = chat_completion_response(result, model="m")
    assert response["orchestration"]["requested_output_tokens"] == 256
    assert response["orchestration"]["effective_output_tokens"] == 64
    assert response["orchestration"]["output_budget_clamped"] is True


def test_route_trace_and_response_report_unclamped_when_not_clamped() -> None:
    agent = _remote_agent(id="worker_agent", max_output_tokens=256)
    client = _ClampedBudgetClient(requested=64, effective=64, clamped=False)
    orchestrator = TaskOrchestrator([agent], client=client)

    result = orchestrator.complete([{"role": "user", "content": "hi"}], mode="route")

    trace_row = result["trace"][-1]
    assert trace_row["output_budget_clamped"] is False
    assert result["output_budget_clamped"] is False

    response = chat_completion_response(result, model="m")
    assert response["orchestration"]["output_budget_clamped"] is False


# -- ADR 0130 follow-up sites: immediate_race, structured/free_only synthesis,
# -- and true-streaming passthrough now also surface clamp evidence -----------


def _text_race_contract(**changes: Any) -> EndpointEquivalenceContract:
    values: dict[str, Any] = dict(
        contract_id="shared_contract",
        model_revision="revision_2026_08",
        reasoning_effort_profile="worker_medium",
        capability_set=("text",),
        structured_output_contract="openai_response_v1",
        accuracy_class="full_precision",
        data_residency_policy="kr_region_only",
        retention_policy="zero_retention",
        context_limit=128_000,
        pricing_evidence_id="catalog_snapshot_2026_08_26",
        hedge_eligible=True,
        cancellation_supported=False,
        execution_policy="immediate_race",
    )
    values.update(changes)
    return EndpointEquivalenceContract(**values)  # type: ignore[arg-type]


def _race_agents(*, max_output_tokens: int) -> list[ModelAgent]:
    raw_contract = dict(_text_race_contract().__dict__)
    return [
        ModelAgent(
            endpoint_id,
            "provider/shared",
            tags=("reasoning",),
            group_name="shared_text_group",
            endpoint_equivalence=raw_contract,
            max_output_tokens=max_output_tokens,
        )
        for endpoint_id in ("first_endpoint", "second_endpoint")
    ]


def test_immediate_race_winner_surfaces_clamp_evidence_when_clamped() -> None:
    """(a) The multi-endpoint immediate_race branch records the winner's clamp evidence."""
    agents = _race_agents(max_output_tokens=64)
    orchestrator = TaskOrchestrator(agents)

    def chat(agent: ModelAgent, _messages: list[dict], **_kwargs: object) -> str:
        return f"completed by {agent.id}"

    orchestrator.client.chat = chat  # type: ignore[method-assign]
    orchestrator.client.take_output_budget = lambda: {  # type: ignore[method-assign]
        "requested_output_tokens": 256,
        "effective_output_tokens": 64,
        "output_budget_clamped": True,
    }

    result = orchestrator.route_once(
        [{"role": "user", "content": "use the declared replica group"}],
        model_name="shared-text-group",
    )

    trace_row = result["trace"][0]
    assert trace_row["requested_output_tokens"] == 256
    assert trace_row["effective_output_tokens"] == 64
    assert trace_row["output_budget_clamped"] is True
    assert result["requested_output_tokens"] == 256
    assert result["effective_output_tokens"] == 64
    assert result["output_budget_clamped"] is True

    response = chat_completion_response(result, model="m")
    assert response["orchestration"]["requested_output_tokens"] == 256
    assert response["orchestration"]["effective_output_tokens"] == 64
    assert response["orchestration"]["output_budget_clamped"] is True


def test_immediate_race_winner_reports_unclamped_when_not_clamped() -> None:
    """(a) An unclamped race winner still names ``output_budget_clamped: false``."""
    agents = _race_agents(max_output_tokens=256)
    orchestrator = TaskOrchestrator(agents)

    def chat(agent: ModelAgent, _messages: list[dict], **_kwargs: object) -> str:
        return f"completed by {agent.id}"

    orchestrator.client.chat = chat  # type: ignore[method-assign]
    orchestrator.client.take_output_budget = lambda: {  # type: ignore[method-assign]
        "requested_output_tokens": 64,
        "effective_output_tokens": 64,
        "output_budget_clamped": False,
    }

    result = orchestrator.route_once(
        [{"role": "user", "content": "use the declared replica group"}],
        model_name="shared-text-group",
    )

    trace_row = result["trace"][0]
    assert trace_row["output_budget_clamped"] is False
    assert result["output_budget_clamped"] is False

    response = chat_completion_response(result, model="m")
    assert response["orchestration"]["output_budget_clamped"] is False


def _structured_workflow() -> dict[str, object]:
    """Return bounded pre-synthesis evidence, bypassing the conduct workflow itself."""
    return {
        "mode": "conduct",
        "answer": "evidence",
        "trace": [],
        "verification": {},
        "plan_source": "template",
    }


def _tools_request(model: str, *, max_tokens: int) -> dict[str, object]:
    """Build one virtual chat request whose ``tools`` key opts into synthesis."""
    return {
        "model": model,
        "messages": [{"role": "user", "content": "call a tool"}],
        "max_tokens": max_tokens,
        "tools": [
            {
                "type": "function",
                "function": {"name": "noop", "parameters": {"type": "object"}},
            }
        ],
    }


def test_structured_synthesis_surfaces_clamp_evidence_when_clamped() -> None:
    """(b) The structured/free_only synthesis send site records clamp evidence."""
    agent = _remote_agent(id="synth_agent", max_output_tokens=64)
    orchestrator = TaskOrchestrator([agent])

    with (
        patch.object(orchestrator, "conduct", return_value=_structured_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=agent),
        patch.object(orchestrator, "_ranked_agents", return_value=[agent]),
        patch.object(orchestrator.client, "_validate_provider", return_value=None),
        _patched_credentials(),
        patch.object(orchestrator.client, "_open_provider", side_effect=_fake_open_provider),
    ):
        result = orchestrator.proxy_completion(
            _tools_request(TaskOrchestrator.AUTO_MODEL, max_tokens=256),
            single_agent=False,
        )

    assert result["orchestration"]["requested_output_tokens"] == 256
    assert result["orchestration"]["effective_output_tokens"] == 64
    assert result["orchestration"]["output_budget_clamped"] is True


def test_structured_synthesis_reports_unclamped_when_not_clamped() -> None:
    """(b) An unclamped structured/free_only synthesis request stays honest about it."""
    agent = _remote_agent(id="synth_agent", max_output_tokens=256)
    orchestrator = TaskOrchestrator([agent])

    with (
        patch.object(orchestrator, "conduct", return_value=_structured_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=agent),
        patch.object(orchestrator, "_ranked_agents", return_value=[agent]),
        patch.object(orchestrator.client, "_validate_provider", return_value=None),
        _patched_credentials(),
        patch.object(orchestrator.client, "_open_provider", side_effect=_fake_open_provider),
    ):
        result = orchestrator.proxy_completion(
            _tools_request(TaskOrchestrator.AUTO_MODEL, max_tokens=64),
            single_agent=False,
        )

    assert result["orchestration"]["requested_output_tokens"] == 64
    assert result["orchestration"]["effective_output_tokens"] == 64
    assert result["orchestration"]["output_budget_clamped"] is False


class _CapturingSSEProvider:
    """Minimal local OpenAI-compatible SSE provider for the true-streaming site."""

    def __init__(self, frames: list[str]) -> None:
        self.payloads: list[dict] = []
        payloads = self.payloads

        class Handler(BaseHTTPRequestHandler):
            def do_POST(inner_self) -> None:  # noqa: N802
                length = int(inner_self.headers.get("content-length", 0))
                payloads.append(json.loads(inner_self.rfile.read(length).decode("utf-8")))
                inner_self.send_response(200)
                inner_self.send_header("content-type", "text/event-stream")
                inner_self.end_headers()
                for frame in frames:
                    inner_self.wfile.write(frame.encode("utf-8"))
                    inner_self.wfile.flush()

            def log_message(inner_self, *args: object) -> None:
                del inner_self, args

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "_CapturingSSEProvider":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        del exc
        self._server.shutdown()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"


def _sse_delta(content: str) -> str:
    return "data: " + json.dumps({"choices": [{"delta": {"content": content}}]}) + "\n\n"


def _post_stream(port: int, token: str, *, max_tokens: int) -> str:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(
            {
                "model": "gpt-x",
                "messages": [{"role": "user", "content": "stream"}],
                "mode": "route",
                "max_tokens": max_tokens,
                "stream": True,
            }
        ).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "connection": "close",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read().decode("utf-8")


def _final_stream_frame(body: str) -> dict:
    frames = [
        json.loads(line[len("data: "):])
        for line in body.split("\n\n")
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    for frame in reversed(frames):
        if frame.get("choices") and frame["choices"][0].get("finish_reason") == "stop":
            return frame
    raise AssertionError(f"no finish=stop frame found in {frames!r}")


def test_streaming_passthrough_final_chunk_surfaces_clamp_evidence_when_clamped() -> None:
    """(c) The true-streaming (_stream_send/proxy_send) path carries clamp evidence
    on the final SSE chunk's ``orchestration`` object, mirroring
    ``chat_completion_chunks`` (evidence is only known after ``_begin_sse`` has
    already flushed headers, so it cannot ride a response header instead)."""
    frames = [_sse_delta("hi"), "data: [DONE]\n\n"]
    token = "clamp_stream_token"
    with _CapturingSSEProvider(frames) as provider:
        orchestrator = TaskOrchestrator(
            [
                ModelAgent(
                    "worker_agent",
                    "gpt-x",
                    base_url=provider.base_url.replace("http://", "local://"),
                    max_output_tokens=64,
                )
            ]
        )
        server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            body = _post_stream(server.server_address[1], token, max_tokens=256)
        finally:
            server.shutdown()
            thread.join(timeout=5)

    final_frame = _final_stream_frame(body)
    assert final_frame["orchestration"]["requested_output_tokens"] == 256
    assert final_frame["orchestration"]["effective_output_tokens"] == 64
    assert final_frame["orchestration"]["output_budget_clamped"] is True


def test_streaming_passthrough_final_chunk_reports_unclamped_when_not_clamped() -> None:
    """(c) An unclamped streaming request still names ``output_budget_clamped: false``."""
    frames = [_sse_delta("hi"), "data: [DONE]\n\n"]
    token = "unclamped_stream_token"
    with _CapturingSSEProvider(frames) as provider:
        orchestrator = TaskOrchestrator(
            [
                ModelAgent(
                    "worker_agent",
                    "gpt-x",
                    base_url=provider.base_url.replace("http://", "local://"),
                    max_output_tokens=256,
                )
            ]
        )
        server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            body = _post_stream(server.server_address[1], token, max_tokens=64)
        finally:
            server.shutdown()
            thread.join(timeout=5)

    final_frame = _final_stream_frame(body)
    assert final_frame["orchestration"]["requested_output_tokens"] == 64
    assert final_frame["orchestration"]["effective_output_tokens"] == 64
    assert final_frame["orchestration"]["output_budget_clamped"] is False