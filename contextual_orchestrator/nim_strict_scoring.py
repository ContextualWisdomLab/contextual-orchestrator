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


STRICT_SCORING_POLICY_VERSION = "2026-08-07.4"
MAX_STRICT_ANSWER_CHARACTERS = 4096
_DEFAULT_TASK_MANIFEST = Path("examples/nim_task_manifest.json")
_STRICT_NUMBER_KEY = ("exact_number_match", "2")
_STRICT_TEXT_KEY = ("exact_text_match", "1")
_LEGACY_NUMBER_KEY = ("exact_number_match", "1")
_LEGACY_TEXT_KEY = ("substring_match", "1")
_ASCII_DECIMAL_LITERAL = re.compile(
    r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
)
_NUMERIC_PROMPT_TOKEN = re.compile(
    r"(?<![0-9A-Za-z_.])"
    r"([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)"
    r"(?![0-9A-Za-z_]|\.[0-9])"
)


def _require_expected_character_budget(value: str, label: str) -> None:
    """Reject an answer-key string that exceeds the strict-scoring input cap."""
    if len(value) > MAX_STRICT_ANSWER_CHARACTERS:
        raise benchmark.BenchmarkContractError(
            f"{label} exceeds the strict-scoring character budget"
        )


def _normalized_exact_text(value: str, *, case_sensitive: bool) -> str:
    """Return NFC text with normalized whitespace and the declared case policy."""
    normalized = unicodedata.normalize("NFC", value)
    compact = " ".join(normalized.split())
    return compact if case_sensitive else compact.casefold()


def _expected_decimal(expected: dict[str, Any]) -> decimal.Decimal:
    """Return one finite, reproducible expected numeric literal.

    Raises:
        benchmark.BenchmarkContractError: If ``expected.number`` is not one
            bounded finite ASCII decimal literal represented as a JSON string.
    """
    value = expected.get("number")
    if not isinstance(value, str):
        raise benchmark.BenchmarkContractError(
            "exact-number expected.number must be a finite numeric literal string"
        )
    _require_expected_character_budget(value, "exact-number expected.number")
    literal = unicodedata.normalize("NFC", value).strip()
    if _ASCII_DECIMAL_LITERAL.fullmatch(literal) is None:
        raise benchmark.BenchmarkContractError(
            "exact-number expected.number must be a finite numeric literal string"
        )
    try:
        return decimal.Decimal(literal)
    except decimal.InvalidOperation as exc:
        raise benchmark.BenchmarkContractError(
            "exact-number expected.number must be a finite numeric literal string"
        ) from exc


def _answer_decimal(answer_text: str) -> decimal.Decimal | None:
    """Parse one bounded complete numeric answer, returning ``None`` when unusable."""
    if len(answer_text) > MAX_STRICT_ANSWER_CHARACTERS:
        return None
    literal = unicodedata.normalize("NFC", answer_text).strip()
    if _ASCII_DECIMAL_LITERAL.fullmatch(literal) is None:
        return None
    try:
        return decimal.Decimal(literal)
    except decimal.InvalidOperation:
        return None


def score_exact_number_match_v2(
    expected: dict[str, Any],
    answer_text: str,
) -> float:
    """Score one full numeric response by exact finite decimal value.

    Containment is deliberately rejected: prose, negation, units, and multiple
    numbers cannot earn credit merely because they include the expected token.
    Oversized or unrepresentable model output scores zero instead of consuming
    unbounded normalization resources or aborting the benchmark.
    """
    expected_value = _expected_decimal(expected)
    answer_value = _answer_decimal(answer_text)
    return 1.0 if answer_value is not None and answer_value == expected_value else 0.0


def _text_case_sensitive(expected: dict[str, Any]) -> bool:
    """Return an explicit Boolean case policy, defaulting legacy text to folded."""
    value = expected.get("case_sensitive", False)
    if not isinstance(value, bool):
        raise benchmark.BenchmarkContractError(
            "exact-text expected.case_sensitive must be boolean"
        )
    return value


def _expected_texts(expected: dict[str, Any]) -> tuple[tuple[str, ...], bool]:
    """Return unique normalized alternatives and their declared case policy.

    Raises:
        benchmark.BenchmarkContractError: If alternatives or case policy are
            absent, malformed, empty, oversized, or duplicate after normalization.
    """
    values = expected.get("texts")
    if not isinstance(values, list) or not values:
        raise benchmark.BenchmarkContractError(
            "exact-text expected must contain a non-empty texts list"
        )
    case_sensitive = _text_case_sensitive(expected)
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise benchmark.BenchmarkContractError(
                "exact-text expected must contain a non-empty texts list of strings"
            )
        _require_expected_character_budget(value, "exact-text expected alias")
        candidate = _normalized_exact_text(
            value,
            case_sensitive=case_sensitive,
        )
        if not candidate:
            raise benchmark.BenchmarkContractError(
                "exact-text expected must contain a non-empty texts list of strings"
            )
        if candidate in normalized:
            raise benchmark.BenchmarkContractError(
                "exact-text expected contains a duplicate normalized answer"
            )
        normalized.append(candidate)
    return tuple(normalized), case_sensitive


def score_exact_text_match(expected: dict[str, Any], answer_text: str) -> float:
    """Score one bounded complete text response against explicit alternatives."""
    expected_values, case_sensitive = _expected_texts(expected)
    if len(answer_text) > MAX_STRICT_ANSWER_CHARACTERS:
        return 0.0
    answer_value = _normalized_exact_text(
        answer_text,
        case_sensitive=case_sensitive,
    )
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


def _legacy_text_expectation(expected: dict[str, Any]) -> dict[str, Any]:
    """Translate one legacy substring key into explicit strict text semantics."""
    substring = expected.get("substring")
    if not isinstance(substring, str) or not substring.strip():
        raise benchmark.BenchmarkContractError(
            "legacy locked substring expectation must be a non-empty string"
        )
    texts = expected.get("strict_texts", [substring])
    strict_expected = {
        "texts": texts,
        "case_sensitive": expected.get("strict_case_sensitive", False),
    }
    _expected_texts(strict_expected)
    return strict_expected


def _prompt_leaks_decimal(prompt: str, expected_value: decimal.Decimal) -> bool:
    """Return whether a complete prompt token equals the numeric answer key."""
    _require_expected_character_budget(prompt, "locked task prompt")
    for match in _NUMERIC_PROMPT_TOKEN.finditer(prompt):
        try:
            observed = decimal.Decimal(match.group(1))
        except decimal.InvalidOperation:
            continue
        if observed == expected_value:
            return True
    return False


def _prompt_leaks_text(prompt: str, expected: dict[str, Any]) -> bool:
    """Return whether a declared complete text alias appears in the prompt."""
    _require_expected_character_budget(prompt, "locked task prompt")
    expected_values, case_sensitive = _expected_texts(expected)
    normalized_prompt = _normalized_exact_text(
        prompt,
        case_sensitive=case_sensitive,
    )
    for expected_value in expected_values:
        prefix = r"(?<!\w)" if expected_value[0].isalnum() or expected_value[0] == "_" else ""
        suffix = r"(?!\w)" if expected_value[-1].isalnum() or expected_value[-1] == "_" else ""
        if re.search(f"{prefix}{re.escape(expected_value)}{suffix}", normalized_prompt):
            return True
    return False


def _strict_task_leaks_expected(task: dict[str, Any]) -> bool:
    """Return whether one strict locked task reveals any accepted answer token."""
    prompt = task.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise benchmark.BenchmarkContractError(
            "strict scoring requires a non-empty locked task prompt"
        )
    scorer = task["scorer"]
    expected = task["expected"]
    scorer_key = (str(scorer.get("name")), str(scorer.get("version")))
    if scorer_key == _STRICT_NUMBER_KEY:
        return _prompt_leaks_decimal(prompt, _expected_decimal(expected))
    if scorer_key == _STRICT_TEXT_KEY:
        return _prompt_leaks_text(prompt, expected)
    raise benchmark.BenchmarkContractError(
        f"locked task names unsupported strict scorer: {scorer_key}"
    )


def strict_task_manifest_payload(manifest: object) -> dict[str, Any]:
    """Derive a strict locked-split manifest while preserving exploratory tasks.

    Historical authoring manifests may use the legacy containment scorers. This
    function upgrades only locked tasks to versioned complete-answer scorers.
    Already-strict locked tasks are preserved. Unknown locked scorer contracts
    and prompt leakage fail closed before provider egress.

    Args:
        manifest: Parsed task-manifest JSON value.

    Returns:
        Deep-copied, strict, versioned manifest payload.

    Raises:
        benchmark.BenchmarkContractError: If the manifest or a locked scorer
            cannot be converted without ambiguity or leaks an accepted answer.
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
            _expected_decimal(expected)
            task["scorer"] = {
                "name": _STRICT_NUMBER_KEY[0],
                "version": _STRICT_NUMBER_KEY[1],
            }
        elif scorer_key == _LEGACY_TEXT_KEY:
            task["scorer"] = {
                "name": _STRICT_TEXT_KEY[0],
                "version": _STRICT_TEXT_KEY[1],
            }
            task["expected"] = _legacy_text_expectation(expected)
        elif scorer_key == _STRICT_NUMBER_KEY:
            _expected_decimal(expected)
        elif scorer_key == _STRICT_TEXT_KEY:
            _expected_texts(expected)
        else:
            raise benchmark.BenchmarkContractError(
                f"locked task names unsupported strict scorer: {scorer_key}"
            )
        if _strict_task_leaks_expected(task):
            raise benchmark.BenchmarkContractError(
                f"task {task.get('task_id')!r} leaks its expected answer into the prompt"
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
