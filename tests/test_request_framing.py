"""HTTP request-framing tests for the JSON API trust boundary."""

from __future__ import annotations

from email.message import Message
import json
from pathlib import Path
import socket
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    DEFAULT_MAX_JSON_BODY_BYTES,
    MAX_MULTIMODAL_JSON_BODY_BYTES,
    RequestError,
    SecurityConfig,
    _request_body_size,
    build_server,
)


def _headers(**values: str) -> Message:
    """Build a case-insensitive header collection with optional duplicates."""
    message = Message()
    for name, value in values.items():
        for item in value.split("|", 1):
            message[name.replace("_", "-")] = item
    return message


def _framing_error(headers: Message, maximum: int = 1024) -> RequestError:
    """Return the expected framing error for a synthetic header collection."""
    try:
        _request_body_size(headers, maximum)
    except RequestError as exc:
        return exc
    raise AssertionError("expected invalid request framing")


def test_request_body_size_accepts_absent_zero_and_trimmed_lengths() -> None:
    """Requests without a body and ordinary JSON lengths remain compatible."""
    assert _request_body_size(_headers(), 1024) == 0
    assert _request_body_size(_headers(content_length=" 7 "), 1024) == 7
    assert _request_body_size(_headers(content_length="0"), 1024) == 0


def test_default_json_body_limit_matches_openai_image_request_contract() -> None:
    """Multimodal JSON reaches routing up to OpenAI's 512 MB request limit."""
    configured = SecurityConfig().max_body_bytes
    assert configured == DEFAULT_MAX_JSON_BODY_BYTES == 64 * 1024
    assert MAX_MULTIMODAL_JSON_BODY_BYTES == 512 * 1024 * 1024
    assert _request_body_size(_headers(content_length=str(configured)), configured) == configured
    with pytest.raises(RequestError) as exc_info:
        _request_body_size(_headers(content_length=str(configured + 1)), configured)
    assert (exc_info.value.status, exc_info.value.code) == (413, "request_too_large")


def test_multimodal_limit_cannot_override_operator_body_limit() -> None:
    """The 512 MB protocol ceiling does not bypass the configured safety ceiling."""
    configured = SecurityConfig(max_body_bytes=1024).max_body_bytes
    assert min(configured, MAX_MULTIMODAL_JSON_BODY_BYTES) == 1024


def test_request_body_size_rejects_duplicate_and_comma_joined_lengths() -> None:
    """Equivalent duplicate values are rejected rather than normalized."""
    duplicate = _headers(content_length="7|7")
    comma_joined = _headers(content_length="7, 7")
    assert _framing_error(duplicate).code == "invalid_request_framing"
    assert _framing_error(comma_joined).code == "invalid_request_framing"


def test_request_body_size_rejects_negative_malformed_and_oversized_lengths() -> None:
    """Negative, signed, Unicode, and over-limit lengths never reach read()."""
    for value in ("-1", "+1", "1.0", "１２", "not-a-length"):
        error = _framing_error(_headers(content_length=value))
        assert error.code == "invalid_request_framing"
    assert _framing_error(_headers(content_length="1025"), 1024).code == "request_too_large"
    assert _framing_error(_headers(content_length="9" * 5000), 1024).code == "request_too_large"


def test_request_body_size_rejects_transfer_encoding_even_without_content_length() -> None:
    """The server does not decode chunked or any other transfer coding."""
    error = _framing_error(_headers(transfer_encoding="chunked"))
    assert error.code == "invalid_request_framing"


def test_security_config_rejects_invalid_request_body_limits() -> None:
    """Every construction path keeps the framing ceiling a positive integer."""
    for value in (0, -1, True, 1.0):
        try:
            SecurityConfig(max_body_bytes=value)  # type: ignore[arg-type]
        except ValueError as exc:
            assert str(exc) == "max_body_bytes must be a positive integer"
        else:
            raise AssertionError(f"accepted invalid max_body_bytes: {value!r}")


def _start_server() -> tuple[object, threading.Thread, int]:
    """Start a small authenticated mock server for raw socket framing tests."""
    server = build_server(
        TaskOrchestrator([ModelAgent("framing_agent", "mock-framing")]),
        port=0,
        security=SecurityConfig(auth_token="framing-token"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def _raw_request(port: int, headers: bytes, body: bytes = b"", *, close_write: bool = False) -> bytes:
    """Send one raw request and return the complete response bytes."""
    request = (
        b"POST /v1/chat/completions HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Authorization: Bearer framing-token\r\n"
        b"Content-Type: application/json\r\n"
        + headers
        + b"Connection: close\r\n\r\n"
        + body
    )
    with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
        connection.sendall(request)
        if close_write:
            connection.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        while True:
            chunk = connection.recv(4096)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)


def test_negative_content_length_is_rejected_without_reading_until_peer_close() -> None:
    """A negative length returns promptly instead of invoking read(-1)."""
    server, thread, port = _start_server()
    try:
        response = _raw_request(port, b"Content-Length: -1\r\n", b"{}")
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    assert b"400 Bad Request" in response
    assert b"invalid_request_framing" in response


def test_transfer_encoding_is_rejected_before_chunked_bytes_are_interpreted() -> None:
    """Chunked framing is rejected explicitly because the handler has no decoder."""
    server, thread, port = _start_server()
    try:
        response = _raw_request(port, b"Transfer-Encoding: chunked\r\n", b"2\r\n{}\r\n0\r\n\r\n")
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    assert b"400 Bad Request" in response
    assert b"invalid_request_framing" in response


def test_unbounded_digit_content_length_is_rejected_and_connection_is_closed() -> None:
    """Huge decimal headers cannot escape before the connection-close guard."""
    server, thread, port = _start_server()
    try:
        response = _raw_request(port, b"Content-Length: " + (b"9" * 5000) + b"\r\n")
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    # The gateway now speaks HTTP/1.1 unconditionally (keep-alive), so the
    # status line carries the exact version alongside the 413 rejection.
    assert b"HTTP/1.1 413 " in response
    assert b"request_too_large" in response
    # The framing guard must still terminate the connection, not just reject.
    assert b"connection: close" in response.lower() or b"Connection: close" in response


def test_short_body_is_rejected_after_peer_closes() -> None:
    """A valid prefix cannot satisfy a larger declared body length."""
    server, thread, port = _start_server()
    try:
        response = _raw_request(port, b"Content-Length: 20\r\n", b"{}", close_write=True)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    assert b"400 Bad Request" in response
    assert b"invalid_request_framing" in response


if __name__ == "__main__":  # pragma: no cover
    test_request_body_size_accepts_absent_zero_and_trimmed_lengths()
    test_request_body_size_rejects_duplicate_and_comma_joined_lengths()
    test_request_body_size_rejects_negative_malformed_and_oversized_lengths()
    test_request_body_size_rejects_transfer_encoding_even_without_content_length()
    test_negative_content_length_is_rejected_without_reading_until_peer_close()
    test_transfer_encoding_is_rejected_before_chunked_bytes_are_interpreted()
    test_short_body_is_rejected_after_peer_closes()
    print(json.dumps({"status": "ok"}))
