#!/usr/bin/env python3
"""Atheris coverage-guided harness: HTTP request-body parser + validators.

Surface: ``server._coerce_json`` / ``_reject_unknown_keys`` / ``_validate_mode``
/ ``_validate_messages`` -- everything that touches an untrusted HTTP body.

Run locally (needs a permissive-licensed build of Atheris, Apache-2.0)::

    python fuzz/fuzz_request_body.py -atomic_step -max_total_time=60 fuzz/corpus/request_body
"""

import sys
from pathlib import Path

import atheris

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

with atheris.instrument_imports():
    from fuzz.targets import exercise_request_body


def one_input(data: bytes) -> None:
    exercise_request_body(data)


def main() -> None:
    atheris.Setup(sys.argv, one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
