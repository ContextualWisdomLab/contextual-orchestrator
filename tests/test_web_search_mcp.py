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


def test_builder_uses_supplied_frozen_evidence_without_filesystem_capture(search_auth_backend, monkeypatch) -> None:
    """Trusted bootstrap injection is Python-only and cannot be replaced by KV/files."""
    pytest.importorskip("mcp.server.mcpserver")
    from contextual_orchestrator import web_search_mcp as gateway
    from contextual_orchestrator.vulnerability_claim import RepositoryPackageEvidence
    evidence = (RepositoryPackageEvidence("npm", frozenset({"lodash"})),)
    def no_capture():
        raise AssertionError("injected evidence must not reread files")
    monkeypatch.setattr(gateway, "capture_repository_package_evidence", no_capture)
    server = gateway.build_web_search_mcp_server(repository_evidence=evidence)
    assert {tool.name for tool in server._tool_manager.list_tools()} == {"web_search", "assess_vulnerability_claim"}


def test_claim_tool_passes_through_an_unverified_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    def _unverified(*_args: object, **_kwargs: object) -> VulnerabilityClaimVerdict:
        return VulnerabilityClaimVerdict(CLAIM_UNVERIFIED, "search is unavailable")

    monkeypatch.setattr(
        "contextual_orchestrator.web_search_mcp.assess_vulnerability_claim",
        _unverified,
    )
    payload = vulnerability_claim_tool_payload("CVE-2024-1234", "lodash", "npm")
    assert payload["status"] == CLAIM_UNVERIFIED
    assert payload["versions_checked"] is False
    assert payload["finding_allowed"] is False


def test_serve_refuses_a_public_bind() -> None:
    with pytest.raises(ValueError, match="loopback"):
        serve_web_search_mcp(host="0.0.0.0")


def test_serve_requires_dedicated_search_auth_before_build_or_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    from contextual_orchestrator.credentials import InMemoryCredentialBackend, NotConfigured

    backend = InMemoryCredentialBackend()
    backend.set("CONTEXTUAL_ORCHESTRATOR_AUTH_TOKEN", "fixture-chat-only-token")
    monkeypatch.setattr("contextual_orchestrator.credentials._backend", backend)
    built: list[bool] = []

    class Server:
        def run(self, **_kwargs: object) -> None:
            built.append(True)

    monkeypatch.setattr("contextual_orchestrator.web_search_mcp.build_web_search_mcp_server", lambda **_kwargs: Server())
    with pytest.raises(NotConfigured):
        serve_web_search_mcp()
    assert built == []


def test_server_registers_both_tools_when_sdk_is_present(search_auth_backend) -> None:
    try:
        server = build_web_search_mcp_server()
    except ImportError as exc:
        assert "mcp SDK 2.x" in str(exc)
        return
    names = {tool.name for tool in server._tool_manager.list_tools()}
    assert {"web_search", "assess_vulnerability_claim"} <= names


def test_claim_tool_schema_does_not_accept_paths_or_package_lists(search_auth_backend) -> None:
    try:
        server = build_web_search_mcp_server()
    except ImportError:
        pytest.skip("SDK not installed in this interpreter")
    tool = next(tool for tool in server._tool_manager.list_tools() if tool.name == "assess_vulnerability_claim")
    assert set(tool.parameters["properties"]) == {"identifier", "package_name", "ecosystem"}


@pytest.fixture
def search_auth_backend(monkeypatch: pytest.MonkeyPatch):
    from contextual_orchestrator.credentials import InMemoryCredentialBackend
    from contextual_orchestrator.web_search_mcp import SEARCH_ISSUER_KEY, SEARCH_RESOURCE_KEY, SEARCH_TOKEN_KEY

    backend = InMemoryCredentialBackend()
    backend.set(SEARCH_TOKEN_KEY, "fixture-search-capability-token-0123456789")
    backend.set(SEARCH_ISSUER_KEY, "https://issuer.example.test/search")
    backend.set(SEARCH_RESOURCE_KEY, "http://127.0.0.1:8765/mcp")
    monkeypatch.setattr("contextual_orchestrator.credentials._backend", backend)
    return backend


@pytest.mark.parametrize(("key", "value"), [
    ("WEB_SEARCH_MCP_AUTH_TOKEN", None),
    ("WEB_SEARCH_MCP_AUTH_TOKEN", ""),
    ("WEB_SEARCH_MCP_AUTH_TOKEN", "short"),
    ("WEB_SEARCH_MCP_AUTH_TOKEN", "fixture token with whitespace 0123456789"),
    ("WEB_SEARCH_MCP_AUTH_TOKEN", "fixture-search-token-0123456789\n"),
    ("WEB_SEARCH_MCP_AUTH_TOKEN", "fixture-search-token-0123456789é"),
    ("WEB_SEARCH_MCP_ISSUER_URL", None),
    ("WEB_SEARCH_MCP_ISSUER_URL", "http://issuer.example.test"),
    ("WEB_SEARCH_MCP_ISSUER_URL", "https://user:password@issuer.example.test"),
    ("WEB_SEARCH_MCP_ISSUER_URL", "https://issuer.example.test/#fragment"),
    ("WEB_SEARCH_MCP_ISSUER_URL", "https://issuer.example.test/?query=yes"),
    ("WEB_SEARCH_MCP_ISSUER_URL", "https://issuer.example.test:bad"),
    ("WEB_SEARCH_MCP_RESOURCE_URL", None),
    ("WEB_SEARCH_MCP_RESOURCE_URL", "http://127.0.0.1:0/mcp"),
    ("WEB_SEARCH_MCP_RESOURCE_URL", "http://127.0.0.1:65536/mcp"),
    ("WEB_SEARCH_MCP_RESOURCE_URL", "http://127.0.0.1:8765\n/mcp"),
    ("WEB_SEARCH_MCP_RESOURCE_URL", "http://127.0.0.1:8765\t/mcp"),
    ("WEB_SEARCH_MCP_RESOURCE_URL", "http://127.0.0.1:8765\x00/mcp"),
    ("WEB_SEARCH_MCP_RESOURCE_URL", "http://127.0.0.1:8765/mcp "),
    ("WEB_SEARCH_MCP_RESOURCE_URL", "http://search.example.test:8765/mcp"),
    ("WEB_SEARCH_MCP_RESOURCE_URL", "http://127.0.0.1:9999/mcp"),
    ("WEB_SEARCH_MCP_RESOURCE_URL", "http://127.0.0.1:8765/mcp?query=yes"),
    ("WEB_SEARCH_MCP_RESOURCE_URL", "http://127.0.0.1:8765/other"),
])
def test_serve_rejects_malformed_auth_before_build(
    key: str, value: str | None, search_auth_backend, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextual_orchestrator.credentials import NotConfigured

    if value is None:
        search_auth_backend.delete(key)
    else:
        search_auth_backend.set(key, value)

    def must_not_build(**_kwargs: object):
        raise AssertionError("server constructed before auth validation")

    monkeypatch.setattr("contextual_orchestrator.web_search_mcp.build_web_search_mcp_server", must_not_build)
    with pytest.raises(NotConfigured):
        serve_web_search_mcp()


def test_auth_configuration_rejects_zero_resource_port(search_auth_backend) -> None:
    from contextual_orchestrator.credentials import NotConfigured
    from contextual_orchestrator.web_search_mcp import SEARCH_RESOURCE_KEY, _search_auth_configuration

    search_auth_backend.set(SEARCH_RESOURCE_KEY, "http://127.0.0.1:0/mcp")
    with pytest.raises(NotConfigured):
        _search_auth_configuration()


def test_serve_builds_authenticated_server_without_fixture_bypass(
    search_auth_backend, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class Server:
        def run(self, **kwargs: object) -> None:
            calls.append(kwargs)

    def build(**kwargs: object):
        assert kwargs == {"resource_url": "http://127.0.0.1:8765/mcp"}
        return Server()

    monkeypatch.setattr("contextual_orchestrator.web_search_mcp.build_web_search_mcp_server", build)
    serve_web_search_mcp()
    assert calls == [{
        "transport": "streamable-http", "host": "127.0.0.1", "port": 8765,
        "stateless_http": True, "json_response": True,
    }]


def test_sdk_verifier_compares_exactly_and_observes_kv_rotation(
    search_auth_backend, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import hmac

    pytest.importorskip("mcp.server.mcpserver")
    from contextual_orchestrator.web_search_mcp import SEARCH_SCOPE, SEARCH_TOKEN_KEY

    compare = hmac.compare_digest
    comparisons: list[bool] = []

    def checked_compare(candidate: bytes, expected: bytes) -> bool:
        comparisons.append(isinstance(candidate, bytes) and isinstance(expected, bytes))
        return compare(candidate, expected)

    monkeypatch.setattr("contextual_orchestrator.web_search_mcp.hmac.compare_digest", checked_compare)
    verifier = build_web_search_mcp_server()._token_verifier

    async def exercise() -> None:
        token = search_auth_backend.get(SEARCH_TOKEN_KEY)
        access = await verifier.verify_token(token)
        assert access.scopes == [SEARCH_SCOPE]
        assert access.resource == "http://127.0.0.1:8765/mcp"
        for wrong in (token + "-extra", token[:-1], "é" + token):
            assert await verifier.verify_token(wrong) is None
        rotated = "fixture-rotated-search-token-0123456789"
        search_auth_backend.set(SEARCH_TOKEN_KEY, rotated)
        assert await verifier.verify_token(token) is None
        assert await verifier.verify_token(rotated) is not None
        search_auth_backend.delete(SEARCH_TOKEN_KEY)
        assert await verifier.verify_token(rotated) is None
        assert comparisons == [True] * 5

    asyncio.run(exercise())


def test_sdk_auth_asgi_denies_before_tools_and_allows_exact_search_capability(
    search_auth_backend, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    pytest.importorskip("mcp.server.mcpserver")
    httpx = pytest.importorskip("httpx")
    from contextual_orchestrator.web_search_mcp import SEARCH_SCOPE, SEARCH_TOKEN_KEY

    executions: list[str] = []

    def search(_query: str):
        executions.append("web_search")
        return []

    def claim(*_args: str, **_kwargs: object):
        executions.append("assess_vulnerability_claim")
        return {"versions_checked": False, "finding_allowed": False}

    monkeypatch.setattr("contextual_orchestrator.web_search_mcp.web_search_tool_payload", search)
    monkeypatch.setattr("contextual_orchestrator.web_search_mcp.vulnerability_claim_tool_payload", claim)
    server = build_web_search_mcp_server()
    assert server.settings.auth.required_scopes == [SEARCH_SCOPE]
    assert {tool.name for tool in server._tool_manager.list_tools()} == {
        "web_search", "assess_vulnerability_claim",
    }
    verifier = server._token_verifier
    tools = [
        {"name": "web_search", "arguments": {"query": "fixture search"}},
        {"name": "assess_vulnerability_claim", "arguments": {
            "identifier": "CVE-2024-1234", "package_name": "fixture", "ecosystem": "PyPI",
        }},
    ]

    async def exercise() -> None:
        app = server.streamable_http_app(stateless_http=True, json_response=True)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765",
                headers={"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"},
            ) as client:
                for authorization in (None, "Bearer fixture-wrong-token", "Bearer fixture-search-capability-token-0123456789-extra"):
                    headers = {} if authorization is None else {"Authorization": authorization}
                    for params in tools:
                        response = await client.post("/mcp", headers=headers, json={
                            "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params,
                        })
                        assert response.status_code == 401
                        assert "resource_metadata=" in response.headers["www-authenticate"]
                        assert executions == []
                        await response.aclose()

                # The SDK, not custom middleware, must enforce scope denial too.
                class MissingScopeVerifier:
                    async def verify_token(self, token: str):
                        access = await verifier.verify_token(token)
                        return access.model_copy(update={"scopes": []}) if access else None

                scoped_server = build_web_search_mcp_server()
                scoped_server._token_verifier = MissingScopeVerifier()
                scoped_app = scoped_server.streamable_http_app(stateless_http=True, json_response=True)
                exact_headers = {"Authorization": "Bearer " + search_auth_backend.get(SEARCH_TOKEN_KEY)}
                async with scoped_app.router.lifespan_context(scoped_app):
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=scoped_app), base_url="http://127.0.0.1:8765",
                        headers=client.headers,
                    ) as denied_client:
                        for params in tools:
                            response = await denied_client.post("/mcp", headers=exact_headers, json={
                                "jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": params,
                            })
                            assert response.status_code == 403
                            assert response.json()["error"] == "insufficient_scope"
                            assert executions == []
                            await response.aclose()

                response = await client.post("/mcp", headers=exact_headers, json={
                    "jsonrpc": "2.0", "id": 3, "method": "initialize", "params": {
                        "protocolVersion": "2025-11-25", "capabilities": {},
                        "clientInfo": {"name": "fixture_client", "version": "1"},
                    },
                })
                assert response.status_code == 200
                assert response.json()["result"]["protocolVersion"] == "2025-11-25"
                await response.aclose()
                for params in tools:
                    response = await client.post("/mcp", headers=exact_headers, json={
                        "jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": params,
                    })
                    assert response.status_code == 200
                    assert not response.json()["result"].get("isError", False)
                    if params["name"] == "assess_vulnerability_claim":
                        assert response.json()["result"]["structuredContent"] == {
                            "versions_checked": False, "finding_allowed": False,
                        }
                    await response.aclose()
                assert executions == ["web_search", "assess_vulnerability_claim"]
                response = await client.get("/.well-known/oauth-protected-resource/mcp")
                assert response.status_code == 200
                metadata = response.json()
                assert metadata["resource"] == "http://127.0.0.1:8765/mcp"
                assert metadata["authorization_servers"] == ["https://issuer.example.test/search"]
                assert metadata["scopes_supported"] == [SEARCH_SCOPE]
                await response.aclose()
                for path in ("/authorize", "/token", "/register", "/.well-known/oauth-authorization-server"):
                    response = await client.get(path)
                    assert response.status_code == 404
                    await response.aclose()

    asyncio.run(exercise())


@pytest.mark.parametrize("initial", ['{"dependencies":{"lodash":"4.17.20"}}', '{"dependencies":', None])
def test_sdk_claim_capture_survives_files_kv_and_bearer_rotation(
    initial, tmp_path, search_auth_backend, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    pytest.importorskip("mcp.server.mcpserver")
    from contextual_orchestrator import vulnerability_claim as claims
    from contextual_orchestrator.web_search import WebSearchResult
    from contextual_orchestrator.web_search_mcp import SEARCH_TOKEN_KEY

    first = tmp_path / "snapshot_a"
    second = tmp_path / "snapshot_b"
    first.mkdir()
    second.mkdir()
    if initial is not None:
        (first / "package.json").write_text(initial)
    search_auth_backend.set(claims.REPOSITORY_SNAPSHOT_CREDENTIAL, str(first))
    server_a = build_web_search_mcp_server()
    (first / "package.json").write_text('{"dependencies":{"other":"1"}}')
    (second / "package.json").write_text('{"dependencies":{"other":"1"}}')
    search_auth_backend.set(claims.REPOSITORY_SNAPSHOT_CREDENTIAL, str(second))
    server_b = build_web_search_mcp_server()
    (second / "package.json").write_text('{"dependencies":{"later":"1"}}')

    searches = []
    monkeypatch.setattr(claims, "web_search", lambda identifier: searches.append(identifier) or [
        WebSearchResult("https://nvd.nist.gov/vuln/detail/CVE-2024-1234", "fixture", "", "searxng")])
    monkeypatch.setattr(claims, "_fetch_official_record", lambda _: {
        "cveMetadata": {"cveId": "CVE-2024-1234", "state": "PUBLISHED"},
        "containers": {"cna": {"affected": [{"collectionURL": "https://www.npmjs.com", "packageName": "lodash"}]}},
    })

    async def assess(server, package="lodash"):
        result = await server.call_tool("assess_vulnerability_claim", {
            "identifier": "CVE-2024-1234", "package_name": package, "ecosystem": "npm",
        })
        assert not result.is_error
        payload = result.structured_content
        assert payload["versions_checked"] is False and payload["finding_allowed"] is False
        return payload

    async def exercise():
        before = await assess(server_a)
        assert before["status"] == "unverified"
        token = search_auth_backend.get(SEARCH_TOKEN_KEY)
        rotated = "fixture-rotated-search-token-0123456789"
        search_auth_backend.set(SEARCH_TOKEN_KEY, rotated)
        assert await server_a._token_verifier.verify_token(token) is None
        assert await server_a._token_verifier.verify_token(rotated) is not None
        assert await assess(server_a) == before
        if initial and initial.endswith("}}"):
            assert before["repository_package_present"] is True and before["package_match"] is True
        else:
            assert before["repository_package_present"] is None
            assert before["reason"] == (
                "repository manifest evidence is unavailable" if initial is not None
                else "package presence is not established by supported manifests"
            )
        assert (await assess(server_b))["repository_package_present"] is None
        assert (await assess(server_b, "other"))["repository_package_present"] is True
        assert await assess(server_a) == before

    asyncio.run(exercise())
    assert len(searches) == (4 if initial and initial.endswith("}}") else 1)
