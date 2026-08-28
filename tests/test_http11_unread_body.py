"""Raw-socket regressions for unread bodies on HTTP/1.1 connections."""

from __future__ import annotations

import socket
import threading
import urllib.error
import urllib.request

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.server import SecurityConfig, build_server


def _start(
    *,
    rate_limit_requests: int = 100,
    rate_limit_window_seconds: int = 60,
) -> tuple[object, threading.Thread, int]:
    """Start an authenticated gateway with a deterministic local model."""
    server = build_server(
        TaskOrchestrator([ModelAgent("persistent_agent", "mock-persistent")]),
        port=0,
        security=SecurityConfig(
            auth_token="persistent-token",
            rate_limit_requests=rate_limit_requests,
            rate_limit_window_seconds=rate_limit_window_seconds,
        ),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def _pipeline(port: int, first_request: bytes) -> bytes:
    """Send a body-bearing request followed by liveness on one connection."""
    second_request = (
        b"GET /healthz HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Connection: close\r\n\r\n"
    )
    with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
        connection.sendall(first_request + second_request)
        chunks: list[bytes] = []
        while True:
            chunk = connection.recv(4096)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)


def _post_headers(*, token: str, content_type: str, body: bytes) -> bytes:
    """Build one raw body-bearing POST without hiding framing details."""
    return (
        b"POST /v1/chat/completions HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        + f"Authorization: Bearer {token}\r\n".encode("ascii")
        + f"Content-Type: {content_type}\r\n".encode("ascii")
        + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        + body
    )


def _assert_single_closed_response(response: bytes, status: bytes) -> None:
    """Assert the rejected body cannot become another parsed request."""
    assert response.startswith(b"HTTP/1.1 " + status)
    assert response.lower().count(b"connection: close\r\n") == 1
    assert response.count(b"HTTP/1.1 ") == 1
    assert b'"status": "ok"' not in response


def test_auth_rejection_closes_connection_with_unread_body() -> None:
    """An unauthorized JSON body cannot desynchronize a persistent stream."""
    server, thread, port = _start()
    try:
        body = b'{"model":"mock-persistent"}'
        response = _pipeline(
            port,
            _post_headers(token="wrong-token", content_type="application/json", body=body),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    _assert_single_closed_response(response, b"401 ")


def test_non_json_rejection_closes_connection_with_unread_body() -> None:
    """A media-type rejection cannot leave its body for the request parser."""
    server, thread, port = _start()
    try:
        response = _pipeline(
            port,
            _post_headers(
                token="persistent-token",
                content_type="text/plain",
                body=b"synthetic unread body",
            ),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    _assert_single_closed_response(response, b"415 ")


def test_rate_limit_rejection_closes_connection_with_unread_body() -> None:
    """A pre-body rate-limit rejection closes before another request is parsed."""
    server, thread, port = _start(rate_limit_requests=1)
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=b"{}",
            headers={
                "authorization": "Bearer persistent-token",
                "content-type": "application/json",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=2)
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            exc.read()
        response = _pipeline(
            port,
            _post_headers(
                token="persistent-token",
                content_type="application/json",
                body=b'{"model":"mock-persistent"}',
            ),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    _assert_single_closed_response(response, b"429 ")


def test_zero_length_health_request_keeps_connection_alive() -> None:
    """Content-Length zero declares no unread bytes and preserves keep-alive."""
    server, thread, port = _start()
    try:
        response = _pipeline(
            port,
            b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\n\r\n",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert response.count(b"HTTP/1.1 200 ") == 2


def test_unsupported_method_with_body_closes_connection() -> None:
    """The stdlib 501 path cannot reinterpret an unread body as a request."""
    server, thread, port = _start()
    try:
        body = b"unread"
        response = _pipeline(
            port,
            b"PUT /healthz HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
            + body,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    _assert_single_closed_response(response, b"501 ")


def test_incomplete_request_headers_time_out_within_abuse_window() -> None:
    """A slow client cannot pin a request thread beyond the configured window."""
    server, thread, port = _start(rate_limit_window_seconds=1)
    assert server.RequestHandlerClass.timeout == 1.0
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
            connection.settimeout(3)
            connection.sendall(b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Slow: ")
            assert connection.recv(1) == b""
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
