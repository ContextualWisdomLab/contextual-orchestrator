"""Packaging contract for mandatory fast-mlsirm response-quality evaluation."""

from __future__ import annotations

from pathlib import Path
import tomllib


def test_supported_python_floor_matches_fast_mlsirm_runtime() -> None:
    """Every supported interpreter must install the mandatory psychometric runtime."""
    project_data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project_data["requires-python"] == ">=3.12"
    fast_mlsirm_dependencies = [
        dependency
        for dependency in project_data["dependencies"]
        if dependency.startswith("fast-mlsirm ")
    ]
    assert fast_mlsirm_dependencies == [
        "fast-mlsirm @ https://github.com/ContextualWisdomLab/fast-mlsirm/archive/refs/tags/v0.9.1.tar.gz"
    ]
