"""Strict, explicitly activated scoring for evidence-grade NIM benchmarks.

The historical benchmark scorers remain available for compatibility with old
manifests and tests. The supported ``nim-benchmark`` composition root activates
this module and derives a temporary, versioned strict manifest before any
provider request. Ordinary ``import contextual_orchestrator`` remains free of
benchmark imports and global mutation.
"""

from __future__ import annotations

import copy
import decimal
import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Callable

from . import nim_benchmark as benchmark


STRICT_SCORING_POLICY_VERSION = "2026-08-07.1"
_DEFAULT_TASK_MANIFEST = Path("examples/nim_task_manifest.json")
_STRICT_NUMBER_KEY = ("exact_number_match", "2")
_STRICT_TEXT_KEY = ("exact_text_match", "1")
_LEGACY_NUMBER_KEY = ("exact_number_match", "1")
_LEGACY_TEXT_KEY = ("substring_match", "1")
_ASCII_DECIMAL_LITERAL = re.compile(
    r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
)


def _normalized_exact_text(value: str) -> str:
    """Return NFC, case-folded text with surrounding and repeated whitespace removed."""
    normalized = unicodedata.normalize("NFC", value)
    return " ".join(normalized.split()).casefold()


def _expected_decimal(expected: dict[str, Any]) -> decimal.Decimal:
    """Return one finite, reproducible expected numeric literal.

    Raises:
        benchmark.BenchmarkContractError: If ``expected.number`` is not one
            finite ASCII decimal literal represented as a JSON string.
    """
    value = expected.get("number")
    if not isinstance(value, str):
        raise benchmark.BenchmarkContractError(
            "exact-number expected.number must be a finite numeric literal string"
        )
    literal = unicodedata.normalize("NFC", value).strip()
    if _ASCII_DECIMAL_LITERAL.fullmatch(literal) is None:
        raise benchmark.BenchmarkContractError(
            "exact-number expected.number must be a finite numeric literal string"
        )
    return decimal.Decimal(literal)


def _answer_decimal(answer_text: str) -> decimal.Decimal | None:
    """Parse a complete finite numeric answer, returning ``None`` for other text."""
    literal = unicodedata.normalize("NFC", answer_text).strip()
    if _ASCII_DECIMAL_LITERAL.fullmatch(literal) is None:
        return None
    return decimal.Decimal(literal)


def score_exact_number_match_v2(
    expected: dict[str, Any],
    answer_text: str,
) -> float:
    """Score one full numeric response by exact finite decimal value.

    Containment is deliberately rejected: prose, negation, units, and multiple
    numbers cannot earn credit merely because they include the expected token.
    """
    expected_value = _expected_decimal(expected)
    answer_value = _answer_decimal(answer_text)
    return 1.0 if answer_value is not None and answer_value == expected_value else 0.0


def _expected_texts(expected: dict[str, Any]) -> tuple[str, ...]:
    """Return unique normalized exact-text alternatives from one expectation.

    Raises:
        benchmark.BenchmarkContractError: If the alternatives are absent,
            malformed, empty, or duplicate after normalization.
    """
    values = expected.get("texts")
    if not isinstance(values, list) or not values:
        raise benchmark.BenchmarkContractError(
            "exact-text expected must contain a non-empty texts list"
        )
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise benchmark.BenchmarkContractError(
                "exact-text expected must contain a non-empty texts list of strings"
            )
        candidate = _normalized_exact_text(value)
        if not candidate:
            raise benchmark.BenchmarkContractError(
                "exact-text expected must contain a non-empty texts list of strings"
            )
        if candidate in normalized:
            raise benchmark.BenchmarkContractError(
                "exact-text expected contains a duplicate normalized answer"
            )
        normalized.append(candidate)
    return tuple(normalized)


def score_exact_text_match(expected: dict[str, Any], answer_text: str) -> float:
    """Score one complete normalized text response against explicit alternatives."""
    expected_values = _expected_texts(expected)
    answer_value = _normalized_exact_text(answer_text)
    return 1.0 if answer_value in expected_values else 0.0


def enable_strict_evidence_scoring() -> None:
    """Idempotently register strict scorer versions at an explicit composition root.

    Raises:
        benchmark.BenchmarkContractError: If another implementation already
            owns either versioned scorer identity.
    """
    registrations: dict[
        tuple[str, str],
        Callable[[dict[str, Any], str], float],
    ] = {
        _STRICT_NUMBER_KEY: score_exact_number_match_v2,
        _STRICT_TEXT_KEY: score_exact_text_match,
    }
    for scorer_key, scorer_function in registrations.items():
        existing = benchmark.SCORER_REGISTRY.get(scorer_key)
        if existing is not None and existing is not scorer_function:
            raise benchmark.BenchmarkContractError(
                f"strict scorer identity collision: {scorer_key}"
            )
        benchmark.SCORER_REGISTRY[scorer_key] = scorer_function


def strict_task_manifest_payload(manifest: object) -> dict[str, Any]:
    """Derive a strict locked-split manifest while preserving exploratory tasks.

    Historical authoring manifests may use the legacy containment scorers. This
    function upgrades only locked tasks to versioned complete-answer scorers.
    Already-strict locked tasks are preserved. Unknown locked scorer contracts
    fail closed rather than being silently interpreted.

    Args:
        manifest: Parsed task-manifest JSON value.

    Returns:
        Deep-copied, strict, versioned manifest payload.

    Raises:
        benchmark.BenchmarkContractError: If the manifest or a locked scorer
            cannot be converted without ambiguity.
    """
    if not isinstance(manifest, dict):
        raise benchmark.BenchmarkContractError(
            "strict scoring requires a task manifest object"
        )
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list):
        raise benchmark.BenchmarkContractError(
            "strict scoring requires a task manifest tasks list"
        )
    strict_manifest = copy.deepcopy(manifest)
    strict_tasks = strict_manifest["tasks"]
    for task in strict_tasks:
        if not isinstance(task, dict):
            raise benchmark.BenchmarkContractError(
                "strict scoring requires every task to be an object"
            )
        if task.get("split") != "locked":
            continue
        scorer = task.get("scorer")
        expected = task.get("expected")
        if not isinstance(scorer, dict) or not isinstance(expected, dict):
            raise benchmark.BenchmarkContractError(
                "strict scoring requires locked scorer and expected objects"
            )
        scorer_key = (str(scorer.get("name")), str(scorer.get("version")))
        if scorer_key == _LEGACY_NUMBER_KEY:
            task["scorer"] = {
                "name": _STRICT_NUMBER_KEY[0],
                "version": _STRICT_NUMBER_KEY[1],
            }
        elif scorer_key == _LEGACY_TEXT_KEY:
            substring = expected.get("substring")
            if not isinstance(substring, str) or not substring.strip():
                raise benchmark.BenchmarkContractError(
                    "legacy locked substring expectation must be a non-empty string"
                )
            task["scorer"] = {
                "name": _STRICT_TEXT_KEY[0],
                "version": _STRICT_TEXT_KEY[1],
            }
            task["expected"] = {"texts": [substring]}
        elif scorer_key not in {_STRICT_NUMBER_KEY, _STRICT_TEXT_KEY}:
            raise benchmark.BenchmarkContractError(
                f"locked task names unsupported strict scorer: {scorer_key}"
            )
    source_version = strict_manifest.get("manifest_version")
    if not isinstance(source_version, str) or not source_version:
        raise benchmark.BenchmarkContractError(
            "strict scoring requires a non-empty manifest_version"
        )
    strict_manifest["manifest_version"] = (
        f"{source_version}+strict.{STRICT_SCORING_POLICY_VERSION}"
    )
    strict_manifest["scoring_policy_version"] = STRICT_SCORING_POLICY_VERSION
    return strict_manifest


def _task_manifest_argument(argv: list[str]) -> tuple[Path, list[str]]:
    """Return the source manifest path and arguments without its selector."""
    source_path = _DEFAULT_TASK_MANIFEST
    remaining: list[str] = []
    found = False
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--task-manifest":
            if found or index + 1 >= len(argv):
                raise benchmark.BenchmarkContractError(
                    "--task-manifest must be supplied exactly once with a value"
                )
            source_path = Path(argv[index + 1])
            found = True
            index += 2
            continue
        if argument.startswith("--task-manifest="):
            if found:
                raise benchmark.BenchmarkContractError(
                    "--task-manifest may be supplied only once"
                )
            value = argument.split("=", 1)[1]
            if not value:
                raise benchmark.BenchmarkContractError(
                    "--task-manifest requires a non-empty value"
                )
            source_path = Path(value)
            found = True
            index += 1
            continue
        remaining.append(argument)
        index += 1
    return source_path, remaining


def _write_strict_manifest(source_path: Path, destination_path: Path) -> None:
    """Validate, transform, and privately write one deterministic strict manifest."""
    try:
        source_payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise benchmark.BenchmarkContractError(
            "strict scoring could not read a valid task manifest"
        ) from exc
    strict_payload = strict_task_manifest_payload(source_payload)
    serialized = json.dumps(
        strict_payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    file_descriptor = os.open(
        destination_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(serialized)


def run_strict_benchmark_cli(
    argv: list[str],
    *,
    benchmark_cli: Callable[[list[str]], int] = benchmark.run_benchmark_cli,
) -> int:
    """Run the benchmark CLI with a private strict locked-task manifest.

    The scorer registry is activated explicitly, the selected source manifest
    is converted before provider egress, and the derived manifest is deleted
    when the one-shot CLI call ends. Its deterministic contents remain bound to
    the artifact through the existing manifest SHA-256 and version provenance.
    """
    enable_strict_evidence_scoring()
    source_path, remaining_argv = _task_manifest_argument(argv)
    with tempfile.TemporaryDirectory(prefix="nim-strict-scoring-") as directory:
        strict_path = Path(directory) / "task_manifest.strict.json"
        _write_strict_manifest(source_path, strict_path)
        return benchmark_cli(
            [*remaining_argv, "--task-manifest", str(strict_path)]
        )
