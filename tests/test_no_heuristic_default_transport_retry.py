"""Fail-closed contracts for default provider transport retry allocation."""

from __future__ import annotations

from contextual_orchestrator.orchestrator import ModelAgent, ModelClient


def test_model_client_default_allocates_no_unproven_retry_attempts() -> None:
    """The library default cannot invent a retry count for provider inference."""
    client = ModelClient()
    agent = ModelAgent(
        "provider_route",
        "arbitrary-chat-model",
        base_url="https://provider.example/v1",
        provider_name="provider",
    )

    assert client.max_retries == 0
    assert client.local_max_retries == 0
    assert client._retry_limit(agent) == 0


def test_default_retry_policy_is_independent_of_model_or_provider_identity() -> None:
    """No name/capability branch may manufacture a default retry budget."""
    client = ModelClient()
    agents = (
        ModelAgent("a_route", "model-a", base_url="https://a.example/v1", provider_name="a"),
        ModelAgent(
            "b_route",
            "model-b",
            base_url="https://b.example/v1",
            provider_name="b",
            reasoning_effort_supported=True,
        ),
    )

    assert {client._retry_limit(agent) for agent in agents} == {0}
