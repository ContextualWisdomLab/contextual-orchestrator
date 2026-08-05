"""Coverage-focused edge tests for the reasoning-control pure functions."""

from __future__ import annotations

from collections import UserDict

import pytest

import contextual_orchestrator.reasoning_control as rc


def decision(level: str = "low") -> rc.ReasoningDecision:
    """Return a minimal valid decision."""
    return rc.ReasoningDecision(level, "coverage", "worker", 0, ("coverage",))


def one_level_profile(**kwargs: object) -> rc.ReasoningProfile:
    """Return a one-level profile with optional overrides."""
    values: dict[str, object] = {
        "supported_levels": ("low",),
        "default_level": "low",
        "maximum_level": "low",
    }
    values.update(kwargs)
    return rc.ReasoningProfile(**values)


def test_payload_rule_defensive_validation() -> None:
    with pytest.raises(ValueError, match="1 to 8"):
        rc.PayloadRule((), "low")
    with pytest.raises(ValueError, match="JSON scalar"):
        rc.PayloadRule(("reasoning",), object())
    with pytest.raises(ValueError, match="must be an object"):
        rc.PayloadRule.from_dict([])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="non-empty string array"):
        rc.PayloadRule.from_dict({"path": [], "value": "low"})
    with pytest.raises(ValueError, match="non-empty string array"):
        rc.PayloadRule.from_dict({"path": [1], "value": "low"})


def test_profile_defensive_validation() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        rc.ReasoningProfile(supported_levels=("low", "low"), default_level="low", maximum_level="low")
    with pytest.raises(ValueError, match="unknown level"):
        rc.ReasoningProfile(supported_levels=("low", "ultra"), default_level="low", maximum_level="low")
    with pytest.raises(ValueError, match="maximum_level must be supported"):
        rc.ReasoningProfile(supported_levels=("low",), default_level="low", maximum_level="high")
    with pytest.raises(ValueError, match="duplicate keys"):
        rc.ReasoningProfile(
            preset="custom",
            supported_levels=("low",),
            default_level="low",
            maximum_level="low",
            level_values=(("low", 1), ("low", 2)),
            chat_rules=(rc.PayloadRule(("budget",), "$mapped"),),
        )
    with pytest.raises(ValueError, match="unsupported levels"):
        rc.ReasoningProfile(
            supported_levels=("low",),
            default_level="low",
            maximum_level="low",
            level_values=(("high", 3),),
        )


def test_profile_from_dict_defensive_validation() -> None:
    with pytest.raises(ValueError, match="must be an object"):
        rc.ReasoningProfile.from_dict([])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="preset must be a string"):
        rc.ReasoningProfile.from_dict({"preset": 1})
    with pytest.raises(ValueError, match="string array"):
        rc.ReasoningProfile.from_dict({"supported_levels": "low"})
    with pytest.raises(ValueError, match="string array"):
        rc.ReasoningProfile.from_dict({"supported_levels": [1]})
    with pytest.raises(ValueError, match="must be strings"):
        rc.ReasoningProfile.from_dict({"default_level": 1})
    with pytest.raises(ValueError, match="level_values must be an object"):
        rc.ReasoningProfile.from_dict({"level_values": []})

    class OddMapping(UserDict):
        """Mapping that can expose non-string keys for validation."""

    with pytest.raises(ValueError, match="keys must be strings"):
        rc.ReasoningProfile.from_dict({"level_values": OddMapping({1: "low"})})
    with pytest.raises(ValueError, match="JSON scalars"):
        rc.ReasoningProfile.from_dict({"level_values": {"low": object()}})


def test_profile_to_dict_includes_responses_rules() -> None:
    profile = rc.ReasoningProfile(
        preset="custom",
        supported_levels=("low",),
        default_level="low",
        maximum_level="low",
        responses_rules=(rc.PayloadRule(("reasoning", "effort"), "$level"),),
    )
    assert profile.to_dict()["responses_rules"] == [
        {"path": ["reasoning", "effort"], "value": "$level"}
    ]


def test_policy_from_dict_and_validation_edges() -> None:
    with pytest.raises(ValueError, match="strategy must be"):
        rc.ReasoningPolicy(strategy="unknown")
    with pytest.raises(ValueError, match="canonical"):
        rc.ReasoningPolicy(strategy="fixed", fixed_level="ultra")
    with pytest.raises(ValueError, match="must be an object"):
        rc.ReasoningPolicy.from_dict([])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unknown reasoning policy keys"):
        rc.ReasoningPolicy.from_dict({"typo": True})
    parsed = rc.ReasoningPolicy.from_dict(
        {"strategy": "fixed", "fixed_level": "high", "max_escalations": 0}
    )
    assert parsed.to_dict() == {
        "strategy": "fixed",
        "fixed_level": "high",
        "max_escalations": 0,
    }


def test_decision_validation_edges() -> None:
    with pytest.raises(ValueError, match="source and role"):
        rc.ReasoningDecision("low", "", "worker", 0, ("x",))
    with pytest.raises(ValueError, match="must be an integer"):
        rc.ReasoningDecision("low", "x", "worker", True, ("x",))
    with pytest.raises(ValueError, match="non-negative"):
        rc.ReasoningDecision("low", "x", "worker", -1, ("x",))
    with pytest.raises(ValueError, match="non-empty strings"):
        rc.ReasoningDecision("low", "x", "worker", 0, ("",))
    with pytest.raises(ValueError, match="escalation_index must be an integer"):
        rc.ReasoningDecision("low", "x", "worker", 0, ("x",), True)
    with pytest.raises(ValueError, match="escalation_index must be non-negative"):
        rc.ReasoningDecision("low", "x", "worker", 0, ("x",), -1)


def test_selection_input_long_context_and_multi_step_branches() -> None:
    profile = rc.ReasoningProfile(
        supported_levels=("low", "medium", "high"),
        default_level="low",
        maximum_level="high",
    )
    with pytest.raises(ValueError, match="task and role"):
        rc.select_reasoning_decision(profile, rc.ReasoningPolicy(), 3, "worker")  # type: ignore[arg-type]
    long = rc.select_reasoning_decision(profile, rc.ReasoningPolicy(), "x" * 801, "worker")
    structured = rc.select_reasoning_decision(
        profile,
        rc.ReasoningPolicy(),
        "\n".join(str(index) for index in range(9)),
        "worker",
    )
    assert long is not None and "long_context" in long.factors
    assert structured is not None and "multi_step_structure" in structured.factors
    assert rc.select_reasoning_decision(None, rc.ReasoningPolicy(), "x", "worker") is None


def test_adaptation_and_escalation_none_and_ceiling_edges() -> None:
    profile = one_level_profile()
    assert rc.adapt_reasoning_decision(None, decision()) is None
    assert rc.adapt_reasoning_decision(profile, None) is None
    assert rc.adapt_reasoning_decision(profile, decision()) == decision()
    assert rc.escalate_reasoning_decision(None, rc.ReasoningPolicy(), decision()) is None
    assert rc.escalate_reasoning_decision(profile, rc.ReasoningPolicy(), None) is None
    assert rc.escalate_reasoning_decision(profile, rc.ReasoningPolicy(), decision()) is None


def test_payload_input_none_profile_and_unknown_endpoint_edges() -> None:
    with pytest.raises(ValueError, match="payload must be an object"):
        rc.apply_reasoning_payload([], one_level_profile(), decision(), "chat/completions")  # type: ignore[arg-type]
    payload = {"model": "x"}
    assert rc.apply_reasoning_payload(payload, None, decision(), "chat/completions") == payload
    assert rc.apply_reasoning_payload(payload, one_level_profile(), None, "chat/completions") == payload
    with pytest.raises(ValueError, match="endpoint must be a string"):
        rc.apply_reasoning_payload({}, one_level_profile(), decision(), 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unsupported reasoning endpoint"):
        rc.apply_reasoning_payload({}, one_level_profile(), decision(), "embeddings")


def test_usage_negative_values_and_invalid_total_are_ignored() -> None:
    assert rc.extract_reasoning_tokens({"reasoning_tokens": -1}) is None
    assert rc.extract_reasoning_tokens({"output_tokens_details": {"reasoning_tokens": -1}}) is None
    assert rc.sum_usage_tokens([{"usage": {"total_tokens": True}}]) == (0, 0)


def test_rule_parsing_projection_and_empty_rules_edges() -> None:
    assert rc._parse_rules(None) == ()
    with pytest.raises(ValueError, match="must be an array"):
        rc._parse_rules("bad")
    with pytest.raises(ValueError, match="no bounded"):
        rc._nearest_supported((), "low")
    with pytest.raises(ValueError, match="unknown canonical"):
        rc._nearest_supported(("low",), "ultra")
    assert rc._nearest_supported(("medium", "high"), "minimal") == "medium"
    custom = rc.ReasoningProfile(
        preset="custom",
        supported_levels=("low",),
        default_level="low",
        maximum_level="low",
        chat_rules=(rc.PayloadRule(("literal",), 7),),
    )
    assert rc.apply_reasoning_payload({}, custom, decision(), "chat/completions") == {"literal": 7}
    empty_responses = rc.ReasoningProfile(
        preset="nvidia_nemotron_thinking",
        supported_levels=("low",),
        default_level="low",
        maximum_level="low",
    )
    assert rc.apply_reasoning_payload({}, empty_responses, decision(), "responses") == {}


def test_explicit_response_rule_and_template_failure_edges() -> None:
    explicit = rc.ReasoningProfile(
        preset="custom",
        supported_levels=("low",),
        default_level="low",
        maximum_level="low",
        responses_rules=(rc.PayloadRule(("thinking",), "$level"),),
    )
    assert rc.apply_reasoning_payload({}, explicit, decision(), "responses") == {"thinking": "low"}
    with pytest.raises(ValueError, match="has no provider mapping"):
        rc._render_value("$mapped", "low", {})
    with pytest.raises(ValueError, match="requires an integer"):
        rc._render_value("$int", "low", {"low": True})
    with pytest.raises(ValueError, match="unsupported reasoning template"):
        rc._render_value("$unknown", "low", {"low": "low"})
    assert rc._render_value("$enabled", "none", {}) is False
    assert rc._render_value("$low_effort", "low", {}) is True


def test_any_complete_path_and_existing_mapping_branches() -> None:
    assert rc._any_complete_path({"a": {"b": None}}, (("a", "b"),)) is True
    assert rc._any_complete_path({"a": "scalar"}, (("a", "b"),)) is False
    target = {"a": {}}
    rc._set_nested_if_absent(target, ("a", "b"), 1)
    rc._set_nested_if_absent(target, ("a", "b"), 2)
    assert target == {"a": {"b": 1}}


def test_decision_and_ablation_cell_serialize_all_fields() -> None:
    assert decision().to_dict() == {
        "level": "low",
        "source": "coverage",
        "role": "worker",
        "complexity_score": 0,
        "factors": ["coverage"],
        "escalation_index": 0,
    }
    cell = rc.ReasoningAblationCell("low", 2, 1, 3, 10)
    assert cell.to_dict() == {
        "level": "low",
        "prompt_count": 2,
        "accepted_count": 1,
        "reasoning_tokens": 3,
        "total_tokens": 10,
    }
