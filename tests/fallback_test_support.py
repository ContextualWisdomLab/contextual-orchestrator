"""Shared test fixtures for model fallback policy tests."""

from __future__ import annotations

from contextual_orchestrator.model_fallback import (
    CostTier,
    FallbackCandidate,
)


def candidate(
    candidate_id: str,
    model: str,
    *,
    cost_tier: CostTier = CostTier.FREE,
    priority: int = 100,
    credentials: tuple[str, ...] = (),
    visibilities: frozenset[str] = frozenset(
        {"public", "private", "internal"}
    ),
    capabilities: frozenset[str] = frozenset({"text"}),
) -> FallbackCandidate:
    """Build a concise candidate for tests."""
    return FallbackCandidate(
        candidate_id=candidate_id,
        provider="provider",
        model=model,
        cost_tier=cost_tier,
        priority=priority,
        required_credentials=credentials,
        repository_visibilities=visibilities,
        capabilities=capabilities,
    )


def manifest_document() -> dict[str, object]:
    """Return a complete manifest for parsing and CLI tests."""
    return {
        "schema_version": 1,
        "agents": {
            "noema": {
                "candidates": [
                    {
                        "candidate_id": "paid-primary",
                        "provider": "openai",
                        "model": "openai/paid",
                        "cost_tier": "paid",
                        "priority": 0,
                        "required_credentials": ["PAID_API_KEY"],
                        "repository_visibilities": ["public", "private"],
                        "capabilities": ["text", "structured_output"],
                    },
                    {
                        "candidate_id": "free-primary",
                        "provider": "nvidia-nim",
                        "model": "nvidia/free",
                        "cost_tier": "free",
                        "priority": 10,
                        "required_credentials": ["FREE_API_KEY"],
                        "repository_visibilities": ["public"],
                        "capabilities": ["text", "structured_output"],
                    },
                ]
            }
        },
    }
