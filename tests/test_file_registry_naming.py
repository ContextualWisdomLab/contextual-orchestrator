"""Naming-contract regressions for the file-registry bounded context."""

from __future__ import annotations

import inspect

from contextual_orchestrator.file_registry import FileRegistry, file_agent_affinity_key


def test_file_registry_owned_parameters_use_bounded_context_names() -> None:
    """Keep owned Python seams specific while OpenAI payload keys stay external."""
    assert tuple(inspect.signature(file_agent_affinity_key).parameters) == ("model_agent",)
    assert tuple(inspect.signature(FileRegistry.public_response).parameters) == (
        "provider_document",
        "file_owner",
    )
    assert tuple(inspect.signature(FileRegistry.retain_replicas).parameters) == (
        "self",
        "gateway_file_id",
        "owner_id",
        "provider_replicas",
    )
    assert tuple(inspect.signature(FileRegistry.bind_request).parameters) == (
        "self",
        "request_document",
        "owner_id",
    )
