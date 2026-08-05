"""Provider payload projection and reasoning-token accounting."""

from __future__ import annotations

import copy
from typing import Any, Mapping, MutableMapping, Sequence

from ._reasoning_profile import JsonScalar, PayloadRule, ReasoningProfile
from ._reasoning_policy import ReasoningDecision, _nearest_supported

def apply_reasoning_payload(
    payload: Mapping[str, Any],
    profile: ReasoningProfile | None,
    decision: ReasoningDecision | None,
    endpoint: str,
) -> dict[str, Any]:
    """Return a copied payload with provider reasoning fields set if unowned."""
    if not isinstance(payload, Mapping):
        raise ValueError("provider payload must be an object")
    output = copy.deepcopy(dict(payload))
    if profile is None or decision is None:
        return output
    level = _nearest_supported(profile.bounded_levels, decision.level)
    normalized = _normalize_endpoint(endpoint)
    rules = _rules_for(profile, normalized)
    if _any_complete_path(output, tuple(rule.path for rule in rules)):
        return output
    mapping = dict(profile.level_values) or {item: item for item in profile.supported_levels}
    for rule in rules:
        _set_nested_if_absent(output, rule.path, _render_value(rule.value, level, mapping))
    return output


def extract_reasoning_tokens(usage: Mapping[str, Any] | None) -> int | None:
    """Extract provider-reported reasoning tokens from known usage shapes."""
    if not isinstance(usage, Mapping):
        return None
    direct = usage.get("reasoning_tokens")
    if isinstance(direct, int) and not isinstance(direct, bool) and direct >= 0:
        return direct
    for key in ("output_tokens_details", "completion_tokens_details"):
        details = usage.get(key)
        if isinstance(details, Mapping):
            value = details.get("reasoning_tokens")
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
    return None


def sum_usage_tokens(trace: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    """Return reasoning and total token sums from a workflow trace."""
    reasoning_total = 0
    total = 0
    for step in trace:
        usage = step.get("usage")
        if not isinstance(usage, Mapping):
            continue
        reasoning_total += extract_reasoning_tokens(usage) or 0
        value = usage.get("total_tokens")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            total += value
    return reasoning_total, total



def _normalize_endpoint(endpoint: str) -> str:
    """Normalize supported OpenAI-compatible endpoint names."""
    if not isinstance(endpoint, str):
        raise ValueError("endpoint must be a string")
    value = endpoint.strip().lower().strip("/")
    if value.startswith("v1/"):
        value = value[3:]
    if value not in {"chat/completions", "responses"}:
        raise ValueError(f"unsupported reasoning endpoint: {endpoint}")
    return value


def _rules_for(profile: ReasoningProfile, endpoint: str) -> tuple[PayloadRule, ...]:
    """Return explicit or preset rules for an endpoint."""
    if endpoint == "chat/completions" and profile.chat_rules:
        return profile.chat_rules
    if endpoint == "responses" and profile.responses_rules:
        return profile.responses_rules
    if profile.preset in {"openai_effort", "nvidia_reasoning_effort"}:
        return (
            (PayloadRule(("reasoning_effort",), "$mapped"),)
            if endpoint == "chat/completions"
            else (PayloadRule(("reasoning", "effort"), "$mapped"),)
        )
    if profile.preset == "nvidia_nemotron_thinking" and endpoint == "chat/completions":
        return (
            PayloadRule(("chat_template_kwargs", "enable_thinking"), "$enabled"),
            PayloadRule(("chat_template_kwargs", "low_effort"), "$low_effort"),
        )
    if profile.preset == "gemini_thinking_level" and endpoint == "chat/completions":
        return (
            PayloadRule(("extra_body", "google", "thinking_config", "thinking_level"), "$mapped"),
        )
    return ()


def _render_value(template: JsonScalar, level: str, mapping: Mapping[str, JsonScalar]) -> JsonScalar:
    """Render one fixed template without expression evaluation."""
    if not isinstance(template, str) or not template.startswith("$"):
        return template
    if template == "$level":
        return level
    if template == "$mapped":
        if level not in mapping:
            raise ValueError(f"reasoning level has no provider mapping: {level}")
        return mapping[level]
    if template == "$enabled":
        return level != "none"
    if template == "$low_effort":
        return level in {"minimal", "low"}
    if template == "$int":
        value = mapping.get(level)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("$int requires an integer level mapping")
        return value
    raise ValueError(f"unsupported reasoning template: {template}")


def _any_complete_path(payload: Mapping[str, Any], paths: Sequence[tuple[str, ...]]) -> bool:
    """Return whether the caller owns any complete target path, including ``None``."""
    for path in paths:
        cursor: Any = payload
        for segment in path:
            if not isinstance(cursor, Mapping) or segment not in cursor:
                break
            cursor = cursor[segment]
        else:
            return True
    return False


def _set_nested_if_absent(target: MutableMapping[str, Any], path: tuple[str, ...], value: JsonScalar) -> None:
    """Set a nested value without overwriting caller-owned fields."""
    cursor: MutableMapping[str, Any] = target
    for segment in path[:-1]:
        current = cursor.get(segment)
        if current is None:
            child: dict[str, Any] = {}
            cursor[segment] = child
            cursor = child
        elif isinstance(current, MutableMapping):
            cursor = current
        else:
            raise ValueError(f"reasoning path conflicts with caller scalar: {segment}")
    cursor.setdefault(path[-1], value)



__all__ = [
    "apply_reasoning_payload",
    "extract_reasoning_tokens",
    "sum_usage_tokens",
    "_any_complete_path",
    "_normalize_endpoint",
    "_render_value",
    "_rules_for",
    "_set_nested_if_absent",
]
