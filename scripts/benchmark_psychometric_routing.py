"""Measure gateway overhead around a fixed psychometric fit seam."""

from __future__ import annotations

import json
import math
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CONTEXT_COUNT = 512
CRITERION_ITEMS_PER_OBSERVATION = 1
OBSERVATION_REPETITIONS = 101


def _require_runtime(
    version_info: tuple[int, ...] | None = None,
    *,
    benchmark_script: str = "scripts/benchmark_psychometric_routing.py",
) -> None:
    if tuple((sys.version_info if version_info is None else version_info)[:2]) < (3, 12):
        raise SystemExit(
            "psychometric routing benchmark requires Python 3.12 or newer; "
            f"run: uv run --python 3.12 python {benchmark_script}"
        )


def _last_context_request(context_count: int) -> tuple[str, list[float]]:
    """Return the exact-match context id and score vector for the final context."""
    if context_count < 1:
        raise ValueError("context_count must be positive")
    return f"context_{context_count - 1}", [1.0, float(context_count)]


def main() -> None:
    """Print repeatable fit-preparation and ranking latency in milliseconds."""
    _require_runtime()
    import numpy as np
    from contextual_orchestrator.psychometric_routing import PsychometricRoutingEvidence

    model_ids = [f"model_{model_index}" for model_index in range(4)]
    last_context, last_vector = _last_context_request(CONTEXT_COUNT)
    evidence = PsychometricRoutingEvidence(max_contexts=CONTEXT_COUNT)
    for context_index in range(CONTEXT_COUNT):
        for model_index, model_id in enumerate(model_ids):
            accepted = (context_index + model_index) % 2 == 0
            evidence.observe(
                f"context_{context_index}",
                model_id,
                accepted,
                [1.0, float(context_index + 1)],
                irt_row=(int(not accepted),),
            )

    fit_result = SimpleNamespace(
        convergence_status="converged", params=None, model="MLSRM"
    )
    samples_ms: list[float] = []
    with (
        patch("fast_mlsirm.fit_irt_experiment", return_value=fit_result),
        patch(
            "fast_mlsirm.predict_proba",
            side_effect=lambda _params, factor_id, *, model: np.full(
                (len(model_ids), len(factor_id)), 0.5
            ),
        ),
    ):
        for _ in range(9):
            evidence._fit_revision = -1
            started_ns = time.perf_counter_ns()
            ranked = evidence.ranked_evidence(model_ids, last_context, last_vector)
            samples_ms.append((time.perf_counter_ns() - started_ns) / 1_000_000)

    assert len(ranked) == len(model_ids)
    observation_samples_ms: list[float] = []
    for sample_index in range(OBSERVATION_REPETITIONS):
        started_ns = time.perf_counter_ns()
        evidence.observe(
            last_context,
            "model_3",
            bool(sample_index % 2),
            None,
            irt_row=(int(not sample_index % 2),),
        )
        observation_samples_ms.append(
            (time.perf_counter_ns() - started_ns) / 1_000_000
        )
    print(
        json.dumps(
            {
                "contexts": CONTEXT_COUNT,
                "models": len(model_ids),
                # Acceptance is item zero; irt_row adds one criterion item.
                "items_per_context": 1 + CRITERION_ITEMS_PER_OBSERVATION,
                "median_fit_and_rank_ms": statistics.median(samples_ms),
                "median_observe_ms": statistics.median(observation_samples_ms),
                "p95_observe_ms": sorted(observation_samples_ms)[
                    math.ceil(0.95 * len(observation_samples_ms)) - 1
                ],
                "samples_ms": samples_ms,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
