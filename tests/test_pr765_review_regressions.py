"""Regression contracts for the PR 765 review findings."""

from __future__ import annotations

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


def test_internal_chat_omits_unrequested_temperature(monkeypatch) -> None:
    """Internal workflow calls must not invent a sampling value unsupported by a model."""
    client = ModelClient()
    agent = ModelAgent(
        id="azure_worker",
        model="azure/gpt-5.5",
        base_url="https://gateway.example.com",
        credential_key="",
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(client, "_validate_provider", lambda _agent: None)

    def capture_payload(_agent, payload, _destination):
        captured.update(payload)
        return "OK"

    monkeypatch.setattr(client, "_send_with_retry", capture_payload)

    assert client.chat(agent, [{"role": "user", "content": "Synthesize."}]) == "OK"
    assert "temperature" not in captured
