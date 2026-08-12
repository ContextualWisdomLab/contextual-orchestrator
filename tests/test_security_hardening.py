from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.credentials import InMemoryCredentialBackend, get_credential, set_backend  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient, chat_completion_response, redact_text, redact_value  # noqa: E402
from contextual_orchestrator.server import ADMIN_SESSION_COOKIE, SecurityConfig, build_server  # noqa: E402

# Test-only bearer values (not production secrets). Narrow noqa for Ruff S106.
_TEST_AUTH_TOKEN = "secret_token"  # noqa: S105
_TEST_ADMIN_TOKEN = "admin_secret"  # noqa: S105
_TEST_INFERENCE_TOKEN = "inference_secret"  # noqa: S105
_TEST_CREDENTIAL_VALUE = "sk-secret-value"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator([ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))])


def post_json(url: str, payload: dict[str, object], token: str | None = None) -> tuple[int, dict[str, object]]:
    headers = {"content-type": "application/json", "connection": "close"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_http_api_requires_bearer_token_and_hides_trace_by_default() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    payload = {"messages": [{"role": "user", "content": "hello"}]}

    try:
        unauthorized_status, unauthorized_body = post_json(f"http://127.0.0.1:{port}/v1/chat/completions", payload)
        authorized_status, authorized_body = post_json(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            payload,
            token=_TEST_AUTH_TOKEN,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert unauthorized_status == 401
    assert unauthorized_body["error"]["code"] == "unauthorized"
    assert authorized_status == 200
    assert authorized_body["orchestration"]["mode"] == "route"
    assert "workflow_run_id" in authorized_body["orchestration"]
    assert "trace" not in authorized_body["orchestration"]


def test_admin_and_inference_tokens_are_separate() -> None:
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token="", admin_token=_TEST_ADMIN_TOKEN, inference_token=_TEST_INFERENCE_TOKEN),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    payload = {"messages": [{"role": "user", "content": "hello"}]}

    try:
        admin_for_chat_status, _ = post_json(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            payload,
            token=_TEST_ADMIN_TOKEN,
        )
        inference_status, inference_body = post_json(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            payload,
            token=_TEST_INFERENCE_TOKEN,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert admin_for_chat_status == 401
    assert inference_status == 200
    assert inference_body["orchestration"]["mode"] == "route"
    assert "trace" not in inference_body["orchestration"]


def test_admin_credential_endpoint_registers_into_kv_without_echoing_value() -> None:
    backend = InMemoryCredentialBackend()
    set_backend(backend)
    server = build_server(build(), port=0, security=SecurityConfig(admin_token=_TEST_ADMIN_TOKEN, inference_token=_TEST_INFERENCE_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    try:
        inference_status, inference_body = post_json(
            f"http://127.0.0.1:{port}/admin/api/credentials",
            {"name": "LITELLM_API_KEY", "value": _TEST_CREDENTIAL_VALUE},
            token=_TEST_INFERENCE_TOKEN,
        )
        admin_status, admin_body = post_json(
            f"http://127.0.0.1:{port}/admin/api/credentials",
            {"name": "LITELLM_API_KEY", "value": _TEST_CREDENTIAL_VALUE},
            token=_TEST_ADMIN_TOKEN,
        )
        assert get_credential("LITELLM_API_KEY") == _TEST_CREDENTIAL_VALUE
        assert backend.get("LITELLM_API_KEY") == _TEST_CREDENTIAL_VALUE
        bad_name_status, bad_name_body = post_json(
            f"http://127.0.0.1:{port}/admin/api/credentials",
            {"name": "not-upper-snake", "value": _TEST_CREDENTIAL_VALUE},
            token=_TEST_ADMIN_TOKEN,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        set_backend(None)

    assert inference_status == 401
    assert admin_status == 201
    assert admin_body == {"registered": "LITELLM_API_KEY"}
    assert _TEST_CREDENTIAL_VALUE not in json.dumps(admin_body)
    assert bad_name_status == 400
    assert bad_name_body["error"]["code"] == "invalid_credential_name"


def _establish_admin_session(port: int, token: str) -> tuple[str, str]:
    """POST /admin/session and return (set-cookie header, cookie name=value pair)."""
    session_req = urllib.request.Request(
        f"http://127.0.0.1:{port}/admin/session",
        data=json.dumps({"token": token}).encode("utf-8"),
        headers={"content-type": "application/json", "connection": "close"},
        method="POST",
    )
    with urllib.request.urlopen(session_req, timeout=5) as response:
        assert response.status == 200
        set_cookie = response.headers.get("Set-Cookie") or response.headers.get("set-cookie") or ""
        body = json.loads(response.read().decode("utf-8"))
    assert body == {"session_status": "established"}
    cookie_pair = set_cookie.split(";", 1)[0]
    return set_cookie, cookie_pair


def test_admin_session_cookie_authorizes_admin_api_without_js_token_storage() -> None:
    """Browser path: POST /admin/session mints opaque HttpOnly cookie; admin calls use it."""
    backend = InMemoryCredentialBackend()
    set_backend(backend)
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(admin_token=_TEST_ADMIN_TOKEN, inference_token=_TEST_INFERENCE_TOKEN),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        set_cookie, cookie_value = _establish_admin_session(port, _TEST_ADMIN_TOKEN)
        assert ADMIN_SESSION_COOKIE in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=Strict" in set_cookie
        assert "Secure" in set_cookie
        session_id = cookie_value.split("=", 1)[1]
        assert session_id != _TEST_ADMIN_TOKEN
        assert _TEST_ADMIN_TOKEN not in set_cookie
        assert _TEST_ADMIN_TOKEN not in session_id
        cred_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/admin/api/credentials",
            data=json.dumps({"name": "LITELLM_API_KEY", "value": _TEST_CREDENTIAL_VALUE}).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "connection": "close",
                "cookie": cookie_value,
            },
            method="POST",
        )
        with urllib.request.urlopen(cred_req, timeout=5) as response:
            assert response.status == 201
            cred_body = json.loads(response.read().decode("utf-8"))
        assert cred_body == {"registered": "LITELLM_API_KEY"}
        assert get_credential("LITELLM_API_KEY") == _TEST_CREDENTIAL_VALUE
        # Opaque session id must not work as an Authorization bearer.
        bearer_status, bearer_body = post_json(
            f"http://127.0.0.1:{port}/admin/api/credentials",
            {"name": "OTHER_KEY", "value": _TEST_CREDENTIAL_VALUE},
            token=session_id,
        )
        assert bearer_status == 401
        assert bearer_body["error"]["code"] == "unauthorized"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        set_backend(None)


def test_admin_session_expires_and_logout_revokes() -> None:
    """Expired sessions and DELETE /admin/session both stop authorizing admin APIs."""
    backend = InMemoryCredentialBackend()
    set_backend(backend)
    security = SecurityConfig(
        admin_token=_TEST_ADMIN_TOKEN,
        inference_token=_TEST_INFERENCE_TOKEN,
        admin_session_ttl_seconds=1,
    )
    server = build_server(build(), port=0, security=security)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        _, cookie_value = _establish_admin_session(port, _TEST_ADMIN_TOKEN)
        session_id = cookie_value.split("=", 1)[1]

        # Immediate logout path.
        logout_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/admin/session",
            headers={"connection": "close", "cookie": cookie_value},
            method="DELETE",
        )
        with urllib.request.urlopen(logout_req, timeout=5) as response:
            assert response.status == 200
            logout_body = json.loads(response.read().decode("utf-8"))
            clear_cookie = response.headers.get("Set-Cookie") or response.headers.get("set-cookie") or ""
        assert logout_body["session_status"] == "cleared"
        assert logout_body["session_revoked"] is True
        assert "Max-Age=0" in clear_cookie

        denied = urllib.request.Request(
            f"http://127.0.0.1:{port}/admin/api/credentials",
            data=json.dumps({"name": "AFTER_LOGOUT", "value": _TEST_CREDENTIAL_VALUE}).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "connection": "close",
                "cookie": cookie_value,
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(denied, timeout=5)
            raise AssertionError("revoked session should not authorize")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401

        # Fresh short-TTL session then expire.
        _, cookie2 = _establish_admin_session(port, _TEST_ADMIN_TOKEN)
        import time as _time
        _time.sleep(1.2)
        expired = urllib.request.Request(
            f"http://127.0.0.1:{port}/admin/api/credentials",
            data=json.dumps({"name": "AFTER_EXPIRY", "value": _TEST_CREDENTIAL_VALUE}).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "connection": "close",
                "cookie": cookie2,
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(expired, timeout=5)
            raise AssertionError("expired session should not authorize")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401

        # Replaying the raw admin bearer as the cookie value is not a session.
        raw_cookie = f"{ADMIN_SESSION_COOKIE}={_TEST_ADMIN_TOKEN}"
        raw_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/admin/api/credentials",
            data=json.dumps({"name": "RAW_BEARER_COOKIE", "value": _TEST_CREDENTIAL_VALUE}).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "connection": "close",
                "cookie": raw_cookie,
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(raw_req, timeout=5)
            raise AssertionError("raw bearer cookie must not authorize")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
        assert not security._admin_session_is_active(session_id)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        set_backend(None)


def test_admin_session_store_is_capped_and_rate_limited() -> None:
    """Session table has a hard bound; /admin/session counts toward rate limit."""
    security = SecurityConfig(
        admin_token=_TEST_ADMIN_TOKEN,
        inference_token=_TEST_INFERENCE_TOKEN,
        max_admin_sessions=2,
        rate_limit_requests=3,
        rate_limit_window_seconds=60,
    )
    first = security.establish_admin_session(_TEST_ADMIN_TOKEN)
    second = security.establish_admin_session(_TEST_ADMIN_TOKEN)
    third = security.establish_admin_session(_TEST_ADMIN_TOKEN)
    assert security._admin_session_is_active(third)
    assert security._admin_session_is_active(second)
    # Oldest session evicted when over cap.
    assert not security._admin_session_is_active(first)
    assert len(security._admin_sessions) <= 2

    server = build_server(build(), port=0, security=security)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        for _ in range(3):
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/admin/session",
                data=json.dumps({"token": _TEST_ADMIN_TOKEN}).encode("utf-8"),
                headers={"content-type": "application/json", "connection": "close"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                assert response.status == 200
        blocked = urllib.request.Request(
            f"http://127.0.0.1:{port}/admin/session",
            data=json.dumps({"token": _TEST_ADMIN_TOKEN}).encode("utf-8"),
            headers={"content-type": "application/json", "connection": "close"},
            method="POST",
        )
        try:
            urllib.request.urlopen(blocked, timeout=5)
            raise AssertionError("session establish must share the request rate budget")
        except urllib.error.HTTPError as exc:
            assert exc.code == 429
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_constant_time_token_match_accepts_non_ascii_without_raising() -> None:
    """Non-ASCII secrets must not raise TypeError from compare_digest(str)."""
    security = SecurityConfig(admin_token="토큰-α", inference_token="infer-β")
    assert security._constant_time_token_match("토큰-α", "토큰-α")
    assert not security._constant_time_token_match("토큰-α", "토큰-γ")
    assert not security._constant_time_token_match("ascii", "토큰-α")


def test_loopback_without_configured_token_is_rejected() -> None:
    server = build_server(build(), port=0, security=SecurityConfig())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    payload = {"messages": [{"role": "user", "content": "hello"}]}

    try:
        status, body = post_json(f"http://127.0.0.1:{port}/v1/chat/completions", payload)
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 401
    assert body["error"]["code"] == "unauthorized"


def test_http_api_validates_mode_and_request_shape() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    try:
        status, body = post_json(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            {"messages": [{"role": "owner", "content": "hello"}], "orchestration": "unsafe"},
            token=_TEST_AUTH_TOKEN,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 400
    assert body["error"]["code"] in {"invalid_message", "invalid_mode"}


def test_http_api_rejects_unknown_request_fields() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    try:
        status, body = post_json(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            {"messages": [{"role": "user", "content": "hello"}], "unexpected": True},
            token=_TEST_AUTH_TOKEN,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 400
    assert body["error"]["code"] == "unknown_fields"


def test_rate_limit_returns_429_after_configured_budget() -> None:
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=1),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    payload = {"messages": [{"role": "user", "content": "hello"}]}

    try:
        first_status, _ = post_json(f"http://127.0.0.1:{port}/v1/chat/completions", payload, token=_TEST_AUTH_TOKEN)
        second_status, second_body = post_json(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            payload,
            token=_TEST_AUTH_TOKEN,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert first_status == 200
    assert second_status == 429
    assert second_body["error"]["code"] == "rate_limit_exceeded"


def test_public_bind_requires_explicit_opt_in() -> None:
    try:
        SecurityConfig(auth_token=_TEST_AUTH_TOKEN).check_bind("0.0.0.0")
    except ValueError as exc:
        assert "--allow-public-bind" in str(exc)
    else:
        raise AssertionError("public bind should require opt-in")


def test_concurrency_limit_rejects_when_slots_are_full() -> None:
    security = SecurityConfig(auth_token=_TEST_AUTH_TOKEN, max_concurrent_runs=1)
    security.acquire_run_slot()

    try:
        try:
            security.acquire_run_slot()
        except Exception as exc:
            assert getattr(exc, "status") == 503
            assert getattr(exc, "code") == "concurrency_limit_exceeded"
        else:
            raise AssertionError("second run slot should be rejected")
    finally:
        security.release_run_slot()


def test_chat_completion_response_requires_explicit_trace() -> None:
    result = {
        "mode": "route",
        "answer": "ok",
        "trace": [{"agent_id": "general_agent", "output": "Bearer abcdefghijklmnopqrstuvwxyz"}],
    }

    assert "trace" not in chat_completion_response(result)["orchestration"]
    trace = chat_completion_response(result, include_trace=True)["orchestration"]["trace"]
    assert trace[0]["output"] == "Bearer [REDACTED]"


def test_redaction_masks_common_sensitive_values() -> None:
    text = "api_key='abcdefghijklmnopqrstuvwxyz' sent by alice@example.com"

    assert redact_text(text) == "api_key='[REDACTED]' sent by [REDACTED]"


def test_external_provider_requires_resolvable_credential_and_public_https() -> None:
    client = ModelClient()
    # No credential registered in the KV: a non-mock agent must fail loudly and
    # must NOT fall back to reading os.getenv. Default credential is OPENAI_API_KEY.
    set_backend(InMemoryCredentialBackend())
    try:
        no_key_agent = ModelAgent("remote_agent", "gpt-example", "https://api.openai.com/v1")
        loopback_agent = ModelAgent("loopback_agent", "gpt-example", "https://127.0.0.1/v1", "MODEL_KEY")

        try:
            client._validate_provider(no_key_agent)
        except RuntimeError as exc:
            # Unresolvable credential is reported (message references legacy api_key_env).
            assert "credential" in str(exc)
            assert "api_key_env" in str(exc)
        else:
            raise AssertionError("provider without a resolvable credential should fail")

        # Register the credential so the host-safety checks are reached and exercised.
        backend = InMemoryCredentialBackend()
        backend.set("MODEL_KEY", "sk-loopback")
        set_backend(backend)
        try:
            client._validate_provider(loopback_agent)
        except RuntimeError as exc:
            assert "non-public address" in str(exc)
        else:
            raise AssertionError("loopback provider should fail")
    finally:
        set_backend(None)


def test_external_provider_rejects_insecure_or_unlisted_hosts() -> None:
    client = ModelClient()
    insecure_agent = ModelAgent("insecure_agent", "gpt-example", "http://api.openai.com/v1", "MODEL_KEY")
    unlisted_agent = ModelAgent("unlisted_agent", "gpt-example", "https://api.openai.com/v1", "MODEL_KEY")
    previous = os.environ.get("CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS")
    os.environ["CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS"] = "example.com"
    # Register the credential so validation proceeds to the host-safety checks.
    backend = InMemoryCredentialBackend()
    backend.set("MODEL_KEY", "sk-host-check")
    set_backend(backend)

    try:
        try:
            client._validate_provider(insecure_agent)
        except RuntimeError as exc:
            assert "https" in str(exc)
        else:
            raise AssertionError("http provider should fail")

        try:
            client._validate_provider(unlisted_agent)
        except RuntimeError as exc:
            assert "allowlisted" in str(exc)
        else:
            raise AssertionError("unlisted provider should fail")
    finally:
        set_backend(None)
        if previous is None:
            os.environ.pop("CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS", None)
        else:
            os.environ["CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS"] = previous


def test_provider_transport_rejects_local_url_schemes_before_urllib() -> None:
    client = ModelClient()
    file_agent = ModelAgent("file_agent", "gpt-example", "file:///etc/passwd", "MODEL_KEY")

    try:
        client._send(file_agent, {"model": "gpt-example"})
    except RuntimeError as exc:
        assert "http(s)" in str(exc)
    else:
        raise AssertionError("file:// provider URL should fail before urllib opens it")


def test_provider_transport_rejects_protocol_relative_batch_paths() -> None:
    client = ModelClient()
    remote_agent = ModelAgent("remote_agent", "gpt-example", "https://api.openai.com/v1", "MODEL_KEY")

    try:
        client._batch_raw(remote_agent, "//evil.example/files/leak")
    except RuntimeError as exc:
        assert "absolute URL path" in str(exc)
    else:
        raise AssertionError("protocol-relative provider path should fail before urllib opens it")


def test_redact_value_preserves_non_string_scalars() -> None:
    assert redact_value(7) == 7


if __name__ == "__main__":
    test_http_api_requires_bearer_token_and_hides_trace_by_default()
    test_admin_and_inference_tokens_are_separate()
    test_admin_credential_endpoint_registers_into_kv_without_echoing_value()
    test_admin_session_cookie_authorizes_admin_api_without_js_token_storage()
    test_admin_session_expires_and_logout_revokes()
    test_admin_session_store_is_capped_and_rate_limited()
    test_constant_time_token_match_accepts_non_ascii_without_raising()
    test_loopback_without_configured_token_is_rejected()
    test_http_api_validates_mode_and_request_shape()
    test_http_api_rejects_unknown_request_fields()
    test_rate_limit_returns_429_after_configured_budget()
    test_public_bind_requires_explicit_opt_in()
    test_concurrency_limit_rejects_when_slots_are_full()
    test_chat_completion_response_requires_explicit_trace()
    test_redaction_masks_common_sensitive_values()
    test_external_provider_requires_resolvable_credential_and_public_https()
    test_external_provider_rejects_insecure_or_unlisted_hosts()
    test_provider_transport_rejects_local_url_schemes_before_urllib()
    test_provider_transport_rejects_protocol_relative_batch_paths()
    test_redact_value_preserves_non_string_scalars()
    print("ok")
