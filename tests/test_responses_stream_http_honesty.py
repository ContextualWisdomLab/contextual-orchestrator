"""Responses stream=true is framed as official SSE and matches non-stream text.

Official Responses SDKs default to streaming (OpenAI, 2024e). The gateway
frames the completed passthrough JSON as ``response.created``,
``response.output_text.delta``, and ``response.completed`` events so a buyer
can use ``client.responses.create(..., stream=True)`` without a silent 400.
Concatenated deltas must equal the non-stream ``output_text``.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import (  # noqa: E402
    response_output_text,
    response_stream_events,
    responses_sse_body,
)
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "responses_stream_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post_raw(port: int, payload: dict) -> tuple[int, str, str]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return (
                response.status,
                response.headers.get("content-type", ""),
                response.read().decode("utf-8"),
            )
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("content-type", ""), exc.read().decode("utf-8")


def _server():
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def _parse_sse_events(body: str) -> list[dict]:
    events: list[dict] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload == "[DONE]":
                    continue
                data_lines.append(payload)
        if not data_lines:
            continue
        events.append(json.loads("".join(data_lines)))
    return events


def _output_text_from_response(payload: dict) -> str:
    texts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and part.get("type") == "output_text":
                texts.append(str(part.get("text") or ""))
    return "".join(texts)


def test_response_stream_events_reconstruct_output_text() -> None:
    payload = {
        "id": "resp_unit",
        "object": "response",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Hello framed stream"}],
            }
        ],
    }
    events = response_stream_events(payload)
    types = [event["type"] for event in events]
    assert types[0] == "response.created"
    assert types[-1] == "response.completed"
    streamed = "".join(
        event["delta"] for event in events if event["type"] == "response.output_text.delta"
    )
    assert streamed == "Hello framed stream"
    assert response_output_text(payload) == streamed
    body = responses_sse_body(events)
    assert "event: response.created" in body
    assert "event: response.output_text.delta" in body
    assert "event: response.completed" in body
    assert "[DONE]" not in body


def test_http_responses_stream_true_matches_non_stream_output_text() -> None:
    """Buyer accuracy: streamed deltas reconstruct the non-stream output_text."""
    server, thread, port = _server()
    try:
        json_status, json_type, json_raw = _post_raw(
            port,
            {"model": "mock-planner", "input": "stream accuracy"},
        )
        assert json_status == 200, json_raw
        assert "json" in json_type
        expected = _output_text_from_response(json.loads(json_raw))
        assert expected, json_raw

        stream_status, stream_type, stream_raw = _post_raw(
            port,
            {"model": "mock-planner", "input": "stream accuracy", "stream": True},
        )
        assert stream_status == 200, stream_raw
        assert "text/event-stream" in stream_type, stream_type

        events = _parse_sse_events(stream_raw)
        types = [event.get("type") for event in events]
        assert "response.created" in types, types
        assert "response.output_text.delta" in types, types
        assert "response.completed" in types, types

        streamed = "".join(
            event.get("delta", "")
            for event in events
            if event.get("type") == "response.output_text.delta"
        )
        assert streamed == expected, (streamed, expected)

        completed = next(event for event in events if event.get("type") == "response.completed")
        assert _output_text_from_response(completed.get("response") or {}) == expected
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_stream_false_stays_json() -> None:
    server, thread, port = _server()
    try:
        status, content_type, raw = _post_raw(
            port,
            {"model": "mock-planner", "input": "no stream", "stream": False},
        )
        assert status == 200, raw
        assert "json" in content_type
        assert json.loads(raw)["object"] == "response"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_response_stream_events_reconstruct_output_text()
    test_http_responses_stream_true_matches_non_stream_output_text()
    test_http_responses_stream_false_stays_json()
    print("ok")
