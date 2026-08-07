"""Validated model-level reasoning capability profiles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ._reasoning_profile_types import (
    CANONICAL_REASONING_LEVELS,
    JsonScalar,
    PayloadRule,
    PRESETS,
    _validate_json_scalar,
)


@dataclass(frozen=True)
class ReasoningProfile:
    """Explicit reasoning capability and payload mapping for one model."""

    preset: str = "openai_effort"
    supported_levels: tuple[str, ...] = ("minimal", "low", "medium", "high")
    default_level: str = "low"
    maximum_level: str = "high"
    level_values: tuple[tuple[str, JsonScalar], ...] = ()
    chat_rules: tuple[PayloadRule, ...] = ()
    responses_rules: tuple[PayloadRule, ...] = ()

    def __post_init__(self) -> None:
        """Validate the complete provider capability contract."""
        if not isinstance(self.supported_levels, tuple):
            raise ValueError("supported_levels must be a tuple")
        if not isinstance(self.level_values, tuple):
            raise ValueError("level_values must be a tuple")
        if not isinstance(self.chat_rules, tuple):
            raise ValueError("chat_rules must be a tuple")
        if not isinstance(self.responses_rules, tuple):
            raise ValueError("responses_rules must be a tuple")
        if self.preset not in PRESETS:
            raise ValueError(f"unsupported reasoning preset: {self.preset}")
        if not self.supported_levels:
            raise ValueError("supported_levels must not be empty")
        if len(set(self.supported_levels)) != len(self.supported_levels):
            raise ValueError("supported_levels must not contain duplicates")
        try:
            indexes = [CANONICAL_REASONING_LEVELS.index(level) for level in self.supported_levels]
        except ValueError as exc:
            raise ValueError("supported_levels contains an unknown level") from exc
        if indexes != sorted(indexes):
            raise ValueError("supported_levels must follow canonical order")
        if self.default_level not in self.supported_levels:
            raise ValueError("default_level must be supported")
        if self.maximum_level not in self.supported_levels:
            raise ValueError("maximum_level must be supported")
        if self.supported_levels.index(self.default_level) > self.supported_levels.index(self.maximum_level):
            raise ValueError("default_level cannot exceed maximum_level")
        if self.preset == "custom" and not (self.chat_rules or self.responses_rules):
            raise ValueError("custom preset requires chat_rules or responses_rules")
        mapping = dict(self.level_values)
        if len(mapping) != len(self.level_values):
            raise ValueError("level_values must not contain duplicate keys")
        for mapped in mapping.values():
            _validate_json_scalar(mapped, "level_values values")
        unknown = set(mapping) - set(self.supported_levels)
        if unknown:
            raise ValueError(f"level_values maps unsupported levels: {sorted(unknown)}")
        rules = self.chat_rules + self.responses_rules
        if any(rule.value in {"$mapped", "$int"} for rule in rules):
            missing = set(self.supported_levels) - set(mapping)
            if missing:
                raise ValueError(f"mapped rules require every supported level: {sorted(missing)}")

    @property
    def bounded_levels(self) -> tuple[str, ...]:
        """Return supported levels no more expensive than ``maximum_level``."""
        return self.supported_levels[: self.supported_levels.index(self.maximum_level) + 1]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReasoningProfile":
        """Parse a strict JSON-compatible model capability profile."""
        if not isinstance(value, Mapping):
            raise ValueError("reasoning_profile must be an object")
        allowed = {
            "preset",
            "supported_levels",
            "default_level",
            "maximum_level",
            "level_values",
            "chat_rules",
            "responses_rules",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown reasoning_profile keys: {sorted(unknown)}")
        preset = value.get("preset", "openai_effort")
        supported = value.get("supported_levels", ("minimal", "low", "medium", "high"))
        default_level = value.get("default_level", "low")
        maximum_level = value.get("maximum_level", "high")
        if not isinstance(preset, str):
            raise ValueError("reasoning preset must be a string")
        if not isinstance(supported, (list, tuple)) or not all(isinstance(item, str) for item in supported):
            raise ValueError("supported_levels must be a string array")
        if not isinstance(default_level, str) or not isinstance(maximum_level, str):
            raise ValueError("default_level and maximum_level must be strings")
        raw_values = value.get("level_values", {})
        if not isinstance(raw_values, Mapping):
            raise ValueError("level_values must be an object")
        level_values: list[tuple[str, JsonScalar]] = []
        for level, mapped in raw_values.items():
            if not isinstance(level, str):
                raise ValueError("level_values keys must be strings")
            level_values.append(
                (level, _validate_json_scalar(mapped, "level_values values"))
            )
        return cls(
            preset=preset,
            supported_levels=tuple(supported),
            default_level=default_level,
            maximum_level=maximum_level,
            level_values=tuple(level_values),
            chat_rules=_parse_rules(value.get("chat_rules", ())),
            responses_rules=_parse_rules(value.get("responses_rules", ())),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the capability profile as stable JSON-compatible data."""
        value: dict[str, Any] = {
            "preset": self.preset,
            "supported_levels": list(self.supported_levels),
            "default_level": self.default_level,
            "maximum_level": self.maximum_level,
        }
        if self.level_values:
            value["level_values"] = dict(self.level_values)
        if self.chat_rules:
            value["chat_rules"] = [rule.to_dict() for rule in self.chat_rules]
        if self.responses_rules:
            value["responses_rules"] = [rule.to_dict() for rule in self.responses_rules]
        return value


def _parse_rules(value: Any) -> tuple[PayloadRule, ...]:
    """Parse an optional payload-rule array."""
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("payload rules must be an array")
    return tuple(PayloadRule.from_dict(item) for item in value)


__all__ = ["ReasoningProfile", "_parse_rules"]
