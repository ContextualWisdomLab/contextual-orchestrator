#!/usr/bin/env python3
"""Atheris harness for the request endpoint selector parser."""

import sys
from pathlib import Path

import atheris

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

with atheris.instrument_imports():
    from fuzz.targets import exercise_endpoint_selector


def one_input(data: bytes) -> None:
    """Feed arbitrary Unicode endpoint selectors through the shared invariant."""
    fdp = atheris.FuzzedDataProvider(data)
    exercise_endpoint_selector(fdp.ConsumeUnicodeNoSurrogates(fdp.remaining_bytes()))


def main() -> None:
    """Run the coverage-guided endpoint parser target."""
    atheris.Setup(sys.argv, one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
