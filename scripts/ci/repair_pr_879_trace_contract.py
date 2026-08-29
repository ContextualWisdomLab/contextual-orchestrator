"""One-shot repair for structured and tool-passthrough trace contracts in PR #879."""

from __future__ import annotations

from pathlib import Path


def main() -> None:
    """Remove the over-broad trace rejection that shadows specific contracts."""
    path = Path("contextual_orchestrator/server.py")
    text = path.read_text(encoding="utf-8")
    old = '''                        if explicit_trace:
                            raise RequestError(
                                400,
                                "unsupported_trace_disclosure",
                                "remove include_orchestration_trace or use chat without tools or response_format",
                            )
                        tool_loop = bool(tools_list)
'''
    new = '''                        tool_loop = bool(tools_list)
'''
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one over-broad trace guard; found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


if __name__ == "__main__":
    main()
