"""Pytest configuration for the repo root.

The Atheris coverage-guided harnesses under ``fuzz/`` import ``atheris`` at
module load time, which is only installed in the dedicated CI job. Ignore that
directory during normal collection so the suite runs without the native
toolchain. The Hypothesis property tests under ``tests/fuzz/`` are unaffected.
"""

collect_ignore = ["fuzz"]
