#!/usr/bin/env python3
"""Atheris harness for the trusted governed-rater observation parser."""

import json
import sys
from pathlib import Path

import atheris

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

with atheris.instrument_imports():
    from fuzz.rater_observation_target import exercise_rater_observation


def one_input(data: bytes) -> None:
    """Feed one decoded JSON value through the trusted observation parser."""
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return
    exercise_rater_observation(value)


def main() -> None:
    """Run the Atheris coverage-guided fuzz loop."""
    atheris.Setup(sys.argv, one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
