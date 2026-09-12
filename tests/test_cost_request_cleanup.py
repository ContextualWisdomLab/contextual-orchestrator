"""The shared HTTP test client owns error responses on every parse outcome."""

import io
import json
import urllib.error
import urllib.request

import pytest

from test_cost_review_server import _request


@pytest.mark.parametrize("body_bytes", [b'{"error":"unit"}', b'not-json'])
def test_request_closes_http_error(monkeypatch, body_bytes):
    """Parsing errors must not leave the shared client's response open."""
    response_error = urllib.error.HTTPError("http://unit.invalid", 400, "unit", {}, io.BytesIO(body_bytes))

    def raise_response(request):
        raise response_error

    monkeypatch.setattr(urllib.request, "urlopen", raise_response)
    try:
        if body_bytes.startswith(b"{"):
            assert _request("GET", "http://unit.invalid") == (400, {"error": "unit"})
        else:
            with pytest.raises(json.JSONDecodeError):
                _request("GET", "http://unit.invalid")
        assert response_error.closed
    finally:
        response_error.close()
