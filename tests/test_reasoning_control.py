"""Behavioral tests for adaptive reasoning policy and provider payload mapping."""

from __future__ import annotations

import pytest

from contextual_orchestrator.reasoning_control import (
    CANONICAL_REASONING_LEVELS,
    PayloadRule,
    ReasoningDecision,
    ReasoningPolicy,
    ReasoningProfile,
    adapt_reasoning_decision,
    apply_reasoning_payload,
    escalate_reasoning_decision,
    extract_reasoning_tokens,
    select_reasoning_decision,
    sum_usage_tokens,
)


def profile(preset: str = "openai_effort") -> ReasoningProfile:
    """Return the common four-level profile used by tests."""
    return ReasoningProfile(
        preset=preset,
        supported_levels=("minimal", "low", "medium", "high"),
        default_level="low",
        maximum_level="high",
    )


def test_canonical_levels_are_cheapest_to_most_expensive() -> None:
    assert CANONICAL_REASONING_LEVELS == (
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"preset": "unknown"}, "unsupported reasoning preset"),
        ({"supported_levels": ()}, "must not be empty"),
        ({"supported_levels": ("low", "minimal")}, "canonical order"),
        ({"default_level": "xhigh"}, "default_level must be supported"),
        ({"maximum_level": "minimal"}, "default_level cannot exceed"),
        ({"preset": "custom"}, "custom preset requires"),
    ],
)
def test_profile_rejects_ambiguous_or_unsupported_contracts(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ReasoningProfile(**kwargs)


def test_profile_round_trips_custom_mapping() -> None:
    source = {
        "preset": "custom",
        "supported_levels": ["low", "medium", "high"],
        "default_level": "low",
        "maximum_level": "high",
        "level_values": {"low": 128, "medium": 512, "high": 1024},
        "chat_rules": [{"path": ["thinking", "budget"], "value": "$int"}],
    }
    parsed = ReasoningProfile.from_dict(source)
    assert ReasoningProfile.from_dict(parsed.to_dict()) == parsed
    assert parsed.bounded_levels == ("low", "medium", "high")


def test_profile_rejects_unknown_keys_and_incomplete_mapped_rules() -> None:
    with pytest.raises(ValueError, match="unknown reasoning_profile keys"):
        ReasoningProfile.from_dict({"preset": "openai_effort", "typo": True})
    with pytest.raises(ValueError, match="require every supported level"):
        ReasoningProfile(
            preset="custom",
            supported_levels=("low", "high"),
            default_level="low",
            maximum_level="high",
            level_values=(("low", 128),),
            chat_rules=(PayloadRule(("thinking", "budget"), "$int"),),
        )


def test_payload_rule_rejects_unsafe_path_and_unknown_template() -> None:
    with pytest.raises(ValueError, match="unsafe segment"):
        PayloadRule(("../secret",), "low")
    with pytest.raises(ValueError, match="unsupported reasoning payload template"):
        PayloadRule(("reasoning",), "$eval")
    with pytest.raises(ValueError, match="unknown reasoning payload rule keys"):
        PayloadRule.from_dict({"path": ["reasoning"], "value": "low", "extra": 1})


@pytest.mark.parametrize(
    ("preset", "endpoint", "expected"),
    [
        ("openai_effort", "chat/completions", {"reasoning_effort": "medium"}),
        ("openai_effort", "/v1/responses", {"reasoning": {"effort": "medium"}}),
        ("nvidia_reasoning_effort", "chat/completions", {"reasoning_effort": "medium"}),
        (
            "nvidia_nemotron_thinking",
            "chat/completions",
            {"chat_template_kwargs": {"enable_thinking": True, "low_effort": False}},
        ),
        (
            "gemini_thinking_level",
            "chat/completions",
            {"extra_body": {"google": {"thinking_config": {"thinking_level": "medium"}}}},
        ),
    ],
)
def test_provider_presets_map_one_canonical_decision(
    preset: str,
    endpoint: str,
    expected: dict[str, object],
) -> None:
    decision = ReasoningDecision("medium", "test", "worker", 1, ("test",))
    assert apply_reasoning_payload({}, profile(preset), decision, endpoint) == expected


def test_caller_owned_reasoning_field_is_never_overwritten() -> None:
    decision = ReasoningDecision("high", "test", "worker", 2, ("test",))
    payload = {"reasoning": {"effort": "minimal"}, "input": "task"}
    result = apply_reasoning_payload(payload, profile(), decision, "responses")
    assert result == payload
    assert result is not payload


def test_custom_integer_mapping_sets_nested_field() -> None:
    custom = ReasoningProfile(
        preset="custom",
        supported_levels=("low", "medium"),
        default_level="low",
        maximum_level="medium",
        level_values=(("low", 128), ("medium", 512)),
        chat_rules=(PayloadRule(("thinking", "budget_tokens"), "$int"),),
    )
    decision = ReasoningDecision("medium", "test", "worker", 1, ("test",))
    assert apply_reasoning_payload({}, custom, decision, "chat/completions") == {
        "thinking": {"budget_tokens": 512}
    }


def test_nested_mapping_conflict_fails_closed() -> None:
    custom = ReasoningProfile(
        preset="custom",
        supported_levels=("low",),
        default_level="low",
        maximum_level="low",
        chat_rules=(PayloadRule(("thinking", "effort"), "$level"),),
    )
    decision = ReasoningDecision("low", "test", "worker", 0, ("test",))
    with pytest.raises(ValueError, match="conflicts with caller scalar"):
        apply_reasoning_payload({"thinking": "caller scalar"}, custom, decision, "chat/completions")


def test_adaptive_policy_uses_default_for_simple_worker_and_more_for_verifier() -> None:
    simple = select_reasoning_decision(profile(), ReasoningPolicy(), "Summarize this note.", "worker")
    verifier = select_reasoning_decision(profile(), ReasoningPolicy(), "Verify this result.", "verifier")
    assert simple is not None and simple.level == "low"
    assert verifier is not None and verifier.level == "medium"


def test_adaptive_policy_requires_multiple_high_impact_signals_for_extra_compute() -> None:
    one = select_reasoning_decision(profile(), ReasoningPolicy(), "Review authentication wording.", "worker")
    two = select_reasoning_decision(
        profile(),
        ReasoningPolicy(),
        "Analyze and verify authentication privacy security architecture failure modes.",
        "worker",
    )
    assert one is not None and one.level == "low"
    assert two is not None and two.level == "high"
    assert "multiple_high_impact_signals" in two.factors


def test_fixed_and_disabled_policies_are_deterministic() -> None:
    fixed = select_reasoning_decision(
        profile(),
        ReasoningPolicy(strategy="fixed", fixed_level="medium", max_escalations=0),
        "anything",
        "worker",
    )
    disabled = select_reasoning_decision(profile(), ReasoningPolicy(strategy="disabled"), "anything", "worker")
    assert fixed is not None and fixed.level == "medium" and fixed.source == "fixed_policy"
    assert disabled is None


def test_failover_projection_never_exceeds_provider_capability() -> None:
    decision = ReasoningDecision("high", "adaptive_policy", "worker", 2, ("complex",))
    small = ReasoningProfile(
        supported_levels=("minimal", "low"),
        default_level="minimal",
        maximum_level="low",
    )
    projected = adapt_reasoning_decision(small, decision)
    assert projected is not None and projected.level == "low"
    assert projected.source.endswith("capability_projection")


def test_verifier_escalation_moves_exactly_one_supported_step() -> None:
    prior = ReasoningDecision("low", "adaptive_policy", "worker", 0, ("default",))
    escalated = escalate_reasoning_decision(profile(), ReasoningPolicy(), prior)
    assert escalated is not None and escalated.level == "medium"
    assert escalated.escalation_index == 1
    assert escalate_reasoning_decision(profile(), ReasoningPolicy(), escalated) is None
    assert escalate_reasoning_decision(profile(), ReasoningPolicy(max_escalations=0), prior) is None


def test_reasoning_token_usage_supports_responses_and_chat_shapes() -> None:
    assert extract_reasoning_tokens({"reasoning_tokens": 3}) == 3
    assert extract_reasoning_tokens({"output_tokens_details": {"reasoning_tokens": 5}}) == 5
    assert extract_reasoning_tokens({"completion_tokens_details": {"reasoning_tokens": 7}}) == 7
    assert extract_reasoning_tokens({"reasoning_tokens": True}) is None
    assert extract_reasoning_tokens(None) is None


def test_sum_usage_tokens_ignores_unknown_or_malformed_fields() -> None:
    trace = [
        {"usage": {"total_tokens": 20, "output_tokens_details": {"reasoning_tokens": 5}}},
        {"usage": {"total_tokens": 10, "completion_tokens_details": {"reasoning_tokens": 3}}},
        {"usage": "unknown"},
    ]
    assert sum_usage_tokens(trace) == (8, 30)


def test_policy_and_decision_validation_reject_ambiguous_values() -> None:
    with pytest.raises(ValueError, match="fixed strategy requires"):
        ReasoningPolicy(strategy="fixed")
    with pytest.raises(ValueError, match="max_escalations"):
        ReasoningPolicy(max_escalations=2)
    with pytest.raises(ValueError, match="decision level"):
        ReasoningDecision("ultra", "test", "worker", 0, ("test",))
