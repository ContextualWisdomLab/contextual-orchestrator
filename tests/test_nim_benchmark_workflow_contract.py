"""Static least-privilege contracts for scheduled NIM benchmark automation."""

from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _ordered_step_blocks(
    workflow: str,
    first_step_name: str,
    second_step_name: str,
) -> tuple[str, str]:
    """Return non-empty ordered workflow slices for two named steps.

    Raises:
        AssertionError: If either step is absent, reversed, or has an empty
            structural slice.
    """
    first_marker = f"- name: {first_step_name}"
    second_marker = f"- name: {second_step_name}"
    first_start = workflow.index(first_marker)
    second_start = workflow.index(second_marker)
    assert first_start < second_start, (
        f"{first_step_name!r} must precede {second_step_name!r}"
    )
    first_block = workflow[first_start:second_start]
    second_block = workflow[second_start:]
    assert first_block.strip(), f"{first_step_name!r} block must not be empty"
    assert second_block.strip(), f"{second_step_name!r} block must not be empty"
    return first_block, second_block


def test_dry_run_workflow_never_receives_live_nvidia_secret() -> None:
    """The zero-egress dry path must have no NVIDIA credential in its environment."""
    workflow = (REPOSITORY_ROOT / ".github/workflows/nim-benchmark.yml").read_text(
        encoding="utf-8"
    )
    dry_block, live_block = _ordered_step_blocks(
        workflow,
        "Run dry benchmark",
        "Run live benchmark",
    )

    assert "NVIDIA_NIM_API_KEY" not in dry_block
    assert live_block.count("NVIDIA_NIM_API_KEY:") == 1
    assert "secrets.NVIDIA_NIM_API_KEY" in live_block


def test_dry_run_workflow_honors_optional_pricing_scenario_without_secret() -> None:
    """Manual dry runs may validate an explicit scenario without live credentials."""
    workflow = (REPOSITORY_ROOT / ".github/workflows/nim-benchmark.yml").read_text(
        encoding="utf-8"
    )
    dry_block, _ = _ordered_step_blocks(
        workflow,
        "Run dry benchmark",
        "Run live benchmark",
    )

    assert "PRICING_SCENARIO: ${{ inputs.pricing_scenario }}" in dry_block
    assert 'extra_args+=(--pricing-scenario "$PRICING_SCENARIO")' in dry_block
    assert '"${extra_args[@]}"' in dry_block


def test_temporary_review_export_job_is_absent_from_mergeable_tests_workflow() -> None:
    """Mergeable CI must not retain the one-use exact-head export mechanism."""
    workflow = (REPOSITORY_ROOT / ".github/workflows/tests.yml").read_text(
        encoding="utf-8"
    )
    assert "export_review_workspace" not in workflow
    assert "Recover reviewed transformation source as inert evidence" not in workflow


def test_temporary_review_evidence_source_is_absent() -> None:
    """Mergeable source must not retain any one-use transformation payload."""
    assert not (REPOSITORY_ROOT / ".review-evidence/nim-source-repair.yml").exists()
    assert not (
        REPOSITORY_ROOT / ".github/workflows/export-pr90-workspace.yml"
    ).exists()


def test_compatibility_monkeypatch_module_is_absent() -> None:
    """Security and budget behavior must live directly in the optional benchmark."""
    assert not (
        REPOSITORY_ROOT / "contextual_orchestrator/nim_benchmark_hardening.py"
    ).exists()
    assert not (REPOSITORY_ROOT / "tests/test_nim_benchmark_hardening.py").exists()


def test_tests_workflow_enforces_nim_coverage_docstrings_and_package_smoke() -> None:
    """The exact PR head must prove 100% branches, docstrings, and installability."""
    workflow = (REPOSITORY_ROOT / ".github/workflows/tests.yml").read_text(
        encoding="utf-8"
    )
    assert "nim_benchmark_quality:" in workflow
    assert "coverage run --branch" in workflow
    assert "--source=contextual_orchestrator.nim_benchmark" in workflow
    assert "tests/test_nim_benchmark_review_regressions.py" in workflow
    assert "coverage report" in workflow and "--fail-under=100" in workflow
    assert "interrogate -f 100 contextual_orchestrator/nim_benchmark.py" in workflow
    assert "pip wheel --no-deps . --wheel-dir dist" in workflow
    assert "--no-build-isolation" not in workflow
    assert '--target "$RUNNER_TEMP/nim-wheel-site"' in workflow
    assert 'cd "$RUNNER_TEMP"' in workflow
    assert 'PYTHONPATH="$RUNNER_TEMP/nim-wheel-site"' in workflow
    assert "import contextual_orchestrator.nim_benchmark" in workflow


def test_scheduled_live_budget_covers_the_reviewed_current_catalog_scale() -> None:
    """Monthly live runs reserve enough calls for full probes plus evaluation."""
    workflow = (REPOSITORY_ROOT / ".github/workflows/nim-benchmark.yml").read_text(
        encoding="utf-8"
    )

    assert 'echo "max_requests=2000" >> "$GITHUB_OUTPUT"' in workflow
    assert 'echo "max_requests=300" >> "$GITHUB_OUTPUT"' not in workflow
