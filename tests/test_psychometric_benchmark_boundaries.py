"""Diagnostic harness denominators and startup guards, not estimator validation."""

import builtins
import json
from pathlib import Path
import runpy
import sys

import pytest

from scripts import benchmark_psychometric_heldout as heldout
from scripts import benchmark_psychometric_routing as routing


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
