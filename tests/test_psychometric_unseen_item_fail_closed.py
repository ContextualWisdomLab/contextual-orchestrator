"""Regression contracts for evidence-only psychometric routing."""

from __future__ import annotations

from contextual_orchestrator.psychometric_routing import PsychometricRoutingEvidence


def test_unseen_prompt_cannot_borrow_nearest_observed_item_score() -> None:
    """Embedding proximity alone is not calibrated evidence for a new IRT item."""
    evidence = PsychometricRoutingEvidence()
    observed_prompt = "system policy / observed request"
    observed_id = evidence.context_id(observed_prompt)
    evidence._contexts[observed_id] = [1.0, 0.0]
    evidence._scores = {observed_id: {"measured_model": 0.91}}
    evidence._fit_revision = evidence._revision

    assert evidence.ranked_evidence(
        ["measured_model"], observed_prompt, [1.0, 0.0]
    ) == [("measured_model", 0.91)]
    assert evidence.ranked_evidence(
        ["measured_model"], "different unseen request", [1.0, 0.0]
    ) == []


def test_observation_ledger_has_no_implicit_context_eviction_threshold() -> None:
    """Observed item evidence is not discarded by the former arbitrary 512-item cap."""
    evidence = PsychometricRoutingEvidence()
    for index in range(513):
        evidence.observe(f"prompt-{index}", "measured_model", bool(index % 2), None)

    assert len(evidence.records()) == 513
