"""Fail closed while observed-health admission has no released authority."""

from __future__ import annotations

import inspect

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)


def test_uncalibrated_constructor_activation_is_not_supported() -> None:
    """A boolean opt-in cannot authorize heuristic model admission."""
    assert "observed_health_quarantine" not in inspect.signature(TaskOrchestrator).parameters
    with pytest.raises(TypeError, match="observed_health_quarantine"):
        TaskOrchestrator(
            [ModelAgent("worker_one", "mock/worker")],
            observed_health_quarantine=True,
        )


def test_uncalibrated_kv_activation_has_no_runtime_surface() -> None:
    """A KV flag cannot substitute for released calibration evidence."""
    set_backend(InMemoryCredentialBackend())
    try:
        register_credential(
            "CONTEXTUAL_ORCHESTRATOR_OBSERVED_HEALTH_QUARANTINE", "enabled"
        )
        orchestrator = TaskOrchestrator([ModelAgent("worker_one", "mock/worker")])
        assert not hasattr(orchestrator, "observed_health_quarantine")
    finally:
        set_backend(None)
