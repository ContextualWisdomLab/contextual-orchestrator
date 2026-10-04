"""Private diagnosis of same-server repository binding; not release acceptance."""

import asyncio

from contextual_orchestrator import vulnerability_claim as claims
from contextual_orchestrator import web_search_mcp as gateway
from test_vulnerability_claim import _npm_lock, _versioned_record


def test_mcp_server_keeps_original_repository_versions_after_sibling_build(tmp_path, monkeypatch):
    first = tmp_path / "repository_a"
    second = tmp_path / "repository_b"
    first.mkdir()
    second.mkdir()
    _npm_lock(first, "2.0.0")
    _npm_lock(second, "1.5.0")
    configuration = {claims.REPOSITORY_SNAPSHOT_CREDENTIAL: str(first),
                     gateway.MCP_SERVER_TOKEN_CREDENTIAL: "fixture-only-search-token"}
    monkeypatch.setattr(claims, "get_credential", configuration.get)
    monkeypatch.setattr(gateway, "get_credential", configuration.get)
    payload = _versioned_record("CVE-2024-1234", [{
        "version": "1.0.0", "lessThan": "2.0.0",
        "versionType": "semver", "status": "affected",
    }], defaultStatus="unaffected")
    monkeypatch.setattr(claims, "_fetch_official_record", lambda _: payload)
    server_a = gateway.build_web_search_mcp_server()

    async def assess(server):
        result = await server.call_tool("assess_vulnerability_claim", {
            "identifier": "CVE-2024-1234", "package_name": "lodash", "ecosystem": "npm",
        })
        assert not result.is_error
        return result.structured_content

    initial = asyncio.run(assess(server_a))
    assert initial["status"] == claims.CLAIM_REJECTED
    assert initial["installed_versions"] == ["2.0.0"]
    configuration[claims.REPOSITORY_SNAPSHOT_CREDENTIAL] = str(second)
    server_b = gateway.build_web_search_mcp_server()
    sibling = asyncio.run(assess(server_b))
    assert sibling["status"] == claims.CLAIM_SUPPORTED
    assert sibling["installed_versions"] == ["1.5.0"]
    original = asyncio.run(assess(server_a))
    assert original == initial
