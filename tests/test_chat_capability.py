"""Boundary tests for model-family chat and orchestration-role capability gates."""

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
    (
        "bge-small-en",
        "clip-vit",
        "dall-e-3",
        "e5-large",
        "embed-model",
        "embedding-model",
        "embeddings-v2",
        "gte-base",
        "image-model",
        "images-v2",
        "moderation-latest",
        "realtime-preview",
        "rerank-v3",
        "reranker-large",
        "siglip-base",
        "sora-video",
        "speech-model",
        "transcribe-large",
        "transcription-v2",
        "tts-1",
        "whisper-1",
    ),
)
def test_endpoint_only_model_families_cannot_use_chat_transport(model_id: str) -> None:
    """Reject every explicitly known endpoint-only model family."""
    assert is_chat_compatible_model_id(model_id) is False
    assert is_general_chat_agent_model_id(model_id) is False


@pytest.mark.parametrize("model_id", ("embedder-v2", "moderator-v1", "reranking-v1", "transcriber-v1"))
def test_endpoint_prefixes_reject_unlisted_model_variants(model_id: str) -> None:
    """Reject future-looking family variants without matching exact tokens."""
    assert is_chat_compatible_model_id(model_id) is False


def test_empty_and_non_string_identifiers_fail_closed() -> None:
    """Unknown identifier shapes never become eligible by accident."""
    assert is_chat_compatible_model_id("") is False
    assert is_chat_compatible_model_id(None) is False  # type: ignore[arg-type]
    assert is_general_chat_agent_model_id("") is False


@pytest.mark.parametrize("model_id", ("safety-classifier", "guard-model", "shieldgemma-2b", "nemo_guard_v2"))
def test_transport_compatible_policy_models_stay_out_of_general_agent_roles(model_id: str) -> None:
    """Safety and guard models may use chat transport but are not thinkers."""
    assert is_chat_compatible_model_id(model_id) is True
    assert is_general_chat_agent_model_id(model_id) is False


def test_normal_chat_identifier_remains_eligible() -> None:
    """A normal provider model remains eligible for both ordinary gates."""
    assert is_chat_compatible_model_id("provider/gpt-5.5") is True
    assert is_general_chat_agent_model_id("provider/gpt-5.5") is True
