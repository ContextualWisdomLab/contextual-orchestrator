"""Validity contracts for strict locked-answer benchmark scoring."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from contextual_orchestrator import nim_benchmark as nb
from contextual_orchestrator import nim_strict_scoring as strict


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TASK_MANIFEST_PATH = REPOSITORY_ROOT / "examples" / "nim_task_manifest.json"


def _source_manifest() -> dict[str, Any]:
    """Load the reviewed authoring manifest without changing its source file."""
    return json.loads(TASK_MANIFEST_PATH.read_text(encoding="utf-8"))


def test_strict_numeric_scorer_requires_the_entire_answer() -> None:
    """Contradictory prose must not earn credit merely by containing the answer."""
    strict.enable_strict_evidence_scoring()
    scorer = nb.SCORER_REGISTRY[("exact_number_match", "2")]

    assert scorer({"number": "21"}, "21") == 1.0
    assert scorer({"number": "21"}, "  21.0  ") == 1.0
    assert scorer({"number": "0.05"}, ".05") == 1.0
    assert scorer({"number": "21"}, "The answer is 21.") == 0.0
    assert scorer({"number": "21"}, "not 21") == 0.0
    assert scorer({"number": "21"}, "21 22") == 0.0
    assert scorer({"number": "21"}, "NaN") == 0.0


@pytest.mark.parametrize("expected", [{}, {"number": 21}, {"number": "NaN"}])
def test_strict_numeric_scorer_rejects_invalid_expected_literals(
    expected: dict[str, object],
) -> None:
    """Invalid numeric answer keys must fail manifest validation, not score zero."""
    with pytest.raises(nb.BenchmarkContractError, match="finite numeric literal"):
        strict.score_exact_number_match_v2(expected, "21")


def test_exact_text_scorer_rejects_substrings_and_negations() -> None:
    """A symbol or label must be the complete normalized response, not a substring."""
    strict.enable_strict_evidence_scoring()
    scorer = nb.SCORER_REGISTRY[("exact_text_match", "1")]

    assert scorer({"texts": ["Au"]}, "  au  ") == 1.0
    assert scorer({"texts": ["Pacific", "Pacific Ocean"]}, "PACIFIC   OCEAN") == 1.0
    assert scorer({"texts": ["caf\u00e9"]}, "cafe\u0301") == 1.0
    assert scorer({"texts": ["Au"]}, "Australia") == 0.0
    assert scorer({"texts": ["Au"]}, "not Au") == 0.0


@pytest.mark.parametrize(
    ("expected", "message"),
    [
        ({}, "non-empty texts list"),
        ({"texts": "Au"}, "non-empty texts list"),
        ({"texts": [7]}, "list of strings"),
        ({"texts": ["   "]}, "list of strings"),
        ({"texts": ["Au", " au "]}, "duplicate normalized answer"),
    ],
)
def test_exact_text_scorer_rejects_invalid_answer_keys(
    expected: dict[str, object],
    message: str,
) -> None:
    """Malformed text alternatives must never silently create scoring evidence."""
    with pytest.raises(nb.BenchmarkContractError, match=message):
        strict.score_exact_text_match(expected, "Au")


def test_activation_is_idempotent_and_fails_closed_on_identity_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Versioned scorer ownership may be repeated but never silently replaced."""
    strict.enable_strict_evidence_scoring()
    strict.enable_strict_evidence_scoring()
    assert nb.SCORER_REGISTRY[("exact_number_match", "2")] is strict.score_exact_number_match_v2

    monkeypatch.setitem(
        nb.SCORER_REGISTRY,
        ("exact_number_match", "2"),
        lambda _expected, _answer: 0.0,
    )
    with pytest.raises(nb.BenchmarkContractError, match="identity collision"):
        strict.enable_strict_evidence_scoring()


def test_strict_manifest_derivation_upgrades_only_locked_tasks() -> None:
    """Headline evidence uses strict versions while exploratory tuning stays legacy."""
    strict.enable_strict_evidence_scoring()
    source = _source_manifest()
    derived = strict.strict_task_manifest_payload(source)

    assert derived is not source
    assert derived["scoring_policy_version"] == strict.STRICT_SCORING_POLICY_VERSION
    assert derived["manifest_version"].endswith(
        "+strict." + strict.STRICT_SCORING_POLICY_VERSION
    )
    assert source["tasks"][0]["scorer"]["version"] == "1"

    locked = nb.locked_evaluation_tasks(derived)
    locked_scorers = {
        (task["scorer"]["name"], task["scorer"]["version"])
        for task in locked
    }
    assert locked_scorers == {
        ("exact_number_match", "2"),
        ("exact_text_match", "1"),
    }
    exploratory = [task for task in derived["tasks"] if task["split"] == "exploratory"]
    assert {
        (task["scorer"]["name"], task["scorer"]["version"])
        for task in exploratory
    } == {("substring_match", "1")}
    assert derived["tasks"][6]["expected"] == {"texts": ["Paris"]}

    validated = nb.load_task_manifest_from_payload(derived)
    assert len(nb.locked_evaluation_tasks(validated)) == 30


def test_strict_manifest_preserves_already_strict_locked_tasks() -> None:
    """A caller-supplied strict manifest must remain semantically unchanged."""
    source = {
        "manifest_version": "strict-source.1",
        "tasks": [
            {
                "task_id": "strict_number_task",
                "split": "locked",
                "prompt": "Return one number only.",
                "scorer": {"name": "exact_number_match", "version": "2"},
                "expected": {"number": "7"},
            },
            {
                "task_id": "strict_text_task",
                "split": "locked",
                "prompt": "Return one word only.",
                "scorer": {"name": "exact_text_match", "version": "1"},
                "expected": {"texts": ["answer"]},
            },
        ],
    }

    derived = strict.strict_task_manifest_payload(source)
    assert derived["tasks"] == source["tasks"]


@pytest.mark.parametrize(
    ("manifest", "message"),
    [
        ([], "manifest object"),
        ({"manifest_version": "1", "tasks": "bad"}, "tasks list"),
        ({"manifest_version": "1", "tasks": ["bad"]}, "every task"),
        (
            {
                "manifest_version": "1",
                "tasks": [
                    {
                        "task_id": "bad_locked_task",
                        "split": "locked",
                        "scorer": "bad",
                        "expected": {},
                    }
                ],
            },
            "scorer and expected objects",
        ),
        (
            {
                "manifest_version": "1",
                "tasks": [
                    {
                        "task_id": "bad_text_task",
                        "split": "locked",
                        "scorer": {"name": "substring_match", "version": "1"},
                        "expected": {"substring": ""},
                    }
                ],
            },
            "non-empty string",
        ),
        (
            {
                "manifest_version": "1",
                "tasks": [
                    {
                        "task_id": "unknown_scorer_task",
                        "split": "locked",
                        "scorer": {"name": "rubric_match", "version": "9"},
                        "expected": {"rubric": "x"},
                    }
                ],
            },
            "unsupported strict scorer",
        ),
        ({"manifest_version": "", "tasks": []}, "manifest_version"),
    ],
)
def test_strict_manifest_rejects_ambiguous_authoring_contracts(
    manifest: object,
    message: str,
) -> None:
    """Unconvertible authoring contracts must fail before benchmark egress."""
    with pytest.raises(nb.BenchmarkContractError, match=message):
        strict.strict_task_manifest_payload(manifest)


def test_task_manifest_argument_supports_default_split_and_equals_forms() -> None:
    """CLI rewriting preserves unrelated arguments and accepts both path forms."""
    source_path, remaining = strict._task_manifest_argument(["--dry-run"])
    assert source_path == Path("examples/nim_task_manifest.json")
    assert remaining == ["--dry-run"]

    source_path, remaining = strict._task_manifest_argument(
        ["--dry-run", "--task-manifest", "custom.json", "--seed", "9"]
    )
    assert source_path == Path("custom.json")
    assert remaining == ["--dry-run", "--seed", "9"]

    source_path, remaining = strict._task_manifest_argument(
        ["--task-manifest=equals.json"]
    )
    assert source_path == Path("equals.json")
    assert remaining == []


@pytest.mark.parametrize(
    "argv",
    [
        ["--task-manifest"],
        ["--task-manifest", "one.json", "--task-manifest", "two.json"],
        ["--task-manifest=one.json", "--task-manifest=two.json"],
        ["--task-manifest="],
    ],
)
def test_task_manifest_argument_rejects_missing_or_duplicate_values(
    argv: list[str],
) -> None:
    """Ambiguous task-manifest selectors must fail before reading any provider key."""
    with pytest.raises(nb.BenchmarkContractError, match="task-manifest"):
        strict._task_manifest_argument(argv)


def test_strict_manifest_writer_rejects_invalid_source_and_uses_private_mode(
    tmp_path: Path,
) -> None:
    """The derived evidence manifest is deterministic, valid, and owner-readable."""
    invalid_source = tmp_path / "invalid.json"
    invalid_source.write_text("{broken", encoding="utf-8")
    with pytest.raises(nb.BenchmarkContractError, match="valid task manifest"):
        strict._write_strict_manifest(invalid_source, tmp_path / "unused.json")

    source = tmp_path / "source.json"
    source.write_text(json.dumps(_source_manifest()), encoding="utf-8")
    destination = tmp_path / "strict.json"
    strict._write_strict_manifest(source, destination)
    assert destination.stat().st_mode & 0o777 == 0o600
    derived = json.loads(destination.read_text(encoding="utf-8"))
    assert derived["scoring_policy_version"] == strict.STRICT_SCORING_POLICY_VERSION

    with pytest.raises(FileExistsError):
        strict._write_strict_manifest(source, destination)


def test_strict_cli_wrapper_passes_only_the_derived_manifest(
    tmp_path: Path,
) -> None:
    """The supported CLI runs with strict provenance and removes the private file."""
    source = tmp_path / "source.json"
    source.write_text(json.dumps(_source_manifest()), encoding="utf-8")
    observed: dict[str, object] = {}

    def benchmark_cli(argv: list[str]) -> int:
        observed["argv"] = list(argv)
        manifest_index = argv.index("--task-manifest") + 1
        manifest_path = Path(argv[manifest_index])
        observed["manifest_path"] = manifest_path
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        observed["policy_version"] = payload["scoring_policy_version"]
        observed["locked_scorers"] = {
            (task["scorer"]["name"], task["scorer"]["version"])
            for task in payload["tasks"]
            if task["split"] == "locked"
        }
        return 17

    result = strict.run_strict_benchmark_cli(
        ["--dry-run", "--task-manifest", str(source), "--seed", "3"],
        benchmark_cli=benchmark_cli,
    )

    assert result == 17
    assert observed["policy_version"] == strict.STRICT_SCORING_POLICY_VERSION
    assert observed["locked_scorers"] == {
        ("exact_number_match", "2"),
        ("exact_text_match", "1"),
    }
    assert observed["argv"][0:3] == ["--dry-run", "--seed", "3"]
    manifest_path = observed["manifest_path"]
    assert isinstance(manifest_path, Path)
    assert not manifest_path.exists()
