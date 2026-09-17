"""Every HTTP response carries the server-generated request identity as a header.

Issue #1016: a caller could only correlate *failed* requests to gateway logs,
because the trusted request id reached error payloads alone. Success bodies
carry an unrelated ``chatcmpl-…`` id and no header existed, so a long-running
consumer could not tie a served request to the provider evidence recorded
under ``docs/doctoring/provider_request_correlation.md``.
"""
from __future__ import annotations

import http.client
import json
import re
import threading
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "request_id_header_token"  # noqa: S105
_SERVER_REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")
_CLIENT_SUPPLIED_ID = "untrusted-client-id"


def _build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("planner_agent", "mock-planner", tags=("planning", "reasoning"))]
    )


def _request(port: int, payload: dict, *, authorized: bool = True) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    try:
        headers = {
            "content-type": "application/json",
            "connection": "close",
            "x-request-id": _CLIENT_SUPPLIED_ID,
        }
        if authorized:
            headers["authorization"] = f"Bearer {_TEST_AUTH_TOKEN}"
        connection.request("POST", "/v1/chat/completions", json.dumps(payload), headers)
        response = connection.getresponse()
        raw = response.read()
        return response.status, {key.lower(): value for key, value in response.getheaders()}, raw
    finally:
        connection.close()


def _serve():
    server = build_server(_build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def _stop(server, thread) -> None:
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


def test_success_response_carries_server_request_id_header() -> None:
    server, thread, port = _serve()
    try:
        status, headers, raw = _request(
            port,
            {"model": "mock-planner", "messages": [{"role": "user", "content": "say hi"}], "mode": "route"},
        )
        assert status == 200, raw
        assert "choices" in json.loads(raw)
        request_id = headers.get("x-request-id")
        assert request_id and _SERVER_REQUEST_ID.match(request_id), headers
        assert request_id != _CLIENT_SUPPLIED_ID
    finally:
        _stop(server, thread)


def test_error_response_header_matches_body_request_id() -> None:
    server, thread, port = _serve()
    try:
        status, headers, raw = _request(
            port,
            {"model": "mock-planner", "messages": [{"role": "user", "content": "say hi"}]},
            authorized=False,
        )
        assert status == 401, raw
        body_request_id = json.loads(raw)["error"]["detail"]["request_id"]
        assert headers.get("x-request-id") == body_request_id
        assert body_request_id != _CLIENT_SUPPLIED_ID
    finally:
        _stop(server, thread)


def test_streaming_response_carries_server_request_id_header() -> None:
    server, thread, port = _serve()
    try:
        status, headers, raw = _request(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "say hi"}],
                "mode": "route",
                "stream": True,
            },
        )
        assert status == 200, raw
        assert headers.get("content-type", "").startswith("text/event-stream")
        request_id = headers.get("x-request-id")
        assert request_id and _SERVER_REQUEST_ID.match(request_id), headers
        assert request_id != _CLIENT_SUPPLIED_ID
    finally:
        _stop(server, thread)


if __name__ == "__main__":  # pragma: no cover
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok {_name}")
    print("ok")
