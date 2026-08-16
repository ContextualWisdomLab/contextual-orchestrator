#!/usr/bin/env python3
"""Atheris coverage-guided harness: image placement catalog.

Surface: ``orchestrator.collect_image_catalog`` -- untrusted multimodal
message lists. The catalog must stay 3NF-shaped and must never echo raw
base64 image payloads (see ``fuzz.targets``).

Run locally::

    python fuzz/fuzz_image_catalog.py -max_total_time=60 fuzz/corpus/image_catalog
"""

import json
import sys
from pathlib import Path

import atheris

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

with atheris.instrument_imports():
    from fuzz.targets import exercise_image_catalog


def one_input(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    raw = fdp.ConsumeUnicodeNoSurrogates(fdp.remaining_bytes())
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = raw
    exercise_image_catalog(value)


def main() -> None:
    atheris.Setup(sys.argv, one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
