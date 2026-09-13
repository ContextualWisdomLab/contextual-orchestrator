"""Output budget defaults to the selected model's published ceiling.

The gateway must not impose an arbitrary fixed ``max_tokens`` cap that truncates
a model's own long-form output. When no caller, request, client, or model
metadata ceiling is known, the field is omitted so the provider default governs
instead of a hidden constant.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest

from contextual_orchestrator import ModelAgent
from contextual_orchestrator import orchestrator as orchestrator_module
from contextual_orchestrator.orchestrator import (
    ModelClient,
    TaskOrchestrator,
    chat_completion_response,
)


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


def _sent_chat_payload(client: ModelClient, agent: ModelAgent) -> dict:
    captured: dict = {}

    def fake_send(_agent, payload, _destination=None, **_kwargs):
        captured["payload"] = payload
        return "ok"

    with patch.object(client, "_validate_provider", return_value=None), _patched_credentials(), patch.object(
        client, "_send_with_retry", side_effect=fake_send
    ):
        client.chat(agent, [{"role": "user", "content": "hi"}])
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
