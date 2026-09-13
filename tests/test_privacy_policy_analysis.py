"""Grounded privacy-policy analysis through a discovered ZDR model."""

import asyncio
import base64
import importlib.metadata
import json
import sys
import types
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)
from contextual_orchestrator.model_discovery import DiscoveredModel
from contextual_orchestrator.orchestrator import ModelClient
from contextual_orchestrator.privacy_policy_analysis import (
    _installed_mcp_sdk_version,
    _call_analyzer,
    _render_policy_document_with_camoufox,
    _wardnet_browser_proxy,
    analyze_discovered_privacy_policies,
    crawl_policy_document,
)


def _model(
    provider: str,
    model_id: str,
    *,
    zdr: bool | None = None,
    policy_urls: tuple[str, ...] = (),
) -> DiscoveredModel:
    return DiscoveredModel(
        provider_name=provider,
        model_id=model_id,
        credential_name=f"{provider.upper()}_API_KEY",
        chat_base_url=f"https://{provider}.example/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
        supports_zero_data_retention=zdr,
        privacy_policy_urls=policy_urls,
    )


def test_zdr_model_analysis_keeps_optional_zdr_as_provenance_only() -> None:
    policy_url = "https://provider.example/privacy"
    analyzer = _model("openrouter", "zdr-analyzer", zdr=True)
    target = _model("provider", "paid-model", policy_urls=(policy_url,))
    policy_text = "API inputs are not used for training. Optional ZDR requires approval."

    enriched, evidence = analyze_discovered_privacy_policies(
        [analyzer, target],
        crawler=lambda url: policy_text if url == policy_url else "",
        analyzer=lambda candidate, documents: {
            "assessments": [
                {
                    "source_url": policy_url,
                    "zero_data_retention_available": True,
                    "no_training": True,
                    "no_prompt_retention": None,
                    "evidence_quote": "API inputs are not used for training.",
                }
            ]
        },
    )

    assert evidence[0].analyzer_model == "zdr-analyzer"
    assert evidence[0].zero_data_retention_available is True
    assert enriched[1].supports_no_training is True
    assert enriched[1].supports_no_prompt_retention is None
    assert enriched[1].supports_zero_data_retention is None


def test_analysis_rejects_hallucinated_quote_and_non_zdr_analyzer() -> None:
    policy_url = "https://provider.example/privacy"
    target = _model("provider", "model", policy_urls=(policy_url,))
    non_zdr = _model("openrouter", "ordinary-model", zdr=False)

    unchanged, absent = analyze_discovered_privacy_policies(
        [non_zdr, target],
        crawler=lambda _url: "No retained prompts.",
        analyzer=lambda _candidate, _documents: {},
    )
    assert unchanged == [non_zdr, target]
    assert absent == []

    zdr = _model("openrouter", "zdr-model", zdr=True)
    unchanged, absent = analyze_discovered_privacy_policies(
        [zdr, target],
        crawler=lambda _url: "No retained prompts.",
        analyzer=lambda _candidate, _documents: {
            "assessments": [{
                "source_url": policy_url,
                "zero_data_retention_available": True,
                "no_training": True,
                "no_prompt_retention": True,
                "evidence_quote": "invented evidence",
            }]
        },
    )
    assert unchanged == [zdr, target]
    assert absent == []


def test_analysis_fails_over_after_analyzer_returns_only_ungrounded_rows() -> None:
    """A schema-shaped hallucination cannot prevent a grounded candidate attempt."""
    policy_url = "https://provider.example/privacy"
    first = _model("a-provider", "first-zdr", zdr=True)
    second = _model("b-provider", "second-zdr", zdr=True)
    target = _model("provider", "model", policy_urls=(policy_url,))
    attempted: list[str] = []

    def analyze(candidate, _documents):
        attempted.append(candidate.model_id)
        quote = "invented evidence" if candidate is first else "No retained prompts."
        return {
            "assessments": [
                {
                    "source_url": policy_url,
                    "zero_data_retention_available": None,
                    "no_training": None,
                    "no_prompt_retention": True,
                    "evidence_quote": quote,
                }
            ]
        }

    enriched, evidence = analyze_discovered_privacy_policies(
        [first, second, target],
        crawler=lambda _url: "No retained prompts.",
        analyzer=analyze,
    )

    assert attempted == ["first-zdr", "second-zdr"]
    assert evidence[0].analyzer_model == "second-zdr"
    assert enriched[2].supports_no_prompt_retention is True


def test_analysis_rejects_ambiguous_duplicate_source_assessments() -> None:
    """Conflicting rows for one source cannot become order-dependent truth."""
    policy_url = "https://provider.example/privacy"
    analyzer_model = _model("openrouter", "zdr-analyzer", zdr=True)
    target = _model("provider", "model", policy_urls=(policy_url,))
    policy_text = "Inputs are used for training. Inputs are not used for training."

    enriched, evidence = analyze_discovered_privacy_policies(
        [analyzer_model, target],
        crawler=lambda _url: policy_text,
        analyzer=lambda _candidate, _documents: {
            "assessments": [
                {
                    "source_url": policy_url,
                    "zero_data_retention_available": None,
                    "no_training": True,
                    "no_prompt_retention": None,
                    "evidence_quote": "Inputs are not used for training.",
                },
                {
                    "source_url": policy_url,
                    "zero_data_retention_available": None,
                    "no_training": False,
                    "no_prompt_retention": None,
                    "evidence_quote": "Inputs are used for training.",
                },
            ]
        },
    )

    assert enriched[1].supports_no_training is None
    assert evidence == []


def test_policy_crawler_delegates_external_fetch_to_wardnet() -> None:
    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return json.dumps({
                "status": 200,
                "content_type": "text/html; charset=utf-8",
                "final_url": "https://provider.example/privacy",
                "body_base64": base64.b64encode(
                    b"<html><body>No training.</body></html>"
                ).decode("ascii"),
                "redirects": 0,
            }).encode("utf-8")

    set_backend(InMemoryCredentialBackend())
    register_credential("WARDNET_API_URL", "http://127.0.0.1:8080")
    register_credential("WARDNET_ADMIN_TOKEN", "wardnet-test-token")
    try:
        with patch(
            "contextual_orchestrator.privacy_policy_analysis.ModelClient._open_provider",
            return_value=_Response(),
        ) as opened, patch(
            "contextual_orchestrator.privacy_policy_analysis.ModelClient._resolve_addresses",
            return_value=[(2, ("127.0.0.1", 8080))],
        ):
            assert crawl_policy_document("https://provider.example/privacy") == "No training."
    finally:
        set_backend(None)

    request = opened.call_args.args[0]
    assert opened.call_args.kwargs["timeout"] is None
    assert request.full_url == "http://127.0.0.1:8080/api/outbound/fetch"
    assert json.loads(request.data) == {
        "url": "https://provider.example/privacy",
        "max_bytes": 512 * 1024,
    }


def test_policy_crawler_uses_camoufox_rendering_after_wardnet_approval() -> None:
    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return json.dumps({
                "status": 200,
                "content_type": "text/plain",
                "final_url": "https://provider.example/privacy",
                "body_base64": base64.b64encode(b"<html>Static shell</html>").decode(),
            }).encode()

    set_backend(InMemoryCredentialBackend())
    for name, value in {
        "WARDNET_API_URL": "http://127.0.0.1:8080",
        "WARDNET_ADMIN_TOKEN": "wardnet-test-token",
        "WARDNET_EGRESS_PROXY_URL": "http://127.0.0.1:8081",
        "WARDNET_EGRESS_PROXY_TOKEN": "wardnet-proxy-test-token",
        "CAMOUFOX_MCP_URL": "http://127.0.0.1:9377/mcp",
        "CAMOUFOX_MCP_TOKEN": "camoufox-test-token",
    }.items():
        register_credential(name, value)
    try:
        with patch(
            "contextual_orchestrator.privacy_policy_analysis.ModelClient._open_provider",
            return_value=_Response(),
        ), patch(
            "contextual_orchestrator.privacy_policy_analysis.ModelClient._resolve_addresses",
            return_value=[(2, ("127.0.0.1", 8080))],
        ):
            text = crawl_policy_document(
                "https://provider.example/privacy",
                camoufox_renderer=lambda _url: (
                    f"<script>{'x' * 24_000}</script><main>Rendered policy.</main>"
                ),
            )
            proxy = _wardnet_browser_proxy()
    finally:
        set_backend(None)

    assert text == "Rendered policy."
    assert proxy == {
        "host": "127.0.0.1",
        "port": "8081",
        "username": "wardnet",
        "password": "wardnet-proxy-test-token",
    }


def _install_stub_mcp_sdk(monkeypatch, *, client, streamable_http_client, create_mcp_http_client) -> None:
    """Install a minimal MCP SDK 2.x module surface so the renderer runs without the package."""
    modules = {
        "mcp": types.ModuleType("mcp"),
        "mcp.client": types.ModuleType("mcp.client"),
        "mcp.client.streamable_http": types.ModuleType("mcp.client.streamable_http"),
        "mcp.shared": types.ModuleType("mcp.shared"),
        "mcp.shared._httpx_utils": types.ModuleType("mcp.shared._httpx_utils"),
    }
    modules["mcp"].Client = client
    modules["mcp"].client = modules["mcp.client"]
    modules["mcp"].shared = modules["mcp.shared"]
    modules["mcp.client"].streamable_http = modules["mcp.client.streamable_http"]
    modules["mcp.client.streamable_http"].streamable_http_client = streamable_http_client
    modules["mcp.shared"]._httpx_utils = modules["mcp.shared._httpx_utils"]
    modules["mcp.shared._httpx_utils"].create_mcp_http_client = create_mcp_http_client
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)


def test_installed_mcp_sdk_version_names_both_states(monkeypatch) -> None:
    """The diagnostic names the installed version, or says the package is absent."""
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "1.23.3")
    assert _installed_mcp_sdk_version() == "mcp 1.23.3"

    def missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", missing)
    assert _installed_mcp_sdk_version() == "mcp not installed"


def test_camoufox_render_reports_pre_v2_mcp_sdk(monkeypatch) -> None:
    """A 1.x MCP SDK without ``mcp.Client`` fails with the required version named."""
    legacy_mcp_module = types.ModuleType("mcp")
    legacy_mcp_module.ClientSession = object
    monkeypatch.setitem(sys.modules, "mcp", legacy_mcp_module)
    with pytest.raises(ImportError, match=r"MCP Python SDK >= 2\.0") as raised:
        asyncio.run(_render_policy_document_with_camoufox("https://provider.example/privacy"))
    assert "installed:" in str(raised.value)
    assert isinstance(raised.value.__cause__, ImportError)


def test_pinned_mcp_client_renders_and_closes_camoufox_tab(monkeypatch) -> None:
    """The renderer drives the SDK 2.x surface (verified against mcp==2.2.0) via stubs."""
    calls: list[tuple[str, dict[str, object]]] = []

    class _Context:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    class _Client:
        def __init__(self, transport: object) -> None:
            assert transport == "streamable-transport"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def call_tool(self, name: str, arguments: dict[str, object]):
            calls.append((name, arguments))
            payload = {
                "create_tab": {"tabId": "policy-tab"},
                "camofox_get_page_html": {"html": "<html>Rendered policy</html>"},
                "close_tab": {},
            }[name]
            return SimpleNamespace(
                is_error=False,
                content=[SimpleNamespace(text=json.dumps(payload))],
            )

    set_backend(InMemoryCredentialBackend())
    for name, value in {
        "WARDNET_EGRESS_PROXY_URL": "http://127.0.0.1:8080",
        "WARDNET_EGRESS_PROXY_TOKEN": "proxy-token",
        "CAMOUFOX_MCP_URL": "http://127.0.0.1:9377/mcp",
        "CAMOUFOX_MCP_TOKEN": "mcp-token",
    }.items():
        register_credential(name, value)
    _install_stub_mcp_sdk(
        monkeypatch,
        client=_Client,
        streamable_http_client=lambda url, http_client: (
            "streamable-transport"
            if url == "http://127.0.0.1:9377/mcp" and http_client is not None
            else None
        ),
        create_mcp_http_client=lambda **kwargs: (
            _Context()
            if kwargs == {"headers": {"authorization": "Bearer mcp-token"}}
            else None
        ),
    )
    try:
        rendered = asyncio.run(
            _render_policy_document_with_camoufox("https://provider.example/privacy")
        )
    finally:
        set_backend(None)

    assert rendered == "<html>Rendered policy</html>"
    assert calls == [
        (
            "create_tab",
            {
                "url": "https://provider.example/privacy",
                "proxy": {
                    "host": "127.0.0.1",
                    "port": "8080",
                    "username": "wardnet",
                    "password": "proxy-token",
                },
            },
        ),
        ("camofox_get_page_html", {"tabId": "policy-tab"}),
        ("close_tab", {"tabId": "policy-tab"}),
    ]


def test_analysis_preserves_provider_truth_and_requires_complete_consensus() -> None:
    first_url = "https://provider.example/privacy"
    second_url = "https://provider.example/terms"
    analyzer_model = _model("openrouter", "zdr-analyzer", zdr=True)
    declared = _model("declared", "model", policy_urls=(first_url,))
    declared = replace(declared, supports_no_training=False)
    incomplete = _model("incomplete", "model", policy_urls=(first_url, second_url))

    enriched, _evidence = analyze_discovered_privacy_policies(
        [analyzer_model, declared, incomplete],
        crawler=lambda _url: "Inputs are not used for training.",
        analyzer=lambda _candidate, _documents: {
            "assessments": [{
                "source_url": first_url,
                "zero_data_retention_available": None,
                "no_training": True,
                "no_prompt_retention": None,
                "evidence_quote": "Inputs are not used for training.",
            }]
        },
    )

    assert enriched[1].supports_no_training is False
    assert enriched[2].supports_no_training is None


def _analyzer_response(policy_url: str) -> dict:
    assessments = {
        "assessments": [
            {
                "source_url": policy_url,
                "zero_data_retention_available": True,
                "no_training": True,
                "no_prompt_retention": None,
                "evidence_quote": "Inputs are not used for training.",
            }
        ]
    }
    return {
        "choices": [{"message": {"content": json.dumps(assessments)}, "finish_reason": "stop"}]
    }


def test_analyzer_sends_selected_model_published_output_ceiling() -> None:
    policy_url = "https://provider.example/privacy"
    candidate = _model("openrouter", "zdr-analyzer", zdr=True)
    candidate = replace(candidate, max_output_tokens=12345)
    captured: dict = {}

    def fake_send(_agent, _endpoint, payload):
        captured["payload"] = payload
        return _analyzer_response(policy_url)

    with patch.object(ModelClient, "proxy_send_once", side_effect=fake_send):
        _call_analyzer(candidate, {policy_url: "Inputs are not used for training."}, ModelClient())

    assert captured["payload"]["max_tokens"] == 12345


def test_analyzer_omits_cap_when_model_ceiling_unknown() -> None:
    policy_url = "https://provider.example/privacy"
    candidate = _model("openrouter", "zdr-analyzer", zdr=True)
    captured: dict = {}

    def fake_send(_agent, _endpoint, payload):
        captured["payload"] = payload
        return _analyzer_response(policy_url)

    with patch.object(ModelClient, "proxy_send_once", side_effect=fake_send):
        _call_analyzer(candidate, {policy_url: "Inputs are not used for training."}, ModelClient())

    assert "max_tokens" not in captured["payload"]
