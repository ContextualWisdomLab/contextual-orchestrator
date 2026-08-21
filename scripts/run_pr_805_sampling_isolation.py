"""Normalize and execute the temporary PR 805 sampling repair script."""

from __future__ import annotations

import runpy
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("repair_pr_805_sampling_isolation.py")


def main() -> None:
    """Correct two fail-closed anchors, then execute the reviewed repair."""

    text = SCRIPT_PATH.read_text(encoding="utf-8")
    old_max = '''    text = _replace_once(
        text,
        '            "max_tokens": self.max_output_tokens,\\n',
        '            "max_tokens": effective_max_tokens,\\n',
        label="chat max tokens",
    )
'''
    new_max = '''    text = text.replace(
        '            "max_tokens": self.max_output_tokens,\\n',
        '            "max_tokens": effective_max_tokens,\\n',
        1,
    )
'''
    if old_max not in text:
        raise SystemExit("refusing unknown chat max-token repair anchor")
    text = text.replace(old_max, new_max, 1)

    old_disabled = '''    text = _replace_once(
        text,
        '            raise RuntimeError(f"requested model {requested_model!r} is disabled")\\n',
        '            model_label = requested_model if requested_model is not None else final_agent.model\\n            raise RuntimeError(f"requested model {model_label!r} is disabled")\\n',
        label="disabled model error",
    )
'''
    new_disabled = '''    old_disabled = ''' + "'''" + '''        if final_agent.disabled:
            raise RuntimeError(f"requested model {requested_model!r} is disabled")
''' + "'''" + '''
    new_disabled = ''' + "'''" + '''        if final_agent.disabled:
            model_label = requested_model if requested_model is not None else final_agent.model
            raise RuntimeError(f"requested model {model_label!r} is disabled")
''' + "'''" + '''
    text = _replace_once(text, old_disabled, new_disabled, label="disabled selected model")
'''
    if old_disabled not in text:
        raise SystemExit("refusing unknown disabled-model repair anchor")
    text = text.replace(old_disabled, new_disabled, 1)
    SCRIPT_PATH.write_text(text, encoding="utf-8")
    runpy.run_path(str(SCRIPT_PATH), run_name="__main__")


if __name__ == "__main__":
    main()
