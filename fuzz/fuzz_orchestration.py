#!/usr/bin/env python3
"""Atheris coverage-guided harness: end-to-end orchestration on arbitrary prompt.

Surface: ``orchestrator.TaskOrchestrator.run`` against ``mock://`` providers --
drives prompt classification, agent scoring, route/conduct, trace assembly, and
SSE framing entirely offline.

Run locally::

    python fuzz/fuzz_orchestration.py -max_total_time=60 fuzz/corpus/orchestration
"""

import sys
from pathlib import Path

import atheris

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

with atheris.instrument_imports():
    from fuzz.targets import exercise_orchestration

_MODES = ("auto", "route", "conduct")


def one_input(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    mode = _MODES[fdp.ConsumeIntInRange(0, len(_MODES) - 1)]
    prompt = fdp.ConsumeUnicodeNoSurrogates(fdp.remaining_bytes())
    exercise_orchestration(prompt, mode)


def main() -> None:
    atheris.Setup(sys.argv, one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
