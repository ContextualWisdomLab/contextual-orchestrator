"""Test-owned HTTP resources close on success and decoding failures."""

import io
import json
import urllib.error

import pytest

from test_actions_model_fallback import _post
from test_true_streaming import _CapturingSSEProvider, _FakeSSEProvider


@pytest.mark.parametrize("provider_type", [_FakeSSEProvider, _CapturingSSEProvider])
def test_provider_context_closes_listening_socket(provider_type):
    """Leaving either provider context releases its real listening socket."""
    provider = provider_type([])
    try:
        with provider:
            assert provider._server.socket.fileno() >= 0
        assert provider._server.socket.fileno() == -1
        assert not provider._thread.is_alive()
    finally:
        provider._server.server_close()
        provider._thread.join()


@pytest.mark.parametrize("body_bytes", [b'{"error":"unavailable"}', b'not-json'])
def test_post_closes_error_body_even_when_decoding_fails(monkeypatch, body_bytes):
    """The shared HTTP helper owns error bodies, including invalid JSON."""
    body_stream = io.BytesIO(body_bytes)
    response_error = urllib.error.HTTPError(
        "http://127.0.0.1/", 502, "Bad Gateway", {}, body_stream
    )

    def raise_response_error(*args, **kwargs):
        raise response_error

    monkeypatch.setattr("urllib.request.urlopen", raise_response_error)
    try:
        if body_bytes == b'not-json':
            with pytest.raises(json.JSONDecodeError):
                _post(1, {})
        else:
            assert _post(1, {}) == (502, {"error": "unavailable"}, "application/json")
        assert body_stream.closed
    finally:
        response_error.close()
