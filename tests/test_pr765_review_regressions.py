"""Regression contracts for the PR 765 review findings."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from contextual_orchestrator import server
from contextual_orchestrator.orchestrator import ModelAgent, ModelClient


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "properties": []},
        {"type": "object", "required": ["answer", 7]},
        {"type": "array", "items": []},
    ],
)
def test_malformed_json_schema_is_rejected_before_response_validation(schema) -> None:
    with pytest.raises(server.RequestError) as captured:
        server._validate_chat_response_format(
            {
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "answer", "schema": schema},
                }
            }
        )
    assert captured.value.status == 400
    assert captured.value.code == "invalid_response_format"


@pytest.mark.parametrize(
    "field",
    [
        "temperature",
        "top_p",
        "presence_penalty",
        "frequency_penalty",
        "seed",
        "stop",
        "logit_bias",
        "logprobs",
        "top_logprobs",
    ],
)
def test_unapplied_responses_controls_fail_closed(field) -> None:
    values = {
        "temperature": 0.2,
        "top_p": 0.9,
        "presence_penalty": 0.1,
        "frequency_penalty": -0.1,
        "seed": 42,
        "stop": ["END"],
        "logit_bias": {"1": 1},
        "logprobs": True,
        "top_logprobs": 3,
    }
    with pytest.raises(server.RequestError) as captured:
        server._reject_responses_orchestration_controls({field: values[field]})
    assert captured.value.status == 400
    assert captured.value.code == "unsupported_responses_orchestration_controls"
    assert captured.value.detail == {"fields": [field]}


def test_empty_responses_controls_remain_omit_equivalent() -> None:
    server._reject_responses_orchestration_controls(
        {
            "temperature": None,
            "stop": "",
            "logit_bias": {},
            "logprobs": False,
            "top_logprobs": 0,
        }
    )


def test_internal_chat_preserves_explicit_temperature(monkeypatch) -> None:
    """An explicit caller sampling control remains an honest provider passthrough."""
    client = ModelClient()
    agent = ModelAgent(
        id="chat_worker",
        model="provider/model",
        base_url="https://gateway.example.com",
        credential_key="",
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(client, "_validate_provider", lambda _agent: None)

    def capture_payload(_agent, payload, _destination=None, *, timeout=None):
        del timeout
        captured.update(payload)
        return "OK"

    monkeypatch.setattr(client, "_send", capture_payload)

    assert client.chat(
        agent,
        [{"role": "user", "content": "Sample."}],
        temperature=0.2,
    ) == "OK"
    assert captured["temperature"] == 0.2


@pytest.mark.parametrize(
    "userinfo_url",
    [
        "https://@gateway.example.com/v1/models",
        "https://:secret@gateway.example.com/v1/models",
    ],
)
def test_provider_json_rejects_empty_userinfo_before_provider_transport(userinfo_url: str) -> None:
    """An empty username or password is still userinfo and cannot bypass origin checks."""
    agent = ModelAgent(
        id="model_discovery_agent",
        model="model_catalog",
        base_url="https://gateway.example.com/v1",
        credential_key="",
    )
    client = ModelClient()
    with (
        patch.object(client, "_validate_provider") as validate_provider,
        patch.object(client, "_open_provider") as open_provider,
        pytest.raises(RuntimeError, match="validated agent origin"),
    ):
        client.fetch_json(agent, userinfo_url)
    validate_provider.assert_not_called()
    open_provider.assert_not_called()
