"""Fail-closed inbound HTTP request framing regressions."""

from __future__ import annotations

from email.message import Message
import io
import socket
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    RequestError,
    SecurityConfig,
    _parse_request_framing,
    build_server,
)


class _FakeConnection:
    """Record socket timeout changes made by the bounded body reader."""

    def __init__(self) -> None:
        self.timeout: float | None = None

    def gettimeout(self) -> float | None:
        """Return the current synthetic socket timeout."""
        return self.timeout

    def settimeout(self, value: float | None) -> None:
        """Record a synthetic socket timeout."""
        self.timeout = value


class _TimeoutReader:
    """Raise a real socket timeout to exercise request deadline handling."""

    def read(self, _size: int) -> bytes:
        """Raise a bounded-read timeout."""
        raise socket.timeout("test timeout")


class _ExplodingReader:
    """Fail if framing validation accidentally consumes bytes."""

    def read(self, _size: int) -> bytes:
        """Report an invalid unbounded read."""
        raise AssertionError("request bytes were consumed before framing validation")


class _GetAllHeaders:
    """Expose only the standard get_all header API."""

    def get_all(self, field_name: str, _default: list[str]) -> list[str]:
        """Return one valid fixed-length field."""
        return [] if field_name.casefold() == "transfer-encoding" else ["1"]


class _GetHeaders:
    """Expose only a mapping-like get API."""

    def get(self, field_name: str) -> str | None:
        """Return one valid fixed-length field."""
        return None if field_name.casefold() == "transfer-encoding" else "1"


def _headers(content_length: str | None = None, *, transfer_encoding: str | None = None) -> Message:
    """Build raw-like headers for the pure framing and handler tests."""
    headers = Message()
    headers["content-type"] = "application/json"
    if content_length is not None:
        headers["content-length"] = content_length
    if transfer_encoding is not None:
        headers["transfer-encoding"] = transfer_encoding
    return headers


def _handler(headers: Message, body: bytes | object, *, timeout: float = 1.0):
    """Create the real nested request handler without opening a listening socket."""
    server = build_server(
        TaskOrchestrator([ModelAgent("general_agent", "mock-generalist")]),
        port=0,
        security=SecurityConfig(auth_token="test_token", request_read_timeout_seconds=timeout),
    )
    handler = server.RequestHandlerClass.__new__(server.RequestHandlerClass)
    handler.headers = headers
    handler.rfile = body if hasattr(body, "read") else io.BytesIO(body)
    handler.connection = _FakeConnection()
    handler.close_connection = False
    return server, handler


@pytest.mark.parametrize("value", ["-1", "+1", " 1", "1 ", "1.0", "1,1", ""])
def test_invalid_content_length_is_rejected_before_read(value: str) -> None:
    """Reject signed, padded, non-decimal, and comma-ambiguous lengths."""
    with pytest.raises(RequestError, match="content-length"):
        _parse_request_framing(_headers(value), 64)


def test_missing_length_and_transfer_encoding_fail_closed() -> None:
    """Require fixed-length framing and reject unsupported transfer coding."""
    with pytest.raises(RequestError, match="required") as missing:
        _parse_request_framing(_headers(), 64)
    assert missing.value.status == 411
    with pytest.raises(RequestError, match="transfer-encoded"):
        _parse_request_framing(_headers("1", transfer_encoding="chunked"), 64)


def test_header_value_fallbacks_and_integer_overflow_are_safe() -> None:
    """Support ordinary header mappings without weakening strict parsing."""
    assert _parse_request_framing(_GetAllHeaders(), 64) == 1
    assert _parse_request_framing(_GetHeaders(), 64) == 1
    with pytest.raises(RequestError, match="invalid"):
        _parse_request_framing(_headers("9" * 5000), 64)


def test_duplicate_content_length_is_rejected_even_when_equal() -> None:
    """Do not choose a value when duplicate header lines are present."""
    headers = _headers("1")
    headers.add_header("Content-Length", "1")
    with pytest.raises(RequestError, match="duplicate"):
        _parse_request_framing(headers, 64)


def test_oversized_content_length_is_rejected_before_read() -> None:
    """Enforce the configured byte limit before touching the body stream."""
    with pytest.raises(RequestError) as error:
        _parse_request_framing(_headers("65"), 64)
    assert error.value.status == 413


def test_read_json_requires_exact_body_and_restores_timeout() -> None:
    """Read exactly the declared bytes and restore the connection timeout."""
    server, handler = _handler(_headers("7"), b'{"x":1}')
    try:
        assert handler._read_json() == {"x": 1}
        assert handler.connection.timeout is None
        assert handler.close_connection is False
    finally:
        server.server_close()


def test_zero_length_json_body_is_framing_valid_and_returns_empty_object() -> None:
    """Leave endpoint-level required-field validation to the existing caller."""
    server, handler = _handler(_headers("0"), b"")
    try:
        assert handler._read_json() == {}
        assert handler.close_connection is False
    finally:
        server.server_close()


def test_read_json_rejects_truncated_body_and_closes_connection() -> None:
    """Reject premature EOF rather than decoding a partial request."""
    server, handler = _handler(_headers("7"), b'{"x":')
    try:
        with pytest.raises(RequestError, match="ended before"):
            handler._read_json()
        assert handler.close_connection is True
    finally:
        server.server_close()


def test_read_json_rejects_invalid_framing_without_consuming_body() -> None:
    """Mark the connection closed when framing fails before the first read."""
    server, handler = _handler(_headers("-1"), _ExplodingReader())
    try:
        with pytest.raises(RequestError, match="content-length"):
            handler._read_json()
        assert handler.close_connection is True
    finally:
        server.server_close()


def test_read_json_times_out_slow_body_and_closes_connection() -> None:
    """Release a handler blocked on an incomplete declared body."""
    server, handler = _handler(_headers("1"), _TimeoutReader(), timeout=0.1)
    try:
        with pytest.raises(RequestError, match="timed out") as error:
            handler._read_json()
        assert error.value.status == 408
        assert handler.close_connection is True
        assert handler.connection.timeout is None
    finally:
        server.server_close()


def test_security_config_rejects_unbounded_body_read_timeout() -> None:
    """Keep deployment-provided body deadlines finite and bounded."""
    with pytest.raises(ValueError, match="request_read_timeout_seconds"):
        SecurityConfig(request_read_timeout_seconds=float("inf"))
    with pytest.raises(ValueError, match="max_body_bytes"):
        SecurityConfig(max_body_bytes=0)


def test_security_readiness_exposes_bounded_request_controls() -> None:
    """Let operators verify the active body limit and deadline without secrets."""
    profile = SecurityConfig(max_body_bytes=128, request_read_timeout_seconds=2.0).readiness_profile()
    assert profile["max_body_bytes"] == 128
    assert profile["request_read_timeout_seconds"] == 2.0
