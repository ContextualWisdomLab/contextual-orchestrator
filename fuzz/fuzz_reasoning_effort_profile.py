#!/usr/bin/env python3
"""Atheris coverage-guided harness: reasoning-effort profile parser.

Surface: ``reasoning_effort_profile.parse_reasoning_effort_profile`` -- parses
untrusted role-compute JSON for issue #568.

Run locally::

    python fuzz/fuzz_reasoning_effort_profile.py -max_total_time=60 fuzz/corpus/reasoning_effort_profile
"""

import json
import sys
from pathlib import Path

import atheris

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

with atheris.instrument_imports():
    from fuzz.targets import exercise_reasoning_effort_profile


def one_input(data: bytes) -> None:
    """Feed one Atheris-fuzzed byte string through the profile parser."""
    fdp = atheris.FuzzedDataProvider(data)
    text = fdp.ConsumeUnicodeNoSurrogates(fdp.remaining_bytes())
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):
        return
    exercise_reasoning_effort_profile(value)


def main() -> None:
    """Run the Atheris coverage-guided fuzz loop against ``one_input``."""
    atheris.Setup(sys.argv, one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
