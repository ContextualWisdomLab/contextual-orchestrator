from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.credentials import InMemoryCredentialBackend, set_backend  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient, chat_completion_response, redact_text, redact_value  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


def build() -> TaskOrchestrator:
    return TaskOrchestrator([ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))])


def test_external_bearer_verifier_is_fail_closed_and_scoped() -> None:
    seen: list[tuple[str, str]] = []

    def verify(token: str, scope: str) -> bool:
        seen.append((token, scope))
        return token == "keyverse-token" and scope == "inference"

    security = SecurityConfig(bearer_verifier=verify)
    security.authorize({"authorization": "Bearer keyverse-token"}, "inference", "127.0.0.1")
    try:
        security.authorize({"authorization": "Bearer keyverse-token"}, "admin", "127.0.0.1")
    except Exception as exc:
        assert "invalid" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("external verifier accepted the wrong scope")
    assert seen == [("keyverse-token", "inference"), ("keyverse-token", "admin")]
    assert security.readiness_profile()["auth_mode"] == "external_bearer_verifier"


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


def request_json(
    url: str,
    method: str,
    *,
    body: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object], object]:
    """Make a JSON request and retain response headers for cookie assertions."""
    request_headers = {"content-type": "application/json", "connection": "close", **(headers or {})}
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8")), response.headers
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8")), exc.headers


def test_admin_session_is_opaque_scoped_and_revocable() -> None:
    """A browser cookie replaces, but never becomes, the long-lived bearer."""
    server = build_server(build(), port=0, security=SecurityConfig(auth_token="secret_token"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, body, headers = request_json(
            f"{base}/admin/session",
            "POST",
            body={"token": "secret_token"},
        )
        set_cookie = headers.get("set-cookie") or headers.get("Set-Cookie") or ""
        cookie_pair = set_cookie.split(";", 1)[0]
        session_id = cookie_pair.split("=", 1)[1]
        assert status == 200
        assert body == {"session_status": "established"}
        assert "secret_token" not in set_cookie
        assert "HttpOnly" in set_cookie and "SameSite=Strict" in set_cookie and "Secure" in set_cookie
        assert session_id != "secret_token"

        status, state, _ = request_json(f"{base}/admin/state", "GET", headers={"cookie": cookie_pair})
        assert status == 200 and "agents" in state
        status, evaluation, _ = request_json(
            f"{base}/api/v1/evaluation_runs",
            "POST",
            body={"prompts": ["evaluate this"]},
            headers={"cookie": cookie_pair, "origin": base},
        )
        assert status == 201 and evaluation["prompt_count"] == 1
        status, _, _ = request_json(f"{base}/v1/models", "GET", headers={"cookie": cookie_pair})
        assert status == 401
        status, body, _ = request_json(
            f"{base}/admin/simulate",
            "POST",
            body={"prompt": "cross-origin must fail"},
            headers={"cookie": cookie_pair, "origin": "https://evil.example"},
        )
        assert status == 403 and body["error"]["code"] == "csrf_origin_rejected"

        status, body, _ = request_json(
            f"{base}/admin/session",
            "DELETE",
            headers={"cookie": cookie_pair, "origin": "https://evil.example"},
        )
        assert status == 403 and body["error"]["code"] == "csrf_origin_rejected"

        status, body, clear_headers = request_json(
            f"{base}/admin/session",
            "DELETE",
            headers={"cookie": cookie_pair, "origin": base},
        )
        clear_cookie = clear_headers.get("set-cookie") or clear_headers.get("Set-Cookie") or ""
        assert status == 200 and body == {"session_status": "cleared", "session_revoked": True}
        assert "Max-Age=0" in clear_cookie
        status, _, _ = request_json(f"{base}/admin/state", "GET", headers={"cookie": cookie_pair})
        assert status == 401
    finally:
        server.shutdown()
        thread.join(timeout=5)



def test_admin_session_requests_partition_cache_without_bearer() -> None:
    """A cookie-authenticated admin POST must not 401 in the cache partitioner.

    Regression: #772's cache partitioner required a bearer header, breaking
    every state-changing admin route for opaque-session operators after #788.
    """
    server = build_server(build(), port=0, security=SecurityConfig(auth_token="secret_token"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, body, headers = request_json(
            f"{base}/admin/session",
            "POST",
            body={"token": "secret_token"},
        )
        assert status == 200
        set_cookie = headers.get("set-cookie") or headers.get("Set-Cookie") or ""
        cookie_pair = set_cookie.split(";", 1)[0]
        status, evaluation, _ = request_json(
            f"{base}/api/v1/evaluation_runs",
            "POST",
            body={"prompts": ["evaluate this"]},
            headers={"cookie": cookie_pair, "origin": base},
        )
        assert status == 201 and evaluation["prompt_count"] == 1

        status, other, other_headers = request_json(
            f"{base}/admin/session",
            "POST",
            body={"token": "secret_token"},
        )
        other_cookie = (other_headers.get("set-cookie") or "").split(";", 1)[0]
        status2, evaluation2, _ = request_json(
            f"{base}/api/v1/evaluation_runs",
            "POST",
            body={"prompts": ["evaluate this"]},
            headers={"cookie": other_cookie, "origin": base},
        )
        assert status2 == 201
    finally:
        server.shutdown()
        thread.join(timeout=5)

def test_http_api_requires_bearer_token_and_hides_trace_by_default() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token="secret_token"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    payload = {"model": "mock-generalist", "messages": [{"role": "user", "content": "hello"}]}

    try:
        unauthorized_status, unauthorized_body = post_json(f"http://127.0.0.1:{port}/v1/chat/completions", payload)
        authorized_status, authorized_body = post_json(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            payload,
            token="secret_token",
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
        security=SecurityConfig(auth_token="", admin_token="admin_secret", inference_token="inference_secret"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    payload = {"model": "mock-generalist", "messages": [{"role": "user", "content": "hello"}]}

    try:
        admin_for_chat_status, _ = post_json(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            payload,
            token="admin_secret",
        )
        inference_status, inference_body = post_json(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            payload,
            token="inference_secret",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert admin_for_chat_status == 401
    assert inference_status == 200
    assert inference_body["orchestration"]["mode"] == "route"
    assert "trace" not in inference_body["orchestration"]


def test_single_and_split_token_modes_cannot_be_combined() -> None:
    try:
        SecurityConfig(auth_token="shared_secret", admin_token="admin_secret", inference_token="inference_secret")
    except ValueError as exc:
        assert str(exc) == "single auth_token cannot be combined with split tokens"
    else:  # pragma: no cover
        raise AssertionError("mixed single and split token modes must be rejected")


def test_public_bind_rejects_shared_token_at_security_boundary() -> None:
    try:
        SecurityConfig(auth_token="shared_secret", allow_public_bind=True)
    except ValueError as exc:
        assert str(exc) == "public bind requires split admin_token and inference_token credentials"
    else:  # pragma: no cover
        raise AssertionError("public bind must not accept one shared bearer token")


def test_scope_token_precedes_mutated_shared_token() -> None:
    security = SecurityConfig(admin_token="admin_secret", inference_token="inference_secret")
    security.auth_token = "mutated_shared_secret"

    try:
        security.authorize({"authorization": "Bearer mutated_shared_secret"}, "admin", "127.0.0.1")
    except Exception as exc:
        assert "invalid" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("scope token must remain authoritative after field mutation")

    security.authorize({"authorization": "Bearer admin_secret"}, "admin", "127.0.0.1")


def test_loopback_without_configured_token_is_rejected() -> None:
    server = build_server(build(), port=0, security=SecurityConfig())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    payload = {"model": "mock-generalist", "messages": [{"role": "user", "content": "hello"}]}

    try:
        status, body = post_json(f"http://127.0.0.1:{port}/v1/chat/completions", payload)
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 401
    assert body["error"]["code"] == "unauthorized"


def test_http_api_validates_mode_and_request_shape() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token="secret_token"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    try:
        status, body = post_json(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            {"model": "mock-generalist", "messages": [{"role": "owner", "content": "hello"}], "orchestration": "unsafe"},
            token="secret_token",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 400
    assert body["error"]["code"] in {"invalid_message", "invalid_mode"}


def test_http_api_rejects_unknown_request_fields() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token="secret_token"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    try:
        status, body = post_json(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            {"model": "mock-generalist", "messages": [{"role": "user", "content": "hello"}], "unexpected": True},
            token="secret_token",
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
        security=SecurityConfig(auth_token="secret_token", rate_limit_requests=1),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    payload = {"model": "mock-generalist", "messages": [{"role": "user", "content": "hello"}]}

    try:
        first_status, _ = post_json(f"http://127.0.0.1:{port}/v1/chat/completions", payload, token="secret_token")
        second_status, second_body = post_json(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            payload,
            token="secret_token",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert first_status == 200
    assert second_status == 429
    assert second_body["error"]["code"] == "rate_limit_exceeded"


def test_public_bind_requires_explicit_opt_in() -> None:
    security = SecurityConfig(auth_token="secret_token")
    for host in ("0.0.0.0", "192.0.2.1", "2001:db8::1"):
        try:
            security.check_bind(host)
        except ValueError as exc:
            assert "--allow-public-bind" in str(exc)
        else:
            raise AssertionError(f"public bind should require opt-in: {host}")
    for host in ("127.0.0.1", "::1", "localhost"):
        security.check_bind(host)


def test_concurrency_limit_rejects_when_slots_are_full() -> None:
    security = SecurityConfig(auth_token="secret_token", max_concurrent_runs=1)
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


def test_concurrency_limit_rejects_unbounded_or_non_integer_configuration() -> None:
    for value in (0, 65, False, 1.5):
        try:
            SecurityConfig(auth_token="secret_token", max_concurrent_runs=value)  # type: ignore[arg-type]
        except ValueError as exc:
            assert "max_concurrent_runs" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("invalid max_concurrent_runs configuration was accepted")


def test_chat_completion_response_requires_explicit_trace() -> None:
    result = {
        "mode": "route",
        "answer": "ok",
        "trace": [{"agent_id": "general_agent", "output": "Bearer abcdefghijklmnopqrstuvwxyz"}],
    }

    assert "trace" not in chat_completion_response(result)["orchestration"]
    trace = chat_completion_response(result, include_trace=True)["orchestration"]["trace"]
    assert trace[0]["output"] == "Bearer [REDACTED]"


def test_redaction_masks_credentials_but_not_email_pii() -> None:
    text = "api_key='abcdefghijklmnopqrstuvwxyz' sent by alice@example.com"

    assert redact_text(text) == "api_key='[REDACTED]' sent by alice@example.com"


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
    client = ModelClient(allowed_provider_hosts={"example.com"})
    insecure_agent = ModelAgent("insecure_agent", "gpt-example", "http://api.openai.com/v1", "MODEL_KEY")
    unlisted_agent = ModelAgent("unlisted_agent", "gpt-example", "https://api.openai.com/v1", "MODEL_KEY")
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


def test_provider_allowlist_ignores_request_time_environment_changes() -> None:
    client = ModelClient(allowed_provider_hosts={"provider.example"})
    agent = ModelAgent(
        "remote_agent",
        "remote-model",
        base_url="https://provider.example/v1",
        credential_key="remote-key",
    )
    with patch.dict(
        "contextual_orchestrator.orchestrator.os.environ",
        {"CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS": "other.example"},
    ), patch(
        "contextual_orchestrator.orchestrator.get_credential",
        return_value="secret",
    ), patch.object(
        client,
        "_resolve_addresses",
        return_value=[(socket.AF_INET, ("93.184.216.34", 443))],
    ):
        assert client._validate_provider(agent) == (socket.AF_INET, ("93.184.216.34", 443))


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
    test_loopback_without_configured_token_is_rejected()
    test_http_api_validates_mode_and_request_shape()
    test_http_api_rejects_unknown_request_fields()
    test_rate_limit_returns_429_after_configured_budget()
    test_public_bind_requires_explicit_opt_in()
    test_concurrency_limit_rejects_when_slots_are_full()
    test_chat_completion_response_requires_explicit_trace()
    test_redaction_masks_credentials_but_not_email_pii()
    test_external_provider_requires_resolvable_credential_and_public_https()
    test_external_provider_rejects_insecure_or_unlisted_hosts()
    test_provider_transport_rejects_local_url_schemes_before_urllib()
    test_provider_transport_rejects_protocol_relative_batch_paths()
    test_redact_value_preserves_non_string_scalars()
    print("ok")
