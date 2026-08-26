"""Grounded privacy-policy analysis through a discovered ZDR model."""

import base64
import json
from dataclasses import replace
from unittest.mock import patch

from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)
from contextual_orchestrator.model_discovery import DiscoveredModel
from contextual_orchestrator.privacy_policy_analysis import (
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


def test_zdr_model_analysis_updates_only_quote_grounded_policy_fields() -> None:
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
                "content_type": "text/html",
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
                camoufox_renderer=lambda _url: "<html><body>Rendered policy.</body></html>",
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
