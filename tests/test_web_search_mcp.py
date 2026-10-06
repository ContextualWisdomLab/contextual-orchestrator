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


def test_advertised_claim_contract_matches_bounded_version_verdict(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Advertise supported exact-SemVer findings without promising general coverage."""
    import json

    from contextual_orchestrator import vulnerability_claim as claims
    from test_vulnerability_claim import _versioned_record

    values = {
        "WEB_SEARCH_MCP_TOKEN": "mcp-test-token",
        claims.REPOSITORY_SNAPSHOT_CREDENTIAL: str(tmp_path),
    }
    monkeypatch.setattr(web_search_mcp, "get_credential", values.get)
    monkeypatch.setattr(claims, "get_credential", values.get)
    (tmp_path / "package-lock.json").write_text(json.dumps({
        "lockfileVersion": 3,
        "packages": {"node_modules/lodash": {
            "version": "1.5.0",
            "resolved": "https://registry.npmjs.org/lodash/-/lodash-1.5.0.tgz",
        }},
    }))
    record = _versioned_record("CVE-2024-1234", [{
        "version": "1.0.0", "lessThan": "2.0.0",
        "versionType": "semver", "status": "affected",
    }])
    monkeypatch.setattr(claims, "_fetch_official_record", lambda _url: record)
    server = build_web_search_mcp_server()
    result = asyncio.run(server.call_tool("assess_vulnerability_claim", {
        "identifier": "CVE-2024-1234", "package_name": "lodash", "ecosystem": "npm",
    }))
    assert not result.is_error
    assert result.structured_content["versions_checked"] is True
    assert result.structured_content["finding_allowed"] is True
    tool = next(tool for tool in asyncio.run(server.list_tools())
                if tool.name == "assess_vulnerability_claim")
    for text in (server.instructions, tool.description):
        assert text is not None
        assert "Versions are not checked" not in text
        assert "does not check versions" not in text
        assert "no finding is authorized" not in text
        assert "exact SemVer" in text
        assert "finding_allowed" in text
        assert "GHSA" in text and "unverified" in text
        assert "versions_checked=false" in text
        assert "never rejected" in text
