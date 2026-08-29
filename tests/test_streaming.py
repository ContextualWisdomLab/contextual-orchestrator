"""SSE streaming for /v1/chat/completions — OpenAI-compatible chat.completion.chunk frames.

Streaming is table-stakes for a drop-in OpenAI-compatible gateway. These assert the
chunk shape, the SSE framing/[DONE] terminator, the end-to-end HTTP contract, and that
the non-streaming default is unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import chat_completion_chunks, chat_completion_response, sse_stream_body  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


def _build() -> TaskOrchestrator:
    return TaskOrchestrator([ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))])


def test_chunks_reconstruct_answer_with_openai_shape() -> None:
    result = {"answer": "Hello streaming world " * 5, "mode": "route", "workflow_run_id": "run_abc"}
    chunks = chat_completion_chunks(result, model="contextual-orchestrator")

    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant"}
    assert all(chunk["object"] == "chat.completion.chunk" for chunk in chunks)
    assert len({chunk["id"] for chunk in chunks}) == 1  # one completion id across all frames

    content = "".join(
        chunk["choices"][0]["delta"].get("content", "")
        for chunk in chunks
        if "content" in chunk["choices"][0]["delta"]
    )
    assert content == result["answer"]  # deltas losslessly reconstruct the full answer

    final = chunks[-1]
    assert final["choices"][0]["finish_reason"] == "stop"
    assert final["choices"][0]["delta"] == {}
    assert final["orchestration"]["mode"] == "route"
    assert final["orchestration"]["workflow_run_id"] == "run_abc"


def test_empty_answer_produces_role_and_stop_only() -> None:
    chunks = chat_completion_chunks({"answer": "", "mode": "route"})
    assert len(chunks) == 2  # role delta + stop delta, no content frames
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant"}
    assert chunks[1]["choices"][0]["finish_reason"] == "stop"


def test_chunks_include_requested_provider_usage_after_stop() -> None:
    usage = {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8}
    chunks = chat_completion_chunks(
        {
            "answer": "OK",
            "mode": "route",
            "usage": usage,
            "cost": {"measurement_status": "measured"},
        },
        include_usage=True,
    )

    assert chunks[-2]["choices"][0]["finish_reason"] == "stop"
    assert chunks[-1]["choices"] == []
    assert chunks[-1]["usage"] == usage


def test_chunks_omit_estimated_usage_even_when_requested() -> None:
    chunks = chat_completion_chunks(
        {
            "answer": "OK",
            "mode": "conduct",
            "usage": {"prompt_tokens": 3, "completion_tokens": 5},
            "cost": {"measurement_status": "estimated"},
        },
        include_usage=True,
    )

    assert all("usage" not in chunk for chunk in chunks)


def test_completion_ids_remain_unique_when_created_in_one_millisecond() -> None:
    result = {"answer": "OK", "mode": "route"}
    with patch("contextual_orchestrator.orchestrator.time.time", return_value=1_786_698_100.0):
        response_ids = {chat_completion_response(result)["id"] for _ in range(128)}
        chunk_ids = {chat_completion_chunks(result)[0]["id"] for _ in range(128)}

    assert len(response_ids) == 128
    assert len(chunk_ids) == 128


def test_sse_body_frames_and_done_terminator() -> None:
    body = sse_stream_body(chat_completion_chunks({"answer": "abc", "mode": "route"}))
    assert body.endswith("data: [DONE]\n\n")
    frames = [f for f in body.split("\n\n") if f]
    assert frames[-1] == "data: [DONE]"
    for frame in frames[:-1]:
        assert frame.startswith("data: ")
        json.loads(frame[len("data: ") :])  # every non-terminator frame is valid JSON


def _post(url: str, payload: dict, token: str) -> tuple[int, str, str]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json", "authorization": f"Bearer {token}", "connection": "close"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.headers.get("content-type", ""), response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("content-type", ""), exc.read().decode("utf-8")


def _serve() -> tuple[object, int, str]:
    token = "stream_token"
    server = build_server(_build(), port=0, security=SecurityConfig(auth_token=token))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1], token


def test_http_stream_true_returns_event_stream_and_reconstructs_answer() -> None:
    server, port, token = _serve()
    url = f"http://127.0.0.1:{port}/v1/chat/completions"
    payload = {"model": "mock-generalist", "messages": [{"role": "user", "content": "stream please"}]}
    try:
        # Non-streaming reference answer.
        _, ref_ct, ref_body = _post(url, payload, token)
        reference = json.loads(ref_body)["choices"][0]["message"]["content"]

        status, content_type, sse = _post(url, {**payload, "stream": True}, token)
    finally:
        server.shutdown()

    assert "application/json" in ref_ct
    assert status == 200
    assert content_type.startswith("text/event-stream")
    assert sse.endswith("data: [DONE]\n\n")

    streamed = ""
    for frame in sse.split("\n\n"):
        frame = frame.strip()
        if not frame.startswith("data: ") or frame == "data: [DONE]":
            continue
        chunk = json.loads(frame[len("data: ") :])
        streamed += chunk["choices"][0]["delta"].get("content", "")
    assert streamed == reference  # streamed deltas equal the non-streamed answer


def test_http_stream_false_is_unchanged_json() -> None:
    server, port, token = _serve()
    url = f"http://127.0.0.1:{port}/v1/chat/completions"
    try:
        status, content_type, body = _post(url, {"model": "mock-generalist", "messages": [{"role": "user", "content": "hi"}], "stream": False}, token)
    finally:
        server.shutdown()
    assert status == 200
    assert "application/json" in content_type
    payload = json.loads(body)
    assert payload["object"] == "chat.completion"
    assert payload["choices"][0]["message"]["role"] == "assistant"


def test_http_stream_non_boolean_is_rejected() -> None:
    server, port, token = _serve()
    url = f"http://127.0.0.1:{port}/v1/chat/completions"
    try:
        status, _, body = _post(url, {"model": "mock-generalist", "messages": [{"role": "user", "content": "hi"}], "stream": "yes"}, token)
    finally:
        server.shutdown()
    assert status == 400
    assert json.loads(body)["error"]["code"] == "invalid_request"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
