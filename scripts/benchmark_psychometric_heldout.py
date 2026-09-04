"""Measure semantic warm-start accuracy and decision latency on held-out contexts."""

from __future__ import annotations

import json
import math
from pathlib import Path
import random
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.psychometric_routing import (  # noqa: E402
    PsychometricRoutingEvidence,
)


MODEL_IDS = tuple(f"model_{index}" for index in range(4))
TRAIN_CONTEXTS = 24
BOOTSTRAP_SAMPLES = 2_000
BOOTSTRAP_SEED = 568


def _expected_brier(predicted: float, target: float) -> float:
    return target * (1.0 - target) + (predicted - target) ** 2


def _probability(model_index: int, angle: float) -> float:
    phase = 2.0 * math.pi * model_index / len(MODEL_IDS)
    return 1.0 / (1.0 + math.exp(-2.5 * math.cos(angle - phase)))


def _vector(angle: float) -> list[float]:
    return [math.cos(angle), math.sin(angle)]


def _paired_bootstrap_mean_ci(
    candidate: list[float], baseline: list[float]
) -> list[float]:
    """Return a deterministic paired 95% interval for candidate-minus-baseline."""
    if not candidate or len(candidate) != len(baseline):
        raise ValueError("paired samples must be non-empty and equal length")
    differences = [left - right for left, right in zip(candidate, baseline)]
    generator = random.Random(BOOTSTRAP_SEED)
    means = sorted(
        statistics.fmean(generator.choices(differences, k=len(differences)))
        for _ in range(BOOTSTRAP_SAMPLES)
    )
    return [means[math.floor(0.025 * BOOTSTRAP_SAMPLES)], means[math.ceil(0.975 * BOOTSTRAP_SAMPLES) - 1]]


def _evaluate(*, two_neighbor: bool) -> tuple[dict[str, float], dict[str, list[float]]]:
    evidence = PsychometricRoutingEvidence(
        max_contexts=TRAIN_CONTEXTS, semantic_warm_start_enabled=two_neighbor
    )
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

    context_brier: list[float] = []
    context_log_loss: list[float] = []
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
        brier_scores: list[float] = []
        log_losses: list[float] = []
        for model_id in MODEL_IDS:
            probability = min(max(predicted[model_id], 1e-12), 1.0 - 1e-12)
            target = truth[model_id]
            brier_scores.append(_expected_brier(probability, target))
            log_losses.append(
                -(target * math.log(probability) + (1.0 - target) * math.log(1.0 - probability))
            )
        context_brier.append(statistics.fmean(brier_scores))
        context_log_loss.append(statistics.fmean(log_losses))
        selected = ranked[0][0]
        regrets.append(max(truth.values()) - truth[selected])

    ordered_ms = sorted(samples_ms)
    return {
        "brier_score": statistics.fmean(context_brier),
        "decision_p50_ms": statistics.median(samples_ms),
        "decision_p95_ms": ordered_ms[math.ceil(0.95 * len(ordered_ms)) - 1],
        "log_loss": statistics.fmean(context_log_loss),
        "top_choice_regret": statistics.fmean(regrets),
    }, {
        "brier_score": context_brier,
        "log_loss": context_log_loss,
        "top_choice_regret": regrets,
    }


def main() -> None:
    """Print paired held-out accuracy uncertainty and decision latency."""
    baseline, baseline_samples = _evaluate(two_neighbor=False)
    candidate, candidate_samples = _evaluate(two_neighbor=True)
    result = {
        **candidate,
        "baseline": baseline,
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "contexts_held_out": TRAIN_CONTEXTS,
        "contexts_train": TRAIN_CONTEXTS,
        "delta_ci95": {
            metric: _paired_bootstrap_mean_ci(
                candidate_samples[metric], baseline_samples[metric]
            )
            for metric in candidate_samples
        },
        "models": len(MODEL_IDS),
    }
    assert all(
        math.isfinite(value)
        for metrics in (baseline, candidate)
        for value in metrics.values()
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
