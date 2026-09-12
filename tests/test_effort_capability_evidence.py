"""Native effort requires literal boolean capability evidence, never truthiness."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
from types import ModuleType
import sys

import pytest


@pytest.fixture
def effort_api(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load the exact production leaf without unrelated package initialization."""
    source_path = (
        Path(__file__).resolve().parents[1]
        / "contextual_orchestrator/reasoning_effort_profile.py"
    )
    module_spec = importlib.util.spec_from_file_location("effort_capability_subject", source_path)
    assert module_spec is not None and module_spec.loader is not None
    source_module = importlib.util.module_from_spec(module_spec)
    monkeypatch.setitem(sys.modules, module_spec.name, source_module)
    module_spec.loader.exec_module(source_module)
    return source_module


class HostileCapability:
    """Capability data must not execute truth, equality or rendering hooks."""

    def __bool__(self) -> bool:
        """Expose accidental truth-value coercion."""
        raise AssertionError("capability truth hook executed")

    def __eq__(self, other: object) -> bool:
        """Expose equality-to-True admission instead of type validation."""
        raise AssertionError("capability equality hook executed")

    def __repr__(self) -> str:
        """Expose accidental logging of caller-controlled capability data."""
        raise AssertionError("capability rendering hook executed")


def explicit_profile(effort_api: ModuleType, fallback_name: str) -> object:
    """Provide an explicit test-only configuration, not a recommended budget."""
    return effort_api.parse_reasoning_effort_profile({
        "profile_version": effort_api.PROFILE_VERSION,
        "reasoning_effort": "low",
        "max_output_tokens": 321,
        "max_calls": 1,
        "max_workflow_steps": 1,
        "max_recursion_depth": 0,
        "max_worker_fan_out": 1,
        "access_list_scope": "none",
        "deadline_ms": 0,
        "cost_token_budget": 642,
        "temperature": 0.3,
        "top_p": 0.8,
        "seed": 11,
        "unsupported_provider_fallback": fallback_name,
    })


@pytest.mark.parametrize("fallback_name", ["abstain", "error", "omit"])
@pytest.mark.parametrize("capability_evidence", [
    pytest.param("false", id="string-false"),
    pytest.param("true", id="string-true"),
    pytest.param("", id="empty-string"),
    pytest.param("unknown", id="unknown-string"),
    pytest.param(1, id="integer-one"),
    pytest.param(0, id="integer-zero"),
    pytest.param(-1, id="negative-integer"),
    pytest.param(1.0, id="float-one"),
    pytest.param(0.0, id="float-zero"),
    pytest.param(float("nan"), id="nan"),
    pytest.param(float("inf"), id="infinity"),
    pytest.param([], id="empty-array"),
    pytest.param([True], id="nonempty-array"),
    pytest.param({}, id="empty-object"),
    pytest.param({"supported": True}, id="nonempty-object"),
    pytest.param(HostileCapability(), id="hostile-hooks"),
])
def test_invalid_capability_is_rejected_before_mutation(
    effort_api: ModuleType, capability_evidence: object, fallback_name: str,
) -> None:
    """Neither truthy nor falsy malformed evidence can select a fallback or effort."""
    request_body = {
        "model": "selected_worker", "reasoning_effort": "high", "max_tokens": 17,
        "messages": [{"role": "user", "content": "unit test request"}],
        "tools": [{"type": "function", "function": {"name": "read_source"}}],
        "stream": True, "temperature": 0.7, "seed": 3,
    }
    original_body = deepcopy(request_body)
    with pytest.raises(effort_api.EffortProfileError, match="must be a boolean or null"):
        effort_api.apply_request_profile(
            request_body, explicit_profile(effort_api, fallback_name),
            supports_reasoning_effort=capability_evidence, default_max_output_tokens=99,
        )
    assert request_body == original_body


@pytest.mark.parametrize("capability_evidence", [False, None])
@pytest.mark.parametrize("fallback_name", ["abstain", "error"])
def test_unproven_capability_does_not_authorize_native_effort(
    effort_api: ModuleType, capability_evidence: bool | None, fallback_name: str,
) -> None:
    """False and unknown retain the explicit fail-closed fallback without mutation."""
    request_body = {"reasoning_effort": "high", "max_tokens": 17}
    with pytest.raises(effort_api.EffortProfileError, match="support is unproven"):
        effort_api.apply_request_profile(
            request_body, explicit_profile(effort_api, fallback_name),
            supports_reasoning_effort=capability_evidence, default_max_output_tokens=99,
        )
    assert request_body == {"reasoning_effort": "high", "max_tokens": 17}


@pytest.mark.parametrize("capability_evidence", [False, None])
def test_explicit_omit_removes_effort_for_unproven_capability(
    effort_api: ModuleType, capability_evidence: bool | None,
) -> None:
    """Unknown support cannot retain effort populated for a previous capability."""
    request_body = {"reasoning_effort": "high", "model": "selected_worker", "stream": True}
    result_body = effort_api.apply_request_profile(
        request_body, explicit_profile(effort_api, "omit"),
        supports_reasoning_effort=capability_evidence, default_max_output_tokens=99,
    )
    assert result_body is request_body
    assert result_body == {
        "model": "selected_worker", "stream": True, "max_tokens": 321,
        "temperature": 0.3, "top_p": 0.8, "seed": 11,
    }


@pytest.mark.parametrize("fallback_name", ["abstain", "error", "omit"])
def test_literal_true_preserves_explicit_native_effort(
    effort_api: ModuleType, fallback_name: str,
) -> None:
    """Positive capability evidence forwards only the explicitly supplied profile."""
    request_body = {"model": "selected_worker", "stream": True}
    result_body = effort_api.apply_request_profile(
        request_body, explicit_profile(effort_api, fallback_name),
        supports_reasoning_effort=True, default_max_output_tokens=99,
    )
    assert result_body is request_body
    assert result_body == {
        "model": "selected_worker", "stream": True, "reasoning_effort": "low",
        "max_tokens": 321, "temperature": 0.3, "top_p": 0.8, "seed": 11,
    }
