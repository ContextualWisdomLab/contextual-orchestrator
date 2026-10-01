"""Expose web search and advisory checks as Streamable HTTP MCP tools.

The official ``mcp`` SDK is the same deployment-provided package the Camoufox
client already uses. It is imported only when the server is built, so the rest
of the gateway keeps running where that package is absent.
"""

from __future__ import annotations

import hmac
import importlib.metadata
import re
from typing import Any
from urllib.parse import urlsplit

from .credentials import NotConfigured, get_credential
from .vulnerability_claim import (
    RepositoryPackageEvidence,
    assess_vulnerability_claim,
    capture_repository_package_evidence,
)
from .web_search import web_search


def web_search_tool_payload(query: str) -> list[dict[str, Any]]:
    """Return bounded SearXNG rows for one MCP ``web_search`` call."""
    return [row.as_dict() for row in web_search(query)]


def vulnerability_claim_tool_payload(
    identifier: str,
    package_name: str,
    ecosystem: str,
    *, repository_evidence: tuple[RepositoryPackageEvidence, ...] | None = None,
) -> dict[str, Any]:
    """Return identity evidence; unchecked versions cannot authorize a finding."""
    return assess_vulnerability_claim(
        identifier, package_name, ecosystem, repository_evidence=repository_evidence,
    ).as_dict()


SEARCH_TOKEN_KEY = "WEB_SEARCH_MCP_AUTH_TOKEN"
SEARCH_ISSUER_KEY = "WEB_SEARCH_MCP_ISSUER_URL"
SEARCH_RESOURCE_KEY = "WEB_SEARCH_MCP_RESOURCE_URL"
SEARCH_SCOPE = "web_search:read"
_BEARER_TOKEN = re.compile(r"[A-Za-z0-9._~+/-]+=*", re.ASCII)


def _valid_search_token(value: object) -> bool:
    """Require at least 32 characters in the RFC 6750 ASCII bearer format."""
    return isinstance(value, str) and len(value) >= 32 and _BEARER_TOKEN.fullmatch(value) is not None


def _search_auth_configuration(resource_url: str | None = None) -> tuple[str, str]:
    """Require dedicated KV credentials and truthful operator-selected metadata."""
    if not _valid_search_token(get_credential(SEARCH_TOKEN_KEY)):
        raise NotConfigured("configure a dedicated search bearer credential (at least 32 token characters)")
    issuer = get_credential(SEARCH_ISSUER_KEY)
    resource = get_credential(SEARCH_RESOURCE_KEY)
    try:
        issuer_parts = urlsplit(issuer or "")
        resource_parts = urlsplit(resource or "")
        if (
            not isinstance(issuer, str)
            or issuer_parts.scheme != "https"
            or not issuer_parts.hostname
            or issuer_parts.username is not None
            or issuer_parts.password is not None
            or issuer_parts.query
            or issuer_parts.fragment
            or issuer.strip() != issuer
            or any(ord(char) <= 32 or ord(char) >= 127 for char in issuer)
        ):
            raise ValueError
        issuer_parts.port  # Reject invalid ports before constructing the SDK.
        if (
            not isinstance(resource, str)
            or resource_parts.scheme != "http"
            or resource_parts.hostname not in {"127.0.0.1", "::1"}
            or resource_parts.port is None
            or not 1 <= resource_parts.port <= 65535
            or any(ord(char) <= 32 or ord(char) >= 127 for char in resource)
            or resource_parts.path != "/mcp"
            or resource_parts.username is not None
            or resource_parts.password is not None
            or resource_parts.query
            or resource_parts.fragment
            or resource != f"http://{resource_parts.netloc}/mcp"
            or (resource_url is not None and resource != resource_url)
        ):
            raise ValueError
    except (TypeError, ValueError):
        raise NotConfigured("configure a real HTTPS search issuer and the exact loopback MCP resource URL") from None
    return issuer, resource


def build_web_search_mcp_server(
    *, resource_url: str | None = None,
    repository_evidence: tuple[RepositoryPackageEvidence, ...] | None = None,
) -> Any:
    """Register the two read tools with dedicated KV-backed SDK authentication.

    In-memory fixtures can supply a credential backend without starting HTTP.
    Production metadata is operator-supplied, not an OAuth server implemented here.
    Trusted bootstrap may inject frozen evidence after independently validating its
    handoff; this Python argument is never part of an MCP tool's caller schema.

    Raises:
        ImportError: The installed ``mcp`` package is missing or older than 2.x.
        NotConfigured: Dedicated search authorization configuration is invalid.
    """
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError as exc:
        raise ImportError(
            "web search MCP server requires mcp SDK 2.x "
            f"(installed: {_installed_mcp_sdk_version()})"
        ) from exc
    from mcp.server.auth.provider import AccessToken, TokenVerifier
    from mcp.server.auth.settings import AuthSettings

    issuer, resource = _search_auth_configuration(resource_url)
    if repository_evidence is None:
        repository_evidence = capture_repository_package_evidence()

    class SearchTokenVerifier(TokenVerifier):
        """Verify only the current dedicated search grant; rotation stays KV-owned."""

        async def verify_token(self, token: str) -> AccessToken | None:
            """Compare the full bearer in constant time and grant only read scope."""
            expected = get_credential(SEARCH_TOKEN_KEY)
            if not _valid_search_token(token) or not _valid_search_token(expected) or not hmac.compare_digest(
                token.encode("utf-8"), expected.encode("ascii")
            ):
                return None
            return AccessToken(
                token=token,
                client_id="web_search_capability",
                scopes=[SEARCH_SCOPE],
                resource=resource,
                claims={"iss": issuer},
            )

    server = MCPServer(
        auth=AuthSettings(
            issuer_url=issuer,
            resource_server_url=resource,
            required_scopes=[SEARCH_SCOPE],
        ),
        token_verifier=SearchTokenVerifier(),
        name="web_search_gateway",
        instructions=(
            "Before reporting a CVE or GHSA, call assess_vulnerability_claim "
            "with the identifier, package name and ecosystem (PyPI, npm, crates.io). "
            "Repository evidence comes from an operator-selected snapshot. "
            "This identity check does not check versions or authorize a finding."
        ),
    )

    @server.tool(name="web_search", description="Search the configured SearXNG instance.")
    def web_search_tool(query: str) -> list[dict[str, Any]]:
        return web_search_tool_payload(query)

    @server.tool(
        name="assess_vulnerability_claim",
        description=(
            "Check package identity against trusted repository manifests and an "
            "official record. Versions are not checked; no finding is authorized."
        ),
    )
    def assess_vulnerability_claim_tool(
        identifier: str,
        package_name: str,
        ecosystem: str,
    ) -> dict[str, Any]:
        return vulnerability_claim_tool_payload(
            identifier, package_name, ecosystem, repository_evidence=repository_evidence,
        )

    return server


def serve_web_search_mcp(*, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Serve the tools on loopback Streamable HTTP. Non-loopback binds are refused."""
    if host not in {"127.0.0.1", "::1"}:
        raise ValueError("web search MCP binds to loopback only")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("port must be an integer from 1 to 65535")
    resource_url = f"http://{'[' + host + ']' if host == '::1' else host}:{port}/mcp"
    _search_auth_configuration(resource_url)  # Fail before server construction or binding.
    server = build_web_search_mcp_server(resource_url=resource_url)
    server.run(
        transport="streamable-http",
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
    )


def _installed_mcp_sdk_version() -> str:
    try:
        return "mcp " + importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError:
        return "mcp not installed"


if __name__ == "__main__":
    serve_web_search_mcp()
