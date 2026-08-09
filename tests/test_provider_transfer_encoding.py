"""Regression tests for fail-closed provider Transfer-Encoding handling.

The provider transport supports the HTTP/1.1 ``chunked`` transfer coding that
Python's ``http.client`` decodes. Other transfer-coding chains are valid in parts
of HTTP/1.1 but are outside this product's decoding contract, so they must be
rejected before application parsing rather than treated as an opaque body.
"""

from __future__ import annotations

import http.client
from unittest import mock

import pytest

from contextual_orchestrator.provider_transport import _ProviderHTTPResponse


class _TransferEncodingResponse(http.client.HTTPResponse):
    """HTTPResponse-shaped double exposing only reviewed framing metadata."""

    def __init__(self, transfer_encoding: str | None) -> None:
        """Store one provider-controlled Transfer-Encoding field value."""
        self._transfer_encoding = transfer_encoding
        self._closed_record = False

    @property
    def closed(self) -> bool:
        """Expose deterministic cleanup without an initialized socket file."""
        return self._closed_record

    def getheader(self, name: str, default: str | None = None) -> str | None:
        """Return framing headers using HTTP's case-insensitive field names."""
        lowered = name.lower()
        if lowered == "transfer-encoding":
            return self._transfer_encoding
        if lowered == "content-length":
            return None
        return default

    def close(self) -> None:
        """Record deterministic response cleanup."""
        self._closed_record = True


@pytest.mark.parametrize(
    "transfer_encoding",
    [
        "gzip",
        "gzip, chunked",
        "chunked, chunked",
        "chunked;foo=bar",
        "identity",
        "",
    ],
)
def test_unsupported_transfer_encoding_fails_closed_before_body_consumption(
    transfer_encoding: str,
) -> None:
    """Only the stdlib-decoded single chunked coding is accepted by the product."""
    response = _TransferEncodingResponse(transfer_encoding)
    connection = mock.Mock()

    with pytest.raises(RuntimeError, match="transfer encoding is unsupported"):
        _ProviderHTTPResponse(response, connection, max_bytes=32)

    assert response.closed is True
    connection.close.assert_called_once_with()


@pytest.mark.parametrize("transfer_encoding", ["chunked", "Chunked", "CHUNKED"])
def test_single_chunked_transfer_encoding_remains_supported(
    transfer_encoding: str,
) -> None:
    """HTTP/1.1 chunked framing remains compatible with bounded body reads."""
    response = _TransferEncodingResponse(transfer_encoding)
    connection = mock.Mock()

    wrapper = _ProviderHTTPResponse(response, connection, max_bytes=32)
    wrapper.close()

    assert response.closed is True
    connection.close.assert_called_once_with()
