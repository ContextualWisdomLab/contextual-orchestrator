#!/usr/bin/env python3
"""Atheris coverage-guided harness: agent-pool config parser.

Surface: ``orchestrator.ModelAgent.from_dict`` -- parses each entry of an
untrusted ``agents.json`` config file.

Run locally::

    python fuzz/fuzz_agent_config.py -max_total_time=60 fuzz/corpus/agent_config
"""

import json
import sys
from pathlib import Path

import atheris

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

with atheris.instrument_imports():
    from fuzz.targets import exercise_agent_config


def one_input(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    text = fdp.ConsumeUnicodeNoSurrogates(fdp.remaining_bytes())
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):
        return
    exercise_agent_config(value)


def main() -> None:
    atheris.Setup(sys.argv, one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
