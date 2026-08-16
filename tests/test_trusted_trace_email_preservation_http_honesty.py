"""Trusted traces keep operational email; credentials stay redacted.

Invoice, HR, and support tickets name a person. Irreversible email masking on
the trusted-caller trace makes those tickets unworkable. Access control (trace
only when the caller opts in) plus credential redaction is the SOC 2 / CSAP
control; see NIST SP 800-122 and NIST SP 800-53 Rev. 5 AU-2.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "trusted_trace_email_preservation_http_honesty_token"  # noqa: S105
_INVOICE_EMAIL = "alice@example.com"
_INVOICE_PROMPT = f"Refund invoice 8841 for {_INVOICE_EMAIL}"


def build() -> TaskOrchestrator:
    """Return a single-mock-agent orchestrator for isolated HTTP honesty probes."""
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    """POST JSON to loopback chat completions and return status plus body."""
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server():
    """Start a daemon stdlib server that hides traces unless the caller opts in."""
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(
            auth_token=_TEST_AUTH_TOKEN,
            expose_trace_by_default=False,
            rate_limit_requests=10_000,
        ),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_trusted_trace_keeps_invoice_email() -> None:
    """A support refund prompt must still name the customer on the trusted trace."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": _INVOICE_PROMPT}],
                "include_orchestration_trace": True,
            },
        )
        assert status == 200, body
        blob = json.dumps(body)
        assert _INVOICE_EMAIL in blob
        trace = (body.get("orchestration") or {}).get("trace") or []
        assert trace, body
        assert any(_INVOICE_EMAIL in json.dumps(step) for step in trace), trace
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_trusted_trace_still_redacts_bearer_secret() -> None:
    """Credential material in a worker output must stay [REDACTED] on the trace."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {
                        "role": "user",
                        "content": "Rotate Bearer abcdefghijklmnopqrstuvwxyz for alice@example.com",
                    }
                ],
                "include_orchestration_trace": True,
            },
        )
        assert status == 200, body
        trace = (body.get("orchestration") or {}).get("trace") or []
        assert trace, body
        blob = json.dumps(trace)
        assert "alice@example.com" in blob
        assert "Bearer [REDACTED]" in blob
        assert "abcdefghijklmnopqrstuvwxyz" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_untrusted_caller_omits_trace_email() -> None:
    """Default callers must not receive orchestration.trace on an invoice prompt."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": _INVOICE_PROMPT}],
            },
        )
        assert status == 200, body
        orchestration = body.get("orchestration") or {}
        assert "trace" not in orchestration, orchestration
        assert orchestration.get("mode") == "route"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_trusted_trace_keeps_invoice_email()
    test_http_trusted_trace_still_redacts_bearer_secret()
    test_http_untrusted_caller_omits_trace_email()
    print("ok")
