#!/usr/bin/env python3
"""Atheris harness for the explicit PII encryption key prefix boundary."""

import sys
from pathlib import Path

import atheris

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

with atheris.instrument_imports():
    from fuzz.targets import exercise_pii_key


def one_input(data: bytes) -> None:
    """Feed arbitrary Unicode key text through the shared invariant."""
    fdp = atheris.FuzzedDataProvider(data)
    exercise_pii_key(fdp.ConsumeUnicodeNoSurrogates(fdp.remaining_bytes()))


def main() -> None:
    """Start the bounded libFuzzer harness."""
    atheris.Setup(sys.argv, one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
