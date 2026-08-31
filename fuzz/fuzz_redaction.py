#!/usr/bin/env python3
"""Atheris coverage-guided harness: secret/PII redaction.

Surface: ``orchestrator.redact_text`` / ``redact_value`` -- regex + recursive
masking applied to arbitrary trace payloads before they leave the process.
Idempotence and no-crash are the load-bearing invariants (see ``fuzz.targets``).

Run locally::

    python fuzz/fuzz_redaction.py -max_total_time=60 fuzz/corpus/redaction
"""

import sys
from pathlib import Path

import atheris

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

with atheris.instrument_imports():
    from fuzz.targets import exercise_redaction


def one_input(data: bytes) -> None:
    """Feed one Atheris-fuzzed byte string through secret/PII redaction."""
    fdp = atheris.FuzzedDataProvider(data)
    text = fdp.ConsumeUnicodeNoSurrogates(fdp.remaining_bytes())
    exercise_redaction(text)


def main() -> None:
    """Run the Atheris coverage-guided fuzz loop against ``one_input``."""
    atheris.Setup(sys.argv, one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
