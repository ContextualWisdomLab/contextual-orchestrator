"""Tests for strict fallback policy manifest parsing."""

from __future__ import annotations

import pytest

from contextual_orchestrator.model_fallback import (
    FallbackManifestError,
    load_fallback_manifest,
)
from tests.fallback_test_support import manifest_document


def test_manifest_parses_candidates_without_reordering_source() -> None:
    """Manifest parsing preserves trusted declaration order."""
    candidates = load_fallback_manifest(manifest_document(), "noema")
    assert tuple(candidate.candidate_id for candidate in candidates) == (
        "paid-primary",
        "free-primary",
    )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda document: document.update({"unknown": True}), "unknown manifest"),
        (lambda document: document.update({"schema_version": 2}), "schema_version"),
        (lambda document: document.update({"schema_version": True}), "schema_version"),
        (lambda document: document.update({"schema_version": 1.0}), "schema_version"),
        (lambda document: document.update({"agents": []}), "agents must be"),
        (
            lambda document: document.update({"agents": {"bad agent": {}}}),
            "agent name",
        ),
    ],
)
def test_manifest_rejects_invalid_root_control_data(mutator, message: str) -> None:
    """Versioned root keys and agent identifiers fail closed."""
    document = manifest_document()
    mutator(document)
    with pytest.raises(FallbackManifestError, match=message):
        load_fallback_manifest(document, "noema")


def test_manifest_rejects_non_object_root_and_missing_agent() -> None:
    """Programmatic inputs cannot bypass root and agent shape checks."""
    with pytest.raises(FallbackManifestError, match="manifest must be an object"):
        load_fallback_manifest([], "noema")  # type: ignore[arg-type]
    with pytest.raises(FallbackManifestError, match="was not found"):
        load_fallback_manifest(manifest_document(), "strix")


@pytest.mark.parametrize("agent", [7, [], "bad agent"])
def test_manifest_rejects_invalid_agent_selector(agent: object) -> None:
    """An unsafe programmatic selector must not reach mapping membership logic."""
    with pytest.raises(FallbackManifestError, match="agent selector"):
        load_fallback_manifest(
            manifest_document(), agent  # type: ignore[arg-type]
        )


def test_manifest_rejects_invalid_agent_container_and_keys() -> None:
    """Agent blocks accept only a non-empty candidate array."""
    document = manifest_document()
    document["agents"]["noema"] = []
    with pytest.raises(FallbackManifestError, match="must be an object"):
        load_fallback_manifest(document, "noema")

    document = manifest_document()
    document["agents"]["noema"]["unknown"] = True
    with pytest.raises(FallbackManifestError, match="unknown agent keys"):
        load_fallback_manifest(document, "noema")

    document = manifest_document()
    document["agents"]["noema"]["candidates"] = {}
    with pytest.raises(FallbackManifestError, match="must be an array"):
        load_fallback_manifest(document, "noema")

    document = manifest_document()
    document["agents"]["noema"]["candidates"] = []
    with pytest.raises(FallbackManifestError, match="at least one"):
        load_fallback_manifest(document, "noema")


def test_manifest_rejects_non_object_candidate_and_unknown_keys() -> None:
    """Candidate entries use an exact schema."""
    document = manifest_document()
    document["agents"]["noema"]["candidates"][0] = []
    with pytest.raises(FallbackManifestError, match="candidate must be an object"):
        load_fallback_manifest(document, "noema")

    document = manifest_document()
    document["agents"]["noema"]["candidates"][0]["unknown"] = True
    with pytest.raises(FallbackManifestError, match="unknown candidate keys"):
        load_fallback_manifest(document, "noema")


@pytest.mark.parametrize(
    ("field_name", "field_value", "message"),
    [
        ("candidate_id", 7, "candidate_id"),
        ("provider", None, "provider"),
        ("model", ["model"], "model"),
    ],
)
def test_manifest_normalizes_non_string_candidate_identifiers(
    field_name: str,
    field_value: object,
    message: str,
) -> None:
    """Wrong JSON scalar types must remain controlled manifest failures."""
    document = manifest_document()
    document["agents"]["noema"]["candidates"][0][field_name] = field_value
    with pytest.raises(FallbackManifestError, match=message):
        load_fallback_manifest(document, "noema")


def test_manifest_rejects_missing_keys_bad_tier_and_bad_sequences() -> None:
    """Candidate schema failures are normalized as manifest errors."""
    document = manifest_document()
    del document["agents"]["noema"]["candidates"][0]["model"]
    with pytest.raises(FallbackManifestError, match="missing candidate keys: model"):
        load_fallback_manifest(document, "noema")

    document = manifest_document()
    document["agents"]["noema"]["candidates"][0]["cost_tier"] = "metered"
    with pytest.raises(FallbackManifestError, match="free or paid"):
        load_fallback_manifest(document, "noema")

    for field in (
        "required_credentials",
        "repository_visibilities",
        "capabilities",
    ):
        document = manifest_document()
        document["agents"]["noema"]["candidates"][0][field] = "not-array"
        with pytest.raises(FallbackManifestError, match=f"{field} must be"):
            load_fallback_manifest(document, "noema")


def test_manifest_normalizes_candidate_validation_and_duplicates() -> None:
    """Unsafe fields and duplicate identities remain manifest errors."""
    document = manifest_document()
    document["agents"]["noema"]["candidates"][0]["provider"] = "Bad/Provider"
    with pytest.raises(FallbackManifestError, match="provider"):
        load_fallback_manifest(document, "noema")

    document = manifest_document()
    document["agents"]["noema"]["candidates"][1]["candidate_id"] = "paid-primary"
    with pytest.raises(FallbackManifestError, match="duplicate candidate_id"):
        load_fallback_manifest(document, "noema")
