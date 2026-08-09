"""Regression coverage for finite provider JSON numeric decoding.

RFC 8259 permits exponent notation, while Python's binary-float decoder can
materialize a syntactically valid but extreme exponent such as ``1e999`` as an
infinite runtime value. Provider-controlled JSON must never turn that parser
artifact into orchestration state, including the parser shared by streaming
server-sent events.
"""

from __future__ import annotations

from unittest import mock

import pytest

from contextual_orchestrator.provider_transport import _ProviderHTTPResponse


class _ByteResponse:
    """Provide one deterministic provider body to the bounded response wrapper."""

    def __init__(self, payload: bytes) -> None:
        """Store the provider-controlled bytes for one complete read."""
        self._payload = payload

    def read(self, amount: int | None = None) -> bytes:
        """Return at most ``amount`` bytes using ``HTTPResponse.read`` semantics."""
        if amount is None or amount < 0:
            amount = len(self._payload)
        chunk = self._payload[:amount]
        self._payload = self._payload[amount:]
        return chunk

    def close(self) -> None:
        """Match the response cleanup protocol used by the wrapper."""


@pytest.mark.parametrize("number", [b"1e999", b"-1e999"])
def test_provider_json_rejects_float_overflow_to_infinity(number: bytes) -> None:
    """Valid JSON exponents that overflow Python floats must fail closed."""
    wrapper = _ProviderHTTPResponse(
        _ByteResponse(b'{"value":' + number + b"}"),
        mock.Mock(),
        max_bytes=512,
    )

    with pytest.raises(RuntimeError, match="provider JSON response is malformed"):
        wrapper.read_json_object()


def test_provider_json_preserves_finite_exponent_numbers() -> None:
    """Ordinary finite exponent notation remains accepted after the hardening."""
    wrapper = _ProviderHTTPResponse(
        _ByteResponse(b'{"value":1.25e2}'),
        mock.Mock(),
        max_bytes=512,
    )

    assert wrapper.read_json_object() == {"value": 125.0}
