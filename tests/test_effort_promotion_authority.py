"""Caller-controlled diagnostics cannot authorize a learned-policy deployment."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

SOURCE_PATH = Path(__file__).resolve().parents[1] / "contextual_orchestrator/reasoning_effort_profile.py"


@pytest.fixture
def profile_module():
    """Load the exact leaf without bootstrapping provider credentials or clients."""
    module_spec = importlib.util.spec_from_file_location("effort_promotion_under_test", SOURCE_PATH)
    assert module_spec is not None and module_spec.loader is not None
    loaded_module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = loaded_module
    module_spec.loader.exec_module(loaded_module)
    return loaded_module


@pytest.mark.parametrize("measurement_status", [None, "", "unknown", "measured", "reported", "estimated"])
def test_diagnostic_labels_are_not_promotion_authority(profile_module, measurement_status):
    """A fabricated improvement and label are not an authenticated evaluation."""
    supplied_report = {
        "single_model_baseline": {"rmse": 1.0},
        "role_differentiated": {"rmse": 0.1},
        "robustness_passed": True,
    }
    if measurement_status is not None:
        supplied_report["measurement_status"] = measurement_status
    assert profile_module.production_default_change_allowed(supplied_report) is False


@pytest.mark.parametrize("candidate_rmse", [-1.0, False, "0.001", 0.0])
def test_numeric_coercion_cannot_create_release_permission(profile_module, candidate_rmse):
    """Validation of a report alone cannot establish its provenance or scope."""
    supplied_report = {
        "single_model_baseline": {"rmse": 1.0},
        "role_differentiated": {"rmse": candidate_rmse},
        "robustness_passed": True,
        "measurement_status": "measured",
    }
    assert profile_module.production_default_change_allowed(supplied_report) is False


def test_relabelled_synthetic_ablation_cannot_unlock_defaults(profile_module):
    """The previous synthetic report crossed the gate after two label edits."""
    supplied_report = profile_module.run_equal_budget_ablation((-1.2, -0.4, 0.2, 0.8, 1.4))
    supplied_report["measurement_status"] = "measured"
    supplied_report["robustness_passed"] = True
    supplied_report["role_differentiated"]["rmse"] = 0.0
    assert profile_module.production_default_change_allowed(supplied_report) is False


def test_report_access_cannot_execute_getters_at_the_authority_boundary(profile_module):
    """The retired gate must not evaluate caller-controlled mapping methods."""
    class HostileReport(dict):
        def __getitem__(self, field_name):
            raise AssertionError("caller-controlled read executed")

    assert profile_module.production_default_change_allowed(HostileReport()) is False
