"""Diagnostic harness denominators and startup guards, not estimator validation."""

import builtins
import inspect
import json
import runpy
import sys
from pathlib import Path

import pytest

from scripts import benchmark_psychometric_heldout as heldout
from scripts import benchmark_psychometric_routing as routing

SMALL_HELDOUT_BOOTSTRAP = {
    "resample_count": 20,
    "confidence_level": 0.95,
    "seed": 568,
}


@pytest.mark.parametrize(
    "candidate_count, unresolved_scope",
    [
        (9, None),
        (401, None),
        (403, None),
        (3, "empty_stratum"),
        (9, "selective_all"),
        (9, "selective_negative"),
    ],
)
def test_selective_coverage_uses_actual_odd_sized_strata(
    monkeypatch, candidate_count, unresolved_scope
):
    """An oracle resolving every row must cover each unequal stratum exactly once."""
    monkeypatch.setattr(heldout, "ADAPTIVE_CALIBRATION_CANDIDATES", candidate_count)
    monkeypatch.setattr(heldout, "SELECTIVE_CLASSIFICATION_REPLICATIONS", 2)
    monkeypatch.setattr(heldout, "SELECTIVE_CLASSIFICATION_MAX_ERROR_UPPER", 1.0)
    candidate_index = -1

    def oracle(_bundle, responses, **_kwargs):
        """Return the known trait sign, with selected strata deliberately unresolved."""
        nonlocal candidate_index
        if not responses:
            candidate_index += 1
        theta = -2.0 + 4.0 * (candidate_index % candidate_count + 0.5) / candidate_count
        unresolved = candidate_index >= 3 * candidate_count and (
            unresolved_scope == "selective_all"
            or (unresolved_scope == "selective_negative" and theta < 0.0)
        )
        return {
            "ranked_items": [len(responses)],
            "theta_eap": [1.0 if theta >= 0.0 else -1.0],
            "theta_sd": [100.0 if unresolved else 0.0],
        }

    monkeypatch.setattr(heldout.fast_mlsirm, "cat_next_item", oracle)
    if unresolved_scope:
        with pytest.raises(ValueError, match="no confidence-resolved candidates"):
            heldout._validate_adaptive_candidate_calibration(**SMALL_HELDOUT_BOOTSTRAP)
        return
    report = heldout._validate_adaptive_candidate_calibration(**SMALL_HELDOUT_BOOTSTRAP)
    screen = report["classification_stopping"]["risk_coverage_screen"]
    for point in (screen["heldout"], screen["heldout_baseline"]):
        for metric in (
            "coverage",
            "near_cut_coverage",
            "negative_coverage",
            "positive_coverage",
        ):
            assert point[metric] == 1.0
        assert point["absolute_directional_coverage_gap"] == 0.0


@pytest.mark.parametrize("candidate_count", [-1, 0, 1, 2])
def test_calibration_rejects_empty_generated_strata(monkeypatch, candidate_count):
    """A missing denominator fails explicitly before the native calibration call."""
    monkeypatch.setattr(heldout, "ADAPTIVE_CALIBRATION_CANDIDATES", candidate_count)
    with pytest.raises(ValueError, match="non-empty near-cut and directional strata"):
        heldout._validate_adaptive_candidate_calibration(**SMALL_HELDOUT_BOOTSTRAP)


def test_calibration_rejects_undefined_resolution_summary(monkeypatch):
    """No resolved decisions cannot be reported as zero error or divide by zero."""
    monkeypatch.setattr(heldout, "ADAPTIVE_CALIBRATION_CANDIDATES", 9)
    monkeypatch.setattr(
        heldout.fast_mlsirm,
        "cat_next_item",
        lambda _bundle, responses, **_kwargs: {
            "ranked_items": [len(responses)],
            "theta_eap": [0.0],
            "theta_sd": [1.0],
        },
    )
    with pytest.raises(ValueError, match="no confidence-resolved candidates"):
        heldout._validate_adaptive_candidate_calibration(**SMALL_HELDOUT_BOOTSTRAP)


def test_adaptive_calibration_report_uses_coverage_neutral_interval_keys(
    monkeypatch,
) -> None:
    """Paired intervals must not bake 95 into the JSON field name."""
    monkeypatch.setattr(heldout, "ADAPTIVE_CALIBRATION_CANDIDATES", 9)
    monkeypatch.setattr(heldout, "SELECTIVE_CLASSIFICATION_REPLICATIONS", 2)
    monkeypatch.setattr(heldout, "SELECTIVE_CLASSIFICATION_MAX_ERROR_UPPER", 1.0)
    candidate_index = -1

    def oracle(_bundle, responses, **_kwargs):
        """Return the known trait sign for every generated candidate."""
        nonlocal candidate_index
        if not responses:
            candidate_index += 1
        theta = -2.0 + 4.0 * (candidate_index % 9 + 0.5) / 9
        return {
            "ranked_items": [len(responses)],
            "theta_eap": [1.0 if theta >= 0.0 else -1.0],
            "theta_sd": [0.0],
        }

    monkeypatch.setattr(heldout.fast_mlsirm, "cat_next_item", oracle)
    report = heldout._validate_adaptive_candidate_calibration(**SMALL_HELDOUT_BOOTSTRAP)
    assert "paired_delta_interval" in report
    assert "paired_delta_ci95" not in report
    stopping = report["classification_stopping"]
    assert "query_delta_interval" in stopping
    assert "accuracy_delta_interval" in stopping
    assert "query_delta_ci95" not in stopping
    screen = stopping["risk_coverage_screen"]
    assert "heldout_paired_delta_interval" in screen
    assert "heldout_paired_delta_ci95" not in screen


@pytest.mark.parametrize("sample_count", [1, 21, 101])
def test_observation_p95_tracks_actual_sample_count(monkeypatch, capsys, sample_count):
    """Keep nearest-rank p95 semantics when diagnostic repetition counts change."""
    monkeypatch.setattr(routing, "CONTEXT_COUNT", 3)
    monkeypatch.setattr(routing, "OBSERVATION_REPETITIONS", sample_count, raising=False)
    elapsed_ns = [1_000_000] * 9 + [
        index * 1_000_000 for index in range(1, sample_count + 1)
    ]
    ticks = iter(value for elapsed in elapsed_ns for value in (0, elapsed))
    monkeypatch.setattr(routing.time, "perf_counter_ns", lambda: next(ticks))
    routing.main()
    report = json.loads(capsys.readouterr().out)
    assert report["p95_observe_ms"] == (95 * sample_count + 99) // 100


def test_paired_latency_requires_declared_repetitions() -> None:
    """Decision-latency KPIs cannot invent a 200-repetition default."""
    parameters = inspect.signature(heldout._measure_paired_latency).parameters
    assert parameters["repetitions_per_context"].default is None
    assert parameters["context_count"].default is None
    evidence = heldout.PsychometricRoutingEvidence()
    with pytest.raises(ValueError, match="repetitions_per_context"):
        heldout._measure_paired_latency(evidence, evidence, context_count=2)
    with pytest.raises(ValueError, match="repetitions_per_context"):
        heldout._measure_paired_latency(
            evidence, evidence, context_count=2, repetitions_per_context=True
        )
    with pytest.raises(ValueError, match="context_count"):
        heldout._measure_paired_latency(
            evidence, evidence, repetitions_per_context=3
        )


def test_paired_latency_uses_declared_repetition_count(monkeypatch) -> None:
    """The declared repetition count is the actual per-context timing loop."""
    calls = {"count": 0}
    evidence = heldout.PsychometricRoutingEvidence()

    def ranked(*_args, **_kwargs):
        """Count ranking calls without exercising live routing work."""
        calls["count"] += 1
        return [("model_0", 1.0)]

    monkeypatch.setattr(evidence, "ranked_evidence", ranked)
    heldout._measure_paired_latency(
        evidence, evidence, context_count=2, repetitions_per_context=3
    )
    assert calls["count"] == 12


def test_heldout_quality_requires_declared_context_count() -> None:
    """Accuracy KPIs cannot invent a 24-context held-out population."""
    parameters = inspect.signature(heldout._evaluate_quality).parameters
    assert parameters["context_count"].default is None
    assert inspect.signature(heldout._build_evidence).parameters[
        "context_count"
    ].default is None
    evidence = heldout.PsychometricRoutingEvidence()
    with pytest.raises(ValueError, match="context_count"):
        heldout._evaluate_quality(evidence)
    with pytest.raises(ValueError, match="context_count"):
        heldout._build_evidence(two_neighbor=False)


def test_heldout_quality_uses_declared_context_count(monkeypatch) -> None:
    """The declared context count is the actual held-out quality loop."""
    calls = {"count": 0}
    evidence = heldout.PsychometricRoutingEvidence()

    def ranked(*_args, **_kwargs):
        """Count ranking calls without exercising live routing work."""
        calls["count"] += 1
        return [("model_0", 0.5), ("model_1", 0.4), ("model_2", 0.3), ("model_3", 0.2)]

    monkeypatch.setattr(evidence, "ranked_evidence", ranked)
    heldout._evaluate_quality(evidence, context_count=3)
    assert calls["count"] == 3


def test_assignment_design_requires_declared_trial_count() -> None:
    """Assignment-design KPIs cannot invent a 24,000-trial default."""
    parameters = inspect.signature(heldout._validate_assignment_design).parameters
    assert parameters["trial_count"].default is None
    evidence = heldout.PsychometricRoutingEvidence()
    with pytest.raises(ValueError, match="trial_count"):
        heldout._validate_assignment_design(evidence)
    with pytest.raises(ValueError, match="trial_count"):
        heldout._validate_assignment_design(evidence, trial_count=True)


def test_assignment_design_uses_declared_trial_count(monkeypatch) -> None:
    """The declared trial count is the actual logging-design loop."""
    calls = {"count": 0}
    evidence = heldout.PsychometricRoutingEvidence()
    model_ids = list(heldout.MODEL_IDS)

    def ranked(*_args, **_kwargs):
        """Rotate the top-ranked model so every candidate is observed."""
        calls["count"] += 1
        start = (calls["count"] - 1) % len(model_ids)
        ordered = model_ids[start:] + model_ids[:start]
        return [(model_id, 0.5) for model_id in ordered]

    monkeypatch.setattr(evidence, "ranked_evidence", ranked)
    report = heldout._validate_assignment_design(evidence, trial_count=40)
    assert calls["count"] == 40
    assert report["trials"] == 40


def test_candidate_group_dif_requires_declared_sample_size() -> None:
    """DIF evidence cannot invent a 4,000-row default."""
    parameters = inspect.signature(heldout._validate_candidate_group_dif).parameters
    assert parameters["sample_size"].default is None
    with pytest.raises(ValueError, match="sample_size"):
        heldout._validate_candidate_group_dif()
    with pytest.raises(ValueError, match="sample_size"):
        heldout._validate_candidate_group_dif(sample_size=True)
    with pytest.raises(ValueError, match="even"):
        heldout._validate_candidate_group_dif(sample_size=3)


def test_candidate_group_dif_uses_declared_sample_size() -> None:
    """The declared sample size is the actual two-group DIF population."""
    report = heldout._validate_candidate_group_dif(sample_size=40)
    assert report["sample_size"] == 40
    assert len(report["expected_dif_items"]) == 1


def test_score_reliability_requires_declared_sample_size() -> None:
    """Reliability evidence cannot invent a 1,200-row default."""
    parameters = inspect.signature(heldout._validate_score_reliability).parameters
    assert parameters["sample_size"].default is None
    with pytest.raises(ValueError, match="sample_size"):
        heldout._validate_score_reliability()
    with pytest.raises(ValueError, match="sample_size"):
        heldout._validate_score_reliability(sample_size=True)


def test_score_reliability_uses_declared_sample_size() -> None:
    """The declared sample size is the actual reliability population per case."""
    report = heldout._validate_score_reliability(sample_size=40)
    assert report["sample_size_per_case"] == 40
    assert report["items"] == 12


def test_sequential_drift_requires_declared_horizon_and_coverage() -> None:
    """CUSUM delay KPIs cannot invent 500/250/100 or a 95% Wilson default."""
    parameters = inspect.signature(heldout._validate_sequential_drift).parameters
    assert parameters["replications"].default is None
    assert parameters["horizon_observations"].default is None
    assert parameters["change_after_observations"].default is None
    assert parameters["confidence_level"].default is None
    with pytest.raises(ValueError, match="replications"):
        heldout._validate_sequential_drift()
    with pytest.raises(ValueError, match="horizon_observations"):
        heldout._validate_sequential_drift(
            replications=8, change_after_observations=4, confidence_level=0.95
        )
    with pytest.raises(ValueError, match="change_after_observations"):
        heldout._validate_sequential_drift(
            replications=8,
            horizon_observations=20,
            change_after_observations=20,
            confidence_level=0.95,
        )
    with pytest.raises(ValueError, match="confidence_level"):
        heldout._validate_sequential_drift(
            replications=8,
            horizon_observations=20,
            change_after_observations=4,
        )


def test_sequential_drift_records_horizon_censored_non_detections() -> None:
    """A threshold that never fires is missed-detection evidence, not an abort."""
    report = heldout._evaluate_sequential_drift_threshold(
        seed=1,
        threshold=1_000.0,
        replications=8,
        horizon_observations=20,
        change_after_observations=10,
        confidence_level=0.95,
    )
    assert report["censored_replications"] == 8
    assert report["false_alarm_rate"] == 0.0
    assert report["post_change_detection_rate_among_no_false_alarm"] == 0.0
    assert report["detection_delay_p50_observations"] is None
    assert report["detection_delay_p95_observations"] is None
    assert report["delay_summary_population"] == "post_change_detections_only"
    assert "false_alarm_rate_upper_95" not in report
    assert report["false_alarm_rate_upper_bound"] == pytest.approx(
        0.3244075648838801
    )


@pytest.mark.parametrize("draw_value", [0.0, 1.0])
def test_sequential_drift_preserves_empty_detection_population(monkeypatch, draw_value):
    """All censored or premature alarms retain evidence without selecting a policy."""
    from types import SimpleNamespace

    monkeypatch.setattr(
        heldout.random, "Random",
        lambda _seed: SimpleNamespace(random=lambda: draw_value),
    )
    report = heldout._validate_sequential_drift(
        replications=8, horizon_observations=20,
        change_after_observations=10, confidence_level=0.95,
    )
    baseline = report["baseline"]
    assert baseline["censored_replications"] == (8 if draw_value == 0.0 else 0)
    assert baseline["false_alarm_count"] == (0 if draw_value == 0.0 else 8)
    assert baseline["post_change_detection_count"] == 0
    assert baseline["detection_delay_p95_observations"] is None
    assert baseline["post_change_detection_rate_among_no_false_alarm"] == (
        0.0 if draw_value == 0.0 else None
    )
    assert report["candidate"] is None
    assert report["candidate_meets_synthetic_targets"] is False
    assert len(report["threshold_search"]["calibration_results"]) == 11


def test_heldout_runtime_guard_precedes_optional_dependency_imports(monkeypatch):
    """Unsupported Python must receive the runnable command before loading ML libraries."""
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        """Fail if an optional ML import precedes the supported-runtime check."""
        if name in {"fast_mlsirm", "numpy"}:
            raise AssertionError("optional dependency imported before runtime guard")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(sys, "version_info", (3, 11))
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    with pytest.raises(
        SystemExit,
        match="uv run --python 3.12 python scripts/benchmark_psychometric_heldout.py",
    ):
        runpy.run_path(str(Path(heldout.__file__)), run_name="__main__")
