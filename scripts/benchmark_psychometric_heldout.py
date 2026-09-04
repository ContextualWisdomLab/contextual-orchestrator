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
LATENCY_REPETITIONS = 200


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


def _build_evidence(*, two_neighbor: bool) -> PsychometricRoutingEvidence:
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
    return evidence


def _evaluate_quality(
    evidence: PsychometricRoutingEvidence,
) -> tuple[dict[str, float], dict[str, list[float]]]:
    context_brier: list[float] = []
    context_log_loss: list[float] = []
    regrets: list[float] = []
    for context_index in range(TRAIN_CONTEXTS):
        angle = 2.0 * math.pi * (context_index + 0.5) / TRAIN_CONTEXTS
        context = f"held_out_{context_index}"
        vector = _vector(angle)
        ranked = evidence.ranked_evidence(MODEL_IDS, context, vector)
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

    return {
        "brier_score": statistics.fmean(context_brier),
        "log_loss": statistics.fmean(context_log_loss),
        "top_choice_regret": statistics.fmean(regrets),
    }, {
        "brier_score": context_brier,
        "log_loss": context_log_loss,
        "top_choice_regret": regrets,
    }


def _measure_paired_latency(
    baseline: PsychometricRoutingEvidence,
    candidate: PsychometricRoutingEvidence,
) -> tuple[dict[str, float], dict[str, float], list[float], list[float]]:
    all_samples: dict[str, list[float]] = {"baseline": [], "candidate": []}
    context_medians: dict[str, list[float]] = {"baseline": [], "candidate": []}
    for context_index in range(TRAIN_CONTEXTS):
        context = f"held_out_{context_index}"
        vector = _vector(2.0 * math.pi * (context_index + 0.5) / TRAIN_CONTEXTS)
        samples: dict[str, list[float]] = {"baseline": [], "candidate": []}
        for repetition in range(LATENCY_REPETITIONS):
            ordered = (
                (("baseline", baseline), ("candidate", candidate))
                if (context_index + repetition) % 2 == 0
                else (("candidate", candidate), ("baseline", baseline))
            )
            for name, evidence in ordered:
                started_ns = time.perf_counter_ns()
                evidence.ranked_evidence(MODEL_IDS, context, vector)
                samples[name].append((time.perf_counter_ns() - started_ns) / 1_000_000)
        for name in samples:
            all_samples[name].extend(samples[name])
            context_medians[name].append(statistics.median(samples[name]))

    def summary(values: list[float]) -> dict[str, float]:
        ordered = sorted(values)
        return {
            "decision_p50_ms": statistics.median(values),
            "decision_p95_ms": ordered[math.ceil(0.95 * len(ordered)) - 1],
        }

    return (
        summary(all_samples["baseline"]),
        summary(all_samples["candidate"]),
        context_medians["baseline"],
        context_medians["candidate"],
    )


def run_benchmark() -> dict[str, object]:
    """Return paired held-out accuracy uncertainty and decision latency."""
    baseline_evidence = _build_evidence(two_neighbor=False)
    candidate_evidence = _build_evidence(two_neighbor=True)
    baseline, baseline_samples = _evaluate_quality(baseline_evidence)
    candidate, candidate_samples = _evaluate_quality(candidate_evidence)
    baseline_latency, candidate_latency, baseline_medians, candidate_medians = (
        _measure_paired_latency(baseline_evidence, candidate_evidence)
    )
    baseline.update(baseline_latency)
    candidate.update(candidate_latency)
    baseline_samples["decision_median_ms"] = baseline_medians
    candidate_samples["decision_median_ms"] = candidate_medians
    delta = {
        metric: statistics.fmean(candidate_samples[metric])
        - statistics.fmean(baseline_samples[metric])
        for metric in candidate_samples
    }
    delta_ci95 = {
        metric: _paired_bootstrap_mean_ci(
            candidate_samples[metric], baseline_samples[metric]
        )
        for metric in candidate_samples
    }
    result: dict[str, object] = {
        **candidate,
        "baseline": baseline,
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "contexts_held_out": TRAIN_CONTEXTS,
        "contexts_train": TRAIN_CONTEXTS,
        "delta": delta,
        "delta_ci95": delta_ci95,
        "models": len(MODEL_IDS),
        "latency_repetitions_per_context": LATENCY_REPETITIONS,
    }
    assert all(
        math.isfinite(value)
        for metrics in (baseline, candidate)
        for value in metrics.values()
    )
    assert all(
        math.isfinite(delta[metric])
        and delta_ci95[metric][0] <= delta[metric] <= delta_ci95[metric][1]
        for metric in delta
    )
    return result


def main() -> None:
    """Print the held-out benchmark report as stable JSON."""
    result = run_benchmark()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
