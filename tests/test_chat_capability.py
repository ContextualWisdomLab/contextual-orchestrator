"""Boundary tests for model-family chat and orchestration-role capability gates."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.chat_capability import (  # noqa: E402
    is_chat_compatible_model_id,
    is_general_chat_candidate,
    is_general_chat_agent_model_id,
)
from contextual_orchestrator.orchestrator import ModelAgent, _is_general_chat_agent  # noqa: E402


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


@pytest.mark.parametrize(
    "metadata",
    (
        {"capabilities": ("chat",)},
        {"output_modalities": ("text",)},
    ),
)
def test_explicit_chat_metadata_does_not_admit_safety_models(metadata: dict) -> None:
    assert is_general_chat_candidate("vendor/safety-guard", **metadata) is False


def test_single_tool_call_evidence_excludes_general_chat_candidate() -> None:
    """A model that only supports one tool call at a time is not a general chat agent."""
    assert is_general_chat_candidate("vendor/model", supports_parallel_tool_calls=False) is False


def test_unproven_tool_call_parallelism_keeps_existing_eligibility() -> None:
    """No tool-call evidence neither adds nor removes eligibility."""
    assert is_general_chat_candidate("vendor/model", supports_parallel_tool_calls=None) is True
    assert is_general_chat_candidate("vendor/model", supports_parallel_tool_calls=True) is True


def test_conflicting_tool_call_tags_fail_closed() -> None:
    """Malformed operator tags cannot override explicit single-call evidence."""
    agent = ModelAgent(
        "conflicting_tool_agent",
        "vendor/model",
        tags=("tool_call:multi", "tool_call:single"),
    )

    assert _is_general_chat_agent(agent) is False
