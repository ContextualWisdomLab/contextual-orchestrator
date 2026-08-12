"""CORS allowlist for browser OpenAI-compatible clients."""

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

_TEST_AUTH_TOKEN = "secret_token"  # noqa: S105
_ALLOWED_ORIGIN = "https://app.example.com"


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_cors_origin_allowed_matches_exact_and_star() -> None:
    security = SecurityConfig(auth_token=_TEST_AUTH_TOKEN, cors_allow_origins=(_ALLOWED_ORIGIN,))
    assert security.cors_origin_allowed(_ALLOWED_ORIGIN) == _ALLOWED_ORIGIN
    assert security.cors_origin_allowed("https://evil.example") is None
    assert security.cors_origin_allowed("") is None
    star = SecurityConfig(auth_token=_TEST_AUTH_TOKEN, cors_allow_origins=("*",))
    assert star.cors_origin_allowed("https://any.example") == "*"
    off = SecurityConfig(auth_token=_TEST_AUTH_TOKEN)
    assert off.cors_origin_allowed(_ALLOWED_ORIGIN) is None


def test_preflight_and_authenticated_response_echo_allowlisted_origin() -> None:
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(
            auth_token=_TEST_AUTH_TOKEN,
            cors_allow_origins=(_ALLOWED_ORIGIN,),
        ),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        preflight = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            method="OPTIONS",
            headers={
                "origin": _ALLOWED_ORIGIN,
                "access-control-request-method": "POST",
                "connection": "close",
            },
        )
        with urllib.request.urlopen(preflight, timeout=5) as response:
            assert response.status == 204
            allow_origin = response.headers.get("Access-Control-Allow-Origin") or response.headers.get(
                "access-control-allow-origin"
            )
            allow_methods = response.headers.get("Access-Control-Allow-Methods") or response.headers.get(
                "access-control-allow-methods"
            )
            credentials = response.headers.get("Access-Control-Allow-Credentials") or response.headers.get(
                "access-control-allow-credentials"
            )
            assert allow_origin == _ALLOWED_ORIGIN
            assert "POST" in (allow_methods or "")
            assert credentials == "true"

        denied = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            method="OPTIONS",
            headers={"origin": "https://evil.example", "connection": "close"},
        )
        try:
            urllib.request.urlopen(denied, timeout=5)
            raise AssertionError("expected 403 for non-allowlisted origin")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403

        chat = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "origin": _ALLOWED_ORIGIN,
                "connection": "close",
            },
            method="POST",
        )
        with urllib.request.urlopen(chat, timeout=5) as response:
            assert response.status == 200
            allow_origin = response.headers.get("Access-Control-Allow-Origin") or response.headers.get(
                "access-control-allow-origin"
            )
            assert allow_origin == _ALLOWED_ORIGIN
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_cors_disabled_by_default_omits_allow_origin_header() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        chat = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "origin": _ALLOWED_ORIGIN,
                "connection": "close",
            },
            method="POST",
        )
        with urllib.request.urlopen(chat, timeout=5) as response:
            assert response.status == 200
            allow_origin = response.headers.get("Access-Control-Allow-Origin") or response.headers.get(
                "access-control-allow-origin"
            )
            assert not allow_origin
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_cors_origin_allowed_matches_exact_and_star()
    test_preflight_and_authenticated_response_echo_allowlisted_origin()
    test_cors_disabled_by_default_omits_allow_origin_header()
    print("ok")
