"""Regression coverage for chat transport versus ordinary agent-role eligibility."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.chat_capability import (  # noqa: E402
    is_chat_compatible_model_id,
    is_general_chat_agent_model_id,
)


@pytest.mark.parametrize(
    "model_id",
    [
        "gpt-audio",
        "gpt-audio-mini",
        "nvidia/llama-3.1-nemotron-safety-guard-8b-v3",
        "nvidia/llama-3.1-nemoguard-8b-content-safety",
        "nvidia/llama-3.1-nemoguard-8b-topic-control",
    ],
)
def test_chat_served_models_remain_transport_compatible(model_id: str) -> None:
    """Do not pre-reject models that provider contracts serve through chat completions."""
    assert is_chat_compatible_model_id(model_id)


@pytest.mark.parametrize(
    "model_id",
    [
        "nvidia/llama-3.1-nemotron-safety-guard-8b-v3",
        "nvidia/llama-3.1-nemoguard-8b-content-safety",
        "nvidia/llama-3.1-nemoguard-8b-topic-control",
    ],
)
def test_policy_classifiers_do_not_enter_general_agent_roles(model_id: str) -> None:
    """Keep chat-served policy classifiers out of ordinary synthesis roles."""
    assert not is_general_chat_agent_model_id(model_id)


@pytest.mark.parametrize(
    "model_id",
    [
        "gpt-audio",
        "gpt-audio-mini",
        "gpt-5.2",
        "qwen/qwen3-235b-a22b-instruct",
    ],
)
def test_general_generation_models_remain_agent_eligible(model_id: str) -> None:
    """Preserve chat generation models for ordinary agent selection."""
    assert is_general_chat_agent_model_id(model_id)


@pytest.mark.parametrize(
    "model_id",
    [
        "azure/text-embedding-3-large",
        "text_embedding_3_large",
        "company/reranker-v2",
        "gpt-4o-mini-transcribe",
        "omni-moderation-latest",
        "gpt-image-1",
        "sora-2",
        "gpt-realtime",
        "tts-1",
    ],
)
def test_endpoint_only_models_fail_both_boundaries(model_id: str) -> None:
    """Reject endpoint-only model families before transport or ordinary role routing."""
    assert not is_chat_compatible_model_id(model_id)
    assert not is_general_chat_agent_model_id(model_id)
