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
from contextual_orchestrator.orchestrator import ModelClient, chat_completion_response, redact_text, redact_value  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


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
    server = build_server(build(), port=0, security=SecurityConfig(auth_token="secret_token"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    payload = {"messages": [{"role": "user", "content": "hello"}]}

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
    payload = {"messages": [{"role": "user", "content": "hello"}]}

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


def test_http_api_validates_mode_and_request_shape() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token="secret_token"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    try:
        status, body = post_json(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            {"messages": [{"role": "owner", "content": "hello"}], "orchestration": "unsafe"},
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
            {"messages": [{"role": "user", "content": "hello"}], "unexpected": True},
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
    payload = {"messages": [{"role": "user", "content": "hello"}]}

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
    try:
        SecurityConfig(auth_token="secret_token").check_bind("0.0.0.0")
    except ValueError as exc:
        assert "--allow-public-bind" in str(exc)
    else:
        raise AssertionError("public bind should require opt-in")


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


def test_external_provider_requires_explicit_key_env_and_public_https() -> None:
    client = ModelClient()
    no_key_agent = ModelAgent("remote_agent", "gpt-example", "https://api.openai.com/v1")
    loopback_agent = ModelAgent("loopback_agent", "gpt-example", "https://127.0.0.1/v1", "MODEL_KEY")

    try:
        client._validate_provider(no_key_agent)
    except RuntimeError as exc:
        assert "api_key_env" in str(exc)
    else:
        raise AssertionError("provider without api_key_env should fail")

    try:
        client._validate_provider(loopback_agent)
    except RuntimeError as exc:
        assert "non-public address" in str(exc)
    else:
        raise AssertionError("loopback provider should fail")


def test_external_provider_rejects_insecure_or_unlisted_hosts() -> None:
    client = ModelClient()
    insecure_agent = ModelAgent("insecure_agent", "gpt-example", "http://api.openai.com/v1", "MODEL_KEY")
    unlisted_agent = ModelAgent("unlisted_agent", "gpt-example", "https://api.openai.com/v1", "MODEL_KEY")
    previous = os.environ.get("CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS")
    os.environ["CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS"] = "example.com"

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
    test_http_api_validates_mode_and_request_shape()
    test_http_api_rejects_unknown_request_fields()
    test_rate_limit_returns_429_after_configured_budget()
    test_public_bind_requires_explicit_opt_in()
    test_concurrency_limit_rejects_when_slots_are_full()
    test_chat_completion_response_requires_explicit_trace()
    test_redaction_masks_common_sensitive_values()
    test_external_provider_requires_explicit_key_env_and_public_https()
    test_external_provider_rejects_insecure_or_unlisted_hosts()
    test_provider_transport_rejects_local_url_schemes_before_urllib()
    test_provider_transport_rejects_protocol_relative_batch_paths()
    test_redact_value_preserves_non_string_scalars()
    print("ok")
