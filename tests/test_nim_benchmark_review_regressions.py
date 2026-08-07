"""Regressions for exact-head NIM benchmark review findings.

These tests intentionally exercise the buyer-visible evidence and failure
boundaries called out by the current review. They remain fully offline and do
not read provider credentials.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from contextual_orchestrator import nim_benchmark as nb


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TASK_MANIFEST_PATH = REPOSITORY_ROOT / "examples" / "nim_task_manifest.json"
_MARKDOWN_REQUIRED_PATHS = (
    "evaluation.observed_paired_task_count",
    "evaluation.observed_completion_fraction",
    "honesty_labels.hypothetical_cost_source",
)


def _set_report_path(report: dict[str, Any], path: str, value: Any) -> None:
    """Populate one dotted report path for focused schema tests."""
    node = report
    keys = path.split(".")
    for key in keys[:-1]:
        child = node.setdefault(key, {})
        assert isinstance(child, dict)
        node = child
    node[keys[-1]] = value


def _delete_report_path(report: dict[str, Any], path: str) -> None:
    """Delete one dotted report path from a complete synthetic report."""
    node = report
    keys = path.split(".")
    for key in keys[:-1]:
        child = node[key]
        assert isinstance(child, dict)
        node = child
    del node[keys[-1]]


def _complete_schema_report() -> dict[str, Any]:
    """Return a synthetic report containing every declared and rendered path."""
    report: dict[str, Any] = {}
    for path in (*nb._REPORT_REQUIRED_PATHS, *_MARKDOWN_REQUIRED_PATHS):
        _set_report_path(report, path, None)
    return report


@pytest.mark.parametrize("missing_path", _MARKDOWN_REQUIRED_PATHS)
def test_report_schema_rejects_missing_markdown_input(missing_path: str) -> None:
    """Schema acceptance must guarantee that Markdown rendering cannot KeyError."""
    report = _complete_schema_report()
    _delete_report_path(report, missing_path)

    with pytest.raises(nb.BenchmarkContractError, match=re.escape(missing_path)):
        nb.validate_report_schema(report)


def test_pareto_frontiers_exclude_policies_without_successful_cells() -> None:
    """A failed policy must not appear efficient merely because its metrics are zero."""
    summaries = [
        {
            "policy_name": "failed_policy",
            "success_count": 0,
            "mean_task_score": 1.0,
            "mean_latency_ms": 0.0,
            "mean_hypothetical_cost_usd": 0.0,
        },
        {
            "policy_name": "valid_policy",
            "success_count": 3,
            "mean_task_score": 0.8,
            "mean_latency_ms": 10.0,
            "mean_hypothetical_cost_usd": 0.1,
        },
    ]

    frontiers = nb.build_pareto_frontiers(summaries)

    assert [row["policy_name"] for row in frontiers["quality_vs_latency"]] == [
        "valid_policy"
    ]
    assert [
        row["policy_name"]
        for row in frontiers["quality_vs_hypothetical_cost"]
    ] == ["valid_policy"]
    assert frontiers["excluded_zero_success_policies"] == ["failed_policy"]


def test_catalog_json_recursion_is_normalized_to_domain_error(monkeypatch) -> None:
    """Attacker-controlled JSON depth must not escape as a raw RecursionError."""

    def raise_recursion(_text: str) -> Any:
        raise RecursionError("catalog nesting exceeded interpreter depth")

    monkeypatch.setattr(nb.json, "loads", raise_recursion)

    with pytest.raises(nb.CatalogDiscoveryError, match="not valid JSON"):
        nb.parse_model_catalog_body(b'[{"nested": true}]')


def test_fuzz_target_does_not_ignore_raw_catalog_recursion() -> None:
    """The fuzz target must trust only the parser's normalized domain failure."""
    target_text = (REPOSITORY_ROOT / "fuzz" / "targets.py").read_text(
        encoding="utf-8"
    )
    catalog_target = target_text.split("def exercise_nim_catalog", 1)[1]
    assert "except RecursionError" not in catalog_target
    assert "plain json RecursionError" not in catalog_target


def test_deterministic_clock_seams_use_named_functions() -> None:
    """Keep dry-run clock seams lintable, documented, and free of E731 lambdas."""
    source = (
        REPOSITORY_ROOT / "contextual_orchestrator" / "nim_benchmark.py"
    ).read_text(encoding="utf-8")
    module = ast.parse(source)
    run_benchmark = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_benchmark"
    )
    lambda_names: set[str] = set()
    nested_function_names: set[str] = set()
    for node in ast.walk(run_benchmark):
        if isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Lambda):
            if isinstance(node.target, ast.Name):
                lambda_names.add(node.target.id)
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Lambda):
            lambda_names.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.FunctionDef) and node is not run_benchmark:
            nested_function_names.add(node.name)

    assert not ({"clock", "probe_timer"} & lambda_names)
    assert {"clock", "probe_timer"} <= nested_function_names


class _CapturedModelTimeout(RuntimeError):
    """Stop a live setup immediately after recording the model-client timeout."""


def test_live_benchmark_preserves_positive_subsecond_model_timeout(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """A valid 250ms operator timeout must not be truncated to zero seconds."""
    observed: dict[str, Any] = {}

    def capture_client(_request_budget: nb.RequestBudget, **kwargs: Any) -> Any:
        observed.update(kwargs)
        raise _CapturedModelTimeout

    monkeypatch.setattr(nb, "get_credential", lambda _name: "test-secret")
    monkeypatch.setattr(nb, "_BudgetedModelClient", capture_client)

    with pytest.raises(_CapturedModelTimeout):
        nb.run_benchmark(
            "live",
            str(TASK_MANIFEST_PATH),
            None,
            str(tmp_path),
            endpoint="https://nim.example.test/v1",
            timeout_seconds=0.25,
            git_sha="a" * 40,
            workflow_run_id="12345",
            transport=lambda *_args: (500, b"{}"),
        )

    assert observed["timeout"] == 0.25


def test_standalone_nim_test_runner_skips_fixture_callables() -> None:
    """The optional direct runner must execute only zero-argument test functions."""
    completed = subprocess.run(
        [sys.executable, "tests/test_nim_benchmark.py"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.rstrip().endswith("ok")
