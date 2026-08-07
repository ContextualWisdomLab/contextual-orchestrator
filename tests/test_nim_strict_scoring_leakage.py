"""No-leakage contracts for derived strict NIM benchmark manifests."""

from __future__ import annotations

import pytest

from contextual_orchestrator import nim_benchmark as nb
from contextual_orchestrator import nim_strict_scoring as strict


def _locked_manifest(
    *,
    prompt: str,
    scorer_name: str,
    expected: dict[str, object],
) -> dict[str, object]:
    """Build one minimal locked authoring manifest for leakage validation."""
    return {
        "manifest_version": "strict-leakage-test.1",
        "tasks": [
            {
                "task_id": "strict_leakage_task",
                "split": "locked",
                "prompt": prompt,
                "scorer": {"name": scorer_name, "version": "1"},
                "expected": expected,
            }
        ],
    }


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("Hint: the result is 21.0. Return a number only.", {"number": "21"}),
        ("Reject 0.050 and solve independently.", {"number": "0.05"}),
    ],
)
def test_strict_numeric_manifest_rejects_equivalent_answer_leakage(
    prompt: str,
    expected: dict[str, object],
) -> None:
    """Equivalent decimal literals embedded in prompts must fail before egress."""
    manifest = _locked_manifest(
        prompt=prompt,
        scorer_name="exact_number_match",
        expected=expected,
    )

    with pytest.raises(nb.BenchmarkContractError, match="leaks its expected answer"):
        strict.strict_task_manifest_payload(manifest)


def test_strict_numeric_leakage_uses_complete_numeric_tokens() -> None:
    """The answer 21 must not be inferred from the unrelated larger number 121."""
    manifest = _locked_manifest(
        prompt="Return the requested value, not 121.",
        scorer_name="exact_number_match",
        expected={"number": "21"},
    )

    derived = strict.strict_task_manifest_payload(manifest)
    assert derived["tasks"][0]["scorer"] == {
        "name": "exact_number_match",
        "version": "2",
    }


def test_strict_text_manifest_rejects_declared_alias_leakage() -> None:
    """Any declared complete-answer alias embedded in a prompt must be rejected."""
    manifest = _locked_manifest(
        prompt="Choose between the Atlantic and Pacific Ocean, then answer only.",
        scorer_name="substring_match",
        expected={
            "substring": "Pacific",
            "strict_texts": ["Pacific", "Pacific Ocean"],
        },
    )

    with pytest.raises(nb.BenchmarkContractError, match="leaks its expected answer"):
        strict.strict_task_manifest_payload(manifest)


def test_case_sensitive_text_leakage_preserves_declared_case() -> None:
    """A lower-case token is not the case-sensitive chemical-symbol answer key."""
    safe_manifest = _locked_manifest(
        prompt="The letters au appear in an unrelated lower-case label.",
        scorer_name="substring_match",
        expected={"substring": "Au", "strict_case_sensitive": True},
    )
    strict.strict_task_manifest_payload(safe_manifest)

    leaking_manifest = _locked_manifest(
        prompt="Do not simply copy Au from this instruction.",
        scorer_name="substring_match",
        expected={"substring": "Au", "strict_case_sensitive": True},
    )
    with pytest.raises(nb.BenchmarkContractError, match="leaks its expected answer"):
        strict.strict_task_manifest_payload(leaking_manifest)


def test_text_leakage_does_not_match_inside_a_larger_word() -> None:
    """The symbol Au must not be treated as leaked by the word Australia."""
    manifest = _locked_manifest(
        prompt="Australia is unrelated to the requested symbol.",
        scorer_name="substring_match",
        expected={"substring": "Au", "strict_case_sensitive": True},
    )

    derived = strict.strict_task_manifest_payload(manifest)
    assert derived["tasks"][0]["expected"] == {
        "texts": ["Au"],
        "case_sensitive": True,
    }
