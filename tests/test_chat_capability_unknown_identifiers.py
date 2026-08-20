"""Regressions for conservative treatment of unknown model identifiers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.chat_capability import (  # noqa: E402
    is_chat_compatible_model_id,
    is_general_chat_agent_model_id,
)


@pytest.mark.parametrize(
    "model_id",
    [
        "vendor/vanguard-7b",
        "vendor/vanguard-instruct",
    ],
)
def test_unknown_names_that_merely_end_with_guard_remain_eligible(model_id: str) -> None:
    """Do not fabricate a policy-classifier capability from an unrelated word suffix."""
    assert is_chat_compatible_model_id(model_id)
    assert is_general_chat_agent_model_id(model_id)


@pytest.mark.parametrize(
    "model_id",
    [
        "meta-llama/llama-guard-4-12b",
        "nvidia/llama-3.1-nemotron-safety-guard-8b-v3",
        "nvidia/llama-3.1-nemoguard-8b-topic-control",
    ],
)
def test_explicit_policy_classifier_markers_remain_role_ineligible(model_id: str) -> None:
    """Keep exact guard, safety, and NemoGuard markers out of general synthesis roles."""
    assert is_chat_compatible_model_id(model_id)
    assert not is_general_chat_agent_model_id(model_id)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
