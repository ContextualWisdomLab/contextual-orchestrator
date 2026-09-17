"""Shared naming conventions for governance-owned API resources."""

from __future__ import annotations

import re

TWO_WORD_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9]*_[a-z0-9]+(?:_[a-z0-9]+)*$")
_LEGACY_DISCOVERED_MODEL_SLUG = re.compile(r"[^a-z0-9]+")


def is_two_word_snake_case(value: str) -> bool:
    """Return whether a value follows the repository's resource-name convention."""
    return bool(TWO_WORD_SNAKE_CASE.fullmatch(value))


def require_object_name(value: str, field_name: str) -> None:
    """Raise a validation error when an object name is not compliant."""
    if not is_two_word_snake_case(value):  # pragma: no cover
        raise ValueError(f"{field_name} must be two or more words in snake_case: {value!r}")


def legacy_discovered_agent_id(provider_name: str, model_id: str) -> str:
    """Reproduce the exact pre-fingerprint discovered-agent identifier."""
    model_slug = _LEGACY_DISCOVERED_MODEL_SLUG.sub("_", model_id.lower()).strip("_")
    return f"{provider_name}_{model_slug or 'model'}"
