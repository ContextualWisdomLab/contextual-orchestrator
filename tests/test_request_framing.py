"""Fail-closed inbound HTTP request framing for JSON bodies."""
from __future__ import annotations

import json
import socket
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TOKEN = "secret_token"  # noqa: S105


def _start():
    orch = TaskOrchestrator([ModelAgent("general_agent", "mock-generalist", tags=("reasoning",))])
    server = build_server(orch, port=0, security=SecurityConfig(auth_token=_TOKEN, max_body_bytes=64))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def _raw_post(port: int, extra_headers: list[str], body: bytes) -> tuple[int, bytes]:
    request = (
        f"POST /v1/chat/completions HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{port}\r\n"
        f"Authorization: Bearer {_TOKEN}\r\n"
        f"Connection: close\r\n"
        + "".join(h + "\r\n" for h in extra_headers)
        + "\r\n"
    ).encode("ascii") + body
    with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
        sock.settimeout(3)
        sock.sendall(request)
        chunks: list[bytes] = []
        while True:
            try:
                data = sock.recv(4096)
            except TimeoutError:
                break
            if not data:
                break
            chunks.append(data)
    raw = b"".join(chunks)
    status_line = raw.split(b"\r\n", 1)[0]
    code = int(status_line.split()[1])
    return code, raw


def test_negative_content_length_is_rejected() -> None:
    server, thread, port = _start()
    try:
        code, raw = _raw_post(
            port,
            ["Content-Type: application/json", "Content-Length: -1"],
            b'{"messages":[{"role":"user","content":"x"}]}',
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert code == 400
    assert b"invalid_content_length" in raw or b"invalid_request" in raw or b"request_framing" in raw


def test_non_decimal_content_length_is_rejected() -> None:
    server, thread, port = _start()
    try:
        code, raw = _raw_post(
            port,
            ["Content-Type: application/json", "Content-Length: 12abc"],
            b"{}",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert code == 400


def test_oversized_content_length_is_rejected() -> None:
    server, thread, port = _start()
    try:
        code, raw = _raw_post(
            port,
            ["Content-Type: application/json", "Content-Length: 65"],
            b"x" * 65,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert code == 413
    assert b"request_too_large" in raw


def test_missing_content_length_is_rejected_for_json_post() -> None:
    server, thread, port = _start()
    try:
        code, raw = _raw_post(
            port,
            ["Content-Type: application/json"],
            b'{"messages":[{"role":"user","content":"x"}]}',
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert code == 411 or code == 400


def test_valid_small_json_body_still_works() -> None:
    server, thread, port = _start()
    body = b'{"messages":[{"role":"user","content":"hi"}]}'
    try:
        code, raw = _raw_post(
            port,
            ["Content-Type: application/json", f"Content-Length: {len(body)}"],
            body,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert code == 200
    assert b"chat.completion" in raw or b"choices" in raw


if __name__ == "__main__":
    test_negative_content_length_is_rejected()
    test_non_decimal_content_length_is_rejected()
    test_oversized_content_length_is_rejected()
    test_missing_content_length_is_rejected_for_json_post()
    test_valid_small_json_body_still_works()
    print("ok")
