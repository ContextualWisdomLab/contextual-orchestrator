"""Measure semantic warm-start accuracy and decision latency on held-out contexts."""

from __future__ import annotations

import json
import math
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.psychometric_routing import (  # noqa: E402
    PsychometricRoutingEvidence,
)


MODEL_IDS = tuple(f"model_{index}" for index in range(4))
TRAIN_CONTEXTS = 24


def _expected_brier(predicted: float, target: float) -> float:
    return target * (1.0 - target) + (predicted - target) ** 2


def _probability(model_index: int, angle: float) -> float:
    phase = 2.0 * math.pi * model_index / len(MODEL_IDS)
    return 1.0 / (1.0 + math.exp(-2.5 * math.cos(angle - phase)))


def _vector(angle: float) -> list[float]:
    return [math.cos(angle), math.sin(angle)]


def main() -> None:
    """Print seeded held-out probability error, regret, and routing latency."""
    evidence = PsychometricRoutingEvidence(max_contexts=TRAIN_CONTEXTS)
    for context_index in range(TRAIN_CONTEXTS):
        angle = 2.0 * math.pi * context_index / TRAIN_CONTEXTS
        context = f"train_{context_index}"
        evidence.observe(context, MODEL_IDS[0], True, _vector(angle))

    evidence._scores = {
        evidence.context_id(f"train_{context_index}"): {
            model_id: _probability(model_index, 2.0 * math.pi * context_index / TRAIN_CONTEXTS)
            for model_index, model_id in enumerate(MODEL_IDS)
        }
        for context_index in range(TRAIN_CONTEXTS)
    }
    evidence._fit_revision = evidence._revision

    brier_scores: list[float] = []
    log_losses: list[float] = []
    regrets: list[float] = []
    samples_ms: list[float] = []
    for context_index in range(TRAIN_CONTEXTS):
        angle = 2.0 * math.pi * (context_index + 0.5) / TRAIN_CONTEXTS
        started_ns = time.perf_counter_ns()
        ranked = evidence.ranked_evidence(
            MODEL_IDS, f"held_out_{context_index}", _vector(angle)
        )
        samples_ms.append((time.perf_counter_ns() - started_ns) / 1_000_000)
        predicted = dict(ranked)
        truth = {
            model_id: _probability(model_index, angle)
            for model_index, model_id in enumerate(MODEL_IDS)
        }
        for model_id in MODEL_IDS:
            probability = min(max(predicted[model_id], 1e-12), 1.0 - 1e-12)
            target = truth[model_id]
            brier_scores.append(_expected_brier(probability, target))
            log_losses.append(
                -(target * math.log(probability) + (1.0 - target) * math.log(1.0 - probability))
            )
        selected = ranked[0][0]
        regrets.append(max(truth.values()) - truth[selected])

    ordered_ms = sorted(samples_ms)
    result = {
        "brier_score": statistics.fmean(brier_scores),
        "contexts_held_out": TRAIN_CONTEXTS,
        "contexts_train": TRAIN_CONTEXTS,
        "decision_p50_ms": statistics.median(samples_ms),
        "decision_p95_ms": ordered_ms[math.ceil(0.95 * len(ordered_ms)) - 1],
        "log_loss": statistics.fmean(log_losses),
        "models": len(MODEL_IDS),
        "top_choice_regret": statistics.fmean(regrets),
    }
    assert all(math.isfinite(value) for value in result.values())
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
