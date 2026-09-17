"""``_open_provider`` must bound the upstream error body it buffers.

On an HTTP >= 400 response the transport previously called ``response.read()``
with no size, buffering an attacker-controlled error body into memory before
wrapping it in ``urllib.error.HTTPError``. Classification only ever inspects
``MAX_PROVIDER_ERROR_BODY_BYTES`` of that body, so the unbounded read was pure
amplification: a hostile or broken provider could stream gigabytes on a request
that is rejected anyway.

The bound must NOT drop the local status/reason/headers -- those drive the
provider-failure taxonomy (401 vs 429 vs 503), so truncating the body must leave
the ``HTTPError`` status intact.
"""

from __future__ import annotations

import http.client
import json
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402
from contextual_orchestrator.provider_errors import (  # noqa: E402
    MAX_PROVIDER_ERROR_BODY_BYTES,
    classify_provider_failure,
    provider_error_body,
)

_DESTINATION = (socket.AF_INET, ("127.0.0.1", 443))


class _RecordingErrorResponse:
    """A >=400 response whose ``read`` records the requested size."""

    def __init__(self, body: bytes, status: int = 503) -> None:
        self._body = body
        self.status = status
        self.reason = "Service Unavailable"
        self.headers = {"content-type": "application/json"}
        self.requested_size: int | None = None
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        self.requested_size = size
        if size is None or size < 0:
            return self._body
        return self._body[:size]

    def close(self) -> None:
        self.closed = True


class _FakeConnection:
    """Stands in for ``http.client.HTTPConnection`` in ``_open_provider``."""

    last: "_FakeConnection | None" = None

    def __init__(self, response: _RecordingErrorResponse) -> None:
        self._response = response
        self.closed = False
        _FakeConnection.last = self

    def request(self, *args: object, **kwargs: object) -> None:
        pass

    def getresponse(self) -> _RecordingErrorResponse:
        return self._response

    def close(self) -> None:
        self.closed = True


def _request() -> urllib.request.Request:
    return urllib.request.Request(
        "http://provider.example/chat/completions",
        data=b"{}",
        headers={"content-type": "application/json"},
        method="POST",
    )


def _open(response: _RecordingErrorResponse) -> urllib.error.HTTPError:
    connection = _FakeConnection(response)
    with patch.object(http.client, "HTTPConnection", lambda *a, **k: connection):
        try:
            ModelClient()._open_provider(_request(), _DESTINATION)
        except urllib.error.HTTPError as error:
            return error
    raise AssertionError("_open_provider did not raise HTTPError for a >=400 response")


def test_error_body_read_is_bounded() -> None:
    """The error-body read requests exactly the classification cap, never all of it."""
    response = _RecordingErrorResponse(b"{}")
    _open(response)
    assert response.requested_size == MAX_PROVIDER_ERROR_BODY_BYTES + 1


def test_oversized_error_body_is_truncated_but_status_preserved() -> None:
    """A huge undeclared body is cut to the cap; the local status still classifies."""
    payload = b'{"error": {"message": "' + b"A" * (MAX_PROVIDER_ERROR_BODY_BYTES * 2) + b'"}}'
    response = _RecordingErrorResponse(payload, status=429)
    error = _open(response)

    body = error.read(MAX_PROVIDER_ERROR_BODY_BYTES * 4)
    assert len(body) <= MAX_PROVIDER_ERROR_BODY_BYTES
    assert len(body) < len(payload)
    assert error.code == 429
    assert (
        classify_provider_failure(error, agent_id="synthetic-agent", model="synthetic-model").retryable
        is True
    )


def test_in_bounds_error_body_reaches_classification_intact() -> None:
    """A normal-sized error body survives the bound and still parses downstream."""
    error = _open(_RecordingErrorResponse(b'{"error": {"message": "slow down upstream"}}'))
    assert error.code == 503
    assert json.loads(provider_error_body(error).decode("utf-8")) == {
        "error": {"message": "slow down upstream"}
    }
