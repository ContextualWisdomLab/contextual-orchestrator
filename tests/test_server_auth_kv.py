"""Gateway Bearer tokens resolve from the credential KV, never live env.

NIST SP 800-53 Rev. 5 IA-5 (authenticator management) and NIST SP 800-63B
require authenticators to be stored and resolved as secrets, not ambient
process environment. ``CONTEXTUAL_ORCHESTRATOR_TOKEN`` (and the split admin /
inference vars) remain bootstrap transport into
``gateway_auth_token`` / ``admin_auth_token`` / ``inference_auth_token``.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.credentials import (  # noqa: E402
    ADMIN_AUTH_TOKEN,
    GATEWAY_AUTH_TOKEN,
    INFERENCE_AUTH_TOKEN,
    InMemoryCredentialBackend,
    get_credential,
    register_credential,
    resolve_server_auth_tokens,
    seed_server_auth_from_environ,
    set_backend,
)
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402
from contextual_orchestrator.__main__ import serve_security_tokens  # noqa: E402

_TOKEN_ENV = "CONTEXTUAL_ORCHESTRATOR_TOKEN"
_ADMIN_ENV = "CONTEXTUAL_ORCHESTRATOR_ADMIN_TOKEN"
_INFERENCE_ENV = "CONTEXTUAL_ORCHESTRATOR_INFERENCE_TOKEN"


def _restore_env(name: str, previous: str | None) -> None:
    if previous is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = previous


def _build_orchestrator() -> TaskOrchestrator:
    return TaskOrchestrator([ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))])


def _post_chat(url: str, token: str) -> int:
    request = urllib.request.Request(
        url,
        data=json.dumps(
            {"model": "mock-generalist", "messages": [{"role": "user", "content": "hello"}]}
        ).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_seed_server_auth_from_environ_copies_once() -> None:
    """Bootstrap may copy env into KV once; a later seed() must not recopy env."""
    previous = os.environ.get(_TOKEN_ENV)
    set_backend(InMemoryCredentialBackend())
    os.environ[_TOKEN_ENV] = "first_gateway_token"
    try:
        seed_server_auth_from_environ()
        assert get_credential(GATEWAY_AUTH_TOKEN) == "first_gateway_token"
        os.environ[_TOKEN_ENV] = "evil_rotated_env"
        seed_server_auth_from_environ()
        assert get_credential(GATEWAY_AUTH_TOKEN) == "first_gateway_token"
        assert get_credential(GATEWAY_AUTH_TOKEN) != "evil_rotated_env"
    finally:
        set_backend(None)
        _restore_env(_TOKEN_ENV, previous)


def test_resolve_server_auth_tokens_ignores_live_environment() -> None:
    """A process env token must not win after the KV already holds a secret."""
    previous = os.environ.get(_TOKEN_ENV)
    set_backend(InMemoryCredentialBackend())
    try:
        register_credential(GATEWAY_AUTH_TOKEN, "kv_gateway_token")
        os.environ[_TOKEN_ENV] = "env_only_token"
        auth_token, admin_token, inference_token = resolve_server_auth_tokens()
        assert auth_token == "kv_gateway_token"
        assert admin_token == ""
        assert inference_token == ""
    finally:
        set_backend(None)
        _restore_env(_TOKEN_ENV, previous)


def test_explicit_cli_token_wins_over_kv() -> None:
    set_backend(InMemoryCredentialBackend())
    try:
        register_credential(GATEWAY_AUTH_TOKEN, "kv_gateway_token")
        auth_token, _, _ = resolve_server_auth_tokens(auth_token="cli_gateway_token")
        assert auth_token == "cli_gateway_token"
    finally:
        set_backend(None)


def test_http_authorize_uses_seeded_kv_not_later_env() -> None:
    """Buyer next action: seed once, then send the KV token. A later env edit is ignored."""
    previous = os.environ.get(_TOKEN_ENV)
    set_backend(InMemoryCredentialBackend())
    os.environ[_TOKEN_ENV] = "seeded_gateway_token"
    seed_server_auth_from_environ()
    os.environ[_TOKEN_ENV] = "later_env_token"
    auth_token, admin_token, inference_token = resolve_server_auth_tokens()
    server = build_server(
        _build_orchestrator(),
        port=0,
        security=SecurityConfig(
            auth_token=auth_token,
            admin_token=admin_token,
            inference_token=inference_token,
            rate_limit_requests=10_000,
        ),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        seeded_status = _post_chat(f"http://127.0.0.1:{port}/v1/chat/completions", "seeded_gateway_token")
        later_status = _post_chat(f"http://127.0.0.1:{port}/v1/chat/completions", "later_env_token")
    finally:
        server.shutdown()
        thread.join(timeout=5)
        set_backend(None)
        _restore_env(_TOKEN_ENV, previous)
    assert seeded_status == 200
    assert later_status == 401


def test_serve_security_tokens_seeds_split_admin_inference() -> None:
    previous_admin = os.environ.get(_ADMIN_ENV)
    previous_inference = os.environ.get(_INFERENCE_ENV)
    previous_token = os.environ.get(_TOKEN_ENV)
    set_backend(InMemoryCredentialBackend())
    os.environ.pop(_TOKEN_ENV, None)
    os.environ[_ADMIN_ENV] = "seeded_admin_token"
    os.environ[_INFERENCE_ENV] = "seeded_inference_token"
    try:
        auth_token, admin_token, inference_token = serve_security_tokens(
            SimpleNamespace(auth_token="", admin_token="", inference_token="")
        )
        assert auth_token == ""
        assert admin_token == "seeded_admin_token"
        assert inference_token == "seeded_inference_token"
        assert get_credential(ADMIN_AUTH_TOKEN) == "seeded_admin_token"
        assert get_credential(INFERENCE_AUTH_TOKEN) == "seeded_inference_token"
    finally:
        set_backend(None)
        _restore_env(_ADMIN_ENV, previous_admin)
        _restore_env(_INFERENCE_ENV, previous_inference)
        _restore_env(_TOKEN_ENV, previous_token)


if __name__ == "__main__":
    test_seed_server_auth_from_environ_copies_once()
    test_resolve_server_auth_tokens_ignores_live_environment()
    test_explicit_cli_token_wins_over_kv()
    test_http_authorize_uses_seeded_kv_not_later_env()
    test_serve_security_tokens_seeds_split_admin_inference()
    print("ok")
