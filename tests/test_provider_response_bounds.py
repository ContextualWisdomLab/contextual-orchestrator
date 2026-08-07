"""Regression tests for bounded provider-response consumption.

These tests keep untrusted provider bodies from becoming an unbounded memory or
stream-processing surface. The production wrapper must enforce one cumulative
byte budget across ordinary reads and server-sent-event iteration and must close
both response and connection resources when the budget is exceeded.
"""

from __future__ import annotations

import http.client
from unittest import mock

import pytest

from contextual_orchestrator import provider_transport
from contextual_orchestrator.provider_transport import _ProviderHTTPResponse


class _ReadableResponse:
    """Small byte-stream double with observable bounded read calls."""

    def __init__(self, payload: bytes) -> None:
        """Store the payload and initialize read and cleanup evidence."""
        self._payload = payload
        self._offset = 0
        self.read_sizes: list[int | None] = []
        self.closed = False

    def read(self, amount: int | None = None) -> bytes:
        """Return at most ``amount`` bytes while recording the requested bound."""
        self.read_sizes.append(amount)
        if amount is None or amount < 0:
            amount = len(self._payload) - self._offset
        start = self._offset
        self._offset = min(len(self._payload), start + amount)
        return self._payload[start : self._offset]

    def close(self) -> None:
        """Record deterministic response cleanup."""
        self.closed = True

    def __iter__(self):
        """Yield the unread payload as one line for non-HTTP test-double fallback."""
        if self._offset >= len(self._payload):
            return iter(())
        payload = self._payload[self._offset :]
        self._offset = len(self._payload)
        return iter((payload,))


class _BoundedHTTPResponse(http.client.HTTPResponse):
    """HTTPResponse-shaped double whose readline calls expose their byte bound."""

    def __init__(self, lines: list[bytes]) -> None:
        """Initialize line data without opening a real socket."""
        self._lines = list(lines)
        self.readline_limits: list[int] = []
        self._closed_record = False

    @property
    def closed(self) -> bool:
        """Expose cleanup state without relying on an uninitialized IOBase socket."""
        return self._closed_record

    def readline(self, limit: int = -1) -> bytes:
        """Return one line, respecting the caller's requested maximum size."""
        self.readline_limits.append(limit)
        if not self._lines:
            return b""
        line = self._lines.pop(0)
        if limit >= 0 and len(line) > limit:
            self._lines.insert(0, line[limit:])
            return line[:limit]
        return line

    def close(self) -> None:
        """Record deterministic response cleanup."""
        self._closed_record = True


def test_default_provider_response_budget_is_eight_mibibytes() -> None:
    """The reviewed default keeps every provider response below eight MiB."""
    assert provider_transport.PROVIDER_RESPONSE_MAX_BYTES == 8 * 1024 * 1024


@pytest.mark.parametrize("invalid_limit", [0, -1, True, 1.5])
def test_provider_response_rejects_invalid_byte_budget(invalid_limit: object) -> None:
    """A non-positive, boolean, or non-integer byte budget fails closed."""
    with pytest.raises(ValueError, match="positive integer"):
        _ProviderHTTPResponse(_ReadableResponse(b""), mock.Mock(), max_bytes=invalid_limit)


def test_unbounded_read_probes_one_byte_past_remaining_budget() -> None:
    """A full read detects one-byte overflow without first buffering the whole body."""
    response = _ReadableResponse(b"abcde")
    connection = mock.Mock()
    wrapper = _ProviderHTTPResponse(response, connection, max_bytes=4)

    with pytest.raises(RuntimeError, match="response byte limit"):
        with wrapper:
            wrapper.read()

    assert response.read_sizes == [5]
    assert response.closed is True
    connection.close.assert_called_once_with()


def test_exact_limit_read_succeeds_and_explicit_small_reads_are_preserved() -> None:
    """Bodies at the limit succeed and caller-requested smaller reads stay bounded."""
    response = _ReadableResponse(b"abcd")
    connection = mock.Mock()
    wrapper = _ProviderHTTPResponse(response, connection, max_bytes=4)

    with wrapper:
        assert wrapper.read(2) == b"ab"
        assert wrapper.read(2) == b"cd"
        assert wrapper.read() == b""

    assert response.read_sizes == [2, 2, 1]
    assert response.closed is True
    connection.close.assert_called_once_with()


def test_explicit_read_larger_than_remaining_budget_cannot_bypass_limit() -> None:
    """A later oversized explicit read probes only remaining bytes plus one."""
    response = _ReadableResponse(b"abcde")
    wrapper = _ProviderHTTPResponse(response, mock.Mock(), max_bytes=4)

    assert wrapper.read(2) == b"ab"
    with pytest.raises(RuntimeError, match="response byte limit"):
        wrapper.read(99)
    assert response.read_sizes == [2, 3]


def test_negative_read_amount_is_treated_as_full_bounded_read() -> None:
    """HTTPResponse's negative full-read convention remains subject to the cap."""
    response = _ReadableResponse(b"abcde")
    wrapper = _ProviderHTTPResponse(response, mock.Mock(), max_bytes=4)

    with pytest.raises(RuntimeError, match="response byte limit"):
        wrapper.read(-1)
    assert response.read_sizes == [5]


def test_http_iteration_uses_bounded_readline_and_accepts_exact_budget() -> None:
    """SSE-style HTTP iteration never asks the socket for more than budget plus one."""
    response = _BoundedHTTPResponse([b"ab\n", b"c"])
    connection = mock.Mock()
    wrapper = _ProviderHTTPResponse(response, connection, max_bytes=4)

    with wrapper:
        assert list(wrapper) == [b"ab\n", b"c"]

    assert response.readline_limits == [5, 2, 1]
    assert response.closed is True
    connection.close.assert_called_once_with()


def test_http_iteration_rejects_cumulative_overflow_and_closes_resources() -> None:
    """A streaming provider cannot exceed the cumulative cap across multiple lines."""
    response = _BoundedHTTPResponse([b"abc\n", b"de"])
    connection = mock.Mock()
    wrapper = _ProviderHTTPResponse(response, connection, max_bytes=5)

    with pytest.raises(RuntimeError, match="response byte limit"):
        with wrapper:
            list(wrapper)

    assert response.readline_limits == [6, 2]
    assert response.closed is True
    connection.close.assert_called_once_with()


def test_non_http_response_iteration_fallback_is_still_cumulatively_bounded() -> None:
    """Existing lightweight response doubles retain iteration with the same cap."""
    response = _ReadableResponse(b"abcde")
    wrapper = _ProviderHTTPResponse(response, mock.Mock(), max_bytes=4)

    with pytest.raises(RuntimeError, match="response byte limit"):
        list(wrapper)
