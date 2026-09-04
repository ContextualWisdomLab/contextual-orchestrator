"""Measure gateway overhead around a fixed psychometric fit seam."""

from __future__ import annotations

import json
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.psychometric_routing import (  # noqa: E402
    PsychometricRoutingEvidence,
)


def _require_runtime(version_info: tuple[int, ...] = sys.version_info) -> None:
    if tuple(version_info[:2]) < (3, 12):
        raise SystemExit(
            "psychometric routing benchmark requires Python 3.12 or newer; "
            "run: uv run --python 3.12 python scripts/benchmark_psychometric_routing.py"
        )


def main() -> None:
    """Print repeatable fit-preparation and ranking latency in milliseconds."""
    _require_runtime()
    import numpy as np

    model_ids = [f"model_{model_index}" for model_index in range(4)]
    evidence = PsychometricRoutingEvidence(max_contexts=512)
    for context_index in range(512):
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
            ranked = evidence.ranked_evidence(
                model_ids, "context_511", [1.0, 512.0]
            )
            samples_ms.append((time.perf_counter_ns() - started_ns) / 1_000_000)

    assert len(ranked) == len(model_ids)
    observation_samples_ms: list[float] = []
    for sample_index in range(101):
        started_ns = time.perf_counter_ns()
        evidence.observe(
            "context_511",
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
                "contexts": 512,
                "models": len(model_ids),
                "items_per_context": 2,
                "median_fit_and_rank_ms": statistics.median(samples_ms),
                "median_observe_ms": statistics.median(observation_samples_ms),
                "p95_observe_ms": sorted(observation_samples_ms)[95],
                "samples_ms": samples_ms,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
