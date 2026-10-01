"""MCP exposure stays loopback-only and does not confirm an unavailable search."""

from __future__ import annotations

import asyncio

import pytest
from starlette.testclient import TestClient

from contextual_orchestrator import web_search_mcp
from contextual_orchestrator.credentials import NotConfigured
from contextual_orchestrator.vulnerability_claim import (
    CLAIM_UNVERIFIED,
    VulnerabilityClaimVerdict,
)
from contextual_orchestrator.web_search_mcp import (
    build_web_search_mcp_server,
    serve_web_search_mcp,
    vulnerability_claim_tool_payload,
)


def _register_mcp_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        web_search_mcp,
        "get_credential",
        lambda name: "mcp-test-token" if name == "WEB_SEARCH_MCP_TOKEN" else None,
    )


@pytest.mark.parametrize("version", ["1.99.0", "3.0.0", "not-a-version"])
def test_mcp_server_rejects_versions_outside_major_2(
    monkeypatch: pytest.MonkeyPatch, version: str,
) -> None:
    assert hasattr(web_search_mcp, "_require_mcp_sdk_2")
    monkeypatch.setattr(
        "contextual_orchestrator.web_search_mcp.importlib.metadata.version",
        lambda _: version,
    )

    with pytest.raises(ImportError, match="requires mcp SDK 2.x"):
        web_search_mcp._require_mcp_sdk_2()


def test_claim_tool_passes_through_an_unverified_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    def _unverified(*_args: object, **_kwargs: object) -> VulnerabilityClaimVerdict:
        return VulnerabilityClaimVerdict(CLAIM_UNVERIFIED, "search is unavailable")

    monkeypatch.setattr(
        "contextual_orchestrator.web_search_mcp.assess_vulnerability_claim",
        _unverified,
    )
    payload = vulnerability_claim_tool_payload("CVE-2024-1234", "lodash", "npm")
    assert payload["status"] == CLAIM_UNVERIFIED


def test_serve_refuses_a_public_bind() -> None:
    with pytest.raises(ValueError, match="loopback"):
        serve_web_search_mcp(host="0.0.0.0")


def test_server_requires_a_registered_caller_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_search_mcp, "get_credential", lambda _name: None, raising=False)

    with pytest.raises(NotConfigured, match="WEB_SEARCH_MCP_TOKEN"):
        build_web_search_mcp_server()


def test_server_verifier_accepts_only_the_registered_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register_mcp_token(monkeypatch)
    server = build_web_search_mcp_server()

    accepted = asyncio.run(server._token_verifier.verify_token("mcp-test-token"))
    rejected = asyncio.run(server._token_verifier.verify_token("wrong-token"))

    assert accepted is not None
    assert accepted.scopes == ["web-search"]
    assert rejected is None


def test_streamable_http_rejects_missing_and_wrong_bearers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register_mcp_token(monkeypatch)
    app = build_web_search_mcp_server().streamable_http_app(
        stateless_http=True,
        json_response=True,
    )

    with TestClient(app) as client:
        missing = client.post("/mcp", json={})
        wrong = client.post(
            "/mcp",
            headers={"Authorization": "Bearer wrong-token"},
            json={},
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.headers["www-authenticate"].startswith("Bearer")


def test_server_registers_both_tools_with_locked_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    _register_mcp_token(monkeypatch)
    server = build_web_search_mcp_server()
    names = {tool.name for tool in server._tool_manager.list_tools()}
    assert {"web_search", "assess_vulnerability_claim"} <= names


def test_claim_tool_schema_does_not_accept_paths_or_package_lists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register_mcp_token(monkeypatch)
    server = build_web_search_mcp_server()
    tool = next(tool for tool in server._tool_manager.list_tools() if tool.name == "assess_vulnerability_claim")
    assert set(tool.parameters["properties"]) == {"identifier", "package_name", "ecosystem"}
