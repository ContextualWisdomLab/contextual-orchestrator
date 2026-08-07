"""Validity contracts for strict locked-answer benchmark scoring."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contextual_orchestrator import nim_benchmark as nb


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TASK_MANIFEST_PATH = REPOSITORY_ROOT / "examples" / "nim_task_manifest.json"


def test_strict_numeric_scorer_requires_the_entire_answer() -> None:
    """Contradictory prose must not earn credit merely by containing the answer."""
    scorer_key = ("exact_number_match", "2")
    assert scorer_key in nb.SCORER_REGISTRY
    scorer = nb.SCORER_REGISTRY[scorer_key]

    assert scorer({"number": "21"}, "21") == 1.0
    assert scorer({"number": "21"}, "  21.0  ") == 1.0
    assert scorer({"number": "21"}, "The answer is 21.") == 0.0
    assert scorer({"number": "21"}, "not 21") == 0.0
    assert scorer({"number": "21"}, "21 22") == 0.0
    assert scorer({"number": "21"}, "NaN") == 0.0


def test_exact_text_scorer_rejects_substrings_and_negations() -> None:
    """A symbol or label must be the complete normalized response, not a substring."""
    scorer_key = ("exact_text_match", "1")
    assert scorer_key in nb.SCORER_REGISTRY
    scorer = nb.SCORER_REGISTRY[scorer_key]

    assert scorer({"texts": ["Au"]}, "  au  ") == 1.0
    assert scorer({"texts": ["Pacific", "Pacific Ocean"]}, "PACIFIC OCEAN") == 1.0
    assert scorer({"texts": ["caf\u00e9"]}, "cafe\u0301") == 1.0
    assert scorer({"texts": ["Au"]}, "Australia") == 0.0
    assert scorer({"texts": ["Au"]}, "not Au") == 0.0


def test_locked_manifest_uses_only_strict_complete_answer_scorers() -> None:
    """Headline evidence must not use containment-based scorer contracts."""
    manifest = nb.load_task_manifest(str(TASK_MANIFEST_PATH))
    locked_scorers = {
        (task["scorer"]["name"], task["scorer"]["version"])
        for task in nb.locked_evaluation_tasks(manifest)
    }

    assert locked_scorers == {
        ("exact_number_match", "2"),
        ("exact_text_match", "1"),
    }


@pytest.mark.parametrize(
    ("scorer", "expected", "message"),
    [
        (
            {"name": "exact_number_match", "version": "2"},
            {"number": "NaN"},
            "finite numeric literal",
        ),
        (
            {"name": "exact_text_match", "version": "1"},
            {"texts": "Au"},
            "non-empty texts list",
        ),
        (
            {"name": "exact_text_match", "version": "1"},
            {"texts": ["Au", " au "]},
            "duplicate normalized answer",
        ),
    ],
)
def test_manifest_rejects_invalid_strict_scorer_expectations(
    tmp_path: Path,
    scorer: dict[str, str],
    expected: dict[str, object],
    message: str,
) -> None:
    """Malformed strict-scorer evidence must fail before any provider egress."""
    manifest_path = tmp_path / "strict-scorer-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": "strict-scorer-test.1",
                "tasks": [
                    {
                        "task_id": "strict_answer_task",
                        "split": "locked",
                        "prompt": "Return the requested answer only.",
                        "scorer": scorer,
                        "expected": expected,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(nb.BenchmarkContractError, match=message):
        nb.load_task_manifest(str(manifest_path))
