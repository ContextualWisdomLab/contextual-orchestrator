"""Measure semantic warm-start accuracy and decision latency on held-out contexts."""

from __future__ import annotations

import json
import math
from pathlib import Path
import random
import statistics
import sys
import time
from types import SimpleNamespace

import fast_mlsirm
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.psychometric_routing import (  # noqa: E402
    PsychometricRoutingEvidence,
)


MODEL_IDS = tuple(f"model_{index}" for index in range(4))
UNSEEN_MODEL_ID = "model_unseen"
TRAIN_CONTEXTS = 24
BOOTSTRAP_SAMPLES = 2_000
BOOTSTRAP_SEED = 568
LATENCY_REPETITIONS = 200
ASSIGNMENT_TRIALS = 24_000
ASSIGNMENT_SEED = 260_905
EXPLORATION_RATE = 0.2
DIF_SAMPLE_SIZE = 4_000
DIF_SEED = 260_906
JUDGE_SAMPLE_SIZE = 1_000
JUDGE_SEED = 260_907
ITEM_COVARIATE_SAMPLE_SIZE = 1_200
ITEM_COVARIATE_SEED = 260_908
UNCERTAINTY_SAMPLE_SIZE = 1_200
UNCERTAINTY_SEED = 260_909
INVARIANCE_DRIFT_TOLERANCE = 0.25
PERSON_FIT_SAMPLE_SIZE = 1_000
PERSON_FIT_SEED = 260_910
DIMENSIONALITY_SAMPLE_SIZE = 1_000
DIMENSIONALITY_SEED = 260_911
DIMENSIONALITY_ITERATIONS = 360
MODEL_FIT_SAMPLE_SIZE = 1_200
MODEL_FIT_SEED = 260_912
RELIABILITY_SAMPLE_SIZE = 1_200
RELIABILITY_SEED = 260_913
EQUATING_BOOTSTRAPS = 300
EQUATING_SEED = 260_914
ROSTER_INVARIANCE_SEED = 260_915
GENERALIZABILITY_SEED = 260_916
SEQUENTIAL_DRIFT_SEED = 260_917
SEQUENTIAL_DRIFT_HOLDOUT_SEED = 270_917
SEQUENTIAL_DRIFT_REPLICATIONS = 500
ADAPTIVE_CALIBRATION_CANDIDATES = 400
ADAPTIVE_CALIBRATION_ITEMS = 31
ADAPTIVE_CALIBRATION_MAX_ITEMS = 12
ADAPTIVE_CALIBRATION_TARGET_SE = 0.5
SELECTIVE_CLASSIFICATION_Z = (1.0, 1.28, 1.645, 1.96, 2.326, 2.576)
SELECTIVE_CLASSIFICATION_MAX_ERROR_UPPER = 0.025
SELECTIVE_CLASSIFICATION_REPLICATIONS = 10


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
    context_calibration_logit_rmse: list[float] = []
    predicted_logits: list[float] = []
    truth_logits: list[float] = []
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
        calibration_logit_errors: list[float] = []
        for model_id in MODEL_IDS:
            probability = min(max(predicted[model_id], 1e-12), 1.0 - 1e-12)
            target = min(max(truth[model_id], 1e-12), 1.0 - 1e-12)
            predicted_logit = math.log(probability / (1.0 - probability))
            truth_logit = math.log(target / (1.0 - target))
            predicted_logits.append(predicted_logit)
            truth_logits.append(truth_logit)
            calibration_logit_errors.append((predicted_logit - truth_logit) ** 2)
            brier_scores.append(_expected_brier(probability, target))
            log_losses.append(
                -(target * math.log(probability) + (1.0 - target) * math.log(1.0 - probability))
            )
        context_brier.append(statistics.fmean(brier_scores))
        context_log_loss.append(statistics.fmean(log_losses))
        context_calibration_logit_rmse.append(
            math.sqrt(statistics.fmean(calibration_logit_errors))
        )
        selected = ranked[0][0]
        regrets.append(max(truth.values()) - truth[selected])

    calibration_slope, calibration_intercept = statistics.linear_regression(
        predicted_logits, truth_logits
    )
    return {
        "brier_score": statistics.fmean(context_brier),
        "log_loss": statistics.fmean(context_log_loss),
        "calibration_intercept": calibration_intercept,
        "calibration_slope": calibration_slope,
        "calibration_logit_rmse": statistics.fmean(
            context_calibration_logit_rmse
        ),
        "top_choice_regret": statistics.fmean(regrets),
    }, {
        "brier_score": context_brier,
        "log_loss": context_log_loss,
        "calibration_logit_rmse": context_calibration_logit_rmse,
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


def _validate_assignment_design(
    evidence: PsychometricRoutingEvidence,
) -> dict[str, object]:
    """Validate a preregistered positive-propensity logging design on known truth."""
    generator = random.Random(ASSIGNMENT_SEED)
    weighted_rewards = {model_id: [] for model_id in MODEL_IDS}
    observed_rewards = {model_id: [] for model_id in MODEL_IDS}
    observations = {model_id: 0 for model_id in MODEL_IDS}
    minimum_probability = EXPLORATION_RATE / len(MODEL_IDS)
    for trial_index in range(ASSIGNMENT_TRIALS):
        context_index = trial_index % TRAIN_CONTEXTS
        angle = 2.0 * math.pi * (context_index + 0.5) / TRAIN_CONTEXTS
        context = f"held_out_{context_index}"
        ranked = evidence.ranked_evidence(MODEL_IDS, context, _vector(angle))
        probabilities = {model_id: minimum_probability for model_id in MODEL_IDS}
        probabilities[ranked[0][0]] += 1.0 - EXPLORATION_RATE
        draw = generator.random()
        cumulative = 0.0
        selected = MODEL_IDS[-1]
        for model_id in MODEL_IDS:
            cumulative += probabilities[model_id]
            if draw < cumulative:
                selected = model_id
                break
        selected_probability = probabilities[selected]
        selected_index = MODEL_IDS.index(selected)
        reward = float(generator.random() < _probability(selected_index, angle))
        observations[selected] += 1
        observed_rewards[selected].append(reward)
        for model_id in MODEL_IDS:
            weighted_rewards[model_id].append(
                reward / selected_probability if model_id == selected else 0.0
            )

    true_values = {
        model_id: statistics.fmean(
            _probability(
                model_index,
                2.0 * math.pi * (context_index + 0.5) / TRAIN_CONTEXTS,
            )
            for context_index in range(TRAIN_CONTEXTS)
        )
        for model_index, model_id in enumerate(MODEL_IDS)
    }
    estimates = {
        model_id: statistics.fmean(values)
        for model_id, values in weighted_rewards.items()
    }
    naive_estimates = {
        model_id: statistics.fmean(values)
        for model_id, values in observed_rewards.items()
    }
    naive_rmse = math.sqrt(
        statistics.fmean(
            (naive_estimates[model_id] - true_values[model_id]) ** 2
            for model_id in MODEL_IDS
        )
    )
    inverse_propensity_rmse = math.sqrt(
        statistics.fmean(
            (estimates[model_id] - true_values[model_id]) ** 2
            for model_id in MODEL_IDS
        )
    )
    confidence_intervals: dict[str, list[float]] = {}
    covered = 0
    for model_id, values in weighted_rewards.items():
        standard_error = statistics.stdev(values) / math.sqrt(ASSIGNMENT_TRIALS)
        interval = [
            estimates[model_id] - 1.96 * standard_error,
            estimates[model_id] + 1.96 * standard_error,
        ]
        confidence_intervals[model_id] = interval
        covered += interval[0] <= true_values[model_id] <= interval[1]
    return {
        "assignment_mechanism": "epsilon_greedy",
        "exploration_rate": EXPLORATION_RATE,
        "minimum_assignment_probability": minimum_probability,
        "trials": ASSIGNMENT_TRIALS,
        "seed": ASSIGNMENT_SEED,
        "observations_by_candidate": observations,
        "inverse_propensity_value": estimates,
        "naive_observed_value": naive_estimates,
        "true_value": true_values,
        "naive_observed_rmse": naive_rmse,
        "inverse_propensity_rmse": inverse_propensity_rmse,
        "inverse_propensity_rmse_reduction": naive_rmse - inverse_propensity_rmse,
        "confidence_interval_95": confidence_intervals,
        "true_value_coverage_rate": covered / len(MODEL_IDS),
    }


def _validate_scale_linking() -> dict[str, object]:
    """Recover a known affine metric change from versioned common-item anchors."""
    old_discrimination = np.asarray([0.7, 0.9, 1.1, 1.3, 1.5, 1.8])
    old_intercept = np.asarray([-1.2, -0.5, 0.1, 0.7, 1.3, 1.8])
    true_slope = 1.3
    true_intercept = -0.4
    result = fast_mlsirm.irt_link(
        old_discrimination,
        old_intercept,
        old_discrimination * true_slope,
        old_intercept + old_discrimination * true_intercept,
        method="stocking_lord",
    )
    return {
        "method": result.method,
        "anchor_items": len(old_discrimination),
        "converged": result.converged,
        "termination_reason": result.termination_reason,
        "estimated_slope": result.slope,
        "estimated_intercept": result.intercept,
        "true_slope": true_slope,
        "true_intercept": true_intercept,
        "true_parameter_rmse": math.sqrt(
            statistics.fmean(
                (
                    (result.slope - true_slope) ** 2,
                    (result.intercept - true_intercept) ** 2,
                )
            )
        ),
    }


def _validate_parameter_invariance() -> dict[str, object]:
    """Detect known post-linking drift without treating it as significance."""
    old_discrimination = np.asarray([0.7, 0.9, 1.1, 1.3, 1.5, 1.8, 1.0, 1.6])
    old_intercept = np.asarray([-1.2, -0.5, 0.1, 0.7, 1.3, 1.8, -0.8, 0.4])
    true_slope = 1.3
    true_intercept = -0.4
    expected_drift_items = [7]
    new_discrimination = old_discrimination * true_slope
    new_intercept = old_intercept + old_discrimination * true_intercept
    new_intercept[expected_drift_items] += 0.8
    anchor_items = np.arange(7)
    linking = fast_mlsirm.irt_link(
        old_discrimination[anchor_items],
        old_intercept[anchor_items],
        new_discrimination[anchor_items],
        new_intercept[anchor_items],
        method="stocking_lord",
    )
    discrimination_drift = new_discrimination - old_discrimination * linking.slope
    intercept_drift = new_intercept - (
        old_intercept + old_discrimination * linking.intercept
    )
    item_drift = np.sqrt(
        (discrimination_drift**2 + intercept_drift**2) / 2.0
    )
    flagged_items = np.flatnonzero(item_drift > INVARIANCE_DRIFT_TOLERANCE).tolist()
    return {
        "method": "linked_parameter_drift_effect_size",
        "items": len(old_discrimination),
        "anchor_items": anchor_items.tolist(),
        "drift_tolerance": INVARIANCE_DRIFT_TOLERANCE,
        "expected_drift_items": expected_drift_items,
        "flagged_items": flagged_items,
        "known_drift_recall": len(set(flagged_items) & set(expected_drift_items))
        / len(expected_drift_items),
        "stable_item_false_positive_count": len(
            set(flagged_items) - set(expected_drift_items)
        ),
        "maximum_stable_item_drift": float(np.max(item_drift[anchor_items])),
        "injected_item_drift": float(item_drift[expected_drift_items[0]]),
        "linking_converged": linking.converged,
    }


def _validate_candidate_roster_invariance() -> dict[str, object]:
    """Compare common candidate measures after a candidate-roster change."""
    generator = np.random.default_rng(ROSTER_INVARIANCE_SEED)
    candidate_count = 20
    retained_candidates = 16
    item_count = 200
    ability = np.linspace(-2.0, 2.0, candidate_count)
    item_intercept = np.linspace(-1.5, 1.5, item_count)
    probabilities = 1.0 / (
        1.0 + np.exp(-(ability[:, None] + item_intercept[None, :]))
    )
    responses = (generator.random(probabilities.shape) < probabilities).astype(float)
    factor_id = np.zeros(item_count, dtype=np.int64)
    config = fast_mlsirm.FitConfig(
        model="MIRT",
        estimator="mmle",
        max_iter=1_000,
        latent_dim=1,
        q_theta=21,
        q_xi=7,
        rust_device="cpu",
        seed=ROSTER_INVARIANCE_SEED,
    )
    full = fast_mlsirm.fit(responses, factor_id, config)
    reduced = fast_mlsirm.fit(responses[:retained_candidates], factor_id, config)
    linking = fast_mlsirm.irt_link(
        np.exp(full.params.alpha),
        np.asarray(full.params.b),
        np.exp(reduced.params.alpha),
        np.asarray(reduced.params.b),
        method="stocking_lord",
    )
    full_theta = np.asarray(full.params.theta)[:retained_candidates, 0]
    reduced_theta = np.asarray(reduced.params.theta)[:, 0]
    linked_theta = linking.slope * reduced_theta + linking.intercept
    return {
        "method": "separate_calibration_common_item_linking",
        "seed": ROSTER_INVARIANCE_SEED,
        "full_candidate_count": candidate_count,
        "retained_candidate_count": retained_candidates,
        "common_items": item_count,
        "full_convergence_status": full.convergence_status,
        "reduced_convergence_status": reduced.convergence_status,
        "linking_converged": linking.converged,
        "linking_termination_reason": linking.termination_reason,
        "linked_common_score_rmse": float(
            np.sqrt(np.mean((linked_theta - full_theta) ** 2))
        ),
        "linked_common_score_correlation": float(
            np.corrcoef(linked_theta, full_theta)[0, 1]
        ),
        "maximum_linked_common_score_shift": float(
            np.max(np.abs(linked_theta - full_theta))
        ),
    }


def _validate_functional_drift() -> dict[str, object]:
    """Detect the known item whose drift changes the test characteristic curve."""
    old = SimpleNamespace(
        alpha=np.zeros(8),
        b=np.linspace(-1.4, 1.4, 8),
        zeta=np.zeros((8, 1)),
        tau=-30.0,
    )
    new = SimpleNamespace(
        alpha=old.alpha.copy(),
        b=old.b.copy(),
        zeta=old.zeta.copy(),
        tau=old.tau,
    )
    expected_drift_items = [6]
    new.b[expected_drift_items] += 0.8
    result = fast_mlsirm.tcc_drift(
        old,
        new,
        np.zeros(8, dtype=np.int64),
        "MIRT",
        threshold=0.05,
        q_theta=21,
        q_xi=5,
    )
    return {
        "method": "backward_tcc_area_elimination",
        "expected_drift_items": expected_drift_items,
        "detected_drift_items": result["drifted"],
        "area_trace": result["area_trace"],
        "iterations": result["iterations"],
        "termination_reason": result["termination_reason"],
    }


def _validate_sequential_drift() -> dict[str, object]:
    """Measure the false-alarm and detection-delay tradeoff for a known shift."""
    before_probability = 0.8
    after_probability = 0.3
    change_after = 100

    def evaluate(seed: int, threshold: float) -> dict[str, float | int]:
        false_alarms = 0
        detection_delays: list[int] = []
        for replication in range(SEQUENTIAL_DRIFT_REPLICATIONS):
            generator = random.Random(seed + replication)
            statistic = 0.0
            alarm_observation: int | None = None
            for observation_index in range(250):
                probability = (
                    before_probability
                    if observation_index < change_after
                    else after_probability
                )
                accepted = generator.random() < probability
                log_likelihood_ratio = (
                    math.log(after_probability / before_probability)
                    if accepted
                    else math.log(
                        (1.0 - after_probability) / (1.0 - before_probability)
                    )
                )
                statistic = max(0.0, statistic + log_likelihood_ratio)
                if statistic >= threshold:
                    alarm_observation = observation_index + 1
                    break
            assert alarm_observation is not None
            if alarm_observation <= change_after:
                false_alarms += 1
            else:
                detection_delays.append(alarm_observation - change_after)
        ordered_delays = sorted(detection_delays)
        false_alarm_rate = false_alarms / SEQUENTIAL_DRIFT_REPLICATIONS
        z_95 = 1.959963984540054
        denominator = 1.0 + (z_95**2 / SEQUENTIAL_DRIFT_REPLICATIONS)
        false_alarm_upper_95 = (
            false_alarm_rate
            + z_95**2 / (2 * SEQUENTIAL_DRIFT_REPLICATIONS)
            + z_95
            * math.sqrt(
                false_alarm_rate
                * (1.0 - false_alarm_rate)
                / SEQUENTIAL_DRIFT_REPLICATIONS
                + z_95**2 / (4 * SEQUENTIAL_DRIFT_REPLICATIONS**2)
            )
        ) / denominator
        return {
            "threshold_log_likelihood_ratio": threshold,
            "false_alarm_rate": false_alarm_rate,
            "false_alarm_rate_upper_95": false_alarm_upper_95,
            "post_change_detection_rate_among_no_false_alarm": (
                len(detection_delays)
                / (SEQUENTIAL_DRIFT_REPLICATIONS - false_alarms)
            ),
            "detection_delay_p50_observations": statistics.median(detection_delays),
            "detection_delay_p95_observations": ordered_delays[
                math.ceil(0.95 * len(ordered_delays)) - 1
            ],
        }

    calibration_baseline = evaluate(SEQUENTIAL_DRIFT_SEED, math.log(100.0))
    threshold_candidates = [value / 10.0 for value in range(60, 71)]
    evaluated_candidates = [
        evaluate(SEQUENTIAL_DRIFT_SEED, value) for value in threshold_candidates
    ]
    eligible_candidates = [
        value
        for value in evaluated_candidates
        if value["false_alarm_rate_upper_95"] <= 0.05
        and value["detection_delay_p95_observations"] <= 25
    ]
    calibration_candidate = min(
        eligible_candidates,
        key=lambda value: (
            value["detection_delay_p95_observations"],
            value["detection_delay_p50_observations"],
            value["threshold_log_likelihood_ratio"],
        ),
    )
    selected_threshold = calibration_candidate["threshold_log_likelihood_ratio"]
    baseline = evaluate(SEQUENTIAL_DRIFT_HOLDOUT_SEED, math.log(100.0))
    candidate = evaluate(SEQUENTIAL_DRIFT_HOLDOUT_SEED, selected_threshold)
    return {
        "method": "one_stream_bernoulli_cusum_screen",
        "seed": SEQUENTIAL_DRIFT_SEED,
        "holdout_seed": SEQUENTIAL_DRIFT_HOLDOUT_SEED,
        "replications": SEQUENTIAL_DRIFT_REPLICATIONS,
        "before_probability": before_probability,
        "after_probability": after_probability,
        "change_after_observations": change_after,
        "baseline": baseline,
        "candidate": candidate,
        "calibration_baseline": calibration_baseline,
        "calibration_candidate": calibration_candidate,
        "threshold_search": {
            "minimum": threshold_candidates[0],
            "maximum": threshold_candidates[-1],
            "step": 0.1,
            "candidates": len(threshold_candidates),
            "selection_rule": (
                "minimum p95 delay, then p50 delay, then threshold among "
                "calibration candidates whose 95% false-alarm upper bound and "
                "p95 delay meet both synthetic targets"
            ),
        },
        "synthetic_targets": {
            "maximum_false_alarm_rate": 0.05,
            "maximum_detection_delay_p95_observations": 25,
        },
        "candidate_meets_synthetic_targets": (
            candidate["false_alarm_rate_upper_95"] <= 0.05
            and candidate["detection_delay_p95_observations"] <= 25
        ),
    }


def _validate_score_equating() -> dict[str, object]:
    """Recover a known score-form transformation with bootstrap uncertainty."""
    old_scores = np.tile(np.arange(11, dtype=np.int64), 100)
    expected_equivalents = 2.0 * np.arange(11, dtype=float) + 1.0
    new_scores = (2 * old_scores) + 1
    result = fast_mlsirm.equate_observed_scores(
        old_scores, new_scores, method="linear", k_x=10, k_y=21
    )
    uncertainty = fast_mlsirm.equating_standard_errors(
        old_scores,
        new_scores,
        method="linear",
        k_x=10,
        k_y=21,
        n_boot=EQUATING_BOOTSTRAPS,
        seed=EQUATING_SEED,
    )
    linked_rmse = float(
        np.sqrt(np.mean((result.y_equivalents - expected_equivalents) ** 2))
    )
    unlinked_rmse = float(
        np.sqrt(np.mean((result.x_scores - expected_equivalents) ** 2))
    )
    return {
        "method": result.method,
        "observations_per_form": len(old_scores),
        "expected_slope": 2.0,
        "expected_intercept": 1.0,
        "estimated_slope": result.slope,
        "estimated_intercept": result.intercept,
        "unlinked_score_rmse": unlinked_rmse,
        "equated_score_rmse": linked_rmse,
        "bootstrap_repetitions": EQUATING_BOOTSTRAPS,
        "bootstrap_seed": EQUATING_SEED,
        "interval_95_coverage": float(
            np.mean(
                (uncertainty["ci_lo"] <= expected_equivalents)
                & (expected_equivalents <= uncertainty["ci_hi"])
            )
        ),
        "maximum_standard_error": float(np.max(uncertainty["se"])),
    }


def _validate_response_pattern_fit() -> dict[str, object]:
    """Rank one known inverted candidate pattern with nonparametric person fit."""
    generator = np.random.default_rng(PERSON_FIT_SEED)
    item_difficulty = np.linspace(-2.0, 2.0, 10)
    ability = generator.normal(size=PERSON_FIT_SAMPLE_SIZE)
    probabilities = 1.0 / (
        1.0 + np.exp(-(ability[:, None] - item_difficulty[None, :]))
    )
    responses = (generator.random(probabilities.shape) < probabilities).astype(float)
    injected_index = PERSON_FIT_SAMPLE_SIZE - 1
    responses[injected_index] = np.asarray([0, 0, 0, 0, 0, 1, 1, 1, 1, 1])
    result = fast_mlsirm.person_fit_np(responses)
    finite = np.isfinite(result.zu3)
    ranked = np.flatnonzero(finite)[np.argsort(result.zu3[finite])[::-1]]
    return {
        "method": "nonparametric_zu3_rank",
        "sample_size": PERSON_FIT_SAMPLE_SIZE,
        "seed": PERSON_FIT_SEED,
        "items": len(item_difficulty),
        "finite_statistics": int(np.count_nonzero(finite)),
        "injected_candidate_index": injected_index,
        "highest_aberrance_candidate_index": int(ranked[0]),
        "injected_zu3": float(result.zu3[injected_index]),
        "next_highest_zu3": float(result.zu3[ranked[1]]),
        "zu3_rank_separation": float(
            result.zu3[injected_index] - result.zu3[ranked[1]]
        ),
    }


def _validate_construct_dimensionality() -> dict[str, object]:
    """Recover two known dimensions with Horn parallel analysis."""
    generator = np.random.default_rng(DIMENSIONALITY_SEED)
    item_count = 12
    expected_dimensions = 2
    ability = generator.normal(
        size=(DIMENSIONALITY_SAMPLE_SIZE, expected_dimensions)
    )
    item_dimension = np.repeat(np.arange(expected_dimensions), item_count // 2)
    item_difficulty = np.tile(np.linspace(-1.2, 1.2, item_count // 2), 2)
    logits = ability[:, item_dimension] - item_difficulty
    probabilities = 1.0 / (1.0 + np.exp(-logits))
    responses = (generator.random(probabilities.shape) < probabilities).astype(float)
    result = fast_mlsirm.parallel_analysis(
        responses,
        n_iterations=DIMENSIONALITY_ITERATIONS,
        centile=95,
        seed=DIMENSIONALITY_SEED,
    )
    return {
        "method": "horn_parallel_analysis_pearson_pca",
        "sample_size": DIMENSIONALITY_SAMPLE_SIZE,
        "seed": DIMENSIONALITY_SEED,
        "iterations": DIMENSIONALITY_ITERATIONS,
        "items": item_count,
        "expected_dimensions": expected_dimensions,
        "retained_dimensions": result.retained,
        "known_dimensions_recovered": result.retained == expected_dimensions,
        "leading_eigenvalues": result.eigenvalues[:3].tolist(),
        "leading_adjusted_eigenvalues": result.adjusted_eigenvalues[:3].tolist(),
    }


def _validate_global_model_fit() -> dict[str, object]:
    """Separate a fitted one-factor design from known two-factor misspecification."""
    item_count = 10
    item_difficulty = np.tile(np.linspace(-1.2, 1.2, item_count // 2), 2)
    factor_id = np.zeros(item_count, dtype=np.int64)
    config = fast_mlsirm.FitConfig(
        model="MIRT",
        estimator="mmle",
        max_iter=1_000,
        latent_dim=1,
        q_theta=15,
        q_xi=7,
        rust_device="cpu",
        seed=MODEL_FIT_SEED,
    )

    def fit_case(dimensions: int) -> dict[str, float | bool | str]:
        generator = np.random.default_rng(MODEL_FIT_SEED)
        ability = generator.normal(size=(MODEL_FIT_SAMPLE_SIZE, dimensions))
        item_dimension = np.repeat(np.arange(dimensions), item_count // dimensions)
        probabilities = 1.0 / (
            1.0
            + np.exp(-(ability[:, item_dimension] - item_difficulty[None, :]))
        )
        responses = (generator.random(probabilities.shape) < probabilities).astype(
            float
        )
        result = fast_mlsirm.fit(responses, factor_id, config)
        diagnostics = fast_mlsirm.fit_diagnostics(
            responses,
            result.params,
            factor_id,
            model="MIRT",
            include_m2=True,
            m2_q_theta=15,
            estimator="mmle",
            population=result.population,
            convergence_status=result.convergence_status,
        ).model_fit
        return {
            "convergence_status": result.convergence_status,
            "m2": float(diagnostics["m2"]),
            "degrees_of_freedom": float(diagnostics["m2_df"]),
            "p_value": float(diagnostics["m2_p_value"]),
            "rmsea": float(diagnostics["rmsea"]),
            "srmr": float(diagnostics["srmr"]),
            "cfi": float(diagnostics["cfi"]),
            "inference_valid": bool(diagnostics["m2_inference_valid"]),
        }

    fitted_case = fit_case(1)
    misspecified_case = fit_case(2)
    return {
        "method": "limited_information_m2",
        "sample_size_per_case": MODEL_FIT_SAMPLE_SIZE,
        "seed": MODEL_FIT_SEED,
        "items": item_count,
        "fitted_one_factor": fitted_case,
        "misspecified_two_factor": misspecified_case,
        "known_misspecification_detected": (
            fitted_case["p_value"] >= 0.05
            and misspecified_case["p_value"] < 0.05
        ),
    }


def _validate_score_reliability() -> dict[str, object]:
    """Verify posterior reliability rises with known item information."""
    generator = np.random.default_rng(RELIABILITY_SEED)
    item_count = 12
    ability = generator.normal(size=RELIABILITY_SAMPLE_SIZE)
    item_difficulty = np.linspace(-1.5, 1.5, item_count)
    random_draws = generator.random((RELIABILITY_SAMPLE_SIZE, item_count))
    factor_id = np.zeros(item_count, dtype=np.int64)
    config = fast_mlsirm.FitConfig(
        model="MIRT",
        estimator="mmle",
        max_iter=1_000,
        latent_dim=1,
        q_theta=21,
        q_xi=7,
        rust_device="cpu",
        seed=RELIABILITY_SEED,
    )

    def fit_case(discrimination: float) -> dict[str, float | int | str]:
        probabilities = 1.0 / (
            1.0
            + np.exp(
                -discrimination
                * (ability[:, None] - item_difficulty[None, :])
            )
        )
        responses = (random_draws < probabilities).astype(float)
        result = fast_mlsirm.fit(responses, factor_id, config)
        reliability = fast_mlsirm.empirical_reliability(result, device="cpu")
        return {
            "true_item_discrimination": discrimination,
            "convergence_status": result.convergence_status,
            "iterations": result.n_iter,
            "empirical_reliability": float(reliability[0]),
        }

    weak_information = fit_case(0.45)
    strong_information = fit_case(1.5)
    return {
        "method": "posterior_variance_empirical_reliability",
        "sample_size_per_case": RELIABILITY_SAMPLE_SIZE,
        "seed": RELIABILITY_SEED,
        "items": item_count,
        "weak_information": weak_information,
        "strong_information": strong_information,
        "reliability_separation": (
            strong_information["empirical_reliability"]
            - weak_information["empirical_reliability"]
        ),
    }


def _validate_generalizability_design() -> dict[str, object]:
    """Separate candidate, query, occasion, and interaction variance."""
    generator = np.random.default_rng(GENERALIZABILITY_SEED)
    candidates, items, occasions = 80, 12, 4
    scores = (
        generator.normal(0.0, 1.0, (candidates, 1, 1))
        + generator.normal(0.0, 0.5, (1, items, 1))
        + generator.normal(0.0, 0.3, (1, 1, occasions))
        + generator.normal(0.0, 0.45, (candidates, items, 1))
        + generator.normal(0.0, 0.25, (candidates, 1, occasions))
        + generator.normal(0.0, 0.2, (1, items, occasions))
        + generator.normal(0.0, 0.55, (candidates, items, occasions))
    )
    result = fast_mlsirm.gtheory_pio(
        scores, n_prime=((1, 1), (6, 2), (12, 4))
    )
    return {
        "method": "two_facet_crossed_g_study_and_d_study",
        "seed": GENERALIZABILITY_SEED,
        "candidates": candidates,
        "items": items,
        "occasions": occasions,
        "variance_component_order": ["p", "i", "o", "pi", "po", "io", "pio"],
        "variance_components_raw": result.var_raw,
        "designs": [
            {
                "items": row.n_i_prime,
                "occasions": row.n_o_prime,
                "generalizability": row.generalizability,
                "dependability": row.dependability,
            }
            for row in result.d_study
        ],
    }


def _validate_conditional_information() -> dict[str, object]:
    """Show that spreading item difficulty improves tail precision."""
    item_count = 12
    trait_points = np.asarray([[-2.0], [0.0], [2.0]])

    def information(item_difficulty: np.ndarray) -> np.ndarray:
        bundle = {
            "schema_version": 1,
            "n_items": item_count,
            "n_dims": 1,
            "latent_dim": 1,
            "model": "MIRT",
            "tau": 0.0,
            "eps_distance": 1e-8,
            "quadrature": {"q_theta": 21, "q_xi": 7},
            "items": [
                {
                    "code": f"item_{index}",
                    "factor_id": 0,
                    "alpha": 0.0,
                    "b": float(difficulty),
                    "zeta": [0.0],
                }
                for index, difficulty in enumerate(item_difficulty)
            ],
            "population": None,
            "eapsum_tables": None,
        }
        return fast_mlsirm.bank_information(
            bundle, trait_points, device="cpu"
        )["test_info"][:, 0]

    center_only = information(np.zeros(item_count))
    range_matched = information(np.linspace(-2.0, 2.0, item_count))
    center_only_worst = float(np.min(center_only))
    range_matched_worst = float(np.min(range_matched))
    return {
        "method": "fisher_test_information",
        "items": item_count,
        "trait_points": trait_points[:, 0].tolist(),
        "center_only_test_information": center_only.tolist(),
        "range_matched_test_information": range_matched.tolist(),
        "center_only_worst_sem": 1.0 / math.sqrt(center_only_worst),
        "range_matched_worst_sem": 1.0 / math.sqrt(range_matched_worst),
        "worst_case_information_gain": (
            range_matched_worst / center_only_worst - 1.0
        ),
    }


def _validate_classification_decision() -> dict[str, object]:
    """Verify that lower score error improves one cut-score decision."""
    measures = np.asarray([-1.0, -0.5, 0.5, 1.0])

    def classify(standard_error: float) -> dict[str, float]:
        result = fast_mlsirm.rudner_classification(
            measures,
            np.full(len(measures), standard_error),
            [0.0],
        )
        return {
            "standard_error": standard_error,
            "accuracy": result.simultaneous_accuracy,
            "consistency": result.simultaneous_consistency,
            "minimum_conditional_accuracy": float(
                np.min(result.conditional_simultaneous_accuracy)
            ),
        }

    uncertain = classify(0.8)
    precise = classify(0.2)
    return {
        "method": "rudner_normal_approximation",
        "decision_cut": 0.0,
        "measures": measures.tolist(),
        "uncertain_scores": uncertain,
        "precise_scores": precise,
        "accuracy_gain": precise["accuracy"] - uncertain["accuracy"],
        "consistency_gain": precise["consistency"] - uncertain["consistency"],
    }


def _validate_selection_utility() -> dict[str, object]:
    """Show why predictive validity must be evaluated net of routing cost."""
    conditions = {
        "selected_requests": 1_000,
        "outcome_value_sd": 10.0,
        "selection_ratio": 0.25,
        "base_success_rate": 0.4,
    }

    def evaluate(validity: float, total_cost: float) -> dict[str, float]:
        utility = fast_mlsirm.selection_utility(
            n=conditions["selected_requests"],
            sdy=conditions["outcome_value_sd"],
            rxy=validity,
            sr=conditions["selection_ratio"],
            cost_total=total_cost,
        )
        success = fast_mlsirm.taylor_russell(
            rxy=validity,
            sr=conditions["selection_ratio"],
            br=conditions["base_success_rate"],
        )
        return {
            "predictive_validity": validity,
            "total_measurement_cost": total_cost,
            "selected_success_ratio": success.success_ratio,
            "net_utility_gain": utility.utility_gain,
        }

    return {
        "method": "taylor_russell_and_brogden_cronbach_gleser",
        **conditions,
        "baseline": evaluate(0.2, 500.0),
        "higher_validity": evaluate(0.6, 2_000.0),
        "cost_exceeds_value": evaluate(0.6, 10_000.0),
    }


def _validate_candidate_group_dif() -> dict[str, object]:
    """Recover one known candidate-cohort item shift after criterion purification."""
    generator = np.random.default_rng(DIF_SEED)
    item_count = 8
    group = np.repeat((0, 1), DIF_SAMPLE_SIZE // 2)
    ability = generator.normal(size=DIF_SAMPLE_SIZE)
    intercept = np.linspace(-1.4, 1.4, item_count)
    logits = ability[:, None] - intercept[None, :]
    logits[:, 0] += 1.4 * group
    probabilities = 1.0 / (1.0 + np.exp(-logits))
    responses = (generator.random((DIF_SAMPLE_SIZE, item_count)) < probabilities).astype(
        np.int8
    )
    result = fast_mlsirm.logistic_dif_purified(responses, group)
    flagged_items = np.flatnonzero(result["flagged_bh"]).tolist()
    expected_items = [0]
    return {
        "method": "logistic_dif_purified",
        "sample_size": DIF_SAMPLE_SIZE,
        "seed": DIF_SEED,
        "expected_dif_items": expected_items,
        "flagged_items": flagged_items,
        "known_dif_recall": len(set(flagged_items) & set(expected_items))
        / len(expected_items),
        "false_positive_count": len(set(flagged_items) - set(expected_items)),
        "purification_converged": bool(result["purify_converged"]),
        "purification_termination_reason": str(
            result["purify_termination_reason"]
        ),
        "anchor_items": int(result["n_anchor"]),
    }


def _validate_judge_effects() -> dict[str, object]:
    """Recover known judge severities from a connected fully crossed design."""
    generator = np.random.default_rng(JUDGE_SEED)
    ability = generator.normal(size=JUDGE_SAMPLE_SIZE)
    item_difficulty = np.linspace(-1.0, 1.0, 6)
    true_severity = np.asarray([-0.7, 0.0, 0.7])
    logits = (
        ability[:, None, None]
        - item_difficulty[None, :, None]
        - true_severity[None, None, :]
    )
    probabilities = 1.0 / (1.0 + np.exp(-logits))
    responses = (generator.random(probabilities.shape) < probabilities).astype(
        np.float64
    )
    result = fast_mlsirm.fit_facets(responses, n_cat=2)
    return {
        "method": "many_facet_rasch",
        "sample_size": JUDGE_SAMPLE_SIZE,
        "seed": JUDGE_SEED,
        "items": len(item_difficulty),
        "judges": len(true_severity),
        "connected": result.connected,
        "converged": result.converged,
        "iterations": result.n_iter,
        "true_severity": true_severity.tolist(),
        "estimated_severity": result.rater_severity.tolist(),
        "severity_rmse": float(
            np.sqrt(np.mean((result.rater_severity - true_severity) ** 2))
        ),
        "severity_order_recovered": bool(
            np.array_equal(
                np.argsort(result.rater_severity), np.argsort(true_severity)
            )
        ),
    }


def _validate_item_covariate_effect() -> dict[str, object]:
    """Estimate one known item-side context contrast without claiming invariance."""
    generator = np.random.default_rng(ITEM_COVARIATE_SEED)
    item_count = 12
    group_id = np.arange(ITEM_COVARIATE_SAMPLE_SIZE) % 2
    covariate = np.vstack(
        (np.linspace(0.0, 1.0, item_count), np.linspace(1.0, 0.0, item_count))
    )
    ability = generator.standard_normal(ITEM_COVARIATE_SAMPLE_SIZE)
    intercept = np.linspace(-1.0, 1.0, item_count)
    true_delta = -0.8
    logits = ability[:, None] + intercept[None, :] + true_delta * covariate[group_id]
    probabilities = 1.0 / (1.0 + np.exp(-logits))
    responses = (generator.random(probabilities.shape) < probabilities).astype(float)
    result = fast_mlsirm.fit(
        responses,
        np.zeros(item_count, dtype=np.int64),
        fast_mlsirm.FitConfig(
            model="ULSRM",
            estimator="mmle",
            max_iter=1_000,
            latent_dim=1,
            q_theta=15,
            q_xi=7,
            rust_device="cpu",
            seed=ITEM_COVARIATE_SEED,
        ),
        group_id=group_id,
        covariate={"w": covariate, "init_delta": 0.0},
    )
    estimated_delta = float(result.population["delta"])
    return {
        "method": "multigroup_item_covariate",
        "sample_size": ITEM_COVARIATE_SAMPLE_SIZE,
        "seed": ITEM_COVARIATE_SEED,
        "contexts": len(covariate),
        "items": item_count,
        "true_delta": true_delta,
        "estimated_delta": estimated_delta,
        "absolute_error": abs(estimated_delta - true_delta),
        "convergence_status": result.convergence_status,
        "iterations": result.n_iter,
    }


def _validate_parameter_uncertainty() -> dict[str, object]:
    """Check Oakes interval coverage for known item intercepts."""
    generator = np.random.default_rng(UNCERTAINTY_SEED)
    item_count = 6
    ability = generator.standard_normal(UNCERTAINTY_SAMPLE_SIZE)
    true_intercept = np.linspace(-1.0, 1.0, item_count)
    probabilities = 1.0 / (
        1.0 + np.exp(-(ability[:, None] + true_intercept[None, :]))
    )
    responses = (generator.random(probabilities.shape) < probabilities).astype(float)
    factor_id = np.zeros(item_count, dtype=np.int64)
    config = fast_mlsirm.FitConfig(
        model="MIRT",
        estimator="mmle",
        max_iter=1_000,
        latent_dim=1,
        q_theta=21,
        q_xi=7,
        rust_device="cpu",
        seed=UNCERTAINTY_SEED,
    )
    result = fast_mlsirm.fit(responses, factor_id, config)
    uncertainty = fast_mlsirm.oakes_standard_errors(
        result, responses, factor_id, config
    )
    label_positions = {
        label: index for index, label in enumerate(uncertainty["labels"])
    }
    estimated_intercept = np.asarray(result.params.b)
    standard_error = np.asarray(
        [
            uncertainty["se"][label_positions[f"b:{index}"]]
            for index in range(item_count)
        ]
    )
    lower = estimated_intercept - 1.96 * standard_error
    upper = estimated_intercept + 1.96 * standard_error
    return {
        "method": "oakes_information_wald_interval",
        "sample_size": UNCERTAINTY_SAMPLE_SIZE,
        "seed": UNCERTAINTY_SEED,
        "items": item_count,
        "convergence_status": result.convergence_status,
        "iterations": result.n_iter,
        "intercept_rmse": float(
            np.sqrt(np.mean((estimated_intercept - true_intercept) ** 2))
        ),
        "interval_95_coverage_rate": float(
            np.mean((lower <= true_intercept) & (true_intercept <= upper))
        ),
        "mean_interval_95_width": float(np.mean(upper - lower)),
    }


def _validate_adaptive_candidate_calibration() -> dict[str, object]:
    """Compare information-selected and random onboarding queries on known truth."""
    from fast_mlsirm import cat_next_item

    discrimination = 1.5
    difficulties = [
        -3.0 + 6.0 * index / (ADAPTIVE_CALIBRATION_ITEMS - 1)
        for index in range(ADAPTIVE_CALIBRATION_ITEMS)
    ]
    bundle = {
        "schema_version": 1,
        "model": "MIRT",
        "n_items": ADAPTIVE_CALIBRATION_ITEMS,
        "n_dims": 1,
        "latent_dim": 1,
        "quadrature": {"q_theta": 41, "q_xi": 7},
        "eps_distance": 1e-8,
        "tau": 0.0,
        "population": None,
        "eapsum_tables": None,
        "items": [
            {
                "code": f"calibration_{index}",
                "factor_id": 0,
                "alpha": math.log(discrimination),
                "b": difficulty,
                "zeta": [0.0],
            }
            for index, difficulty in enumerate(difficulties)
        ],
    }

    def probability(theta: float, difficulty: float) -> float:
        return 1.0 / (1.0 + math.exp(-discrimination * (theta + difficulty)))

    def evaluate(
        *, adaptive: bool
    ) -> tuple[dict[str, float], dict[str, list[float]]]:
        squared_errors: list[float] = []
        candidate_prediction_errors: list[float] = []
        administered_counts: list[int] = []
        target_reached: list[float] = []
        for candidate_index in range(ADAPTIVE_CALIBRATION_CANDIDATES):
            generator = random.Random(10_000 + candidate_index)
            theta = -2.0 + 4.0 * (
                candidate_index + 0.5
            ) / ADAPTIVE_CALIBRATION_CANDIDATES
            responses: dict[str, int] = {}
            random_order = list(range(ADAPTIVE_CALIBRATION_ITEMS))
            random.Random(20_000 + candidate_index).shuffle(random_order)
            state = cat_next_item(bundle, responses, device="cpu")
            for step in range(ADAPTIVE_CALIBRATION_MAX_ITEMS):
                item_index = (
                    state["ranked_items"][0] if adaptive else random_order[step]
                )
                code = f"calibration_{item_index}"
                responses[code] = int(
                    generator.random() < probability(theta, difficulties[item_index])
                )
                state = cat_next_item(bundle, responses, device="cpu")
                if state["theta_sd"][0] <= ADAPTIVE_CALIBRATION_TARGET_SE:
                    break
            estimate = state["theta_eap"][0]
            squared_errors.append((estimate - theta) ** 2)
            administered_counts.append(len(responses))
            prediction_errors = [
                (
                    probability(estimate, difficulty)
                    - probability(theta, difficulty)
                )
                ** 2
                for item_index, difficulty in enumerate(difficulties)
                if f"calibration_{item_index}" not in responses
            ]
            candidate_prediction_errors.append(statistics.fmean(prediction_errors))
            target_reached.append(
                float(state["theta_sd"][0] <= ADAPTIVE_CALIBRATION_TARGET_SE)
            )
        return {
            "theta_rmse": math.sqrt(statistics.fmean(squared_errors)),
            "unobserved_probability_mse": statistics.fmean(
                candidate_prediction_errors
            ),
            "mean_calibration_queries": statistics.fmean(administered_counts),
            "target_se_reached_rate": statistics.fmean(target_reached),
        }, {
            "theta_squared_error": squared_errors,
            "unobserved_probability_squared_error": candidate_prediction_errors,
            "calibration_queries": [float(value) for value in administered_counts],
            "target_se_reached": target_reached,
        }

    adaptive, adaptive_samples = evaluate(adaptive=True)
    random_baseline, random_samples = evaluate(adaptive=False)
    paired_delta = {
        metric: statistics.fmean(adaptive_samples[metric])
        - statistics.fmean(random_samples[metric])
        for metric in adaptive_samples
    }
    paired_delta_ci95 = {
        metric: _paired_bootstrap_mean_ci(
            adaptive_samples[metric], random_samples[metric]
        )
        for metric in adaptive_samples
    }

    confidence_z = 1.96
    sequential_correct: list[float] = []
    fixed_correct: list[float] = []
    sequential_queries: list[float] = []
    classification_rows: list[tuple[float, float, float, float, float]] = []
    for candidate_index in range(ADAPTIVE_CALIBRATION_CANDIDATES):
        generator = random.Random(30_000 + candidate_index)
        theta = -2.0 + 4.0 * (
            candidate_index + 0.5
        ) / ADAPTIVE_CALIBRATION_CANDIDATES
        responses: dict[str, int] = {}
        state = cat_next_item(bundle, responses, device="cpu")
        early_decision: tuple[int, bool] | None = None
        for step in range(ADAPTIVE_CALIBRATION_MAX_ITEMS):
            item_index = state["ranked_items"][0]
            code = f"calibration_{item_index}"
            responses[code] = int(
                generator.random() < probability(theta, difficulties[item_index])
            )
            state = cat_next_item(bundle, responses, device="cpu")
            if early_decision is None and abs(state["theta_eap"][0]) > (
                confidence_z * state["theta_sd"][0]
            ):
                early_decision = (step + 1, state["theta_eap"][0] >= 0.0)
        fixed_decision = state["theta_eap"][0] >= 0.0
        confidence_resolved = early_decision is not None
        if early_decision is None:
            early_decision = (ADAPTIVE_CALIBRATION_MAX_ITEMS, fixed_decision)
        true_decision = theta >= 0.0
        sequential_queries.append(float(early_decision[0]))
        sequential_correct.append(float(early_decision[1] == true_decision))
        fixed_correct.append(float(fixed_decision == true_decision))
        classification_rows.append(
            (
                abs(theta),
                float(early_decision[0]),
                sequential_correct[-1],
                fixed_correct[-1],
                float(confidence_resolved),
            )
        )

    def summarize_stratum(lower: float, upper: float | None) -> dict[str, float]:
        rows = [
            row
            for row in classification_rows
            if row[0] >= lower and (upper is None or row[0] < upper)
        ]
        return {
            "candidates": len(rows),
            "sequential_mean_queries": statistics.fmean(row[1] for row in rows),
            "early_stop_rate": statistics.fmean(
                float(row[1] < ADAPTIVE_CALIBRATION_MAX_ITEMS) for row in rows
            ),
            "sequential_accuracy": statistics.fmean(row[2] for row in rows),
            "fixed_accuracy": statistics.fmean(row[3] for row in rows),
            "confidence_resolved_rate": statistics.fmean(row[4] for row in rows),
            "resolved_accuracy": statistics.fmean(
                row[2] for row in rows if row[4]
            ),
        }

    classification_stopping = {
        "method": "confidence_interval_classification_stopping",
        "decision_cut": 0.0,
        "confidence_z": confidence_z,
        "sequential_mean_queries": statistics.fmean(sequential_queries),
        "fixed_queries": ADAPTIVE_CALIBRATION_MAX_ITEMS,
        "early_stop_rate": statistics.fmean(
            float(value < ADAPTIVE_CALIBRATION_MAX_ITEMS)
            for value in sequential_queries
        ),
        "sequential_accuracy": statistics.fmean(sequential_correct),
        "fixed_accuracy": statistics.fmean(fixed_correct),
        "decision_agreement_rate": statistics.fmean(
            float(left == right)
            for left, right in zip(sequential_correct, fixed_correct)
        ),
        "query_delta_ci95": _paired_bootstrap_mean_ci(
            sequential_queries,
            [float(ADAPTIVE_CALIBRATION_MAX_ITEMS)]
            * ADAPTIVE_CALIBRATION_CANDIDATES,
        ),
        "accuracy_delta_ci95": _paired_bootstrap_mean_ci(
            sequential_correct, fixed_correct
        ),
        "confidence_resolved_rate": statistics.fmean(
            row[4] for row in classification_rows
        ),
        "resolved_accuracy": statistics.fmean(
            row[2] for row in classification_rows if row[4]
        ),
        "distance_from_cut_strata": {
            "near_lt_0_5": summarize_stratum(0.0, 0.5),
            "mid_0_5_to_1": summarize_stratum(0.5, 1.0),
            "far_ge_1": summarize_stratum(1.0, None),
        },
    }

    def selective_point(
        seed: int, confidence: float
    ) -> tuple[dict[str, float], dict[str, list[float]]]:
        resolved: list[tuple[int, float, float, bool]] = []
        resolution_flags: list[float] = []
        all_candidate_queries: list[float] = []
        for candidate_index in range(ADAPTIVE_CALIBRATION_CANDIDATES):
            generator = random.Random(seed + candidate_index)
            theta = -2.0 + 4.0 * (
                candidate_index + 0.5
            ) / ADAPTIVE_CALIBRATION_CANDIDATES
            responses: dict[str, int] = {}
            state = cat_next_item(bundle, responses, device="cpu")
            resolution_flags.append(0.0)
            all_candidate_queries.append(float(ADAPTIVE_CALIBRATION_MAX_ITEMS))
            for step in range(ADAPTIVE_CALIBRATION_MAX_ITEMS):
                item_index = state["ranked_items"][0]
                code = f"calibration_{item_index}"
                responses[code] = int(
                    generator.random() < probability(theta, difficulties[item_index])
                )
                state = cat_next_item(bundle, responses, device="cpu")
                if abs(state["theta_eap"][0]) > confidence * state["theta_sd"][0]:
                    resolved.append(
                        (
                            step + 1,
                            float((state["theta_eap"][0] >= 0.0) != (theta >= 0.0)),
                            abs(theta),
                            theta >= 0.0,
                        )
                    )
                    resolution_flags[-1] = 1.0
                    all_candidate_queries[-1] = float(step + 1)
                    break
        errors = sum(row[1] for row in resolved)
        count = len(resolved)
        risk = errors / count
        z95 = 1.96
        denominator = 1.0 + z95**2 / count
        error_upper = (
            risk
            + z95**2 / (2.0 * count)
            + z95 * math.sqrt(risk * (1.0 - risk) / count + z95**2 / (4.0 * count**2))
        ) / denominator
        negative = [row for row in resolved if not row[3]]
        positive = [row for row in resolved if row[3]]
        return {
            "confidence_z": confidence,
            "coverage": count / ADAPTIVE_CALIBRATION_CANDIDATES,
            "selective_risk": risk,
            "selective_risk_wilson_upper95": error_upper,
            "resolved_mean_queries": statistics.fmean(row[0] for row in resolved),
            "all_candidate_mean_queries": statistics.fmean(all_candidate_queries),
            "near_cut_coverage": sum(row[2] < 0.5 for row in resolved) / 100.0,
            "negative_coverage": len(negative) / 200.0,
            "positive_coverage": len(positive) / 200.0,
            "absolute_directional_coverage_gap": abs(
                len(negative) - len(positive)
            )
            / 200.0,
            "negative_selective_risk": statistics.fmean(row[1] for row in negative),
            "positive_selective_risk": statistics.fmean(row[1] for row in positive),
        }, {
            "resolved": resolution_flags,
            "queries": all_candidate_queries,
        }

    development_points = [
        selective_point(30_000, confidence)[0]
        for confidence in SELECTIVE_CLASSIFICATION_Z
    ]
    selected = max(
        (
            point
            for point in development_points
            if point["selective_risk_wilson_upper95"]
            <= SELECTIVE_CLASSIFICATION_MAX_ERROR_UPPER
        ),
        key=lambda point: point["coverage"],
    )
    heldout, heldout_samples = selective_point(40_000, selected["confidence_z"])
    heldout_baseline, heldout_baseline_samples = selective_point(40_000, 1.96)
    replication_pairs = [(heldout, heldout_baseline)]
    for replication in range(1, SELECTIVE_CLASSIFICATION_REPLICATIONS):
        seed = 40_000 + 1_000 * replication
        candidate, _ = selective_point(seed, selected["confidence_z"])
        baseline, _ = selective_point(seed, 1.96)
        replication_pairs.append((candidate, baseline))
    replication_rows = [
        {
            "coverage_delta": candidate["coverage"] - baseline["coverage"],
            "all_candidate_query_delta": candidate["all_candidate_mean_queries"]
            - baseline["all_candidate_mean_queries"],
            "selective_risk": candidate["selective_risk"],
            "selective_risk_wilson_upper95": candidate[
                "selective_risk_wilson_upper95"
            ],
        }
        for candidate, baseline in replication_pairs
    ]
    replication_count = len(replication_rows)
    pass_rate = statistics.fmean(
        float(
            row["selective_risk_wilson_upper95"]
            <= SELECTIVE_CLASSIFICATION_MAX_ERROR_UPPER
        )
        for row in replication_rows
    )

    def monte_carlo_se(metric: str) -> float:
        return statistics.stdev(row[metric] for row in replication_rows) / math.sqrt(
            replication_count
        )
    classification_stopping["risk_coverage_screen"] = {
        "method": "development_selected_heldout_evaluated_reject_option",
        "development_seed": 30_000,
        "heldout_seed": 40_000,
        "maximum_selective_risk_wilson_upper95": (
            SELECTIVE_CLASSIFICATION_MAX_ERROR_UPPER
        ),
        "development_points": development_points,
        "selected_confidence_z": selected["confidence_z"],
        "heldout": heldout,
        "heldout_baseline": heldout_baseline,
        "heldout_paired_delta": {
            "coverage": statistics.fmean(heldout_samples["resolved"])
            - statistics.fmean(heldout_baseline_samples["resolved"]),
            "all_candidate_queries": statistics.fmean(heldout_samples["queries"])
            - statistics.fmean(heldout_baseline_samples["queries"]),
        },
        "heldout_paired_delta_ci95": {
            "coverage": _paired_bootstrap_mean_ci(
                heldout_samples["resolved"], heldout_baseline_samples["resolved"]
            ),
            "all_candidate_queries": _paired_bootstrap_mean_ci(
                heldout_samples["queries"], heldout_baseline_samples["queries"]
            ),
        },
        "replication_audit": {
            "replications": SELECTIVE_CLASSIFICATION_REPLICATIONS,
            "seed_start": 40_000,
            "seed_step": 1_000,
            "error_upper_bound_pass_rate": pass_rate,
            "error_upper_bound_pass_rate_monte_carlo_se": math.sqrt(
                pass_rate * (1.0 - pass_rate) / replication_count
            ),
            "target_pass_rate_monte_carlo_se": 0.025,
            "worst_case_replications_for_target_monte_carlo_se": math.ceil(
                0.25 / 0.025**2
            ),
            "coverage_delta_mean": statistics.fmean(
                row["coverage_delta"] for row in replication_rows
            ),
            "coverage_delta_monte_carlo_se": monte_carlo_se("coverage_delta"),
            "coverage_delta_range": [
                min(row["coverage_delta"] for row in replication_rows),
                max(row["coverage_delta"] for row in replication_rows),
            ],
            "all_candidate_query_delta_mean": statistics.fmean(
                row["all_candidate_query_delta"] for row in replication_rows
            ),
            "all_candidate_query_delta_monte_carlo_se": monte_carlo_se(
                "all_candidate_query_delta"
            ),
            "all_candidate_query_delta_range": [
                min(row["all_candidate_query_delta"] for row in replication_rows),
                max(row["all_candidate_query_delta"] for row in replication_rows),
            ],
            "selective_risk_mean": statistics.fmean(
                row["selective_risk"] for row in replication_rows
            ),
            "selective_risk_monte_carlo_se": monte_carlo_se("selective_risk"),
            "selective_risk_max": max(
                row["selective_risk"] for row in replication_rows
            ),
            "selective_risk_wilson_upper95_max": max(
                row["selective_risk_wilson_upper95"] for row in replication_rows
            ),
            "candidate_status": "rejected_not_replication_stable",
        },
    }
    return {
        "method": "maximum_fisher_information_eap_screen",
        "candidates": ADAPTIVE_CALIBRATION_CANDIDATES,
        "item_bank_size": ADAPTIVE_CALIBRATION_ITEMS,
        "maximum_queries": ADAPTIVE_CALIBRATION_MAX_ITEMS,
        "target_standard_error": ADAPTIVE_CALIBRATION_TARGET_SE,
        "adaptive": adaptive,
        "random_baseline": random_baseline,
        "paired_delta": paired_delta,
        "paired_delta_ci95": paired_delta_ci95,
        "classification_stopping": classification_stopping,
        "mean_query_reduction": random_baseline["mean_calibration_queries"]
        - adaptive["mean_calibration_queries"],
        "theta_rmse_reduction": random_baseline["theta_rmse"]
        - adaptive["theta_rmse"],
        "unobserved_probability_mse_reduction": random_baseline[
            "unobserved_probability_mse"
        ]
        - adaptive["unobserved_probability_mse"],
        "known_limit": (
            "synthetic one-dimensional onboarding query efficiency is not live "
            "decision latency, buyer calibration, or invariant model ability"
        ),
    }


def run_benchmark() -> dict[str, object]:
    """Return paired held-out accuracy uncertainty and decision latency."""
    baseline_evidence = _build_evidence(two_neighbor=False)
    candidate_evidence = _build_evidence(two_neighbor=True)
    baseline, baseline_samples = _evaluate_quality(baseline_evidence)
    candidate, candidate_samples = _evaluate_quality(candidate_evidence)
    adaptive_candidate_calibration = _validate_adaptive_candidate_calibration()
    unseen_predictions = sum(
        bool(
            candidate_evidence.ranked_evidence(
                (UNSEEN_MODEL_ID,),
                f"held_out_{context_index}",
                _vector(2.0 * math.pi * (context_index + 0.5) / TRAIN_CONTEXTS),
            )
        )
        for context_index in range(TRAIN_CONTEXTS)
    )
    predictive_fit = {
        "method": "cross_validated_prediction_tasks",
        "missing_items": {
            "status": "synthetic_executed",
            "candidates": "existing",
            "items": "held_out",
            "brier_score": candidate["brier_score"],
            "log_loss": candidate["log_loss"],
        },
        "missing_persons": {
            "status": "failed_no_prediction",
            "candidates": "held_out",
            "items": "existing",
            "contexts": TRAIN_CONTEXTS,
            "prediction_coverage": unseen_predictions / TRAIN_CONTEXTS,
            "known_limit": (
                "the router emits no psychometric estimate for an unseen "
                "candidate deployment"
            ),
            "calibration_screen": adaptive_candidate_calibration,
        },
    }
    assignment_design = _validate_assignment_design(candidate_evidence)
    scale_linking = _validate_scale_linking()
    parameter_invariance = _validate_parameter_invariance()
    candidate_roster_invariance = _validate_candidate_roster_invariance()
    functional_drift = _validate_functional_drift()
    sequential_drift = _validate_sequential_drift()
    score_equating = _validate_score_equating()
    response_pattern_fit = _validate_response_pattern_fit()
    construct_dimensionality = _validate_construct_dimensionality()
    global_model_fit = _validate_global_model_fit()
    score_reliability = _validate_score_reliability()
    generalizability_design = _validate_generalizability_design()
    conditional_information = _validate_conditional_information()
    classification_decision = _validate_classification_decision()
    selection_utility = _validate_selection_utility()
    candidate_group_dif = _validate_candidate_group_dif()
    judge_effects = _validate_judge_effects()
    item_covariate_effect = _validate_item_covariate_effect()
    parameter_uncertainty = _validate_parameter_uncertainty()
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
    gate_status = {
        "accuracy_noninferior": "passed" if all(
            delta_ci95[metric][1] <= 0.0
            for metric in (
                "brier_score",
                "log_loss",
                "calibration_logit_rmse",
                "top_choice_regret",
            )
        ) else "failed",
        "buyer_heldout": "not_executed",
        "decision_latency_improved": (
            "passed" if delta_ci95["decision_median_ms"][1] < 0.0 else "failed"
        ),
        "measurement_validity": "not_executed",
    }
    gates = {name: status == "passed" for name, status in gate_status.items()}
    validity_components = {
        "scale_linking": "not_executed",
        "parameter_invariance": "not_executed",
        "sequential_drift": "not_executed",
        "candidate_roster_invariance": "not_executed",
        "score_equating": "not_executed",
        "response_pattern_fit": "not_executed",
        "construct_dimensionality": "not_executed",
        "global_model_fit": "not_executed",
        "score_reliability": "not_executed",
        "generalizability_design": "not_executed",
        "conditional_information": "not_executed",
        "classification_decision": "not_executed",
        "decision_utility": "not_executed",
        "predictive_fit": "not_executed",
        "local_independence": "not_executed",
        "candidate_group_dif": "not_executed",
        "item_language_domain_effects": "not_executed",
        "judge_effects": "not_executed",
        "parameter_uncertainty": "not_executed",
        "adaptive_exposure": "not_executed",
    }
    validity_requirements = {
        "scale_linking": {
            "owner_contract_status": "released",
            "required_evidence": (
                "versioned common-item anchors and a preregistered linking policy"
            ),
        },
        "parameter_invariance": {
            "owner_contract_status": "released_effect_size_screen",
            "required_evidence": (
                "versioned recalibrations, stable anchors, identified linking, and "
                "preregistered drift review rules"
            ),
            "known_limit": (
                "the benchmark drift tolerance is an effect-size screen, not a "
                "sampling-uncertainty or significance test"
            ),
        },
        "sequential_drift": {
            "owner_contract_status": "benchmark_screen_only",
            "required_evidence": (
                "versioned buyer observations over time, declared change risks, "
                "and preregistered false-alarm and detection-delay targets"
            ),
            "known_limit": (
                "the one-stream known-probability CUSUM screen is not the paper's "
                "multistream Bayesian compound-risk procedure"
            ),
        },
        "candidate_roster_invariance": {
            "owner_contract_status": "released_limited_screen",
            "required_evidence": (
                "versioned candidate rosters, common buyer items, identified "
                "linking, and preregistered score-shift targets"
            ),
            "known_limit": (
                "synthetic separate-calibration stability does not establish "
                "invariance for a buyer's models, queries, or deployment versions"
            ),
        },
        "score_equating": {
            "owner_contract_status": "released",
            "required_evidence": (
                "versioned buyer forms, comparable populations or anchors, and "
                "preregistered equating-error targets"
            ),
        },
        "response_pattern_fit": {
            "owner_contract_status": "released_group_based_screen",
            "required_evidence": (
                "complete buyer candidate-by-criterion responses, a preregistered "
                "action threshold, and human review of flagged patterns"
            ),
            "known_limit": (
                "nonparametric person fit ranks unusual response patterns but does "
                "not identify their cause or prove a candidate invalid"
            ),
        },
        "construct_dimensionality": {
            "owner_contract_status": "released_limited_screen",
            "required_evidence": (
                "buyer candidate-by-criterion responses, a preregistered construct "
                "structure, and confirmatory holdout fit"
            ),
            "known_limit": (
                "Pearson-correlation PCA parallel analysis on dichotomous responses "
                "is a dimensionality screen, not construct identification or "
                "confirmatory factor validation"
            ),
        },
        "global_model_fit": {
            "owner_contract_status": "released_limited_information",
            "required_evidence": (
                "converged buyer calibration, complete candidate-by-criterion "
                "responses, a preregistered model, and held-out fit review"
            ),
            "known_limit": (
                "M2 sensitivity depends on the misspecification and sample design; "
                "one global statistic cannot establish construct validity"
            ),
        },
        "score_reliability": {
            "owner_contract_status": "released",
            "required_evidence": (
                "converged buyer calibration, posterior standard errors, "
                "preregistered reliability targets, and model-fit evidence"
            ),
            "known_limit": (
                "reliability summarizes score precision under the fitted model; "
                "it cannot establish model fit, invariance, or construct validity"
            ),
        },
        "generalizability_design": {
            "owner_contract_status": "released_balanced_design",
            "required_evidence": (
                "a complete balanced buyer candidate-by-query-by-occasion design, "
                "random-facet justification, and preregistered dependability target"
            ),
            "known_limit": (
                "clamped ANOVA variance components and a synthetic balanced design "
                "do not establish generalizability for incomplete live routing data"
            ),
        },
        "conditional_information": {
            "owner_contract_status": "released",
            "required_evidence": (
                "buyer-relevant trait regions, calibrated candidate-query items, "
                "and preregistered conditional precision targets"
            ),
            "known_limit": (
                "Fisher information is conditional on the fitted model and item "
                "bank; it cannot establish construct validity or buyer coverage"
            ),
        },
        "classification_decision": {
            "owner_contract_status": "released",
            "required_evidence": (
                "a buyer-defined routing cut, linked candidate measures, valid "
                "standard errors, decision costs, and preregistered targets"
            ),
            "known_limit": (
                "normal-approximation classification assumes valid linked measures "
                "and standard errors; it cannot define the buyer decision or its cost"
            ),
        },
        "decision_utility": {
            "owner_contract_status": "released_selection_analogue",
            "required_evidence": (
                "buyer-valued outcome units, predictive validity, request volume, "
                "routing cost, selection ratio, and preregistered utility target"
            ),
            "known_limit": (
                "the personnel-selection normal model is an analogue, not a "
                "validated economic model for multi-model routing"
            ),
        },
        "predictive_fit": {
            "owner_contract_status": "benchmark_axis_incomplete",
            "required_evidence": (
                "versioned buyer outcomes for held-out queries and held-out "
                "candidate deployments, scored separately"
            ),
            "known_limit": (
                "held-out queries for known candidates do not establish prediction "
                "for a newly introduced or changed candidate deployment"
            ),
        },
        "local_independence": {
            "owner_contract_status": "owner_pr_pending",
            "required_evidence": (
                "buyer response matrix, model probabilities, and preregistered "
                "multiplicity and review rules"
            ),
        },
        "candidate_group_dif": {
            "owner_contract_status": "released",
            "required_evidence": (
                "candidate cohort labels, matched scores, purification, and "
                "preregistered review rules"
            ),
        },
        "item_language_domain_effects": {
            "owner_contract_status": "released_limited",
            "required_evidence": (
                "preregistered item covariates, anchors, and linked multigroup buyer "
                "observations"
            ),
            "known_limit": (
                "one shared covariate coefficient; language-specific discrimination "
                "and residual effects are not implemented"
            ),
        },
        "judge_effects": {
            "owner_contract_status": "released",
            "required_evidence": (
                "connected respondent-task-rater observations with versioned judge "
                "identities"
            ),
        },
        "parameter_uncertainty": {
            "owner_contract_status": "released_limited",
            "required_evidence": (
                "converged buyer calibration, identified estimands, standard errors, "
                "and preregistered interval coverage rules"
            ),
            "known_limit": (
                "Oakes standard errors condition on population parameters and do not "
                "support anchors, zero inflation, or item covariates"
            ),
        },
        "adaptive_exposure": {
            "owner_contract_status": "released_exposure_control_only",
            "required_evidence": (
                "randomized assignment or logged routing propensities for every "
                "candidate outcome"
            ),
            "known_limit": (
                "CAT exposure control does not record gateway propensities or "
                "identify unobserved candidate outcomes"
            ),
        },
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
        "production_default_change_allowed": all(gates.values()),
        "production_gate_status": gate_status,
        "production_gates": gates,
        "measurement_validity_components": validity_components,
        "measurement_validity_requirements": validity_requirements,
        "assignment_design_validation": assignment_design,
        "scale_linking_validation": scale_linking,
        "parameter_invariance_validation": parameter_invariance,
        "candidate_roster_invariance_validation": candidate_roster_invariance,
        "functional_drift_validation": functional_drift,
        "sequential_drift_validation": sequential_drift,
        "score_equating_validation": score_equating,
        "response_pattern_fit_validation": response_pattern_fit,
        "construct_dimensionality_validation": construct_dimensionality,
        "global_model_fit_validation": global_model_fit,
        "score_reliability_validation": score_reliability,
        "generalizability_design_validation": generalizability_design,
        "conditional_information_validation": conditional_information,
        "classification_decision_validation": classification_decision,
        "decision_utility_validation": selection_utility,
        "predictive_fit_validation": predictive_fit,
        "adaptive_candidate_calibration_validation": adaptive_candidate_calibration,
        "candidate_group_dif_validation": candidate_group_dif,
        "judge_effects_validation": judge_effects,
        "item_language_domain_effect_validation": item_covariate_effect,
        "parameter_uncertainty_validation": parameter_uncertainty,
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
    assert result["production_default_change_allowed"] == all(gates.values())
    return result


def main() -> None:
    """Print the held-out benchmark report as stable JSON."""
    result = run_benchmark()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
