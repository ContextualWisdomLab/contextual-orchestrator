"""Unsupported effort is omitted in both native request spellings."""
from __future__ import annotations

from copy import deepcopy
from types import ModuleType

import pytest

from test_effort_capability_evidence import effort_api as effort_api
from test_effort_capability_evidence import explicit_profile


@pytest.mark.parametrize("capability_evidence", [False, None])
@pytest.mark.parametrize("remaining_options", [{}, {"summary": "auto", "mode": "standard"}])
def test_nested_effort_is_removed_without_mutating_shared_options(
    effort_api: ModuleType, capability_evidence: bool | None,
    remaining_options: dict[str, str],
) -> None:
    """Omission removes both spellings but preserves unrelated and aliased input."""
    shared_options = {"effort": "high", **remaining_options}
    request_body = {
        "reasoning_effort": "high", "reasoning": shared_options,
        "input": "unit-test input", "stream": True,
        "tools": [{"type": "function", "name": "read_source"}],
    }
    result_body = effort_api.apply_request_profile(
        request_body, explicit_profile(effort_api, "omit"),
        supports_reasoning_effort=capability_evidence, default_max_output_tokens=None,
    )
    assert result_body is request_body
    assert "reasoning_effort" not in result_body
    if remaining_options:
        assert result_body["reasoning"] == remaining_options
        assert result_body["reasoning"] is not shared_options
    else:
        assert "reasoning" not in result_body
    assert shared_options == {"effort": "high", **remaining_options}
    assert result_body["input"] == "unit-test input"
    assert result_body["stream"] is True
    assert result_body["tools"] == [{"type": "function", "name": "read_source"}]


@pytest.mark.parametrize("reasoning_options", [None, {}, {"summary": "auto"}, [], "auto"])
def test_non_effort_reasoning_value_is_not_reinterpreted(
    effort_api: ModuleType, reasoning_options: object,
) -> None:
    """The effort helper does not replace independent options or validate all JSON."""
    request_body = {"reasoning": reasoning_options}
    effort_api.apply_request_profile(
        request_body, explicit_profile(effort_api, "omit"),
        supports_reasoning_effort=None, default_max_output_tokens=None,
    )
    assert request_body["reasoning"] is reasoning_options


@pytest.mark.parametrize("capability_evidence", [False, None])
@pytest.mark.parametrize("fallback_name", ["abstain", "error"])
def test_nested_effort_refusal_leaves_the_request_unchanged(
    effort_api: ModuleType, capability_evidence: bool | None, fallback_name: str,
) -> None:
    """No mutation precedes the explicit unsupported-provider refusal."""
    request_body = {"reasoning": {"effort": "high", "summary": "auto"}, "max_tokens": 17}
    original_body = deepcopy(request_body)
    with pytest.raises(effort_api.EffortProfileError, match="support is unproven"):
        effort_api.apply_request_profile(
            request_body, explicit_profile(effort_api, fallback_name),
            supports_reasoning_effort=capability_evidence, default_max_output_tokens=None,
        )
    assert request_body == original_body


def test_malformed_capability_never_mutates_nested_effort(effort_api: ModuleType) -> None:
    """The typed-evidence guard still runs before either native effort is removed."""
    request_body = {"reasoning_effort": "high", "reasoning": {"effort": "high"}}
    original_body = deepcopy(request_body)
    with pytest.raises(effort_api.EffortProfileError, match="must be a boolean or null"):
        effort_api.apply_request_profile(
            request_body, explicit_profile(effort_api, "omit"),
            supports_reasoning_effort="false", default_max_output_tokens=None,
        )
    assert request_body == original_body


def test_no_profile_preserves_nested_passthrough_options(effort_api: ModuleType) -> None:
    """The opt-in repair does not change the existing no-profile passthrough contract."""
    request_body = {"reasoning": {"effort": "high", "summary": "auto"}}
    original_body = deepcopy(request_body)
    effort_api.apply_request_profile(
        request_body, None, supports_reasoning_effort=None, default_max_output_tokens=None,
    )
    assert request_body == original_body


@pytest.mark.parametrize("capability_evidence", [False, None])
@pytest.mark.parametrize("remaining_options", [{}, {"summary": "auto", "mode": "standard"}])
def test_real_client_responses_omit_preserves_independent_options(
    capability_evidence: bool | None, remaining_options: dict[str, str],
) -> None:
    """Exercise the real ModelClient Responses adapter without a provider request."""
    from contextual_orchestrator import reasoning_effort_profile as production_effort
    from contextual_orchestrator.orchestrator import ModelAgent, ModelClient

    selected_agent = ModelAgent(
        id="response_worker", model="unit_test_model",
        base_url="https://provider.invalid/v1",
        reasoning_effort_supported=capability_evidence,
    )
    request_body = {"model": "unit_test_model", "reasoning": {"effort": "high", **remaining_options}}
    result_body = ModelClient().apply_effort_profile(
        selected_agent, request_body, explicit_profile(production_effort, "omit"),
        api_surface="responses",
    )
    assert result_body is request_body
    assert "reasoning_effort" not in result_body
    assert "max_tokens" not in result_body
    assert result_body["max_output_tokens"] == 321
    if remaining_options:
        assert result_body["reasoning"] == remaining_options
    else:
        assert "reasoning" not in result_body


class HostileAgentCapability:
    """ModelAgent capability validation must not execute caller hooks."""

    def __bool__(self) -> bool:
        """Expose accidental truth-value coercion."""
        raise AssertionError("capability truth hook executed")

    def __eq__(self, other: object) -> bool:
        """Expose equality-based type admission."""
        raise AssertionError("capability equality hook executed")

    def __repr__(self) -> str:
        """Expose accidental rendering of untrusted capability data."""
        raise AssertionError("capability rendering hook executed")


@pytest.mark.parametrize(
    "capability_evidence",
    [
        pytest.param(1, id="integer-one"),
        pytest.param(1.0, id="float-one"),
        pytest.param(HostileAgentCapability(), id="hostile-hooks"),
    ],
)
def test_model_agent_rejects_malformed_capability_before_client_mutation(
    capability_evidence: object,
) -> None:
    """The real agent/client path rejects non-booleans before request mutation."""
    from contextual_orchestrator import reasoning_effort_profile as production_effort
    from contextual_orchestrator.orchestrator import ModelAgent, ModelClient

    request_body = {"reasoning": {"effort": "high"}, "max_output_tokens": 17}
    original_body = deepcopy(request_body)
    with pytest.raises(TypeError, match="reasoning_effort_supported must be"):
        selected_agent = ModelAgent(
            id="response_worker",
            model="unit_test_model",
            base_url="https://provider.invalid/v1",
            reasoning_effort_supported=capability_evidence,  # type: ignore[arg-type]
        )
        ModelClient().apply_effort_profile(
            selected_agent,
            request_body,
            explicit_profile(production_effort, "omit"),
            api_surface="responses",
        )
    assert request_body == original_body
