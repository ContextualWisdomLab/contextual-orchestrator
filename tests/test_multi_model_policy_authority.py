"""Fail-closed boundary for unreleased multi-model decision policy."""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    (
        "contextual_orchestrator.domain.combination",
        "contextual_orchestrator.application.fan_out",
    ),
)
def test_uncalibrated_combination_policy_is_not_importable(module_name: str) -> None:
    """Do not ship selection or allocation without released owner evidence."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_name)
