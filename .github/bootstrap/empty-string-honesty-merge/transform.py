"""Apply the empty-string no-op contract to the current cumulative API head."""

from pathlib import Path


SERVER_PATH = Path("contextual_orchestrator/server.py")


def _replace_once(text: str, label: str, old: str, new: str) -> str:
    """Replace one expected old fragment or accept an already-applied fragment."""
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one old fragment, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    """Reapply the reviewed feature after taking the canonical base on conflicts."""
    text = SERVER_PATH.read_text(encoding="utf-8")
    replacements = [
        (
            "completions echo",
            '    # Explicit JSON null is treat-as-omit (SDK optional default).\n    if echo is None:\n',
            '    # Explicit JSON null or empty/whitespace string is treat-as-omit.\n    if echo is None or (isinstance(echo, str) and not echo.strip()):\n',
        ),
        (
            "completions n",
            '    # Explicit JSON null is treat-as-omit (SDK optional default).\n    if n is None:\n        return None\n    if isinstance(n, bool) or not isinstance(n, int) or n < 1:\n',
            '    # Explicit JSON null or empty/whitespace string is treat-as-omit.\n    if n is None or (isinstance(n, str) and not n.strip()):\n        return None\n    if isinstance(n, bool) or not isinstance(n, int) or n < 1:\n',
        ),
        (
            "responses n",
            '    # Explicit JSON null is treat-as-omit (SDK optional default).\n    if n is None:\n        return None\n    if isinstance(n, bool) or not isinstance(n, int):\n',
            '    # Explicit JSON null or empty/whitespace string is treat-as-omit.\n    if n is None or (isinstance(n, str) and not n.strip()):\n        return None\n    if isinstance(n, bool) or not isinstance(n, int):\n',
        ),
        (
            "responses parallel tool calls",
            '    # Explicit JSON null is treat-as-omit (SDK optional default).\n    if value is None:\n        return None\n    if not isinstance(value, bool):\n',
            '    # Explicit JSON null or empty/whitespace string is treat-as-omit.\n    if value is None or (isinstance(value, str) and not value.strip()):\n        return None\n    if not isinstance(value, bool):\n',
        ),
        (
            "responses seed",
            '    # Explicit JSON null is treat-as-omit (SDK optional default).\n    if seed is None:\n        return None\n    if isinstance(seed, bool) or not isinstance(seed, int):\n        raise RequestError(400, "invalid_seed", "seed must be an integer")\n',
            '    # Explicit JSON null or empty/whitespace string is treat-as-omit.\n    if seed is None or (isinstance(seed, str) and not seed.strip()):\n        return None\n    if isinstance(seed, bool) or not isinstance(seed, int):\n        raise RequestError(400, "invalid_seed", "seed must be an integer")\n',
        ),
        (
            "responses stop string",
            '    if isinstance(stop, str):\n        # Empty string is omit-equivalent (no stop sequences).\n        if not stop:\n',
            '    if isinstance(stop, str):\n        # Empty/whitespace string is omit-equivalent (no stop sequences).\n        if not stop.strip():\n',
        ),
        (
            "responses stop list",
            '    if isinstance(stop, list):\n        # Empty array is omit-equivalent (no stop sequences).\n        if not stop:\n',
            '    if isinstance(stop, list):\n        # Drop whitespace-only items; empty result is omit-equivalent.\n        stop = [item for item in stop if not (isinstance(item, str) and not item.strip())]\n        if not stop:\n',
        ),
        (
            "completions stop string",
            '    if isinstance(stop, str):\n        # Empty string is omit-equivalent (no stop sequences).\n        if not stop:\n',
            '    if isinstance(stop, str):\n        # Empty/whitespace string is omit-equivalent (no stop sequences).\n        if not stop.strip():\n',
        ),
        (
            "completions stop list",
            '    elif isinstance(stop, list):\n        # Empty array is omit-equivalent (no stop sequences).\n        if not stop:\n',
            '    elif isinstance(stop, list):\n        # Drop whitespace-only items; empty result is omit-equivalent.\n        stop = [item for item in stop if not (isinstance(item, str) and not item.strip())]\n        if not stop:\n',
        ),
        (
            "completions seed",
            '    # Explicit JSON null is treat-as-omit (SDK optional default).\n    if seed is None:\n        return None\n    if isinstance(seed, bool) or not isinstance(seed, int):\n        raise RequestError(400, "invalid_seed", "seed must be an integer")\n',
            '    # Explicit JSON null or empty/whitespace string is treat-as-omit.\n    if seed is None or (isinstance(seed, str) and not seed.strip()):\n        return None\n    if isinstance(seed, bool) or not isinstance(seed, int):\n        raise RequestError(400, "invalid_seed", "seed must be an integer")\n',
        ),
        (
            "frequency penalty",
            '    # Explicit JSON null is treat-as-omit (SDK optional default).\n    if value is None:\n        return None\n    if isinstance(value, bool) or not isinstance(value, (int, float)):\n        raise RequestError(400, "invalid_frequency_penalty", "frequency_penalty must be a number in [-2, 2]")\n',
            '    # Explicit JSON null or empty/whitespace string is treat-as-omit.\n    if value is None or (isinstance(value, str) and not value.strip()):\n        return None\n    if isinstance(value, bool) or not isinstance(value, (int, float)):\n        raise RequestError(400, "invalid_frequency_penalty", "frequency_penalty must be a number in [-2, 2]")\n',
        ),
        (
            "presence penalty",
            '    # Explicit JSON null is treat-as-omit (SDK optional default).\n    if value is None:\n        return None\n    if isinstance(value, bool) or not isinstance(value, (int, float)):\n        raise RequestError(400, "invalid_presence_penalty", "presence_penalty must be a number in [-2, 2]")\n',
            '    # Explicit JSON null or empty/whitespace string is treat-as-omit.\n    if value is None or (isinstance(value, str) and not value.strip()):\n        return None\n    if isinstance(value, bool) or not isinstance(value, (int, float)):\n        raise RequestError(400, "invalid_presence_penalty", "presence_penalty must be a number in [-2, 2]")\n',
        ),
        (
            "temperature",
            '    # Explicit JSON null is treat-as-omit (SDK optional default).\n    if temperature is None:\n',
            '    # Explicit JSON null or empty/whitespace string is treat-as-omit.\n    if temperature is None or (isinstance(temperature, str) and not temperature.strip()):\n',
        ),
        (
            "top p",
            '    # Explicit JSON null is treat-as-omit (SDK optional default).\n    if top_p is None:\n',
            '    # Explicit JSON null or empty/whitespace string is treat-as-omit.\n    if top_p is None or (isinstance(top_p, str) and not top_p.strip()):\n',
        ),
        (
            "max tokens",
            '    # Explicit JSON null is treat-as-omit (SDK optional default).\n    if max_tokens is None:\n',
            '    # Explicit JSON null or empty/whitespace string is treat-as-omit.\n    if max_tokens is None or (isinstance(max_tokens, str) and not max_tokens.strip()):\n',
        ),
        (
            "max completion tokens",
            '    # Explicit JSON null is treat-as-omit (SDK optional default).\n    if max_completion_tokens is None:\n',
            '    # Explicit JSON null or empty/whitespace string is treat-as-omit.\n    if max_completion_tokens is None or (\n        isinstance(max_completion_tokens, str) and not max_completion_tokens.strip()\n    ):\n',
        ),
        (
            "max output tokens",
            '    # Explicit JSON null is treat-as-omit (SDK optional default).\n    if value is None:\n        return None\n    if isinstance(value, bool) or not isinstance(value, int) or value < 1:\n        raise RequestError(\n            400,\n            "invalid_max_output_tokens",\n',
            '    # Explicit JSON null or empty/whitespace string is treat-as-omit.\n    if value is None or (isinstance(value, str) and not value.strip()):\n        return None\n    if isinstance(value, bool) or not isinstance(value, int) or value < 1:\n        raise RequestError(\n            400,\n            "invalid_max_output_tokens",\n',
        ),
        (
            "best of",
            '    # Explicit JSON null is treat-as-omit (SDK optional default).\n    if best_of is None:\n',
            '    # Explicit JSON null or empty/whitespace string is treat-as-omit.\n    if best_of is None or (isinstance(best_of, str) and not best_of.strip()):\n',
        ),
        (
            "embedding dimensions",
            '    Explicit JSON ``null`` is treated as omit (SDK optional default). Any other\n    value fails closed so clients cannot believe reduced dimensionality was applied.\n    """\n    if "dimensions" not in body:\n        return\n    if body.get("dimensions") is None:\n        return\n',
            '    Explicit JSON ``null`` or empty/whitespace string is treat-as-omit. Any other\n    value fails closed so clients cannot believe reduced dimensionality was applied.\n    """\n    if "dimensions" not in body:\n        return\n    value = body.get("dimensions")\n    if value is None or (isinstance(value, str) and not value.strip()):\n        return\n',
        ),
        (
            "chat parallel tool calls",
            '                        # Explicit JSON null is treat-as-omit (SDK optional default).\n                        ptc = body.get("parallel_tool_calls")\n                        if ptc is not None:\n',
            '                        # Explicit JSON null is treat-as-omit (SDK optional default).\n                        ptc = body.get("parallel_tool_calls")\n                        # Empty/whitespace string is treat-as-omit (SDK optional default).\n                        if isinstance(ptc, str) and not ptc.strip():\n                            ptc = None\n                        if ptc is not None:\n',
        ),
        (
            "include orchestration trace",
            '                        # Explicit JSON null is treat-as-omit (SDK optional default).\n                        if include_trace_raw is None:\n                            include_trace = bool(security.expose_trace_by_default)\n',
            '                        # Explicit JSON null or empty/whitespace string is treat-as-omit.\n                        if include_trace_raw is None or (\n                            isinstance(include_trace_raw, str) and not include_trace_raw.strip()\n                        ):\n                            include_trace = bool(security.expose_trace_by_default)\n',
        ),
        (
            "chat seed control",
            '                    if "seed" in body:\n                        # Type-check then fail closed: chat route does not apply seed.\n                        # Explicit JSON null is treat-as-omit (SDK optional default).\n                        if body.get("seed") is not None:\n',
            '                    if "seed" in body:\n                        # Type-check then fail closed: chat route does not apply seed.\n                        # Explicit JSON null or empty/whitespace string is treat-as-omit.\n                        seed_raw = body.get("seed")\n                        if seed_raw is not None and not (\n                            isinstance(seed_raw, str) and not seed_raw.strip()\n                        ):\n',
        ),
        (
            "chat stop control",
            '                    if "stop" in body:\n                        # Explicit JSON null, empty string, or empty [] is treat-as-omit.\n                        stop_val = body.get("stop")\n                        if stop_val is not None and stop_val != [] and stop_val != "":\n',
            '                    if "stop" in body:\n                        # Explicit JSON null, empty string, empty [], or all-whitespace\n                        # array items is treat-as-omit (SDK optional default).\n                        stop_val = body.get("stop")\n                        if isinstance(stop_val, list):\n                            stop_val = [\n                                item\n                                for item in stop_val\n                                if not (isinstance(item, str) and not item.strip())\n                            ]\n                        if stop_val is not None and stop_val != [] and stop_val != "":\n',
        ),
        (
            "chat logprobs control",
            '                        # Explicit JSON null is treat-as-omit (SDK optional default).\n                        if "logprobs" in body:\n                            lp = body.get("logprobs")\n                            if lp is not None:\n',
            '                        # Explicit JSON null is treat-as-omit (SDK optional default).\n                        if "logprobs" in body:\n                            lp = body.get("logprobs")\n                            # Empty/whitespace string is treat-as-omit.\n                            if isinstance(lp, str) and not lp.strip():\n                                lp = None\n                            if lp is not None:\n',
        ),
        (
            "responses stream",
            '                    # stream=true is not implemented for Responses passthrough.\n                    if "stream" in body:\n                        stream = body.get("stream")\n                        # Explicit JSON null / false are omit-equivalent no-ops.\n                        if stream is None or stream is False:\n                            pass\n',
            '                    # stream=true is not implemented for Responses passthrough.\n                    if "stream" in body:\n                        stream = body.get("stream")\n                        # Explicit JSON null / false / empty string are omit-equivalent no-ops.\n                        if (\n                            stream is None\n                            or stream is False\n                            or (isinstance(stream, str) and not stream.strip())\n                        ):\n                            pass\n',
        ),
    ]

    for label, old, new in replacements:
        text = _replace_once(text, label, old, new)

    SERVER_PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
