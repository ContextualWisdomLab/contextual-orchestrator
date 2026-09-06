"""Regression contracts for text-input eligibility in the general free pool."""

from __future__ import annotations

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.model_discovery import (
    DiscoveredModel,
    general_free_serving_candidates,
)


def test_verified_tools_do_not_admit_image_only_discovered_model() -> None:
    """Tool-call support cannot substitute for positive text-input capability."""
    image_only = DiscoveredModel(
        provider_name="gateway",
        model_id="image-only-tool-model",
        credential_name="GATEWAY_API_KEY",
        chat_base_url="https://gateway.example/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
        input_modalities=("image",),
        output_modalities=("text",),
        is_free=True,
        supports_tool_calls=True,
    )

    assert general_free_serving_candidates([image_only]) == []


def test_verified_tools_do_not_admit_image_only_restored_agent() -> None:
    """Restored agent tags keep text-input and tool-call evidence independent."""
    image_only = ModelAgent(
        "image_tool_agent",
        "image-only-tool-model",
        tags=("cost:free", "input:image", "tool_call:supported"),
    )
    orchestrator = TaskOrchestrator([image_only])

    assert orchestrator._is_general_free_agent(image_only) is False
