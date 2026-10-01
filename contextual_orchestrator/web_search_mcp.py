"""Expose web search and advisory checks as Streamable HTTP MCP tools.

The protected API environment installs the official ``mcp`` 2.x SDK from the
project lock. It is imported only when the server is built, and server startup
fails closed when the installed SDK is missing or has another major version.
"""

from __future__ import annotations

import importlib.metadata
import secrets
from typing import Any

from .credentials import NotConfigured, get_credential
from .vulnerability_claim import assess_vulnerability_claim
from .web_search import web_search

MCP_SERVER_TOKEN_CREDENTIAL = "WEB_SEARCH_MCP_TOKEN"
MCP_SERVER_SCOPE = "web-search"


class _StaticMCPTokenVerifier:
    """Verify one KV-backed local deployment bearer without retaining callers."""

    def __init__(self, expected_token: str) -> None:
        self._expected_token = expected_token.encode("utf-8")

    async def verify_token(self, token: str) -> Any | None:
        """Return SDK access data only for the exact configured bearer."""
        try:
            accepted = secrets.compare_digest(token.encode("utf-8"), self._expected_token)
        except (AttributeError, TypeError, ValueError):
            accepted = False
        if not accepted:
            return None
        from mcp.server.auth.provider import AccessToken

        return AccessToken(
            token=token,
            client_id="web-search-mcp-caller",
            scopes=[MCP_SERVER_SCOPE],
        )


def web_search_tool_payload(query: str) -> list[dict[str, Any]]:
    """Return bounded SearXNG rows for one MCP ``web_search`` call."""
    return [row.as_dict() for row in web_search(query)]


def vulnerability_claim_tool_payload(
    identifier: str,
    package_name: str,
    ecosystem: str,
) -> dict[str, Any]:
    """Return identity evidence; unchecked versions cannot authorize a finding."""
    return assess_vulnerability_claim(identifier, package_name, ecosystem).as_dict()


def build_web_search_mcp_server() -> Any:
    """Register the two tools on an official MCP server object.

    Raises:
        ImportError: The installed ``mcp`` package is missing or older than 2.x.
    """
    _require_mcp_sdk_2()
    token = get_credential(MCP_SERVER_TOKEN_CREDENTIAL)
    if not token:
        raise NotConfigured(f"credential {MCP_SERVER_TOKEN_CREDENTIAL} is not configured")
    try:
        from mcp.server.auth.settings import AuthSettings
        from mcp.server.mcpserver import MCPServer
    except ImportError as exc:
        raise ImportError(
            "web search MCP server requires mcp SDK 2.x "
            f"(installed: {_installed_mcp_sdk_version()})"
        ) from exc
    server = MCPServer(
        name="web_search_gateway",
        instructions=(
            "Before reporting a CVE or GHSA, call assess_vulnerability_claim "
            "with the identifier, package name and ecosystem (PyPI, npm, crates.io). "
            "Repository evidence comes from an operator-selected snapshot. "
            "This identity check does not check versions or authorize a finding."
        ),
        auth=AuthSettings(
            issuer_url="http://127.0.0.1",
            resource_server_url=None,
            required_scopes=[MCP_SERVER_SCOPE],
        ),
        token_verifier=_StaticMCPTokenVerifier(token),
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
        return vulnerability_claim_tool_payload(identifier, package_name, ecosystem)

    return server


def _require_mcp_sdk_2() -> str:
    """Return the installed MCP version or fail closed outside major 2."""
    try:
        version = importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError as exc:
        raise ImportError("web search MCP server requires mcp SDK 2.x (not installed)") from exc
    if version.split(".", 1)[0] != "2":
        raise ImportError(f"web search MCP server requires mcp SDK 2.x (installed: {version})")
    return version


def serve_web_search_mcp(*, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Serve the tools on loopback Streamable HTTP. Non-loopback binds are refused."""
    if host not in {"127.0.0.1", "::1"}:
        raise ValueError("web search MCP binds to loopback only")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("port must be an integer from 1 to 65535")
    server = build_web_search_mcp_server()
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
