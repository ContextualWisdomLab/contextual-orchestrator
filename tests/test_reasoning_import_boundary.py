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
