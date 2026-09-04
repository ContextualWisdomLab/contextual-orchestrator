"""Measure semantic warm-start accuracy and decision latency on held-out contexts."""

from __future__ import annotations

import json
import math
from pathlib import Path
import random
import statistics
import sys
import time

import fast_mlsirm
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.psychometric_routing import (  # noqa: E402
    PsychometricRoutingEvidence,
)


MODEL_IDS = tuple(f"model_{index}" for index in range(4))
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


def _validate_assignment_design(
    evidence: PsychometricRoutingEvidence,
) -> dict[str, object]:
    """Validate a preregistered positive-propensity logging design on known truth."""
    generator = random.Random(ASSIGNMENT_SEED)
    weighted_rewards = {model_id: [] for model_id in MODEL_IDS}
    observations = {model_id: 0 for model_id in MODEL_IDS}
    minimum_probability = EXPLORATION_RATE / len(MODEL_IDS)
    for trial_index in range(ASSIGNMENT_TRIALS):
        context_index = trial_index % TRAIN_CONTEXTS
        angle = 2.0 * math.pi * (context_index + 0.5) / TRAIN_CONTEXTS
        context = f"held_out_{context_index}"
        ranked = evidence.ranked_evidence(MODEL_IDS, context, _vector(angle))
        selected_probability = minimum_probability
        probabilities = {model_id: minimum_probability for model_id in MODEL_IDS}
        probabilities[ranked[0][0]] += 1.0 - EXPLORATION_RATE
        draw = generator.random()
        cumulative = 0.0
        selected = MODEL_IDS[-1]
        for model_id in MODEL_IDS:
            cumulative += probabilities[model_id]
            if draw < cumulative:
                selected = model_id
                selected_probability = probabilities[model_id]
                break
        selected_index = MODEL_IDS.index(selected)
        reward = float(generator.random() < _probability(selected_index, angle))
        observations[selected] += 1
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
        "true_value": true_values,
        "inverse_propensity_rmse": math.sqrt(
            statistics.fmean(
                (estimates[model_id] - true_values[model_id]) ** 2
                for model_id in MODEL_IDS
            )
        ),
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


def run_benchmark() -> dict[str, object]:
    """Return paired held-out accuracy uncertainty and decision latency."""
    baseline_evidence = _build_evidence(two_neighbor=False)
    candidate_evidence = _build_evidence(two_neighbor=True)
    baseline, baseline_samples = _evaluate_quality(baseline_evidence)
    candidate, candidate_samples = _evaluate_quality(candidate_evidence)
    assignment_design = _validate_assignment_design(candidate_evidence)
    scale_linking = _validate_scale_linking()
    parameter_invariance = _validate_parameter_invariance()
    response_pattern_fit = _validate_response_pattern_fit()
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
            for metric in ("brier_score", "log_loss", "top_choice_regret")
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
        "response_pattern_fit": "not_executed",
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
        "response_pattern_fit_validation": response_pattern_fit,
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
