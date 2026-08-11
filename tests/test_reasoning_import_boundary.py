"""Regression tests for explicit adaptive-reasoning runtime activation."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _run_fresh_interpreter(source: str) -> subprocess.CompletedProcess[str]:
    """Execute ``source`` in a fresh interpreter rooted at the repository."""
    return subprocess.run(
        [sys.executable, "-c", source],
        cwd=_REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_package_import_does_not_activate_reasoning_hooks() -> None:
    """Importing the public package must not mutate runtime classes."""
    result = _run_fresh_interpreter(
        """
import contextual_orchestrator
from contextual_orchestrator.orchestrator import ModelClient

assert not hasattr(ModelClient, \"_reasoning_control_installed\"), (
    \"package import activated optional reasoning hooks\"
)
"""
    )
    assert result.returncode == 0, result.stderr


def test_cli_activation_is_explicit_and_idempotent() -> None:
    """The product CLI must opt in explicitly without double-wrapping methods."""
    result = _run_fresh_interpreter(
        """
import contextual_orchestrator
from contextual_orchestrator.__main__ import _enable_reasoning_runtime
from contextual_orchestrator.orchestrator import ModelClient

assert not hasattr(ModelClient, \"_reasoning_control_installed\")
_enable_reasoning_runtime()
assert ModelClient._reasoning_control_installed is True
installed_chat = ModelClient.chat
_enable_reasoning_runtime()
assert ModelClient.chat is installed_chat
"""
    )
    assert result.returncode == 0, result.stderr


def test_pytest_config_exposes_test_helpers_without_ci_path_injection() -> None:
    """Plain local pytest must import shared fakes without workflow-only state."""
    project_config = (_REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    tests_workflow = (
        _REPOSITORY_ROOT / ".github" / "workflows" / "tests.yml"
    ).read_text(encoding="utf-8")
    reasoning_workflow = (
        _REPOSITORY_ROOT
        / ".github"
        / "workflows"
        / "reasoning-workload-verify.yml"
    ).read_text(encoding="utf-8")

    assert '[tool.pytest.ini_options]\npythonpath = ["tests"]' in project_config
    assert "PYTHONPATH:" not in tests_workflow
    assert "PYTHONPATH:" not in reasoning_workflow
