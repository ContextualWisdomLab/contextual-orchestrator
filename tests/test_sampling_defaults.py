"""Sampling defaults must not disable providers with narrower capabilities."""

from __future__ import annotations

from unittest.mock import patch

from contextual_orchestrator import ModelAgent
from contextual_orchestrator.orchestrator import ModelClient


def _remote_agent() -> ModelAgent:
    return ModelAgent(
        "reasoning_agent",
        "reasoning-model",
        base_url="https://provider.example/v1",
        credential_key="TEST_PROVIDER_API_KEY",
    )


def test_chat_omits_temperature_when_caller_does_not_provide_one() -> None:
    client = ModelClient()
    captured: list[dict] = []

    def send(_agent, payload, _destination):
        captured.append(payload)
        return "answer"

    with (
        patch.object(client, "_validate_provider", return_value=object()),
        patch("contextual_orchestrator.orchestrator._provider_credential", return_value="secret"),
        patch.object(client, "_send_with_retry", side_effect=send),
    ):
        assert client.chat(_remote_agent(), [{"role": "user", "content": "hello"}]) == "answer"

    assert "temperature" not in captured[0]


def test_chat_forwards_an_explicit_temperature() -> None:
    client = ModelClient()
    captured: list[dict] = []

    def send(_agent, payload, _destination):
        captured.append(payload)
        return "answer"

    with (
        patch.object(client, "_validate_provider", return_value=object()),
        patch("contextual_orchestrator.orchestrator._provider_credential", return_value="secret"),
        patch.object(client, "_send_with_retry", side_effect=send),
    ):
        client.chat(
            _remote_agent(),
            [{"role": "user", "content": "hello"}],
            temperature=0.2,
        )

    assert captured[0]["temperature"] == 0.2
