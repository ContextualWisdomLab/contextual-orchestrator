"""Fail-closed contracts for model-group routing decision authority."""

from __future__ import annotations

import inspect

from contextual_orchestrator.model_group import ModelGroupRouter
from contextual_orchestrator.orchestrator import TaskOrchestrator


def test_uncalibrated_sampling_has_no_runtime_activation_surface() -> None:
    """A research note alone cannot activate a composite live-routing policy."""
    assert "rng" not in inspect.signature(ModelGroupRouter).parameters
    assert not hasattr(ModelGroupRouter, "sampled_ranked_member_ids")


def test_live_member_order_exposes_no_sampling_switch() -> None:
    """Callers cannot opt into an unvalidated stochastic selection path."""
    assert "sample" not in inspect.signature(TaskOrchestrator._measured_member_order).parameters
