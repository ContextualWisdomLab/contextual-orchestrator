"""Static least-privilege contracts for scheduled NIM benchmark automation."""

from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_dry_run_workflow_never_receives_live_nvidia_secret() -> None:
    """The zero-egress dry path must have no NVIDIA credential in its environment."""
    workflow = (REPOSITORY_ROOT / ".github/workflows/nim-benchmark.yml").read_text(
        encoding="utf-8"
    )
    dry_start = workflow.index("- name: Run dry benchmark")
    live_start = workflow.index("- name: Run live benchmark")
    dry_block = workflow[dry_start:live_start]
    live_block = workflow[live_start:]

    assert "NVIDIA_NIM_API_KEY" not in dry_block
    assert live_block.count("NVIDIA_NIM_API_KEY:") == 1
    assert "secrets.NVIDIA_NIM_API_KEY" in live_block


def test_dry_run_workflow_honors_optional_pricing_scenario_without_secret() -> None:
    """Manual dry runs may validate an explicit scenario without live credentials."""
    workflow = (REPOSITORY_ROOT / ".github/workflows/nim-benchmark.yml").read_text(
        encoding="utf-8"
    )
    dry_start = workflow.index("- name: Run dry benchmark")
    live_start = workflow.index("- name: Run live benchmark")
    dry_block = workflow[dry_start:live_start]

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
    """Mergeable source must not retain the one-use transformation payload."""
    assert not (REPOSITORY_ROOT / ".review-evidence/nim-source-repair.yml").exists()


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
    assert "coverage report" in workflow and "--fail-under=100" in workflow
    assert "interrogate -f 100 contextual_orchestrator/nim_benchmark.py" in workflow
    assert "pip wheel --no-deps --no-build-isolation" in workflow
    assert '--target "$RUNNER_TEMP/nim-wheel-site"' in workflow
    assert 'cd "$RUNNER_TEMP"' in workflow
    assert 'PYTHONPATH="$RUNNER_TEMP/nim-wheel-site"' in workflow
    assert "import contextual_orchestrator.nim_benchmark" in workflow
