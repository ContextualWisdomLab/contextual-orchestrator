"""Regression for a total inbound-body deadline, not only idle-socket timeout."""

from __future__ import annotations

from email.message import Message
from types import SimpleNamespace

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator import server as server_module
from contextual_orchestrator.server import RequestError, SecurityConfig, build_server


class _Clock:
    """Deterministic monotonic clock advanced by the synthetic slow reader."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


class _SlowProgressReader:
    """Return progress before every idle timeout while exceeding the total deadline."""

    def __init__(self, payload: bytes, clock: _Clock, step_seconds: float) -> None:
        self.payload = payload
        self.clock = clock
        self.step_seconds = step_seconds
        self.offset = 0

    def read(self, _size: int) -> bytes:
        if self.offset >= len(self.payload):
            return b""
        self.clock.now += self.step_seconds
        result = self.payload[self.offset : self.offset + 1]
        self.offset += 1
        return result


class _FakeConnection:
    """Expose the socket timeout methods used by the request reader."""

    def __init__(self) -> None:
        self.timeout: float | None = None

    def gettimeout(self) -> float | None:
        return self.timeout

    def settimeout(self, value: float | None) -> None:
        self.timeout = value


def _headers(body_size: int) -> Message:
    headers = Message()
    headers["content-type"] = "application/json"
    headers["content-length"] = str(body_size)
    return headers


def test_slow_progress_cannot_extend_request_past_total_deadline(monkeypatch) -> None:
    """A byte trickle below the idle timeout must still terminate at the deadline."""
    payload = b'{"x":1}'
    clock = _Clock()
    server = build_server(
        TaskOrchestrator([ModelAgent("general_agent", "mock-generalist")]),
        port=0,
        security=SecurityConfig(
            auth_token="test_token",
            request_read_timeout_seconds=0.1,
        ),
    )
    handler = server.RequestHandlerClass.__new__(server.RequestHandlerClass)
    handler.headers = _headers(len(payload))
    handler.rfile = _SlowProgressReader(payload, clock, step_seconds=0.06)
    handler.connection = _FakeConnection()
    handler.close_connection = False
    monkeypatch.setattr(
        server_module,
        "time",
        SimpleNamespace(monotonic=clock.monotonic),
    )

    try:
        with pytest.raises(RequestError, match="timed out") as error:
            handler._read_json()
        assert error.value.status == 408
        assert handler.close_connection is True
        assert handler.connection.timeout is None
    finally:
        server.server_close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
