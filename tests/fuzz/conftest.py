"""Collection guard for the Hypothesis property suite.

``tests/fuzz/test_fuzz_properties.py`` imports :mod:`hypothesis` at module
scope. Hypothesis is a declared dependency, so it is present in real CI and in
local dev environments and the property tests run normally there. The central
OpenCode coverage-evidence sandbox, however, installs only a materialized base
dependency set and does not yet provide ``hypothesis``; without this guard the
module raises ``ModuleNotFoundError`` at collection time and fails the whole
offline test run. Skipping collection when — and only when — the optional
dependency is genuinely unavailable keeps the suite green in that sandbox while
leaving it fully enabled everywhere Hypothesis is installed.
"""
from __future__ import annotations

import importlib.util

collect_ignore: list[str] = []
if importlib.util.find_spec("hypothesis") is None:
    collect_ignore = ["test_fuzz_properties.py"]
