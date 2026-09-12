"""Diagnostic harness denominators and startup guards, not estimator validation."""

import builtins
import json
from pathlib import Path
import runpy
import sys

import pytest

from scripts import benchmark_psychometric_heldout as heldout
from scripts import benchmark_psychometric_routing as routing


def test_sequential_drift_seeded_reference_is_unchanged():
    """Default complete detections preserve the established threshold and delays."""
    report = heldout._validate_sequential_drift()
    assert report["candidate"]["threshold_log_likelihood_ratio"] == 6.6
    assert report["candidate"]["false_alarm_rate"] == 0.024
    assert report["candidate"]["detection_delay_p95_observations"] == 20
    assert report["candidate"]["non_detection_count"] == 0
    assert report["candidate_meets_synthetic_targets"] is True


def test_sequential_drift_mixed_non_detections_remain_in_denominator(monkeypatch):
    """Conditional delay summaries must not hide half the unalarmed replications."""
    from types import SimpleNamespace

    def fixed_stream(seed_value):
        observation_count = 0

        def next_draw():
            nonlocal observation_count
            observation_count += 1
            return 1.0 if seed_value % 2 and observation_count > 100 else 0.0

        return SimpleNamespace(random=next_draw)

    monkeypatch.setattr(heldout, "SEQUENTIAL_DRIFT_REPLICATIONS", 10)
    monkeypatch.setattr(heldout.random, "Random", fixed_stream)
    baseline = heldout._validate_sequential_drift()["baseline"]
    assert baseline["false_alarm_count"] == 0
    assert baseline["non_detection_count"] == 5
    assert baseline["post_change_detection_count"] == 5
    assert baseline["post_change_detection_rate_among_no_false_alarm"] == 0.5
    assert baseline["delay_summary_population"] == "post_change_detections_only"
    assert baseline["detection_delay_p95_observations"] > 0


@pytest.mark.parametrize("draw_value", [0.0, 1.0])
def test_sequential_drift_retains_no_detection_outcomes(monkeypatch, draw_value):
    """No alarms and only premature alarms both preserve the full denominator."""
    from types import SimpleNamespace

    monkeypatch.setattr(heldout, "SEQUENTIAL_DRIFT_REPLICATIONS", 10)
    monkeypatch.setattr(heldout.random, "Random", lambda _seed: SimpleNamespace(random=lambda: draw_value))
    report = heldout._validate_sequential_drift()
    baseline = report["baseline"]
    assert baseline["non_detection_count"] == (10 if draw_value == 0.0 else 0)
    assert baseline["false_alarm_count"] == (0 if draw_value == 0.0 else 10)
    assert baseline["post_change_detection_count"] == 0
    assert baseline["post_change_detection_rate_among_no_false_alarm"] == (0.0 if draw_value == 0.0 else None)
    assert baseline["detection_delay_p50_observations"] is None
    assert baseline["detection_delay_p95_observations"] is None
    assert report["candidate"] is None
    assert report["candidate_meets_synthetic_targets"] is False
    assert len(report["threshold_search"]["calibration_results"]) == 11


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
    monkeypatch.setattr(heldout, "BOOTSTRAP_SAMPLES", 20)
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
            heldout._validate_adaptive_candidate_calibration()
        return
    report = heldout._validate_adaptive_candidate_calibration()
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
        heldout._validate_adaptive_candidate_calibration()


def test_calibration_rejects_undefined_resolution_summary(monkeypatch):
    """No resolved decisions cannot be reported as zero error or divide by zero."""
    monkeypatch.setattr(heldout, "ADAPTIVE_CALIBRATION_CANDIDATES", 9)
    monkeypatch.setattr(heldout, "BOOTSTRAP_SAMPLES", 20)
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
        heldout._validate_adaptive_candidate_calibration()


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
        match=r"uv run --python 3\.12 python scripts/benchmark_psychometric_heldout\.py",
    ):
        runpy.run_path(str(Path(heldout.__file__)), run_name="__main__")
