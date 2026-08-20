"""Regression tests for chat-capability checks on passthrough and batch paths."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402


def _embedding_agent() -> ModelAgent:
    """Build the stale embedding agent from the production incident."""
    return ModelAgent(
        "embedding_agent",
        "azure/text-embedding-3-large",
        base_url="mock://local",
    )


def _chat_agent() -> ModelAgent:
    """Build one compatible fallback for explicit-model passthrough tests."""
    return ModelAgent(
        "general_chat_agent",
        "gpt-5.2",
        base_url="mock://local",
        tags=("writing",),
    )


@pytest.mark.parametrize("endpoint", ["chat/completions", "/v1/chat/completions", "responses", "/v1/responses"])
def test_proxy_send_rejects_embedding_before_mock_or_network_transport(endpoint: str) -> None:
    """Keep raw OpenAI passthrough from bypassing the chat transport invariant."""
    client = ModelClient()

    with pytest.raises(ValueError, match="chat-compatible"):
        client.proxy_send(
            _embedding_agent(),
            endpoint,
            {
                "model": "azure/text-embedding-3-large",
                "messages": [{"role": "user", "content": "Return JSON."}],
                "input": "Return JSON.",
            },
        )


def test_explicit_embedding_model_cannot_bypass_through_structured_passthrough() -> None:
    """Reject an explicitly requested stale embedding agent before raw proxy transport."""
    orchestrator = TaskOrchestrator([_embedding_agent(), _chat_agent()])

    with pytest.raises(ValueError, match="chat-compatible"):
        orchestrator.proxy_completion(
            {
                "model": "azure/text-embedding-3-large",
                "messages": [{"role": "user", "content": "Return JSON."}],
                "response_format": {"type": "json_object"},
            }
        )


def test_explicit_embedding_model_cannot_bypass_through_responses_passthrough() -> None:
    """Apply the same transport contract to the Responses passthrough path."""
    orchestrator = TaskOrchestrator([_embedding_agent(), _chat_agent()])

    with pytest.raises(ValueError, match="chat-compatible"):
        orchestrator.proxy_completion(
            {
                "model": "azure/text-embedding-3-large",
                "input": "Return JSON.",
            },
            endpoint="responses",
        )


def test_batch_chat_rejects_embedding_before_mock_or_network_transport() -> None:
    """Prevent direct batch callers from submitting embedding models as chat jobs."""
    client = ModelClient()

    with pytest.raises(ValueError, match="chat-compatible"):
        client.batch_chat(
            _embedding_agent(),
            {"task_0": [{"role": "user", "content": "Return JSON."}]},
        )


@pytest.mark.parametrize(
    "model_id",
    [
        "gpt-audio",
        "nvidia/llama-3.1-nemotron-safety-guard-8b-v3",
    ],
)
def test_chat_served_specialized_models_remain_valid_passthrough_transports(model_id: str) -> None:
    """Do not turn ordinary-role exclusion into a false transport rejection."""
    client = ModelClient()
    agent = ModelAgent("specialized_chat_agent", model_id, base_url="mock://local")

    response = client.proxy_send(
        agent,
        "chat/completions",
        {
            "model": model_id,
            "messages": [{"role": "user", "content": "Classify this."}],
        },
    )

    assert response["object"] == "chat.completion"
    assert response["model"] == model_id
