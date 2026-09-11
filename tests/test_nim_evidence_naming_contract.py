"""Naming-contract regressions for the NIM evidence publication boundary."""

from __future__ import annotations

import inspect

import contextual_orchestrator.nim_evidence as nim_evidence


def test_publication_residue_helper_uses_semantic_owned_identifiers() -> None:
    """Require bounded-context names without rejecting external/vendor contracts."""
    helper = getattr(nim_evidence, "_publication_residue_paths")
    assert not hasattr(nim_evidence, "_residue")
    assert tuple(inspect.signature(helper).parameters) == (
        "final_directory",
        "residue_kind",
    )
