"""OpenAI stream_options.include_usage — final SSE usage chunk for streaming clients."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import chat_completion_chunks  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "stream_options_token"  # noqa: S105


def _build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_chunks_include_usage_when_requested() -> None:
    result = {
        "answer": "hello stream",
        "mode": "route",
        "workflow_run_id": "run_usage",
        "usage": {"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15},
    }
    without = chat_completion_chunks(result, model="mock-generalist")
    assert "usage" not in without[-1]

    with_usage = chat_completion_chunks(
        result,
        model="mock-generalist",
        include_usage=True,
        usage=result["usage"],
    )
    assert with_usage[-2]["choices"][0]["finish_reason"] == "stop"
    final = with_usage[-1]
    assert final["choices"] == []
    assert final["usage"] == result["usage"]
    assert final["object"] == "chat.completion.chunk"


def test_stream_options_unknown_key_rejected() -> None:
    server = build_server(_build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": True,
                    "stream_options": {"include_usage": True, "bogus": 1},
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
            raise AssertionError("expected HTTPError")
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 400
            assert body["error"]["code"] == "invalid_stream_options"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_stream_include_usage_final_chunk() -> None:
    """Buyer path: OpenAI SDKs that set stream_options.include_usage get token usage."""
    server = build_server(_build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "messages": [{"role": "user", "content": "stream with usage please"}],
                    "orchestration": "route",
                    "stream": True,
                    "stream_options": {"include_usage": True},
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            assert "text/event-stream" in response.headers.get("content-type", "")
            raw = response.read().decode("utf-8")
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert raw.strip().endswith("data: [DONE]")
    events = []
    for block in raw.split("\n\n"):
        if not block.startswith("data: "):
            continue
        payload = block[len("data: ") :].strip()
        if payload == "[DONE]":
            continue
        events.append(json.loads(payload))

    usage_events = [e for e in events if e.get("usage") is not None and e.get("choices") == []]
    assert len(usage_events) == 1, events
    usage = usage_events[0]["usage"]
    assert usage["prompt_tokens"] > 0
    assert usage["completion_tokens"] > 0
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
    # usage chunk is last content event before [DONE]
    assert events[-1] is usage_events[0]


if __name__ == "__main__":
    test_chunks_include_usage_when_requested()
    test_stream_options_unknown_key_rejected()
    test_http_stream_include_usage_final_chunk()
    print("ok")
