"""Fuzzing harnesses and shared fuzz-target logic for contextual-orchestrator.

The heavy lifting lives in :mod:`fuzz.targets`, which exposes one ``exercise_*``
function per untrusted-input surface. Both the Atheris coverage-guided harnesses
(``fuzz/fuzz_*.py``) and the Hypothesis property tests (``tests/fuzz/``) call the
same functions, so a bug found by either tool reproduces under the other.
"""
