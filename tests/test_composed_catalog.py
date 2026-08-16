"""Default-on composed catalog: discover when a KV credential is present.

Unique slice vs PR #642: discovery is the default (no ``--discover-models``
flag), and the static seed is used only when GET /v1/models fails. App tests
stay secret-free — credentials are in-memory placeholders, never org keys.
"""

from __future__ import annotations

from contextlib import contextmanager
import http.server
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.composed_catalog import (  # noqa: E402
    FORBIDDEN_CREDENTIAL_NAMES,
    ORG_CREDENTIAL_NAMES,
    ProviderProfile,
    compose_default_catalog,
    default_models_fetch,
    discover_provider_models,
    merge_agent_pools,
    models_list_payload,
    parse_models_list,
    present_org_credentials,
)
from contextual_orchestrator.provider_egress import (  # noqa: E402
    provider_base_url_rejection,
)
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)
from contextual_orchestrator.orchestrator import ModelAgent  # noqa: E402


@contextmanager
def fresh_kv():
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


def test_org_credential_names_are_the_five_actions_secrets() -> None:
    assert ORG_CREDENTIAL_NAMES == (
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "BYTEZ_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    )
    assert "COPILOT_GITHUB_TOKEN" not in ORG_CREDENTIAL_NAMES
    assert "COPILOT_GITHUB_TOKEN" in FORBIDDEN_CREDENTIAL_NAMES


def test_compose_discovers_when_credential_present_without_flag() -> None:
    def fetch(url: str, headers: dict, timeout: float):
        assert "authorization" in headers
        if "api.openai.com" in url:
            return {"data": [{"id": "gpt-4o-mini"}, {"id": "text-embedding-3-small"}]}
        raise AssertionError(f"unexpected url {url}")

    with fresh_kv():
        register_credential("OPENAI_API_KEY", "test-not-a-secret")
        catalog = compose_default_catalog(fetch=fetch)
    models = [agent.model for agent in catalog.agents]
    assert "gpt-4o-mini" in models
    assert "text-embedding-3-small" not in models
    openai_report = next(r for r in catalog.provider_reports if r.credential_name == "OPENAI_API_KEY")
    assert openai_report.discovery_source == "discovered"
    skipped = {r.credential_name for r in catalog.provider_reports if r.discovery_source == "skipped"}
    assert "NVIDIA_NIM_API_KEY" in skipped


def test_static_fallback_only_when_discovery_fails() -> None:
    def fail_fetch(url: str, headers: dict, timeout: float):
        raise TimeoutError("upstream models list down")

    with fresh_kv():
        register_credential("OPENAI_API_KEY", "test-not-a-secret")
        catalog = compose_default_catalog(fetch=fail_fetch)
    assert catalog.agents
    assert all(agent.model == "gpt-4o-mini" for agent in catalog.agents if agent.provider_name == "openai")
    openai_report = next(r for r in catalog.provider_reports if r.credential_name == "OPENAI_API_KEY")
    assert openai_report.discovery_source == "fallback"


def test_malformed_models_payload_is_fallback_not_crash() -> None:
    def bad_fetch(url: str, headers: dict, timeout: float):
        return ["not", "an", "object"]

    with fresh_kv():
        register_credential("BYTEZ_API_KEY", "test-not-a-secret")
        catalog = compose_default_catalog(fetch=bad_fetch)
    bytez = next(r for r in catalog.provider_reports if r.credential_name == "BYTEZ_API_KEY")
    assert bytez.discovery_source == "fallback"
    assert any(agent.provider_name == "bytez" for agent in catalog.agents)


def test_one_provider_failure_does_not_abort_compose() -> None:
    def mixed_fetch(url: str, headers: dict, timeout: float):
        if "openrouter" in url:
            raise RuntimeError("openrouter 500")
        if "api.openai.com" in url:
            return {"data": [{"id": "gpt-4o-mini"}]}
        raise TimeoutError("other")

    with fresh_kv():
        register_credential("OPENAI_API_KEY", "test-not-a-secret")
        register_credential("OPENROUTER_API_KEY", "test-not-a-secret")
        catalog = compose_default_catalog(fetch=mixed_fetch)
    sources = {r.credential_name: r.discovery_source for r in catalog.provider_reports}
    assert sources["OPENAI_API_KEY"] == "discovered"
    assert sources["OPENROUTER_API_KEY"] == "fallback"


def test_absent_credentials_yield_empty_catalog() -> None:
    with fresh_kv():
        assert present_org_credentials() == ()
        catalog = compose_default_catalog(fetch=lambda *a, **k: {"data": []})
    assert catalog.agents == []
    assert all(r.discovery_source == "skipped" for r in catalog.provider_reports)


def test_copilot_token_is_never_composed() -> None:
    profile = ProviderProfile(
        credential_name="COPILOT_GITHUB_TOKEN",
        provider_name="github_models",
        base_url="https://models.github.ai/inference",
        fallback_models=("gpt-5.6-luna",),
    )
    with fresh_kv():
        register_credential("COPILOT_GITHUB_TOKEN", "test-not-a-secret")
        catalog = compose_default_catalog(fetch=lambda *a, **k: {"data": [{"id": "gpt-4o"}]}, profiles=(profile,))
    assert catalog.agents == []
    assert catalog.provider_reports[0].discovery_source == "rejected"


def test_parse_models_list_drops_non_chat_and_github_markers() -> None:
    assert parse_models_list({"data": [{"id": "gpt-4o"}, {"id": "text-embedding-3-large"}, {"id": "gpt-5.6-luna"}]}) == [
        "gpt-4o"
    ]
    assert parse_models_list(None) == []
    assert parse_models_list({"data": "nope"}) == []


def test_models_list_payload_includes_facade_and_composed_ids() -> None:
    agents = [
        ModelAgent("openai_mini", "gpt-4o-mini", provider_name="openai"),
        ModelAgent("nvidia_kimi", "moonshotai/kimi-k2.5", provider_name="nvidia_nim"),
    ]
    payload = models_list_payload(agents)
    ids = [row["id"] for row in payload["data"]]
    assert payload["object"] == "list"
    assert ids[0] == "contextual-orchestrator"
    assert "gpt-4o-mini" in ids
    assert "moonshotai/kimi-k2.5" in ids


def test_loopback_discovery_does_not_send_credential() -> None:
    seen: list[dict] = []

    def fetch(url: str, headers: dict, timeout: float):
        seen.append(headers)
        return {"data": [{"id": "stolen-model"}]}

    profile = ProviderProfile(
        credential_name="OPENAI_API_KEY",
        provider_name="loopback_co",
        base_url="https://127.0.0.1/v1",
        fallback_models=("fallback-model",),
    )
    with fresh_kv():
        register_credential("OPENAI_API_KEY", "sk-must-not-leak")
        catalog = compose_default_catalog(fetch=fetch, profiles=(profile,))
    assert seen == []
    assert provider_base_url_rejection("https://127.0.0.1/v1", resolve_dns=False)
    assert discover_provider_models("https://127.0.0.1/v1", "OPENAI_API_KEY", fetch=fetch) == []
    assert [agent.model for agent in catalog.agents] == ["fallback-model"]


def test_link_local_metadata_discovery_does_not_send_credential() -> None:
    seen: list[dict] = []

    def fetch(url: str, headers: dict, timeout: float):
        seen.append(headers)
        return {"data": [{"id": "stolen-model"}]}

    profile = ProviderProfile(
        credential_name="OPENAI_API_KEY",
        provider_name="metadata_co",
        base_url="https://169.254.169.254/latest",
        fallback_models=("fallback-model",),
    )
    with fresh_kv():
        register_credential("OPENAI_API_KEY", "sk-must-not-leak")
        catalog = compose_default_catalog(fetch=fetch, profiles=(profile,))
    assert seen == []
    assert catalog.provider_reports[0].discovery_source == "fallback"


def test_default_models_fetch_refuses_redirect() -> None:
    hits: list[str] = []

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            hits.append(self.path)
            if self.path == "/v1/models":
                self.send_response(302)
                self.send_header("Location", "/stolen")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"data":[{"id":"leaked"}]}')

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        raised = False
        try:
            default_models_fetch(
                f"http://127.0.0.1:{port}/v1/models",
                {"authorization": "Bearer sk-must-not-leak"},
                2.0,
            )
        except RuntimeError as exc:
            raised = True
            assert "redirect refused" in str(exc)
        assert raised
        assert hits == ["/v1/models"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_merge_agent_pools_does_not_duplicate_base_url_model() -> None:
    existing = [ModelAgent("openai_mini", "gpt-4o-mini", base_url="https://api.openai.com/v1")]
    extra = [ModelAgent("openai_mini_dup", "gpt-4o-mini", base_url="https://api.openai.com/v1")]
    merged = merge_agent_pools(existing, extra)
    assert len(merged) == 1


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
