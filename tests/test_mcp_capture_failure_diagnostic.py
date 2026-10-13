"""Server snapshot failures cannot heal through later operator-file changes."""

import asyncio
import json

import pytest

from contextual_orchestrator import vulnerability_claim as claims
from contextual_orchestrator import web_search_mcp as gateway
from test_vulnerability_claim import _npm_lock, _versioned_record


def _server(tmp_path, monkeypatch):
    configuration = {claims.REPOSITORY_SNAPSHOT_CREDENTIAL: str(tmp_path),
                     gateway.MCP_SERVER_TOKEN_CREDENTIAL: "fixture-only-search-token"}
    monkeypatch.setattr(claims, "get_credential", configuration.get)
    monkeypatch.setattr(gateway, "get_credential", configuration.get)
    payload = _versioned_record("CVE-2024-1234", [{
        "version": "1.0.0", "lessThan": "2.0.0",
        "versionType": "semver", "status": "affected",
    }], defaultStatus="unaffected")
    monkeypatch.setattr(claims, "_fetch_official_record", lambda _: payload)
    return configuration


def _assess(server):
    async def call():
        result = await server.call_tool("assess_vulnerability_claim", {
            "identifier": "CVE-2024-1234", "package_name": "lodash", "ecosystem": "npm",
        })
        assert not result.is_error
        return result.structured_content
    return asyncio.run(call())


@pytest.mark.parametrize("initial", ["missing", "malformed_manifest", "malformed_version", "shrinkwrap"])
def test_server_capture_failure_does_not_heal(tmp_path, monkeypatch, initial):
    _server(tmp_path, monkeypatch)
    _npm_lock(tmp_path, "1.5.0")
    if initial == "missing":
        (tmp_path / "package.json").unlink()
        (tmp_path / "package-lock.json").unlink()
    elif initial == "malformed_manifest":
        (tmp_path / "package.json").write_text('{"dependencies":')
    elif initial == "malformed_version":
        lock = json.loads((tmp_path / "package-lock.json").read_text())
        lock["lockfileVersion"] = True
        (tmp_path / "package-lock.json").write_text(json.dumps(lock))
    else:
        (tmp_path / "npm-shrinkwrap.json").write_text("{}")
    server = gateway.build_web_search_mcp_server()
    original = _assess(server)
    assert original["status"] == claims.CLAIM_UNVERIFIED
    assert not original["finding_allowed"]
    if initial == "shrinkwrap":
        (tmp_path / "npm-shrinkwrap.json").unlink()
    _npm_lock(tmp_path, "1.5.0")
    repaired_server = gateway.build_web_search_mcp_server()
    assert _assess(repaired_server)["status"] == claims.CLAIM_SUPPORTED
    assert _assess(server) == original


def test_same_server_versions_survive_lock_rewrite(tmp_path, monkeypatch):
    _server(tmp_path, monkeypatch)
    _npm_lock(tmp_path, "2.0.0")
    server = gateway.build_web_search_mcp_server()
    original = _assess(server)
    assert original["status"] == claims.CLAIM_REJECTED
    _npm_lock(tmp_path, "1.5.0")
    assert _assess(gateway.build_web_search_mcp_server())["status"] == claims.CLAIM_SUPPORTED
    assert _assess(server) == original


def test_failed_configuration_does_not_heal_after_registration(tmp_path, monkeypatch):
    configuration = _server(tmp_path, monkeypatch)
    _npm_lock(tmp_path, "1.5.0")
    configuration.pop(claims.REPOSITORY_SNAPSHOT_CREDENTIAL)
    server = gateway.build_web_search_mcp_server()
    original = _assess(server)
    assert original["reason"] == "repository manifest evidence is unavailable"
    configuration[claims.REPOSITORY_SNAPSHOT_CREDENTIAL] = str(tmp_path)
    assert _assess(gateway.build_web_search_mcp_server())["status"] == claims.CLAIM_SUPPORTED
    assert _assess(server) == original
