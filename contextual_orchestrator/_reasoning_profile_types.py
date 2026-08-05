"""Primitive types and validated nested payload rules for reasoning profiles."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

JsonScalar = str | int | float | bool | None

CANONICAL_REASONING_LEVELS = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)

PRESETS = {
    "openai_effort",
    "nvidia_reasoning_effort",
    "nvidia_nemotron_thinking",
    "gemini_thinking_level",
    "custom",
}
TEMPLATES = {"$level", "$mapped", "$enabled", "$low_effort", "$int"}
_SAFE_SEGMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class PayloadRule:
    """One validated nested assignment used by a custom provider mapping."""

    path: tuple[str, ...]
    value: JsonScalar

    def __post_init__(self) -> None:
        """Validate path depth, identifier syntax, and template vocabulary."""
        if not 1 <= len(self.path) <= 8:
            raise ValueError("reasoning payload path must contain 1 to 8 segments")
        if any(not isinstance(part, str) or not _SAFE_SEGMENT.fullmatch(part) for part in self.path):
            raise ValueError("reasoning payload path contains an unsafe segment")
        if isinstance(self.value, str) and self.value.startswith("$") and self.value not in TEMPLATES:
            raise ValueError(f"unsupported reasoning payload template: {self.value}")
        if not isinstance(self.value, (str, int, float, bool)) and self.value is not None:
            raise ValueError("reasoning payload value must be a JSON scalar")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PayloadRule":
        """Parse one strict JSON-compatible payload rule."""
        if not isinstance(value, Mapping):
            raise ValueError("reasoning payload rule must be an object")
        unknown = set(value) - {"path", "value"}
        if unknown:
            raise ValueError(f"unknown reasoning payload rule keys: {sorted(unknown)}")
        path = value.get("path")
        if not isinstance(path, (list, tuple)) or not path or not all(isinstance(item, str) for item in path):
            raise ValueError("reasoning payload rule path must be a non-empty string array")
        return cls(tuple(path), value.get("value"))

    def to_dict(self) -> dict[str, Any]:
        """Return the rule as stable JSON-compatible data."""
        return {"path": list(self.path), "value": self.value}


__all__ = [
    "CANONICAL_REASONING_LEVELS",
    "JsonScalar",
    "PayloadRule",
    "PRESETS",
    "TEMPLATES",
]
