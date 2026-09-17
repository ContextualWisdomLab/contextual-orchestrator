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
        "fast-mlsirm @ git+https://github.com/ContextualWisdomLab/fast-mlsirm.git@09f762ded35786dd1078222a4577ff09d649816f ; python_full_version >= '3.12'"
    ]
