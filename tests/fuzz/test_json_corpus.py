"""Verify JSON corpus delivery with real Atheris and isolated target callbacks."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

if importlib.util.find_spec("atheris") is None:
    pytest.skip("The dedicated Security fuzz job installs locked Atheris", allow_module_level=True)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(params=["agent_config", "reasoning_effort_profile"])
def harness_capture(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """Load the real harness while replacing only its domain callback."""
    corpus_name = request.param
    captured_values: list[object] = []
    target_module = ModuleType("fuzz.targets")
    setattr(target_module, f"exercise_{corpus_name}", captured_values.append)
    monkeypatch.setitem(sys.modules, "fuzz.targets", target_module)
    harness_path = REPOSITORY_ROOT / "fuzz" / f"fuzz_{corpus_name}.py"
    module_spec = importlib.util.spec_from_file_location(f"corpus_harness_{corpus_name}", harness_path)
    assert module_spec is not None and module_spec.loader is not None
    harness_module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(harness_module)
    return corpus_name, harness_module.one_input, captured_values


def test_checked_json_corpus_delivers_original_value(harness_capture) -> None:
    """Every checked JSON seed reaches the target unchanged."""
    corpus_name, consume_input, captured_values = harness_capture
    seed_paths = sorted((REPOSITORY_ROOT / "fuzz" / "corpus" / corpus_name).glob("*.json"))
    assert seed_paths, corpus_name
    for seed_path in seed_paths:
        seed_bytes = seed_path.read_bytes()
        consume_input(seed_bytes)
        assert captured_values == [json.loads(seed_bytes)], seed_path
        captured_values.clear()


def test_malformed_bytes_do_not_dispatch(harness_capture) -> None:
    """Invalid encoding and invalid JSON never reach the domain callback."""
    _, consume_input, captured_values = harness_capture
    for malformed_payload in (b"\xff{not-json", b"{not-json"):
        consume_input(malformed_payload)
    assert captured_values == []
