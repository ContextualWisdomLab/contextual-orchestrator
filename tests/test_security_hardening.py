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
from contextual_orchestrator.batch_routing import BatchRequest  # noqa: E402
from contextual_orchestrator.credentials import InMemoryCredentialBackend, set_backend  # noqa: E402
from contextual_orchestrator.cost_router import CostRoutingCoordinator  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient, chat_completion_response, redact_text, redact_value  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    RequestError,
    SecurityConfig,
    VerifiedIdentity,
    build_server,
)


def build() -> TaskOrchestrator:
    return TaskOrchestrator([ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))])


def test_external_bearer_verifier_is_fail_closed_and_scoped() -> None:
    seen: list[tuple[str, str]] = []

    def verify(token: str, scope: str) -> VerifiedIdentity:
        seen.append((token, scope))
        return VerifiedIdentity(
            subject="user-1",
            org="org-a",
            workspace="workspace-a",
            roles=frozenset({"member"}),
            scopes=frozenset({"inference"}),
        )

    security = SecurityConfig(bearer_verifier=verify)
    identity = security.authorize({"authorization": "Bearer keyverse-token"}, "inference", "127.0.0.1")
    assert identity.subject == "user-1"
    assert identity.org == "org-a"
    try:
        security.authorize({"authorization": "Bearer keyverse-token"}, "admin", "127.0.0.1")
    except RequestError as exc:
        assert "invalid" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("external verifier accepted the wrong scope")
    assert seen == [("keyverse-token", "inference"), ("keyverse-token", "admin")]
    assert security.readiness_profile()["auth_mode"] == "external_bearer_verifier"


def test_external_bearer_verifier_rejects_boolean_only_decisions() -> None:
    security = SecurityConfig(bearer_verifier=lambda _token, _scope: True)  # type: ignore[arg-type]

    try:
        security.authorize({"authorization": "Bearer keyverse-token"}, "inference", "127.0.0.1")
    except RequestError as exc:
        assert exc.code == "unauthorized"
    else:  # pragma: no cover
        raise AssertionError("boolean-only verifier must not create an identity")


def test_keyverse_identity_enforces_org_and_workspace_abac() -> None:
    identity = VerifiedIdentity(
        subject="user-1",
        org="org-a",
        workspace="workspace-a",
        scopes=frozenset({"inference"}),
    )
    security = SecurityConfig(auth_token="local-token")

    context = security.authorize_resource(identity, {"org": "org-a", "workspace": "workspace-a"})
    assert context == {
        "subject": "user-1",
        "org": "org-a",
        "workspace": "workspace-a",
    }
    try:
        security.authorize_resource(identity, {"org": "org-b", "workspace": "workspace-a"})
    except RequestError as exc:
        assert exc.status == 403
        assert exc.code == "tenant_forbidden"
    else:  # pragma: no cover
        raise AssertionError("cross-tenant resource must be rejected")


def test_http_external_identity_rejects_cross_tenant_metadata() -> None:
    def verify(_token: str, scope: str) -> VerifiedIdentity:
        return VerifiedIdentity(
            subject="user-1",
            org="org-a",
            workspace="workspace-a",
            scopes=frozenset({scope}),
        )

    server = build_server(build(), port=0, security=SecurityConfig(bearer_verifier=verify))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    payload = {
        "messages": [{"role": "user", "content": "hello"}],
        "metadata": {"org": "org-a", "workspace": "workspace-a"},
    }

    try:
        allowed_status, _ = post_json(
            f"http://127.0.0.1:{port}/v1/chat/completions", payload, token="keyverse-token"
        )
        denied_status, denied_body = post_json(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            {**payload, "metadata": {"org": "org-b", "workspace": "workspace-a"}},
            token="keyverse-token",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert allowed_status == 200
    assert denied_status == 403
    assert denied_body["error"]["code"] == "tenant_forbidden"


def test_workflow_records_are_tenant_scoped() -> None:
    orchestrator = build()
    owner = {"subject": "user-1", "org": "org-a", "workspace": "workspace-a"}
    other = {"subject": "user-2", "org": "org-b", "workspace": "workspace-b"}
    record = orchestrator.run(
        [{"role": "user", "content": "hello"}],
        mode="route",
        authorization_context=owner,
    )

    assert record["authorization_context"] == owner
    assert orchestrator.get_workflow_run(record["workflow_run_id"], authorization_context=owner) == record
    assert orchestrator.list_recent_runs(authorization_context=other) == []
    assert orchestrator.count_recent_runs(authorization_context=other) == 0
    try:
        orchestrator.get_workflow_run(record["workflow_run_id"], authorization_context=other)
    except KeyError:
        pass
    else:  # pragma: no cover
        raise AssertionError("cross-tenant workflow lookup must be hidden")


def test_batch_resources_keep_tenant_context() -> None:
    owner = {"subject": "user-1", "org": "org-a", "workspace": "workspace-a"}
    coordinator = CostRoutingCoordinator(build())
    job = coordinator.submit_batch(
        [BatchRequest(messages=[{"role": "user", "content": "hello"}])],
        metadata={"authorization_context": owner},
    )

    assert coordinator.batch_access_context(job.job_id) == owner


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
