"""MCP exposure stays loopback-only and does not confirm an unavailable search."""

from __future__ import annotations

import pytest

from contextual_orchestrator.vulnerability_claim import (
    CLAIM_UNVERIFIED,
    VulnerabilityClaimVerdict,
)
from contextual_orchestrator.web_search_mcp import (
    build_web_search_mcp_server,
    serve_web_search_mcp,
    vulnerability_claim_tool_payload,
)


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


def test_server_registers_both_tools_when_sdk_is_present() -> None:
    try:
        server = build_web_search_mcp_server()
    except ImportError as exc:
        assert "mcp SDK 2.x" in str(exc)
        return
    names = {tool.name for tool in server._tool_manager.list_tools()}
    assert {"web_search", "assess_vulnerability_claim"} <= names


def test_claim_tool_schema_does_not_accept_paths_or_package_lists() -> None:
    try:
        server = build_web_search_mcp_server()
    except ImportError:
        pytest.skip("SDK not installed in this interpreter")
    tool = next(tool for tool in server._tool_manager.list_tools() if tool.name == "assess_vulnerability_claim")
    assert set(tool.parameters["properties"]) == {"identifier", "package_name", "ecosystem"}
