"""Default-on composed catalog: discover when a KV credential is present.

Unique slice vs PR #642: discovery is the default (no ``--discover-models``
flag), and the static seed is used only when GET /v1/models fails. App tests
stay secret-free — credentials are in-memory placeholders, never org keys.
"""

from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
from urllib.parse import urlparse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.composed_catalog import (  # noqa: E402
    FORBIDDEN_CREDENTIAL_NAMES,
    ORG_CREDENTIAL_NAMES,
    ProviderProfile,
    catalog_allows_fields,
    compose_default_catalog,
    discover_provider_models,
    merge_agent_pools,
    models_list_payload,
    parse_models_list,
    present_org_credentials,
)
from contextual_orchestrator.provider_egress import (  # noqa: E402
    RefuseRedirectHandler,
    provider_base_url_rejection,
)
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)
from contextual_orchestrator.orchestrator import ModelAgent, ModelClient  # noqa: E402


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


def _provider_hostname(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def test_compose_discovers_when_credential_present_without_flag() -> None:
    def fetch(url: str, headers: dict, timeout: float):
        assert "authorization" in headers
        if _provider_hostname(url) == "api.openai.com":
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
        host = _provider_hostname(url)
        if host == "openrouter.ai":
            raise RuntimeError("openrouter 500")
        if host == "api.openai.com":
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


def test_merge_agent_pools_does_not_duplicate_base_url_model() -> None:
    existing = [ModelAgent("openai_mini", "gpt-4o-mini", base_url="https://api.openai.com/v1")]
    extra = [ModelAgent("openai_mini_dup", "gpt-4o-mini", base_url="https://api.openai.com/v1")]
    merged = merge_agent_pools(existing, extra)
    assert len(merged) == 1


def test_loopback_and_metadata_ips_do_not_transmit_kv_key() -> None:
    called: list[dict] = []

    def fetch(url: str, headers: dict, timeout: float):
        called.append(headers)
        return {"data": [{"id": "should-not-run"}]}

    with fresh_kv():
        register_credential("OPENAI_API_KEY", "test-not-a-secret")
        assert discover_provider_models("https://127.0.0.1/v1", "OPENAI_API_KEY", fetch=fetch) == []
        assert discover_provider_models("https://169.254.169.254/latest", "OPENAI_API_KEY", fetch=fetch) == []
        assert discover_provider_models("https://10.0.0.1/v1", "OPENAI_API_KEY", fetch=fetch) == []
        assert discover_provider_models("file:///etc/passwd", "OPENAI_API_KEY", fetch=fetch) == []
        assert discover_provider_models("http://api.openai.com/v1", "OPENAI_API_KEY", fetch=fetch) == []
        assert discover_provider_models("https://localhost/v1", "OPENAI_API_KEY", fetch=fetch) == []
    assert called == []


def test_allow_insecure_does_not_weaken_production_rejection() -> None:
    called: list[str] = []

    def fetch(url: str, headers: dict, timeout: float):
        called.append(url)
        return {"data": [{"id": "should-not-run"}]}

    with fresh_kv():
        register_credential("OPENAI_API_KEY", "test-not-a-secret")
        models = discover_provider_models(
            "https://127.0.0.1/v1",
            "OPENAI_API_KEY",
            fetch=fetch,
            allow_insecure=True,
        )
    assert models == []
    assert called == []


def test_open_provider_refuses_redirect_and_does_not_replay_bearer() -> None:
    captured: list[str | None] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/start":
                self.send_response(302)
                self.send_header("Location", "/steal")
                self.end_headers()
                return
            captured.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/start",
            headers={"authorization": "Bearer test-not-a-secret"},
            method="GET",
        )
        try:
            ModelClient()._open_provider(request)
        except RuntimeError as exc:
            assert "redirect refused" in str(exc)
        else:
            raise AssertionError("provider 3xx must refuse instead of following")
    finally:
        server.shutdown()
    assert captured == []


def test_refuse_redirect_handler_does_not_follow() -> None:
    handler = RefuseRedirectHandler()
    try:
        handler.redirect_request(None, None, 302, "Found", {}, "https://127.0.0.1/steal")
    except RuntimeError as exc:
        assert "redirect refused" in str(exc)
    else:
        raise AssertionError("3xx must not be followed")


def test_composed_catalog_does_not_open_urllib_directly() -> None:
    root = Path(__file__).resolve().parents[1] / "contextual_orchestrator"
    catalog = (root / "composed_catalog.py").read_text(encoding="utf-8")
    egress = (root / "provider_egress.py").read_text(encoding="utf-8")
    assert "urlopen" not in catalog
    assert "urllib.request" not in catalog
    assert "build_opener" not in egress
    assert "os.environ" not in egress
    assert "Request(" not in egress
    assert "getaddrinfo" not in egress
    assert "import socket" not in egress


def test_catalog_allows_fields_matches_hostnames_not_substrings() -> None:
    assert catalog_allows_fields("https://models.github.ai/inference", "gpt-4o", "OPENAI_API_KEY") is False
    assert catalog_allows_fields("https://api.openai.com/v1", "gpt-4o", "OPENAI_API_KEY") is True
    # Substring lookalikes must not be treated as the forbidden host.
    assert catalog_allows_fields("https://models.github.ai.example.com/v1", "gpt-4o", "OPENAI_API_KEY") is True
    assert catalog_allows_fields("https://api.openai.com/v1", "gpt-5.6-luna", "OPENAI_API_KEY") is False


def test_provider_base_url_rejection_covers_literal_non_public() -> None:
    assert provider_base_url_rejection("https://127.0.0.1/v1", resolve_dns=False)
    assert provider_base_url_rejection("https://169.254.169.254/", resolve_dns=False)
    assert provider_base_url_rejection("file:///etc/passwd", resolve_dns=False)
    assert provider_base_url_rejection("http://api.openai.com/v1", resolve_dns=False) == "base_url must use https"
    assert provider_base_url_rejection("https://api.openai.com/v1", resolve_dns=False) is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
