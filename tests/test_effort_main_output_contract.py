"""Preserve protected-main output omission while integrating effort repairs."""
from types import ModuleType

import pytest

from test_effort_capability_evidence import effort_api as effort_api
from test_effort_capability_evidence import explicit_profile


@pytest.mark.parametrize("capability_evidence", [True, False, None])
def test_unknown_output_ceiling_does_not_create_a_token_limit(
    effort_api: ModuleType, capability_evidence: bool | None,
) -> None:
    """An unconfigured profile cannot impose a ceiling absent from the request."""
    request_body = {"model": "selected_worker", "stream": True}
    result_body = effort_api.apply_request_profile(
        request_body, None, supports_reasoning_effort=capability_evidence,
        default_max_output_tokens=None,
    )
    assert result_body is request_body
    assert result_body == {"model": "selected_worker", "stream": True}


def test_unknown_output_ceiling_preserves_explicit_request_limit(effort_api: ModuleType) -> None:
    """No-profile compatibility retains a caller-supplied limit without replacement."""
    request_body = {"max_tokens": 17, "model": "selected_worker"}
    effort_api.apply_request_profile(
        request_body, None, supports_reasoning_effort=False, default_max_output_tokens=None,
    )
    assert request_body == {"max_tokens": 17, "model": "selected_worker"}


def test_explicit_profile_does_not_require_a_default_output_ceiling(effort_api: ModuleType) -> None:
    """A supported explicit test profile keeps its own validated output setting."""
    request_body = {}
    effort_api.apply_request_profile(
        request_body, explicit_profile(effort_api, "abstain"),
        supports_reasoning_effort=True, default_max_output_tokens=None,
    )
    assert request_body["max_tokens"] == 321
    assert request_body["reasoning_effort"] == "low"


def test_omission_with_unknown_output_ceiling_removes_stale_effort(effort_api: ModuleType) -> None:
    """Unknown ceiling does not undo the independently validated omission repair."""
    request_body = {"reasoning_effort": "high"}
    effort_api.apply_request_profile(
        request_body, explicit_profile(effort_api, "omit"),
        supports_reasoning_effort=None, default_max_output_tokens=None,
    )
    assert "reasoning_effort" not in request_body
    assert request_body["max_tokens"] == 321
