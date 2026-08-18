"""ModelClient must not follow HTTP redirects from provider responses.

Strix found: urllib's default opener follows 301/302/303/307/308 without
re-running _validate_provider's private/loopback/link-local IP checks
against the redirect target, so a compromised or attacker-set agent
base_url could redirect a provider request into the internal network
(SSRF via redirect, e.g. to a cloud metadata endpoint). Chat-completions
endpoints have no legitimate reason to redirect, so the opener refuses
every redirect outright.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402


class _RedirectingHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        self.send_response(302)
        self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
        self.end_headers()

    def log_message(self, *args: object) -> None:  # silence test output
        pass


def test_provider_redirect_is_refused_not_followed() -> None:
    server = HTTPServer(("127.0.0.1", 0), _RedirectingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        request = urllib.request.Request(f"http://127.0.0.1:{port}/chat/completions")
        try:
            ModelClient()._open_provider(request)
        except urllib.error.HTTPError as exc:
            assert exc.code == 302
            assert "redirect refused" in str(exc)
        else:
            raise AssertionError("provider redirect should have been refused, not followed")
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":  # pragma: no cover
    test_provider_redirect_is_refused_not_followed()
    print("ok")
