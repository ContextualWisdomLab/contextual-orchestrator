#!/usr/bin/env python3
"""Atheris coverage-guided harness: NIM benchmark model-catalog parser.

Surface: ``nim_benchmark.parse_model_catalog_body`` -- the untrusted-input
parser for the provider's ``GET /v1/models`` response body.

Run locally (needs a permissive-licensed build of Atheris, Apache-2.0)::

    python fuzz/fuzz_nim_catalog.py -atomic_step -max_total_time=60 fuzz/corpus/nim_catalog
"""

import sys
from pathlib import Path

import atheris

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

with atheris.instrument_imports():
    from fuzz.targets import exercise_nim_catalog


def one_input(data: bytes) -> None:
    """Feed one fuzzer-generated body to the catalog parser invariants."""
    exercise_nim_catalog(data)


def main() -> None:
    """Set up and run the Atheris fuzzing loop."""
    atheris.Setup(sys.argv, one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
