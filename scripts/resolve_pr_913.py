#!/usr/bin/env python3
"""Resolve PR #913 over the current protected main without losing later stream fixes."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC_CONFLICTS = {"CHANGELOG.md", "docs/product-technical-gap-baseline.md"}
MAIN_WINS_CONFLICTS = {
    "contextual_orchestrator/orchestrator.py",
    "tests/test_orchestrated_responses_stream.py",
}
TRUE_STREAMING = "tests/test_true_streaming.py"


def run(*args: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def union_document(relative: str) -> None:
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        ours = temp / "ours"
        base = temp / "base"
        theirs = temp / "theirs"
        ours.write_text(run("git", "show", f":2:{relative}", capture=True).stdout, encoding="utf-8")
        base.write_text(run("git", "show", f":1:{relative}", capture=True).stdout, encoding="utf-8")
        theirs.write_text(run("git", "show", f":3:{relative}", capture=True).stdout, encoding="utf-8")
        merged = subprocess.run(
            ["git", "merge-file", "--union", str(ours), str(base), str(theirs)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if merged.returncode not in (0, 1):
            raise RuntimeError(f"{relative}: document union failed: {merged.stderr}")
        (ROOT / relative).write_text(ours.read_text(encoding="utf-8"), encoding="utf-8")
        run("git", "add", "--", relative)


def choose_main_for_diff3(relative: str) -> int:
    run("git", "checkout", "--conflict=diff3", "--", relative)
    path = ROOT / relative
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    output: list[str] = []
    cursor = 0
    conflicts = 0
    while cursor < len(lines):
        if not lines[cursor].startswith("<<<<<<<"):
            output.append(lines[cursor])
            cursor += 1
            continue
        ours_start = cursor + 1
        base_marker = next(
            index for index in range(ours_start, len(lines)) if lines[index].startswith("|||||||")
        )
        split_marker = next(
            index for index in range(base_marker + 1, len(lines)) if lines[index].startswith("=======")
        )
        end_marker = next(
            index for index in range(split_marker + 1, len(lines)) if lines[index].startswith(">>>>>>>")
        )
        ours = "".join(lines[ours_start:base_marker])
        theirs = "".join(lines[split_marker + 1:end_marker])
        if not ours and not theirs:
            raise RuntimeError(f"{relative}: empty semantic conflict")
        output.append(theirs)
        conflicts += 1
        cursor = end_marker + 1

    if conflicts == 0:
        raise RuntimeError(f"{relative}: expected at least one diff3 conflict")
    merged = "".join(output)
    if any(marker in merged for marker in ("<<<<<<<", "|||||||", "=======", ">>>>>>>")):
        raise RuntimeError(f"{relative}: conflict marker remains")
    path.write_text(merged, encoding="utf-8")
    run("git", "add", "--", relative)
    return conflicts


def rebuild_true_streaming_test() -> None:
    run("git", "checkout", "origin/main", "--", TRUE_STREAMING)
    path = ROOT / TRUE_STREAMING
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''    def __init__(self, frames: list[str]) -> None:\n        class Handler(BaseHTTPRequestHandler):\n            def do_POST(self) -> None:  # noqa: N802\n                length = int(self.headers.get("content-length", 0))\n                self.rfile.read(length)\n''',
        '''    def __init__(self, frames: list[str]) -> None:\n        self.payloads: list[dict] = []\n        payloads = self.payloads\n\n        class Handler(BaseHTTPRequestHandler):\n            def do_POST(self) -> None:  # noqa: N802\n                length = int(self.headers.get("content-length", 0))\n                payloads.append(json.loads(self.rfile.read(length)))\n''',
        "fake provider request capture",
    )

    usage_anchor = '''    assert deltas == ["before", "after"]\n    assert client.take_usage() == {"completion_tokens": 7}\n\n\ndef test_stream_chat_requests_and_captures_provider_usage_without_stale_data() -> None:\n'''
    usage_test = '''    assert deltas == ["before", "after"]\n    assert client.take_usage() == {"completion_tokens": 7}\n\n\ndef test_stream_send_preserves_complete_provider_usage_frame() -> None:\n    usage = {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10}\n    frames = [\n        _delta("answer"),\n        _usage_frame(choices=[], usage=usage),\n        "data: [DONE]\\n\\n",\n    ]\n    with _FakeSSEProvider(frames) as provider:\n        client = ModelClient()\n        agent = ModelAgent(\n            "worker_agent",\n            "gpt-x",\n            base_url=provider.base_url,\n            api_key_env="UNSET_KEY_ENV",\n        )\n        assert list(\n            client._stream_send(agent, {"model": "gpt-x", "stream": True})\n        ) == ["answer"]\n    assert client.take_usage() == usage\n\n\ndef test_stream_chat_requests_and_captures_provider_usage_without_stale_data() -> None:\n'''
    text = replace_once(text, usage_anchor, usage_test, "complete provider usage test")

    gateway_anchor = '''    assert len(deltas) >= 2  # chunked, not one blob\n    assert "".join(deltas) == client._mock(agent, messages)  # lossless\n\n\ndef test_would_route_true_for_route_false_for_conduct() -> None:\n'''
    gateway_test = '''    assert len(deltas) >= 2  # chunked, not one blob\n    assert "".join(deltas) == client._mock(agent, messages)  # lossless\n\n\ndef test_stream_chat_omits_usage_option_for_local_gateway() -> None:\n    frames = [_delta("local"), "data: [DONE]\\n\\n"]\n    with _FakeSSEProvider(frames) as provider:\n        client = ModelClient()\n        agent = ModelAgent(\n            "gateway_agent",\n            "gateway-model",\n            base_url=(\n                f"local://127.0.0.1:{provider._server.server_address[1]}/v1"\n            ),\n        )\n        assert list(\n            client.stream_chat(agent, [{"role": "user", "content": "ping"}])\n        ) == ["local"]\n\n    assert "stream_options" not in provider.payloads[0]\n\n\ndef test_would_route_true_for_route_false_for_conduct() -> None:\n'''
    text = replace_once(text, gateway_anchor, gateway_test, "local gateway usage omission test")
    path.write_text(text, encoding="utf-8")
    run("git", "add", "--", TRUE_STREAMING)


def main() -> None:
    unresolved = run("git", "diff", "--name-only", "--diff-filter=U", capture=True)
    conflicts = {line for line in unresolved.stdout.splitlines() if line}
    expected = DOC_CONFLICTS | MAIN_WINS_CONFLICTS | {TRUE_STREAMING}
    unexpected = conflicts - expected
    if unexpected:
        raise RuntimeError(f"unexpected conflicts requiring manual review: {sorted(unexpected)}")
    if not MAIN_WINS_CONFLICTS.issubset(conflicts) or TRUE_STREAMING not in conflicts:
        raise RuntimeError(f"expected semantic conflicts missing: {sorted(expected - conflicts)}")

    for relative in sorted(conflicts & DOC_CONFLICTS):
        union_document(relative)

    orchestrator_conflicts = choose_main_for_diff3("contextual_orchestrator/orchestrator.py")
    import_conflicts = choose_main_for_diff3("tests/test_orchestrated_responses_stream.py")
    if orchestrator_conflicts < 4:
        raise RuntimeError(
            f"orchestrator conflict topology changed: found {orchestrator_conflicts}, expected at least 4"
        )
    if import_conflicts != 1:
        raise RuntimeError(
            f"responses stream import topology changed: found {import_conflicts}, expected 1"
        )

    rebuild_true_streaming_test()
    remaining = run("git", "diff", "--name-only", "--diff-filter=U", capture=True).stdout.strip()
    if remaining:
        raise RuntimeError(f"unresolved conflicts remain:\n{remaining}")


if __name__ == "__main__":
    main()
