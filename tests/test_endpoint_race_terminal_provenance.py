"""Regression coverage for exact terminal provenance in endpoint races."""

from __future__ import annotations

import threading
from concurrent.futures import ALL_COMPLETED, wait as wait_futures

from contextual_orchestrator.endpoint_race import (
    EndpointAttempt,
    EndpointEquivalenceContract,
    race_first_valid,
)


def _contract() -> EndpointEquivalenceContract:
    """Return one complete equivalence contract shared by both attempts."""
    return EndpointEquivalenceContract(
        contract_id="terminal_provenance_contract",
        model_revision="revision_2026_09",
        reasoning_effort_profile="worker_medium",
        capability_set=("text",),
        structured_output_contract="openai_response_v1",
        accuracy_class="full_precision",
        data_residency_policy="kr_region_only",
        retention_policy="zero_retention",
        context_limit=128_000,
        pricing_evidence_id="catalog_snapshot_2026_09_02",
        hedge_eligible=True,
        cancellation_supported=False,
        execution_policy="immediate_race",
    )


def test_failed_completed_loser_is_not_reported_as_successful_completion(monkeypatch) -> None:
    """RaceOutcome must preserve a loser's failed terminal state after it finishes."""
    loser_finished = threading.Event()

    def winner() -> str:
        assert loser_finished.wait(timeout=1)
        return "winner"

    def loser() -> str:
        loser_finished.set()
        raise RuntimeError("synthetic provider failure")

    monkeypatch.setattr(
        "contextual_orchestrator.endpoint_race.wait",
        lambda futures, **_kwargs: (wait_futures(futures, return_when=ALL_COMPLETED)[0], set()),
    )

    outcome = race_first_valid(
        [
            EndpointAttempt("winner_endpoint", _contract(), winner),
            EndpointAttempt("failed_endpoint", _contract(), loser),
        ],
        validate=bool,
        deadline_seconds=1,
        max_concurrency=2,
    )

    assert outcome.winner_endpoint_id == "winner_endpoint"
    assert outcome.cancellation_outcomes == (("failed_endpoint", "failed"),)
