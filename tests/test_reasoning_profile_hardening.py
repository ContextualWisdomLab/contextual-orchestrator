"""Fail-closed tests for immutable, JSON-safe reasoning profile controls."""

from __future__ import annotations

import pytest

from contextual_orchestrator.reasoning_control import PayloadRule, ReasoningProfile


def test_payload_rule_requires_immutable_path_control() -> None:
    """A frozen rule must not retain a caller-mutable path list."""
    with pytest.raises(ValueError, match="path must be a tuple"):
        PayloadRule(["reasoning", "effort"], "$level")  # type: ignore[arg-type]


def test_payload_rule_distinguishes_missing_value_from_explicit_null() -> None:
    """A missing assignment is invalid while an explicit JSON null is valid."""
    with pytest.raises(ValueError, match="must include value"):
        PayloadRule.from_dict({"path": ["reasoning", "effort"]})
    assert PayloadRule.from_dict(
        {"path": ["reasoning", "effort"], "value": None}
    ).value is None


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf"), float("-inf")])
def test_payload_rule_rejects_non_finite_json_numbers(invalid_value: float) -> None:
    """Provider payload rules accept only numbers representable in strict JSON."""
    with pytest.raises(ValueError, match="finite JSON scalar"):
        PayloadRule(("reasoning", "budget"), invalid_value)


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("supported_levels", ["low"]),
        ("level_values", [("low", 1)]),
        ("chat_rules", [PayloadRule(("reasoning",), "$level")]),
        ("responses_rules", [PayloadRule(("reasoning",), "$level")]),
    ],
)
def test_profile_rejects_mutable_direct_constructor_collections(
    field_name: str,
    field_value: object,
) -> None:
    """Frozen profiles reject lists that could change after validation."""
    values: dict[str, object] = {
        "preset": "openai_effort",
        "supported_levels": ("low",),
        "default_level": "low",
        "maximum_level": "low",
        "level_values": (),
        "chat_rules": (),
        "responses_rules": (),
    }
    values[field_name] = field_value
    with pytest.raises(ValueError, match=f"{field_name} must be a tuple"):
        ReasoningProfile(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf"), float("-inf")])
def test_profile_rejects_non_finite_level_mapping(invalid_value: float) -> None:
    """Mapped provider values cannot serialize as NaN or Infinity."""
    with pytest.raises(ValueError, match="finite JSON scalar"):
        ReasoningProfile(
            preset="custom",
            supported_levels=("low",),
            default_level="low",
            maximum_level="low",
            level_values=(("low", invalid_value),),
            chat_rules=(PayloadRule(("reasoning", "budget"), "$mapped"),),
        )
