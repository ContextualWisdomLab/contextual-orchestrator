"""Regression coverage for fail-closed UTF-8 server-sent-event decoding."""

from __future__ import annotations

import http.client
from unittest import mock

import pytest

from contextual_orchestrator.provider_transport import _ProviderHTTPResponse


class _InvalidUtf8HTTPResponse(http.client.HTTPResponse):
    """HTTPResponse-shaped SSE double that emits one malformed UTF-8 line."""

    def __init__(self) -> None:
        """Initialize malformed stream bytes without opening a socket."""
        self._lines = [b"data: \xffprivate-upstream-detail\n"]
        self._closed_record = False

    @property
    def closed(self) -> bool:
        """Expose deterministic cleanup state."""
        return self._closed_record

    def getheader(self, name: str, default: str | None = None) -> str | None:
        """Expose only a valid SSE media type; framing headers remain absent."""
        if name.lower() == "content-type":
            return "text/event-stream; charset=utf-8"
        return default

    def readline(self, limit: int = -1) -> bytes:
        """Return malformed provider bytes while respecting the read bound."""
        if not self._lines:
            return b""
        line = self._lines.pop(0)
        if limit >= 0:
            return line[:limit]
        return line

    def close(self) -> None:
        """Record deterministic response cleanup."""
        self._closed_record = True


def test_invalid_utf8_sse_is_redacted_and_closes_resources() -> None:
    """Malformed provider UTF-8 fails closed without exposing provider text."""
    response = _InvalidUtf8HTTPResponse()
    connection = mock.Mock()
    wrapper = _ProviderHTTPResponse(response, connection, max_bytes=64)

    with pytest.raises(RuntimeError, match="malformed provider stream event") as error:
        with wrapper:
            list(wrapper)

    assert "private-upstream-detail" not in str(error.value)
    assert response.closed is True
    connection.close.assert_called_once_with()
