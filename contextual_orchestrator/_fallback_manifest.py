"""Strict versioned manifest parsing for shared model fallback policy."""

from __future__ import annotations

from typing import Any, Mapping

from ._fallback_plan import validate_candidate_collection
from ._fallback_types import (
    AGENT_NAME_RE,
    ALLOWED_VISIBILITIES,
    SCHEMA_VERSION,
    CandidateValidationError,
    CostTier,
    FallbackCandidate,
    FallbackManifestError,
    joined,
)

_MANIFEST_KEYS = frozenset({"schema_version", "agents"})
_AGENT_KEYS = frozenset({"candidates"})
_CANDIDATE_KEYS = frozenset(
    {
        "candidate_id",
        "provider",
        "model",
        "cost_tier",
        "priority",
        "required_credentials",
        "repository_visibilities",
        "capabilities",
    }
)


def load_fallback_manifest(
    document: Mapping[str, Any], agent: str
) -> tuple[FallbackCandidate, ...]:
    """Parse one agent's candidate list from a strict manifest."""
    if not isinstance(document, Mapping):
        raise FallbackManifestError("manifest must be an object")
    unknown_manifest_keys = set(document) - _MANIFEST_KEYS
    if unknown_manifest_keys:
        raise FallbackManifestError(
            f"unknown manifest keys: {joined(unknown_manifest_keys)}"
        )
    schema_version = document.get("schema_version")
    if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
        raise FallbackManifestError(
            f"schema_version must be {SCHEMA_VERSION}"
        )
    agents = document.get("agents")
    if not isinstance(agents, Mapping):
        raise FallbackManifestError("agents must be an object")
    for agent_name in agents:
        if not isinstance(agent_name, str) or not AGENT_NAME_RE.fullmatch(
            agent_name
        ):
            raise FallbackManifestError(
                "agent name must be a safe identifier"
            )
    if not isinstance(agent, str) or not AGENT_NAME_RE.fullmatch(agent):
        raise FallbackManifestError(
            "agent selector must be a safe identifier"
        )
    if agent not in agents:
        raise FallbackManifestError(
            f"agent {agent!r} was not found in manifest"
        )
    agent_document = agents[agent]
    if not isinstance(agent_document, Mapping):
        raise FallbackManifestError(
            f"agent {agent!r} must be an object"
        )
    unknown_agent_keys = set(agent_document) - _AGENT_KEYS
    if unknown_agent_keys:
        raise FallbackManifestError(
            f"unknown agent keys: {joined(unknown_agent_keys)}"
        )
    raw_candidates = agent_document.get("candidates")
    if not isinstance(raw_candidates, list):
        raise FallbackManifestError("candidates must be an array")
    if not raw_candidates:
        raise FallbackManifestError(
            "agent must declare at least one candidate"
        )

    parsed: list[FallbackCandidate] = []
    for raw_candidate in raw_candidates:
        if not isinstance(raw_candidate, Mapping):
            raise FallbackManifestError("candidate must be an object")
        parsed.append(_parse_candidate(raw_candidate))
    try:
        validate_candidate_collection(tuple(parsed))
    except CandidateValidationError as exc:
        raise FallbackManifestError(str(exc)) from exc
    return tuple(parsed)


def _parse_candidate(
    raw_candidate: Mapping[str, Any]
) -> FallbackCandidate:
    """Parse one strict candidate object into an immutable value object."""
    unknown_candidate_keys = set(raw_candidate) - _CANDIDATE_KEYS
    if unknown_candidate_keys:
        raise FallbackManifestError(
            f"unknown candidate keys: {joined(unknown_candidate_keys)}"
        )
    required_keys = {"candidate_id", "provider", "model", "cost_tier"}
    missing_keys = required_keys - set(raw_candidate)
    if missing_keys:
        raise FallbackManifestError(
            f"missing candidate keys: {joined(missing_keys)}"
        )
    try:
        cost_tier = CostTier(raw_candidate["cost_tier"])
    except (TypeError, ValueError) as exc:
        raise FallbackManifestError(
            "cost_tier must be free or paid"
        ) from exc
    required_credentials = _string_sequence(
        raw_candidate.get("required_credentials", []),
        "required_credentials",
    )
    visibilities = frozenset(
        _string_sequence(
            raw_candidate.get(
                "repository_visibilities",
                sorted(ALLOWED_VISIBILITIES),
            ),
            "repository_visibilities",
        )
    )
    capabilities = frozenset(
        _string_sequence(
            raw_candidate.get("capabilities", ["text"]),
            "capabilities",
        )
    )
    try:
        return FallbackCandidate(
            candidate_id=raw_candidate["candidate_id"],
            provider=raw_candidate["provider"],
            model=raw_candidate["model"],
            cost_tier=cost_tier,
            priority=raw_candidate.get("priority", 100),
            required_credentials=tuple(required_credentials),
            repository_visibilities=visibilities,
            capabilities=capabilities,
        )
    except CandidateValidationError as exc:
        raise FallbackManifestError(str(exc)) from exc


def _string_sequence(value: Any, field_name: str) -> tuple[str, ...]:
    """Return strings from a JSON array, rejecting scalar strings."""
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise FallbackManifestError(
            f"{field_name} must be an array of strings"
        )
    return tuple(value)
