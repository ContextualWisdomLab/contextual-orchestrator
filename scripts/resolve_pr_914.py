#!/usr/bin/env python3
"""Resolve PR #914 against the protected main branch without discarding newer work."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKOUT_MAIN_CONFLICTS = {
    "contextual_orchestrator/orchestrator.py",
    "contextual_orchestrator/server.py",
    "tests/test_chat_stream_options_http_honesty.py",
    "tests/test_stream_options_null_flags_noop_http_honesty.py",
    "tests/test_streaming.py",
}


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


def resolve_conflicts() -> None:
    result = run("git", "diff", "--name-only", "--diff-filter=U", capture=True)
    conflicts = [line for line in result.stdout.splitlines() if line]
    unexpected: list[str] = []

    for relative in conflicts:
        if relative.endswith((".md", ".mdx")):
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
                    raise RuntimeError(
                        f"{relative}: git merge-file failed ({merged.returncode}): {merged.stderr}"
                    )
                (ROOT / relative).write_text(ours.read_text(encoding="utf-8"), encoding="utf-8")
                run("git", "add", "--", relative)
        elif relative in CHECKOUT_MAIN_CONFLICTS:
            run("git", "checkout", "origin/main", "--", relative)
        else:
            unexpected.append(relative)

    if unexpected:
        raise RuntimeError(f"unexpected conflicts requiring manual review: {unexpected}")

    remaining = run("git", "diff", "--name-only", "--diff-filter=U", capture=True).stdout.strip()
    if remaining:
        raise RuntimeError(f"unresolved conflicts remain:\n{remaining}")


def patch_orchestrator() -> None:
    path = ROOT / "contextual_orchestrator/orchestrator.py"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''        if type(include_usage) is not bool:\n            raise TypeError("include_usage must be a boolean")\n        if not is_chat_compatible_model_id(agent.model):\n''',
        '''        if type(include_usage) is not bool:\n            raise TypeError("include_usage must be a boolean")\n        self._local.usage = None\n        if not is_chat_compatible_model_id(agent.model):\n''',
        "stream_chat stale-usage reset",
    )
    text = replace_once(
        text,
        '''            )\n        self._local.usage = None\n        if agent.base_url.startswith("mock://"):\n''',
        '''            )\n        if agent.base_url.startswith("mock://"):\n''',
        "stream_chat duplicate reset",
    )
    text = replace_once(
        text,
        '''                    usage = chunk.get("usage")\n                    if isinstance(usage, dict):\n                        self._local.usage = usage\n                    choices = chunk.get("choices") or [{}]\n                    delta = (choices[0] or {}).get("delta", {}).get("content")\n''',
        '''                    choices = chunk.get("choices")\n                    usage = chunk.get("usage")\n                    if isinstance(usage, dict):\n                        self._local.usage = usage\n                    if choices == []:\n                        continue\n                    if not isinstance(choices, list) or not choices:\n                        continue\n                    delta = (choices[0] or {}).get("delta", {}).get("content")\n''',
        "provider SSE usage parser",
    )

    start = text.index("def chat_completion_chunks(")
    end = text.index("def _new_chat_completion_id()", start)
    replacement = '''def chat_completion_chunks(\n    result: dict[str, Any],\n    model: str = "contextual-orchestrator",\n    include_trace: bool = False,\n    include_usage: bool = False,\n) -> list[dict[str, Any]]:\n    """Frame an orchestration result as OpenAI-compatible chat completion chunks.\n\n    Only provider-reported usage may be emitted. Gateway estimates remain internal\n    because presenting estimates as provider usage would violate the wire contract.\n    """\n    answer = result.get("answer", "")\n    completion_id = _new_chat_completion_id()\n    created = int(time.time())\n    base = {\n        "id": completion_id,\n        "object": "chat.completion.chunk",\n        "created": created,\n        "model": model,\n    }\n    if include_usage:\n        base["usage"] = None\n\n    chunks: list[dict[str, Any]] = [\n        {\n            **base,\n            "choices": [\n                {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}\n            ],\n        }\n    ]\n    for offset in range(0, len(answer), _STREAM_CHUNK_SIZE):\n        piece = answer[offset : offset + _STREAM_CHUNK_SIZE]\n        chunks.append(\n            {\n                **base,\n                "choices": [\n                    {"index": 0, "delta": {"content": piece}, "finish_reason": None}\n                ],\n            }\n        )\n\n    orchestration = {\n        "workflow_run_id": result.get("workflow_run_id"),\n        "mode": result.get("mode"),\n        "verification": result.get("verification"),\n    }\n    if include_trace and "trace" in result:\n        orchestration["trace"] = redact_value(result["trace"])\n\n    final = {\n        **base,\n        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],\n        "orchestration": {\n            key: value for key, value in orchestration.items() if value is not None\n        },\n    }\n    chunks.append(final)\n\n    usage = result.get("usage")\n    cost = result.get("cost")\n    if (\n        include_usage\n        and isinstance(cost, dict)\n        and cost.get("measurement_status") == "measured"\n        and isinstance(usage, dict)\n    ):\n        chunks.append({**base, "choices": [], "usage": usage})\n    return chunks\n\n\n'''
    text = text[:start] + replacement + text[end:]
    path.write_text(text, encoding="utf-8")


def patch_server() -> None:
    path = ROOT / "contextual_orchestrator/server.py"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''                    if body.get("response_format") or tools_list:\n                        if explicit_trace:\n''',
        '''                    if body.get("response_format") or tools_list:\n                        if stream and include_usage:\n                            raise RequestError(\n                                400,\n                                "invalid_stream_options",\n                                "stream_options.include_usage=true is not supported with tools or response_format",\n                            )\n                        if explicit_trace:\n''',
        "structured stream usage gate",
    )

    start = text.index("        def _stream_route_completion(")
    end = text.index("        def _send_security_headers", start)
    replacement = '''        def _stream_route_completion(\n            self,\n            orchestrator: Any,\n            security: Any,\n            messages: Any,\n            model_name: str,\n            *,\n            include_usage: bool = False,\n        ) -> None:\n            """Pipe live provider deltas as OpenAI chat-completion SSE frames."""\n            run_id = f"run_{uuid.uuid4().hex}"\n            completion_id = _new_chat_completion_id()\n            created = int(time.time())\n            stream_usage: dict[str, Any] | None = None\n\n            def capture_usage(usage: dict[str, Any] | None) -> None:\n                nonlocal stream_usage\n                stream_usage = usage\n\n            def frame(delta: dict[str, Any], finish: str | None = None) -> str:\n                payload = {\n                    "id": completion_id,\n                    "object": "chat.completion.chunk",\n                    "created": created,\n                    "model": model_name,\n                    "choices": [\n                        {"index": 0, "delta": delta, "finish_reason": finish}\n                    ],\n                }\n                if include_usage:\n                    payload["usage"] = None\n                return f"data: {json.dumps(payload, ensure_ascii=False)}\\n\\n"\n\n            def usage_frame(usage: dict[str, Any]) -> str:\n                payload = {\n                    "id": completion_id,\n                    "object": "chat.completion.chunk",\n                    "created": created,\n                    "model": model_name,\n                    "choices": [],\n                    "usage": usage,\n                }\n                return f"data: {json.dumps(payload, ensure_ascii=False)}\\n\\n"\n\n            security.acquire_run_slot()\n            try:\n                if not self._begin_sse() or not self._write_sse(\n                    frame({"role": "assistant"})\n                ):\n                    return\n                try:\n                    stream_kwargs: dict[str, Any] = {\n                        "workflow_run_id": run_id,\n                        "model_name": model_name,\n                    }\n                    if include_usage:\n                        stream_kwargs.update(\n                            {"include_usage": True, "usage_callback": capture_usage}\n                        )\n                    for delta in orchestrator.stream_route(messages, **stream_kwargs):\n                        if not self._write_sse(frame({"content": delta})):\n                            return\n                    if not self._write_sse(frame({}, finish="stop")):\n                        return\n                    if (\n                        include_usage\n                        and isinstance(stream_usage, dict)\n                        and not self._write_sse(usage_frame(stream_usage))\n                    ):\n                        return\n                except ToolFallbackStoppedError as exc:\n                    detail = {\n                        "request_id": uuid.uuid4().hex,\n                        **_tool_fallback_error_detail(exc),\n                    }\n                    payload = _error_payload(\n                        TOOL_FALLBACK_STOPPED_CODE,\n                        TOOL_FALLBACK_STOPPED_MESSAGE,\n                        detail,\n                    )\n                    if not self._write_sse(\n                        f"data: {json.dumps(payload, ensure_ascii=False)}\\n\\n"\n                    ):\n                        return\n                    if not self._write_sse(frame({}, finish="error")):\n                        return\n                except Exception:  # noqa: BLE001 - headers already sent\n                    if not self._write_sse(frame({}, finish="error")):\n                        return\n                self._write_sse("data: [DONE]\\n\\n")\n            finally:\n                security.release_run_slot()\n\n'''
    text = text[:start] + replacement + text[end:]
    path.write_text(text, encoding="utf-8")


def patch_readme() -> None:
    path = ROOT / "README.md"
    run("git", "checkout", "origin/main", "--", str(path.relative_to(ROOT)))
    text = path.read_text(encoding="utf-8")
    old = '- `/v1/chat/completions` accepts normal chat messages, and `"stream": true` returns an OpenAI-compatible `text/event-stream` of `chat.completion.chunk` deltas terminated by `data: [DONE]`. In **route** mode the worker\'s tokens are streamed live as they arrive from the provider (real token streaming); in **conduct** mode the multi-step answer is produced then framed as deltas (a workflow can\'t honestly token-stream a synthesizer that hasn\'t run yet).\n'
    new = '- `/v1/chat/completions` accepts normal chat messages, and `"stream": true` returns an OpenAI-compatible `text/event-stream` of `chat.completion.chunk` deltas terminated by `data: [DONE]`. `stream_options.include_usage=true` is accepted for ordinary chat streams and emits a provider-reported usage-only chunk after the terminal stop chunk when usage is available; structured `tools`/`response_format` passthrough rejects that combination before provider execution. In **route** mode the worker\'s tokens are streamed live as they arrive from the provider (real token streaming); in **conduct** mode the multi-step answer is produced then framed as deltas (a workflow can\'t honestly token-stream a synthesizer that hasn\'t run yet).\n'
    path.write_text(replace_once(text, old, new, "README stream contract"), encoding="utf-8")


def patch_stream_option_tests() -> None:
    relative = "tests/test_stream_options_null_flags_noop_http_honesty.py"
    run("git", "checkout", "origin/main", "--", relative)
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")

    start = text.index("def test_http_chat_accepts_include_usage_true()")
    end = text.index("def test_http_chat_structured_streams_include_usage()", start)
    ordinary = '''def test_http_chat_accepts_include_usage_true() -> None:\n    server, thread, port = _server()\n    try:\n        status, content_type, sse = _post_raw(\n            port,\n            "/v1/chat/completions",\n            {\n                "model": "mock-planner",\n                "messages": [{"role": "user", "content": "usage true"}],\n                "stream": True,\n                "stream_options": {"include_usage": True},\n            },\n        )\n        assert status == 200, sse\n        assert content_type.startswith("text/event-stream")\n        frames = [\n            json.loads(frame[len("data: "):])\n            for frame in sse.split("\\n\\n")\n            if frame.startswith("data: ") and frame != "data: [DONE]"\n        ]\n        assert frames\n        assert all(frame.get("usage") is None for frame in frames)\n        assert not any(frame.get("choices") == [] for frame in frames)\n    finally:\n        server.shutdown()\n        thread.join(timeout=5)\n\n\n'''
    text = text[:start] + ordinary + text[end:]

    start = text.index("def test_http_chat_structured_streams_include_usage()")
    end = text.index("def test_http_chat_rejects_non_boolean_non_null_flag()", start)
    structured = '''def test_http_chat_structured_streams_include_usage() -> None:\n    server, thread, port = _server()\n    try:\n        for structured in (\n            {\n                "tools": [\n                    {\n                        "type": "function",\n                        "function": {\n                            "name": "lookup",\n                            "parameters": {"type": "object", "properties": {}},\n                        },\n                    }\n                ]\n            },\n            {"response_format": {"type": "json_object"}},\n        ):\n            status, _, body = _post_raw(\n                port,\n                "/v1/chat/completions",\n                {\n                    "model": "mock-planner",\n                    "messages": [\n                        {"role": "user", "content": "structured usage"}\n                    ],\n                    "stream": True,\n                    "stream_options": {"include_usage": True},\n                    **structured,\n                },\n            )\n            assert status == 400, (structured, body)\n            assert "invalid_stream_options" in body\n    finally:\n        server.shutdown()\n        thread.join(timeout=5)\n\n\n'''
    path.write_text(text[:start] + structured + text[end:], encoding="utf-8")


def patch_disconnect_test() -> None:
    path = ROOT / "tests/test_http_response_write_disconnect_safety.py"
    text = path.read_text(encoding="utf-8")
    old = '''        def stream_route(self, messages, workflow_run_id, *, model_name, include_usage=False):\n            del messages, workflow_run_id, model_name\n            assert include_usage is True\n            yield "answer"\n'''
    new = '''        def stream_route(\n            self,\n            messages,\n            workflow_run_id,\n            *,\n            model_name,\n            include_usage=False,\n            usage_callback=None,\n        ):\n            del messages, workflow_run_id, model_name\n            assert include_usage is True\n            yield "answer"\n            assert usage_callback is not None\n            usage_callback(\n                {"prompt_tokens": 2, "completion_tokens": 4, "total_tokens": 6}\n            )\n'''
    path.write_text(replace_once(text, old, new, "stream usage test double"), encoding="utf-8")


def patch_streaming_tests() -> None:
    relative = "tests/test_streaming.py"
    run("git", "checkout", "origin/main", "--", relative)
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''            "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},\n        },\n        include_usage=True,\n''',
        '''            "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},\n            "cost": {"measurement_status": "measured"},\n        },\n        include_usage=True,\n''',
        "unit usage measurement status",
    )
    text = replace_once(
        text,
        '''        "total_tokens": 5,\n        "usage_source": "reported",\n''',
        '''        "total_tokens": 5,\n''',
        "unit raw usage",
    )
    text = replace_once(
        text,
        '''        "total_tokens": 10,\n        "usage_source": "reported",\n''',
        '''        "total_tokens": 10,\n''',
        "live raw usage",
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    resolve_conflicts()
    patch_orchestrator()
    patch_server()
    patch_readme()
    patch_stream_option_tests()
    patch_disconnect_test()
    patch_streaming_tests()

    remaining = run("git", "diff", "--name-only", "--diff-filter=U", capture=True).stdout.strip()
    if remaining:
        raise RuntimeError(f"unresolved conflicts remain after semantic patch:\n{remaining}")


if __name__ == "__main__":
    main()
