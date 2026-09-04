"""Fast-MLSIRM contextual ability ordering for cold start and failover."""

from __future__ import annotations

import math
import numpy as np
from dataclasses import replace
from pathlib import Path
import threading
import pytest
import scripts.benchmark_psychometric_heldout as heldout_benchmark

from contextual_orchestrator import (
    ModelAgent,
    TaskOrchestrator,
    default_role_effort_catalog,
)
from contextual_orchestrator.psychometric_routing import PsychometricRoutingEvidence
from scripts.benchmark_psychometric_routing import (
    _last_context_request,
    _require_runtime,
)
from scripts.benchmark_psychometric_heldout import (
    _expected_brier,
    _paired_bootstrap_mean_ci,
)


def test_psychometric_benchmark_requires_python_312() -> None:
    try:
        _require_runtime((3, 11))
    except SystemExit as error:
        assert "uv run --python 3.12" in str(error)
    else:
        raise AssertionError("Python 3.11 must not enter the benchmark dependency path")

    _require_runtime((3, 12))


def test_psychometric_benchmark_last_context_request_tracks_context_count() -> None:
    assert _last_context_request(512) == ("context_511", [1.0, 512.0])
    assert _last_context_request(3) == ("context_2", [1.0, 3.0])


def test_psychometric_benchmark_last_context_request_rejects_nonpositive_counts() -> None:
    with pytest.raises(ValueError, match="context_count must be positive"):
        _last_context_request(0)


def test_expected_brier_includes_bernoulli_outcome_variance() -> None:
    assert _expected_brier(0.5, 0.5) == 0.25
    assert _expected_brier(1.0, 0.5) == 0.5


def test_paired_bootstrap_interval_uses_within_context_differences() -> None:
    assert _paired_bootstrap_mean_ci(
        [0.1, 0.2, 0.3], [0.2, 0.3, 0.4]
    ) == pytest.approx([-0.1, -0.1])


def test_paired_bootstrap_interval_rejects_unpaired_samples() -> None:
    with pytest.raises(ValueError, match="non-empty and equal length"):
        _paired_bootstrap_mean_ci([0.1], [])


def test_heldout_report_pairs_every_delta_with_its_interval(monkeypatch) -> None:
    monkeypatch.setattr(
        heldout_benchmark,
        "_measure_paired_latency",
        lambda _baseline, _candidate: (
            {"decision_p50_ms": 1.0, "decision_p95_ms": 1.0},
            {"decision_p50_ms": 2.0, "decision_p95_ms": 2.0},
            [1.0] * heldout_benchmark.TRAIN_CONTEXTS,
            [2.0] * heldout_benchmark.TRAIN_CONTEXTS,
        ),
    )

    report = heldout_benchmark.run_benchmark()

    assert (
        report["latency_repetitions_per_context"]
        == heldout_benchmark.LATENCY_REPETITIONS
    )
    assert report["delta"].keys() == report["delta_ci95"].keys()
    for metric, point in report["delta"].items():
        lower, upper = report["delta_ci95"][metric]
        assert lower <= point <= upper
    assert report["production_gates"] == {
        "accuracy_noninferior": True,
        "buyer_heldout": False,
        "decision_latency_improved": False,
        "measurement_validity": False,
    }
    assert report["production_gate_status"] == {
        "accuracy_noninferior": "passed",
        "buyer_heldout": "not_executed",
        "decision_latency_improved": "failed",
        "measurement_validity": "not_executed",
    }
    assert report["baseline"]["calibration_slope"] == pytest.approx(
        0.9914448613738104
    )
    assert report["calibration_slope"] == pytest.approx(1.014029928095512)
    assert report["baseline"]["calibration_logit_rmse"] == pytest.approx(
        0.2312349809472711
    )
    assert report["calibration_logit_rmse"] == pytest.approx(
        0.025803494528640156
    )
    assert report["delta"]["calibration_logit_rmse"] == pytest.approx(
        -0.20543148641863096
    )
    assert report["delta_ci95"]["calibration_logit_rmse"] == pytest.approx(
        [-0.20803038507771457, -0.20292440265781464]
    )
    assert report["measurement_validity_components"] == {
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
    requirements = report["measurement_validity_requirements"]
    assert set(requirements) == set(report["measurement_validity_components"])
    assert requirements["scale_linking"]["owner_contract_status"] == "released"
    assert requirements["parameter_invariance"]["owner_contract_status"] == (
        "released_effect_size_screen"
    )
    assert "not a sampling-uncertainty" in requirements["parameter_invariance"][
        "known_limit"
    ]
    assert requirements["sequential_drift"]["owner_contract_status"] == (
        "benchmark_screen_only"
    )
    assert "not the paper's multistream" in requirements["sequential_drift"][
        "known_limit"
    ]
    assert requirements["response_pattern_fit"]["owner_contract_status"] == (
        "released_group_based_screen"
    )
    assert "does not identify their cause" in requirements["response_pattern_fit"][
        "known_limit"
    ]
    assert requirements["construct_dimensionality"]["owner_contract_status"] == (
        "released_limited_screen"
    )
    assert "not construct identification" in requirements[
        "construct_dimensionality"
    ]["known_limit"]
    assert requirements["global_model_fit"]["owner_contract_status"] == (
        "released_limited_information"
    )
    assert "cannot establish construct validity" in requirements["global_model_fit"][
        "known_limit"
    ]
    assert requirements["score_reliability"]["owner_contract_status"] == "released"
    assert "cannot establish model fit" in requirements["score_reliability"][
        "known_limit"
    ]
    assert requirements["generalizability_design"]["owner_contract_status"] == (
        "released_balanced_design"
    )
    assert "incomplete live routing data" in requirements[
        "generalizability_design"
    ]["known_limit"]
    assert requirements["conditional_information"]["owner_contract_status"] == (
        "released"
    )
    assert "cannot establish construct validity" in requirements[
        "conditional_information"
    ]["known_limit"]
    assert requirements["classification_decision"]["owner_contract_status"] == (
        "released"
    )
    assert "cannot define the buyer decision" in requirements[
        "classification_decision"
    ]["known_limit"]
    assert requirements["decision_utility"]["owner_contract_status"] == (
        "released_selection_analogue"
    )
    assert "not a validated economic model" in requirements["decision_utility"][
        "known_limit"
    ]
    assert requirements["predictive_fit"]["owner_contract_status"] == (
        "benchmark_axis_incomplete"
    )
    assert "newly introduced or changed candidate" in requirements["predictive_fit"][
        "known_limit"
    ]
    assert (
        requirements["local_independence"]["owner_contract_status"]
        == "owner_pr_pending"
    )
    assert (
        requirements["item_language_domain_effects"]["owner_contract_status"]
        == "released_limited"
    )
    assert "not implemented" in requirements["item_language_domain_effects"][
        "known_limit"
    ]
    assert (
        requirements["adaptive_exposure"]["owner_contract_status"]
        == "released_exposure_control_only"
    )
    assert "does not record gateway propensities" in requirements[
        "adaptive_exposure"
    ]["known_limit"]
    assert requirements["parameter_uncertainty"]["owner_contract_status"] == (
        "released_limited"
    )
    assert "condition on population parameters" in requirements[
        "parameter_uncertainty"
    ]["known_limit"]
    assert report["production_default_change_allowed"] is False
    assignment = report["assignment_design_validation"]
    assert assignment["assignment_mechanism"] == "epsilon_greedy"
    assert assignment["minimum_assignment_probability"] == pytest.approx(0.05)
    assert assignment["trials"] == heldout_benchmark.ASSIGNMENT_TRIALS
    assert assignment["seed"] == heldout_benchmark.ASSIGNMENT_SEED
    assert all(
        count > 0 for count in assignment["observations_by_candidate"].values()
    )
    assert assignment["inverse_propensity_rmse"] == pytest.approx(
        0.008942720293704905
    )
    assert assignment["naive_observed_rmse"] == pytest.approx(
        0.32197876384702356
    )
    assert assignment["inverse_propensity_rmse_reduction"] == pytest.approx(
        0.31303604355331865
    )
    assert assignment["true_value_coverage_rate"] == 1.0
    linking = report["scale_linking_validation"]
    assert linking["method"] == "stocking_lord"
    assert linking["anchor_items"] == 6
    assert linking["converged"] is True
    assert linking["termination_reason"] == "tolerance_met"
    assert linking["estimated_slope"] == pytest.approx(linking["true_slope"])
    assert linking["estimated_intercept"] == pytest.approx(
        linking["true_intercept"]
    )
    assert linking["true_parameter_rmse"] < 1e-12
    invariance = report["parameter_invariance_validation"]
    assert invariance["method"] == "linked_parameter_drift_effect_size"
    assert invariance["anchor_items"] == list(range(7))
    assert invariance["drift_tolerance"] == (
        heldout_benchmark.INVARIANCE_DRIFT_TOLERANCE
    )
    assert invariance["expected_drift_items"] == [7]
    assert invariance["flagged_items"] == [7]
    assert invariance["known_drift_recall"] == 1.0
    assert invariance["stable_item_false_positive_count"] == 0
    assert invariance["maximum_stable_item_drift"] == 0.0
    assert invariance["injected_item_drift"] == pytest.approx(0.5656854249492381)
    assert invariance["linking_converged"] is True
    roster = report["candidate_roster_invariance_validation"]
    assert roster["method"] == "separate_calibration_common_item_linking"
    assert roster["seed"] == heldout_benchmark.ROSTER_INVARIANCE_SEED
    assert roster["full_candidate_count"] == 20
    assert roster["retained_candidate_count"] == 16
    assert roster["common_items"] == 200
    assert roster["full_convergence_status"] == "converged"
    assert roster["reduced_convergence_status"] == "converged"
    assert roster["linking_converged"] is True
    assert roster["linking_termination_reason"] == "tolerance_met"
    assert roster["linked_common_score_rmse"] == pytest.approx(
        0.010865713831645366
    )
    assert roster["linked_common_score_correlation"] == pytest.approx(
        0.9999990868860807
    )
    assert roster["maximum_linked_common_score_shift"] == pytest.approx(
        0.016498037451536662
    )
    equating = report["score_equating_validation"]
    assert equating["method"] == "linear"
    assert equating["observations_per_form"] == 1_100
    assert equating["estimated_slope"] == pytest.approx(2.0)
    assert equating["estimated_intercept"] == pytest.approx(1.0)
    assert equating["unlinked_score_rmse"] == pytest.approx(6.782329983125268)
    assert equating["equated_score_rmse"] == 0.0
    assert equating["bootstrap_repetitions"] == heldout_benchmark.EQUATING_BOOTSTRAPS
    assert equating["bootstrap_seed"] == heldout_benchmark.EQUATING_SEED
    assert equating["interval_95_coverage"] == 1.0
    assert equating["maximum_standard_error"] == pytest.approx(0.351886177855059)
    functional_drift = report["functional_drift_validation"]
    assert functional_drift["method"] == "backward_tcc_area_elimination"
    assert functional_drift["expected_drift_items"] == [6]
    assert functional_drift["detected_drift_items"] == [6]
    assert functional_drift["area_trace"] == pytest.approx(
        [0.12335534738279283, 0.0]
    )
    assert functional_drift["iterations"] == 1
    assert functional_drift["termination_reason"] == "threshold_met"
    sequential_drift = report["sequential_drift_validation"]
    assert sequential_drift["method"] == "one_stream_bernoulli_cusum_screen"
    assert sequential_drift["seed"] == heldout_benchmark.SEQUENTIAL_DRIFT_SEED
    assert sequential_drift["holdout_seed"] == 270_917
    assert sequential_drift["replications"] == 500
    assert sequential_drift["change_after_observations"] == 100
    assert sequential_drift["baseline"]["false_alarm_rate"] == 0.178
    assert sequential_drift["baseline"]["detection_delay_p50_observations"] == 6
    assert sequential_drift["baseline"]["detection_delay_p95_observations"] == 15
    assert sequential_drift["threshold_search"]["candidates"] == 11
    assert sequential_drift["calibration_candidate"][
        "threshold_log_likelihood_ratio"
    ] == 6.6
    assert sequential_drift["calibration_candidate"]["false_alarm_rate"] == 0.026
    assert sequential_drift["candidate"]["threshold_log_likelihood_ratio"] == 6.6
    assert sequential_drift["candidate"]["false_alarm_rate"] == 0.024
    assert sequential_drift["candidate"]["false_alarm_rate_upper_95"] == pytest.approx(
        0.041477057463900756
    )
    assert sequential_drift["candidate"]["detection_delay_p50_observations"] == 10
    assert sequential_drift["candidate"]["detection_delay_p95_observations"] == 20
    assert sequential_drift["candidate_meets_synthetic_targets"] is True
    person_fit = report["response_pattern_fit_validation"]
    assert person_fit["method"] == "nonparametric_zu3_rank"
    assert person_fit["sample_size"] == heldout_benchmark.PERSON_FIT_SAMPLE_SIZE
    assert person_fit["seed"] == heldout_benchmark.PERSON_FIT_SEED
    assert person_fit["items"] == 10
    assert person_fit["finite_statistics"] == 976
    assert person_fit["injected_candidate_index"] == 999
    assert person_fit["highest_aberrance_candidate_index"] == 999
    assert person_fit["injected_zu3"] == pytest.approx(5.22635820493048)
    assert person_fit["next_highest_zu3"] == pytest.approx(3.4076390572266213)
    assert person_fit["zu3_rank_separation"] == pytest.approx(1.8187191477038587)
    dimensionality = report["construct_dimensionality_validation"]
    assert dimensionality["method"] == "horn_parallel_analysis_pearson_pca"
    assert (
        dimensionality["sample_size"]
        == heldout_benchmark.DIMENSIONALITY_SAMPLE_SIZE
    )
    assert dimensionality["seed"] == heldout_benchmark.DIMENSIONALITY_SEED
    assert (
        dimensionality["iterations"]
        == heldout_benchmark.DIMENSIONALITY_ITERATIONS
    )
    assert dimensionality["items"] == 12
    assert dimensionality["expected_dimensions"] == 2
    assert dimensionality["retained_dimensions"] == 2
    assert dimensionality["known_dimensions_recovered"] is True
    assert dimensionality["leading_eigenvalues"] == pytest.approx(
        [1.91125714, 1.80816602, 0.97219015]
    )
    assert dimensionality["leading_adjusted_eigenvalues"] == pytest.approx(
        [1.68362962, 1.64330776, 0.84748594]
    )
    model_fit = report["global_model_fit_validation"]
    assert model_fit["method"] == "limited_information_m2"
    assert (
        model_fit["sample_size_per_case"]
        == heldout_benchmark.MODEL_FIT_SAMPLE_SIZE
    )
    assert model_fit["seed"] == heldout_benchmark.MODEL_FIT_SEED
    assert model_fit["items"] == 10
    assert model_fit["known_misspecification_detected"] is True
    fitted_case = model_fit["fitted_one_factor"]
    misspecified_case = model_fit["misspecified_two_factor"]
    assert fitted_case["convergence_status"] == "converged"
    assert fitted_case["inference_valid"] is True
    assert fitted_case["m2"] == pytest.approx(45.74431659142287)
    assert fitted_case["p_value"] == pytest.approx(0.10561931269955144)
    assert fitted_case["rmsea"] == pytest.approx(0.01600095060876691)
    assert misspecified_case["convergence_status"] == "converged"
    assert misspecified_case["inference_valid"] is True
    assert misspecified_case["m2"] == pytest.approx(287.1636779430094)
    assert misspecified_case["p_value"] == pytest.approx(2.2660557889816854e-41)
    assert misspecified_case["rmsea"] == pytest.approx(0.07751712400695583)
    reliability = report["score_reliability_validation"]
    assert reliability["method"] == "posterior_variance_empirical_reliability"
    assert (
        reliability["sample_size_per_case"]
        == heldout_benchmark.RELIABILITY_SAMPLE_SIZE
    )
    assert reliability["seed"] == heldout_benchmark.RELIABILITY_SEED
    assert reliability["items"] == 12
    weak_information = reliability["weak_information"]
    strong_information = reliability["strong_information"]
    assert weak_information["convergence_status"] == "converged"
    assert strong_information["convergence_status"] == "converged"
    assert weak_information["empirical_reliability"] == pytest.approx(
        0.36643726355460837
    )
    assert strong_information["empirical_reliability"] == pytest.approx(
        0.8004364316297621
    )
    assert reliability["reliability_separation"] == pytest.approx(
        0.43399916807515376
    )
    generalizability = report["generalizability_design_validation"]
    assert generalizability["method"] == "two_facet_crossed_g_study_and_d_study"
    assert generalizability["seed"] == heldout_benchmark.GENERALIZABILITY_SEED
    assert generalizability["candidates"] == 80
    assert generalizability["items"] == 12
    assert generalizability["occasions"] == 4
    assert generalizability["variance_component_order"] == [
        "p", "i", "o", "pi", "po", "io", "pio"
    ]
    assert generalizability["variance_components_raw"] == pytest.approx(
        [
            0.8920854351890845,
            0.38675818561154557,
            0.33929872672516587,
            0.20329167309583476,
            0.06794210129890639,
            0.03957100513262765,
            0.2925758611991488,
        ]
    )
    assert generalizability["designs"] == pytest.approx(
        [
            {"items": 1, "occasions": 1, "generalizability": 0.6127401988587848, "dependability": 0.40156480032236525},
            {"items": 6, "occasions": 2, "generalizability": 0.9062963862712675, "dependability": 0.7301843004795637},
            {"items": 12, "occasions": 4, "generalizability": 0.9570630655050173, "dependability": 0.8496163507384494},
        ]
    )
    information = report["conditional_information_validation"]
    assert information["method"] == "fisher_test_information"
    assert information["items"] == 12
    assert information["trait_points"] == [-2.0, 0.0, 2.0]
    assert information["center_only_test_information"] == pytest.approx(
        [1.2599230248420783, 3.0, 1.2599230248420798]
    )
    assert information["range_matched_test_information"] == pytest.approx(
        [1.4588541892655895, 2.1945285666378105, 1.4588541892655889]
    )
    assert information["center_only_worst_sem"] == pytest.approx(
        0.8908971468449483
    )
    assert information["range_matched_worst_sem"] == pytest.approx(
        0.8279308976837576
    )
    assert information["worst_case_information_gain"] == pytest.approx(
        0.1578915220340864
    )
    classification = report["classification_decision_validation"]
    assert classification["method"] == "rudner_normal_approximation"
    assert classification["decision_cut"] == 0.0
    assert classification["measures"] == [-1.0, -0.5, 0.5, 1.0]
    assert classification["uncertain_scores"]["accuracy"] == pytest.approx(
        0.8141823561518077
    )
    assert classification["uncertain_scores"]["consistency"] == pytest.approx(
        0.7102748784842168
    )
    assert classification["precise_scores"]["accuracy"] == pytest.approx(
        0.9968950241871108
    )
    assert classification["precise_scores"]["consistency"] == pytest.approx(
        0.9938286083133958
    )
    assert classification["accuracy_gain"] == pytest.approx(0.18271266803530306)
    assert classification["consistency_gain"] == pytest.approx(0.283553729829179)
    utility = report["decision_utility_validation"]
    assert utility["method"] == "taylor_russell_and_brogden_cronbach_gleser"
    assert utility["baseline"]["selected_success_ratio"] == pytest.approx(
        0.5002733590986017
    )
    assert utility["baseline"]["net_utility_gain"] == pytest.approx(
        2042.2125814259748
    )
    assert utility["higher_validity"]["selected_success_ratio"] == pytest.approx(
        0.7235151064637407
    )
    assert utility["higher_validity"]["net_utility_gain"] == pytest.approx(
        5626.637744277923
    )
    assert utility["cost_exceeds_value"]["selected_success_ratio"] == pytest.approx(
        utility["higher_validity"]["selected_success_ratio"]
    )
    assert utility["cost_exceeds_value"]["net_utility_gain"] == pytest.approx(
        -2373.362255722077
    )
    predictive_fit = report["predictive_fit_validation"]
    assert predictive_fit["method"] == "cross_validated_prediction_tasks"
    assert predictive_fit["missing_items"] == {
        "status": "synthetic_executed",
        "candidates": "existing",
        "items": "held_out",
        "brier_score": report["brier_score"],
        "log_loss": report["log_loss"],
    }
    assert predictive_fit["missing_persons"]["status"] == "failed_no_prediction"
    assert predictive_fit["missing_persons"]["contexts"] == 24
    assert predictive_fit["missing_persons"]["prediction_coverage"] == 0.0
    assert "no psychometric estimate" in predictive_fit["missing_persons"]["known_limit"]
    adaptive = report["adaptive_candidate_calibration_validation"]
    assert predictive_fit["missing_persons"]["calibration_screen"] == adaptive
    assert adaptive["method"] == "maximum_fisher_information_eap_screen"
    assert adaptive["candidates"] == 400
    assert adaptive["item_bank_size"] == 31
    assert adaptive["maximum_queries"] == 12
    assert adaptive["target_standard_error"] == 0.5
    assert adaptive["adaptive"]["theta_rmse"] == pytest.approx(0.5759957156385006)
    assert adaptive["adaptive"]["mean_calibration_queries"] == 7.1775
    assert adaptive["adaptive"]["target_se_reached_rate"] == 1.0
    assert adaptive["random_baseline"]["theta_rmse"] == pytest.approx(
        0.6071517533210733
    )
    assert adaptive["random_baseline"]["mean_calibration_queries"] == 10.47
    assert adaptive["random_baseline"]["target_se_reached_rate"] == 0.87
    assert adaptive["mean_query_reduction"] == pytest.approx(3.2925)
    assert adaptive["theta_rmse_reduction"] == pytest.approx(0.0311560376825727)
    assert adaptive["unobserved_probability_mse_reduction"] == pytest.approx(
        0.007242434141391531
    )
    assert adaptive["paired_delta"]["calibration_queries"] == pytest.approx(-3.2925)
    assert adaptive["paired_delta_ci95"]["calibration_queries"] == pytest.approx(
        [-3.4125, -3.18]
    )
    assert adaptive["paired_delta"]["theta_squared_error"] == pytest.approx(
        -0.036862187126945056
    )
    assert adaptive["paired_delta_ci95"]["theta_squared_error"] == pytest.approx(
        [-0.0808741028637953, 0.006129009732609613]
    )
    assert adaptive["paired_delta_ci95"][
        "unobserved_probability_squared_error"
    ] == pytest.approx([-0.00880415088135534, -0.005715993179414072])
    assert adaptive["paired_delta_ci95"]["target_se_reached"] == pytest.approx(
        [0.1, 0.1625]
    )
    assert "not live decision latency" in adaptive["known_limit"]
    dif = report["candidate_group_dif_validation"]
    assert dif["method"] == "logistic_dif_purified"
    assert dif["expected_dif_items"] == [0]
    assert dif["flagged_items"] == [0]
    assert dif["known_dif_recall"] == 1.0
    assert dif["false_positive_count"] == 0
    assert dif["purification_converged"] is True
    assert dif["anchor_items"] == 7
    judge = report["judge_effects_validation"]
    assert judge["method"] == "many_facet_rasch"
    assert judge["connected"] is True
    assert judge["converged"] is True
    assert judge["severity_order_recovered"] is True
    assert judge["severity_rmse"] == pytest.approx(0.018292059677437307)
    covariate = report["item_language_domain_effect_validation"]
    assert covariate["method"] == "multigroup_item_covariate"
    assert covariate["sample_size"] == heldout_benchmark.ITEM_COVARIATE_SAMPLE_SIZE
    assert covariate["seed"] == heldout_benchmark.ITEM_COVARIATE_SEED
    assert covariate["true_delta"] == -0.8
    assert covariate["estimated_delta"] == pytest.approx(-0.7896498094289646)
    assert covariate["absolute_error"] == pytest.approx(0.010350190571035478)
    assert covariate["convergence_status"] == "converged"
    assert covariate["iterations"] == 941
    uncertainty = report["parameter_uncertainty_validation"]
    assert uncertainty["method"] == "oakes_information_wald_interval"
    assert uncertainty["sample_size"] == heldout_benchmark.UNCERTAINTY_SAMPLE_SIZE
    assert uncertainty["seed"] == heldout_benchmark.UNCERTAINTY_SEED
    assert uncertainty["convergence_status"] == "converged"
    assert uncertainty["iterations"] == 25
    assert uncertainty["intercept_rmse"] == pytest.approx(0.03915967506825319)
    assert uncertainty["interval_95_coverage_rate"] == 1.0
    assert uncertainty["mean_interval_95_width"] == pytest.approx(
        0.2959451647652092
    )


def test_fast_mlsirm_fit_uses_judge_acceptance_item_for_context_score(monkeypatch) -> None:
    """Criterion IRT rows inform one MLSRM fit; acceptance remains the route score."""
    import fast_mlsirm

    captured: dict[str, object] = {}

    class Result:
        convergence_status = "converged"
        params = object()
        model = "MLSRM"

    def fake_fit_experiment(fit_callable, responses, item_type, **kwargs):
        captured.update(item_type=item_type, responses=responses.copy(), config=kwargs["config"])
        return Result()

    def fake_predict(_params, factor_id, *, model):
        del model
        probabilities = np.full((5, len(factor_id)), 0.5)
        probabilities[:, 0] = [0.1, 0.9, 0.3, 0.4, 0.2]
        return probabilities

    monkeypatch.setattr(fast_mlsirm, "fit_irt_experiment", fake_fit_experiment)
    monkeypatch.setattr(fast_mlsirm, "predict_proba", fake_predict)
    evidence = PsychometricRoutingEvidence()
    contexts = ("system-a/user-a", "system-b/user-b")
    agents = [f"model_{index}" for index in range(5)]
    for context_index, context in enumerate(contexts):
        for agent_index, agent_id in enumerate(agents):
            accepted = (agent_index + context_index) % 2 == 0
            evidence.observe(
                context,
                agent_id,
                accepted,
                [float(context_index + 1), 1.0],
                irt_row=(int(accepted), int(not accepted)),
            )

    ranked = evidence.ranked_evidence(agents, contexts[0], [1.0, 1.0])

    assert captured["item_type"] == "dichotomous"
    assert captured["config"].model == "MLSRM"  # type: ignore[union-attr]
    assert np.asarray(captured["responses"]).shape == (5, 6)
    assert ranked[0][0] == "model_1"


def test_contextual_fast_mlsirm_evidence_precedes_static_coldstart_order(monkeypatch) -> None:
    """Initial selection uses contextual ability before operator/static fallback."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("static_first", "model-a", priority=100),
            ModelAgent("quality_first", "model-b", priority=1),
            ModelAgent("unmeasured_agent", "model-c", priority=50),
        ]
    )
    monkeypatch.setattr(
        orchestrator._psychometric_router,
        "ranked_evidence",
        lambda agent_ids, prompt, vector: [
            (next(agent_id for agent_id in agent_ids if agent_id.startswith("quality_first:")), 0.91)
        ],
    )
    monkeypatch.setattr(orchestrator._psychometric_router, "has_observations", lambda: True)

    ranked = orchestrator._ranked_agents(
        "user request", "worker", prompt_context='[{"role":"system","content":"policy"}]'
    )

    assert [agent.id for agent in ranked] == [
        "quality_first",
        "static_first",
        "unmeasured_agent",
    ]


def test_contextual_evidence_never_promotes_a_role_excluded_agent(monkeypatch) -> None:
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("eligible_agent", "model-a", priority=1),
            ModelAgent(
                "excluded_agent",
                "model-b",
                priority=100,
                provider_exclusions=("worker",),
            ),
        ]
    )
    monkeypatch.setattr(
        orchestrator._psychometric_router, "has_observations", lambda: True
    )
    monkeypatch.setattr(
        orchestrator._psychometric_router,
        "ranked_evidence",
        lambda agent_ids, prompt, vector: [(agent_ids[-1], 0.99)],
    )

    ranked = orchestrator._ranked_agents(
        "request", "worker", prompt_context="system/user"
    )

    assert [agent.id for agent in ranked] == ["eligible_agent", "excluded_agent"]


def test_contextual_fast_mlsirm_evidence_orders_every_post_413_candidate(monkeypatch) -> None:
    """After the rejected primary, evidenced candidates lead unmeasured fallbacks."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("primary_agent", "model-a", priority=100),
            ModelAgent("static_backup", "model-b", priority=90),
            ModelAgent("quality_backup", "model-c", priority=1),
        ]
    )
    monkeypatch.setattr(
        orchestrator._psychometric_router,
        "ranked_evidence",
        lambda agent_ids, prompt, vector: [
            (next(agent_id for agent_id in agent_ids if agent_id.startswith("quality_backup:")), 0.88)
        ],
    )
    monkeypatch.setattr(orchestrator._psychometric_router, "has_observations", lambda: True)

    ranked = orchestrator._failover_candidates(
        orchestrator._agent("primary_agent"),
        "user request",
        "worker",
        allowed_agent_ids={"primary_agent", "static_backup", "quality_backup"},
        prompt_context="system/user interaction",
    )

    assert [agent.id for agent in ranked] == [
        "primary_agent",
        "quality_backup",
        "static_backup",
    ]


def test_contextual_judge_observation_survives_restart_without_raw_prompt(
    tmp_path: Path,
) -> None:
    state_db = str(tmp_path / "state.sqlite3")
    agents = [ModelAgent("model_a", "model-a")]
    first = TaskOrchestrator(agents, state_db=state_db)
    first._observe_contextual_quality(
        "system secret/user request",
        "model_a",
        accepted=True,
        latency_seconds=0.1,
        output_tokens=10,
        irt_row=(1, 0),
    )
    first.close()

    second = TaskOrchestrator(agents, state_db=state_db)
    records = second._psychometric_router.records()
    second.close()

    candidate_id = second._psychometric_candidate_id(agents[0])
    assert records == [
        {
            "context_id": PsychometricRoutingEvidence.context_id(
                "system secret/user request"
            ),
            "agent_id": candidate_id,
            "accepted": True,
            "irt_row": [1, 0],
            "vector": None,
        }
    ]
    assert "system secret" not in Path(state_db).read_bytes().decode(
        "utf-8", errors="ignore"
    )


def test_contextual_judge_observation_does_not_survive_deployment_change(
    tmp_path: Path,
) -> None:
    state_db = str(tmp_path / "state.sqlite3")
    first = TaskOrchestrator([ModelAgent("model_a", "model-a")], state_db=state_db)
    first._observe_contextual_quality(
        "system/user", "model_a", accepted=True, latency_seconds=0.1, output_tokens=10
    )
    first.close()

    second = TaskOrchestrator(
        [ModelAgent("model_a", "model-b")], state_db=state_db
    )
    records = second._psychometric_router.records()
    second.close()

    assert records == []

    reverted = TaskOrchestrator(
        [ModelAgent("model_a", "model-a")], state_db=state_db
    )
    reverted_records = reverted._psychometric_router.records()
    reverted.close()

    assert reverted_records == []


def test_contextual_judge_observation_does_not_survive_decode_policy_change(
    tmp_path: Path,
) -> None:
    state_db = str(tmp_path / "state.sqlite3")
    agents = [ModelAgent("model_a", "model-a")]
    original = default_role_effort_catalog()
    changed = dict(original)
    changed["worker"] = replace(original["worker"], temperature=0.8)
    first = TaskOrchestrator(
        agents, state_db=state_db, role_effort_catalog=original
    )
    first._observe_contextual_quality(
        "system/user", "model_a", accepted=True, latency_seconds=0.1, output_tokens=10
    )
    first.close()

    second = TaskOrchestrator(
        agents, state_db=state_db, role_effort_catalog=changed
    )
    records = second._psychometric_router.records()
    second.close()

    assert records == []


def test_runtime_deployment_change_discards_contextual_judge_observation() -> None:
    orchestrator = TaskOrchestrator([ModelAgent("model_a", "model-a")])
    orchestrator._observe_contextual_quality(
        "system/user", "model_a", accepted=True, latency_seconds=0.1, output_tokens=10
    )

    orchestrator.patch_agent("default", "model_a", {"priority": 2})

    assert orchestrator._psychometric_router.records() == []
    orchestrator.close()


def test_runtime_change_cannot_race_a_persisted_psychometric_observation(
    tmp_path: Path, monkeypatch
) -> None:
    state_db = str(tmp_path / "state.sqlite3")
    orchestrator = TaskOrchestrator(
        [ModelAgent("model_a", "model-a")], state_db=state_db
    )
    saved = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []
    original_save = orchestrator._store.save

    def blocking_save(kind, key, value, **kwargs):
        if kind == "psychometric_observation":
            saved.set()
            assert release.wait(timeout=2)
        original_save(kind, key, value, **kwargs)

    monkeypatch.setattr(orchestrator._store, "save", blocking_save)

    def run(callable_):
        try:
            callable_()
        except BaseException as error:  # pragma: no cover - surfaced below
            errors.append(error)

    observe = threading.Thread(
        target=run,
        args=(
            lambda: orchestrator._observe_contextual_quality(
                "system/user",
                "model_a",
                accepted=True,
                latency_seconds=0.1,
                output_tokens=10,
            ),
        ),
    )
    observe.start()
    assert saved.wait(timeout=2)
    patch = threading.Thread(
        target=run,
        args=(lambda: orchestrator.patch_agent("default", "model_a", {"priority": 2}),),
    )
    patch.start()
    release.set()
    observe.join(timeout=2)
    patch.join(timeout=2)

    assert not observe.is_alive()
    assert not patch.is_alive()
    assert errors == []
    assert orchestrator._psychometric_router.records() == []
    orchestrator.close()

    restarted = TaskOrchestrator(
        [ModelAgent("model_a", "model-a", priority=2)], state_db=state_db
    )
    assert restarted._psychometric_router.records() == []
    restarted.close()


def test_replacing_judge_row_removes_stale_trailing_items() -> None:
    evidence = PsychometricRoutingEvidence()
    evidence.observe("prompt", "model", True, None, (1, 0, 1))
    evidence.observe("prompt", "model", False, None, (0,))

    assert evidence.records()[0]["irt_row"] == [0]


def test_semantic_warm_start_interpolates_two_nearest_contexts() -> None:
    evidence = PsychometricRoutingEvidence(semantic_warm_start_enabled=True)
    evidence.observe("left", "model_a", True, [1.0, 0.0])
    evidence.observe("right", "model_a", True, [0.0, 1.0])
    evidence._scores = {
        evidence.context_id("left"): {
            "model_a": 0.9,
            "model_b": 0.1,
            "model_c": 0.8,
        },
        evidence.context_id("right"): {
            "model_a": 0.3,
            "model_b": 0.7,
            "model_d": 0.2,
        },
    }
    evidence._fit_revision = evidence._revision

    ranked = evidence.ranked_evidence(
        iter(("model_a", "model_b", "model_c", "model_d")),
        "held-out",
        [1.0, 1.0],
    )

    assert [(agent_id, round(score, 6)) for agent_id, score in ranked] == [
        ("model_c", 0.8),
        ("model_a", 0.6),
        ("model_b", 0.4),
        ("model_d", 0.2),
    ]


def test_semantic_warm_start_reuses_observed_unit_vectors(monkeypatch) -> None:
    evidence = PsychometricRoutingEvidence(semantic_warm_start_enabled=True)
    evidence.observe("left", "model_a", True, [1.0, 0.0])
    evidence.observe("right", "model_a", True, [0.0, 1.0])
    evidence._scores = {
        evidence.context_id("left"): {"model_a": 0.9},
        evidence.context_id("right"): {"model_a": 0.3},
    }
    evidence._fit_revision = evidence._revision
    original = evidence._finite_norm
    calls = 0

    def counted(vector):
        nonlocal calls
        calls += 1
        return original(vector)

    monkeypatch.setattr(
        PsychometricRoutingEvidence, "_finite_norm", staticmethod(counted)
    )

    assert evidence.ranked_evidence(("model_a",), "held-out", [1.0, 1.0])
    assert calls == 1


def test_semantic_warm_start_defaults_to_validated_single_neighbor() -> None:
    evidence = PsychometricRoutingEvidence()
    evidence.observe("left", "model_a", True, [1.0, 0.0])
    evidence.observe("right", "model_a", True, [0.0, 1.0])
    evidence._scores = {
        evidence.context_id("left"): {"model_a": 0.9, "model_b": 0.1},
        evidence.context_id("right"): {"model_a": 0.3, "model_b": 0.7},
    }
    evidence._fit_revision = evidence._revision

    ranked = evidence.ranked_evidence(
        ("model_a", "model_b"), "held-out", [0.9, 0.8]
    )

    assert ranked == [("model_a", 0.9), ("model_b", 0.1)]


def test_semantic_warm_start_rejects_non_positive_neighbors() -> None:
    evidence = PsychometricRoutingEvidence(semantic_warm_start_enabled=True)
    evidence.observe("opposite", "model_a", True, [-1.0, 0.0])
    evidence._scores = {
        evidence.context_id("opposite"): {"model_a": 0.9, "model_b": 0.1}
    }
    evidence._fit_revision = evidence._revision

    assert evidence.ranked_evidence(
        ("model_a", "model_b"), "held-out", [1.0, 0.0]
    ) == []


def test_default_single_neighbor_preserves_non_positive_fallback() -> None:
    evidence = PsychometricRoutingEvidence()
    evidence.observe("opposite", "model_a", True, [-1.0, 0.0])
    evidence._scores = {
        evidence.context_id("opposite"): {"model_a": 0.9, "model_b": 0.1}
    }
    evidence._fit_revision = evidence._revision

    assert evidence.ranked_evidence(
        ("model_a", "model_b"), "held-out", [1.0, 0.0]
    ) == [("model_a", 0.9), ("model_b", 0.1)]


def test_semantic_warm_start_rejects_non_finite_embeddings() -> None:
    evidence = PsychometricRoutingEvidence()
    evidence.observe("invalid", "model_a", True, [float("nan"), 1.0])
    evidence._scores = {
        evidence.context_id("invalid"): {"model_a": 0.9, "model_b": 0.1}
    }
    evidence._fit_revision = evidence._revision

    assert evidence.ranked_evidence(
        ("model_a", "model_b"), "held-out", [1.0, 0.0]
    ) == []


def test_cosine_is_finite_for_large_finite_embeddings() -> None:
    similarity = PsychometricRoutingEvidence._cosine(
        [1e308, 1e308], [1e308, 1e308]
    )

    assert similarity is not None
    assert math.isfinite(similarity)
    assert similarity == pytest.approx(1.0)


def test_deployment_configuration_changes_psychometric_identity() -> None:
    before = ModelAgent("model_a", "model-a", base_url="https://one.example/v1")
    after = ModelAgent("model_a", "model-b", base_url="https://two.example/v1")
    orchestrator = TaskOrchestrator([before])

    assert orchestrator._psychometric_candidate_id(
        before
    ) != orchestrator._psychometric_candidate_id(after)
    orchestrator.close()


def test_decode_policy_changes_psychometric_identity() -> None:
    agent = ModelAgent("model_a", "model-a")
    original = default_role_effort_catalog()
    changed = dict(original)
    changed["worker"] = replace(original["worker"], reasoning_effort="high")
    before = TaskOrchestrator([agent], role_effort_catalog=original)
    after = TaskOrchestrator([agent], role_effort_catalog=changed)

    assert before._psychometric_candidate_id(agent) != after._psychometric_candidate_id(agent)
    before.close()
    after.close()


def test_changed_deployment_cannot_inherit_exact_context_score() -> None:
    old_agent = ModelAgent("reused_agent", "model-old", base_url="https://old.example/v1")
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("static_first", "model-static", priority=100),
            ModelAgent(
                "reused_agent",
                "model-new",
                base_url="https://new.example/v1",
                priority=1,
            ),
        ]
    )
    old_candidate_id = orchestrator._psychometric_candidate_id(old_agent)
    context = "versioned system/user interaction"
    orchestrator._psychometric_router.observe(
        context, old_candidate_id, True, None
    )
    orchestrator._psychometric_router._scores = {
        PsychometricRoutingEvidence.context_id(context): {old_candidate_id: 1.0}
    }
    orchestrator._psychometric_router._fit_revision = (
        orchestrator._psychometric_router._revision
    )

    ranked = orchestrator._ranked_agents(
        "request", "worker", prompt_context=context
    )

    assert [agent.id for agent in ranked] == ["static_first", "reused_agent"]
