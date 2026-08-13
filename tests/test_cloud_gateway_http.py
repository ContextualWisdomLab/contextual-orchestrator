"""HTTP contract tests for the Cloud Native tenant gateway."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

from contextual_orchestrator.cloud_gateway import CloudGatewaySecurity, build_cloud_gateway
from contextual_orchestrator.credentials import InMemoryCredentialBackend, set_backend
from contextual_orchestrator.model_group import ModelGroupExecutor
from contextual_orchestrator.tenant_registry import InMemoryTenantRegistry


class _CloudClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def chat(self, agent, messages, temperature=0.2):
        del messages, temperature
        self.calls.append(agent.id)
        if agent.id == "openrouter_primary_endpoint":
            raise RuntimeError("primary failed")
        return "cloud fallback response"

    def take_usage(self):
        return {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}


class _CountingRegistry(InMemoryTenantRegistry):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.ping_count = 0
        self.ping_result = True

    def ping(self) -> bool:
        self.ping_count += 1
        return self.ping_result


def _request(base_url: str, path: str, *, method: str = "GET", body=None, token=None, tenant=None):
    headers = {"accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["content-type"] = "application/json"
    if token:
        headers["authorization"] = f"Bearer {token}"
    if tenant:
        headers["x-contextual-tenant"] = tenant
    request = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=3) as response:  # nosec B310 - loopback test server.
            return response.status, dict(response.headers), response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read().decode("utf-8")


def _start_gateway():
    backend = InMemoryCredentialBackend()
    backend.set("contextual_admin_token", "admin-secret-token")
    backend.set("contextual_inference_token", "inference-secret-token")
    set_backend(backend)
    registry = _CountingRegistry(credential_backend=backend)
    client = _CloudClient()
    executor = ModelGroupExecutor(registry, client)
    security = CloudGatewaySecurity(
        admin_credential_key="contextual_admin_token",
        inference_credential_key="contextual_inference_token",
    )
    server = build_cloud_gateway(registry, executor, security=security, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, thread, registry, client, f"http://{host}:{port}"


def teardown_function() -> None:
    """Reset the process credential backend after every test."""
    set_backend(None)


def test_liveness_is_dependency_free_and_readiness_is_generic() -> None:
    server, thread, registry, _, base_url = _start_gateway()
    try:
        registry.ping_result = False
        status, _, raw = _request(base_url, "/livez")
        assert status == 200
        assert json.loads(raw) == {"status": "live", "service": "contextual-orchestrator"}
        assert registry.ping_count == 0

        status, _, raw = _request(base_url, "/readyz")
        assert status == 503
        assert json.loads(raw) == {"status": "not_ready"}
        assert registry.ping_count == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_admin_crud_is_shared_and_never_echoes_secret() -> None:
    server, thread, _, _, base_url = _start_gateway()
    try:
        admin = "admin-secret-token"
        status, _, _ = _request(
            base_url,
            "/api/v1/tenants",
            method="POST",
            token=admin,
            body={"tenant_id": "acme_corporation", "display_name": "ACME Corporation"},
        )
        assert status == 201

        status, headers, raw = _request(
            base_url,
            "/api/v1/tenants/acme_corporation/provider_credentials",
            method="POST",
            token=admin,
            body={
                "provider_name": "openrouter_provider",
                "credential_label": "openrouter_primary_key",
                "secret_value": "provider-secret-value",
            },
        )
        assert status == 201
        assert headers["Cache-Control"] == "no-store"
        assert "provider-secret-value" not in raw
        credential = json.loads(raw)

        status, _, raw = _request(
            base_url,
            "/api/v1/tenants/acme_corporation/provider_credentials",
            token=admin,
        )
        assert status == 200
        assert "provider-secret-value" not in raw
        assert json.loads(raw)["items"][0]["credential_id"] == credential["credential_id"]

        status, _, raw = _request(
            base_url,
            "/api/v1/tenants/acme_corporation/provider_credentials",
        )
        assert status == 401
        assert "acme_corporation" not in raw
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_openai_model_field_routes_one_tenant_group_with_fallback() -> None:
    server, thread, registry, client, base_url = _start_gateway()
    try:
        registry.create_tenant("acme_corporation", "ACME Corporation")
        first_key = registry.register_provider_credential(
            "acme_corporation", "openrouter_provider", "openrouter_primary_key", "one"
        )
        second_key = registry.register_provider_credential(
            "acme_corporation", "nvidia_provider", "nvidia_secondary_key", "two"
        )
        group = registry.create_model_group("acme_corporation", "general_chat_group")
        first = registry.create_model_endpoint(
            "acme_corporation",
            "openrouter_primary_endpoint",
            "openrouter_provider",
            "openrouter-model-id",
            "mock://openrouter",
            first_key.credential_id,
        )
        second = registry.create_model_endpoint(
            "acme_corporation",
            "nvidia_secondary_endpoint",
            "nvidia_provider",
            "nvidia-model-id",
            "mock://nvidia",
            second_key.credential_id,
        )
        registry.add_group_membership(
            "acme_corporation", group.group_id, first.endpoint_id, fallback_order=10
        )
        registry.add_group_membership(
            "acme_corporation", group.group_id, second.endpoint_id, fallback_order=20
        )

        status, _, raw = _request(
            base_url,
            "/v1/chat/completions",
            method="POST",
            token="inference-secret-token",
            tenant="acme_corporation",
            body={
                "model": "general_chat_group",
                "messages": [{"role": "user", "content": "hello"}],
                "temperature": 0.1,
            },
        )
        payload = json.loads(raw)
        assert status == 200
        assert payload["object"] == "chat.completion"
        assert payload["model"] == "general_chat_group"
        assert payload["choices"][0]["message"] == {
            "role": "assistant",
            "content": "cloud fallback response",
        }
        assert payload["contextual_routing"]["served_endpoint_name"] == "nvidia_secondary_endpoint"
        assert payload["contextual_routing"]["attempt_count"] == 2
        assert client.calls == ["openrouter_primary_endpoint", "nvidia_secondary_endpoint"]
        assert "one" not in raw and "two" not in raw
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_admin_page_uses_same_origin_without_browser_secret_storage() -> None:
    server, thread, _, _, base_url = _start_gateway()
    try:
        status, headers, raw = _request(base_url, "/admin")
        assert status == 200
        assert headers["Content-Type"].startswith("text/html")
        assert "Tenant provider registry" in raw
        assert "localStorage" not in raw
        assert "sessionStorage" not in raw
        assert "secret_value" in raw
        assert "credentials: 'same-origin'" in raw
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
