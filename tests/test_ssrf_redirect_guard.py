"""Egress guard must re-validate redirect targets (SSRF-via-3xx defense).

``_validate_provider`` guards only the first-hop host, but the request is
executed through ``ModelClient._opener``; a provider that answers ``302`` ->
an internal address must NOT be followed. See ``_EgressGuardedRedirectHandler``.
"""
from __future__ import annotations

import http.client
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contextual_orchestrator.orchestrator import (  # noqa: E402
    ModelClient,
    _assert_public_redirect_host,
    _EgressGuardedRedirectHandler,
)


def _serve(handler: type[BaseHTTPRequestHandler]) -> tuple[HTTPServer, int]:
    """Start a daemon loopback HTTP server and return (server, port)."""
    srv = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def test_open_provider_refuses_redirect_to_a_blocked_internal_address() -> None:
    """A provider 302 -> loopback metadata address must not be followed/returned."""

    class Internal(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"internal":"metadata-secret"}')

        def log_message(self, *a: object) -> None:
            return

    internal_srv, internal_port = _serve(Internal)
    target = f"http://127.0.0.1:{internal_port}/latest/meta-data/"

    class Provider(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()

        def log_message(self, *a: object) -> None:
            return

    provider_srv, provider_port = _serve(Provider)
    client = ModelClient()
    request = urllib.request.Request(
        f"http://127.0.0.1:{provider_port}/chat/completions",
        data=b"{}",
        headers={"content-type": "application/json"},
        method="POST",
    )
    followed_url = leaked_body = error = None
    try:
        with client._open_provider(request) as response:
            followed_url = response.geturl()
            leaked_body = response.read().decode()
    except (RuntimeError, urllib.error.URLError) as exc:  # fail-closed is correct
        error = exc
    finally:
        internal_srv.shutdown()
        provider_srv.shutdown()

    # The internal loopback target must never be reached or its body returned,
    # whether the guard refuses the redirect (raises) or declines to follow it.
    if error is None:
        assert "127.0.0.1" not in (followed_url or ""), followed_url
        assert "metadata-secret" not in (leaked_body or "")
    else:
        assert "metadata-secret" not in str(error)
        assert "non-public address" in str(error)


def test_assert_public_redirect_host_allows_public_blocks_internal() -> None:
    """The shared helper permits a public IP and rejects loopback/private ones."""
    _assert_public_redirect_host("8.8.8.8", 443)  # public: must not raise
    for blocked in ("127.0.0.1", "169.254.169.254", "10.0.0.1"):
        raised = False
        try:
            _assert_public_redirect_host(blocked, 80)
        except RuntimeError as exc:
            raised = True
            assert "non-public address" in str(exc)
        assert raised, f"{blocked} should be rejected"


def test_redirect_handler_rejects_non_http_scheme_and_follows_public() -> None:
    """The handler refuses non-http(s) / internal targets and defers public ones."""
    handler = _EgressGuardedRedirectHandler()
    req = urllib.request.Request("http://8.8.8.8/orig")
    headers = http.client.HTTPMessage()

    # Non-http(s) scheme (e.g. file://) is refused outright.
    raised = False
    try:
        handler.redirect_request(req, None, 302, "Found", headers, "file:///etc/passwd")
    except RuntimeError as exc:
        raised = True
        assert "non-http(s)" in str(exc)
    assert raised

    # A blocked internal host is refused.
    raised = False
    try:
        handler.redirect_request(req, None, 302, "Found", headers, "http://127.0.0.1/x")
    except RuntimeError:
        raised = True
    assert raised

    # A public target defers to the default handler, producing a redirect Request.
    result = handler.redirect_request(req, None, 302, "Found", headers, "http://8.8.8.8/new")
    assert isinstance(result, urllib.request.Request)
    assert result.full_url == "http://8.8.8.8/new"


if __name__ == "__main__":
    test_open_provider_refuses_redirect_to_a_blocked_internal_address()
    test_assert_public_redirect_host_allows_public_blocks_internal()
    test_redirect_handler_rejects_non_http_scheme_and_follows_public()
    print("ok")
