#!/usr/bin/env python3
"""Atheris coverage-guided harness for strict model-judge response parsing."""

import sys
from pathlib import Path

import atheris

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

with atheris.instrument_imports():
    from fuzz.targets import exercise_model_judge_reply


def one_input(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    exercise_model_judge_reply(fdp.ConsumeUnicodeNoSurrogates(fdp.remaining_bytes()))


def main() -> None:
    atheris.Setup(sys.argv, one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
