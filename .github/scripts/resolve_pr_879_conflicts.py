"""Resolve the known semantic conflicts between PR #879 and protected main.

The script runs only in the one-shot branch workflow. It preserves current-main
streaming usage and Responses contracts while retaining PR #879's typed provider
errors, telemetry, and trace evidence. Every conflict shape is asserted so a
future drift fails closed rather than selecting a side implicitly.
"""

from __future__ import annotations

from pathlib import Path


ORCHESTRATOR_PATH = "contextual_orchestrator/orchestrator.py"
SERVER_PATH = "contextual_orchestrator/server.py"
PASSTHROUGH_TEST_PATH = "tests/test_passthrough_provider_failover.py"


def _resolve_file(path: str) -> None:
    """Resolve all strictly recognized diff3 blocks in one conflicted file."""
    source = Path(path).read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    output: list[str] = []
    index = 0
    block_index = 0

    while index < len(lines):
        if not lines[index].startswith("<<<<<<<"):
            output.append(lines[index])
            index += 1
            continue

        ours_start = index + 1
        base_marker = ours_start
        while base_marker < len(lines) and not lines[base_marker].startswith("|||||||"):
            base_marker += 1
        if base_marker >= len(lines):
            raise RuntimeError(f"{path}: expected diff3 base marker")

        separator = base_marker + 1
        while separator < len(lines) and not lines[separator].startswith("======="):
            separator += 1
        if separator >= len(lines):
            raise RuntimeError(f"{path}: expected conflict separator")

        end_marker = separator + 1
        while end_marker < len(lines) and not lines[end_marker].startswith(">>>>>>>"):
            end_marker += 1
        if end_marker >= len(lines):
            raise RuntimeError(f"{path}: expected conflict end marker")

        ours = lines[ours_start:base_marker]
        base = lines[base_marker + 1 : separator]
        theirs = lines[separator + 1 : end_marker]
        ours_text = "".join(ours)
        base_text = "".join(base)
        theirs_text = "".join(theirs)
        del base_text  # The asserted ours/theirs contracts determine the resolution.

        resolution = _resolve_block(
            path,
            block_index,
            ours=ours,
            theirs=theirs,
            ours_text=ours_text,
            theirs_text=theirs_text,
        )
        output.extend(resolution)
        block_index += 1
        index = end_marker + 1

    expected_blocks = {
        ORCHESTRATOR_PATH: 2,
        SERVER_PATH: 2,
        PASSTHROUGH_TEST_PATH: 1,
    }[path]
    if block_index != expected_blocks:
        raise RuntimeError(f"{path}: resolved {block_index} blocks; expected {expected_blocks}")

    merged = "".join(output)
    if any(marker in merged for marker in ("<<<<<<<", "|||||||", "=======", ">>>>>>>")):
        raise RuntimeError(f"{path}: unresolved conflict marker remains")

    if path == ORCHESTRATOR_PATH:
        merged = _enrich_streamed_trace_step(merged)

    Path(path).write_text(merged, encoding="utf-8")


def _resolve_block(
    path: str,
    block_index: int,
    *,
    ours: list[str],
    theirs: list[str],
    ours_text: str,
    theirs_text: str,
) -> list[str]:
    """Return the semantic resolution for one strictly recognized block."""
    if path == ORCHESTRATOR_PATH:
        if block_index == 0:
            required_ours = ("stream_usage", "stream_model", "stream_choices.extend")
            required_theirs = ("self._local.usage", "choices == []")
            if not all(token in ours_text for token in required_ours):
                raise RuntimeError("unexpected orchestrator streaming telemetry conflict")
            if not all(token in theirs_text for token in required_theirs):
                raise RuntimeError("unexpected orchestrator streaming usage conflict")
            return [
                "                    if not isinstance(chunk, dict):\n",
                "                        continue\n",
                "                    usage = chunk.get(\"usage\")\n",
                "                    if isinstance(usage, dict):\n",
                "                        self._local.usage = usage\n",
                "                        stream_usage = usage\n",
                "                    if isinstance(chunk.get(\"model\"), str):\n",
                "                        stream_model = chunk[\"model\"]\n",
                "                    choices = chunk.get(\"choices\")\n",
                "                    if choices == []:\n",
                "                        continue\n",
                "                    if not isinstance(choices, list) or not choices:\n",
                "                        continue\n",
                "                    stream_choices.extend(\n",
                "                        {\"finish_reason\": choice[\"finish_reason\"]}\n",
                "                        for choice in choices\n",
                "                        if isinstance(choice, dict)\n",
                "                        and isinstance(choice.get(\"finish_reason\"), str)\n",
                "                        and choice[\"finish_reason\"]\n",
                "                    )\n",
            ]
        if block_index == 1:
            if '"model": agent.model' not in ours_text or "trace_step" not in theirs_text:
                raise RuntimeError("unexpected streamed trace conflict")
            return ["                    trace_step\n"]
        raise RuntimeError(f"unexpected orchestrator conflict block {block_index}")

    if path == SERVER_PATH:
        if block_index == 0:
            if "invalid_stream_options" not in theirs_text or "explicit_trace" not in theirs_text:
                raise RuntimeError("unexpected structured stream-options conflict")
            return theirs
        if block_index == 1:
            if "ProviderUpstreamError" not in ours_text or "except Exception" not in ours_text:
                raise RuntimeError("unexpected SSE provider-error conflict")
            return ours
        raise RuntimeError(f"unexpected server conflict block {block_index}")

    if path == PASSTHROUGH_TEST_PATH:
        if block_index != 0:
            raise RuntimeError(f"unexpected passthrough-test conflict block {block_index}")
        if "test_passthrough_with_no_ranked_provider_fails_cleanly" not in ours_text:
            raise RuntimeError("missing provider-exhaustion regression")
        if "test_virtual_responses_effort_profile_uses_responses_wire_shape" not in theirs_text:
            raise RuntimeError("missing Responses effort-profile regression")
        return ours + theirs

    raise RuntimeError(f"unexpected conflict path {path}")


def _enrich_streamed_trace_step(merged: str) -> str:
    """Combine main's usage-bearing trace object with PR #879 telemetry fields."""
    old_trace = (
        "        trace_step = {\n"
        "            \"id\": 0,\n"
        "            \"role\": \"worker\",\n"
        "            \"agent_id\": agent.id,\n"
        "            \"subtask\": \"Direct route (streamed)\",\n"
        "            \"access\": [],\n"
        "            \"output\": answer,\n"
        "        }\n"
    )
    new_trace = (
        "        trace_step = {\n"
        "            \"id\": 0,\n"
        "            \"role\": \"worker\",\n"
        "            \"agent_id\": agent.id,\n"
        "            \"model\": agent.model,\n"
        "            \"provider\": agent.provider_name or self._infer_provider_name(agent.base_url),\n"
        "            \"subtask\": \"Direct route (streamed)\",\n"
        "            \"access\": [],\n"
        "            \"latency_ms\": round(latency_seconds * 1000, 2),\n"
        "            \"output\": answer,\n"
        "        }\n"
    )
    if merged.count(old_trace) != 1:
        raise RuntimeError("streamed trace-step shape changed unexpectedly")
    return merged.replace(old_trace, new_trace, 1)


def main() -> int:
    """Resolve all expected executable conflicts and fail on any shape drift."""
    for path in (ORCHESTRATOR_PATH, SERVER_PATH, PASSTHROUGH_TEST_PATH):
        _resolve_file(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
