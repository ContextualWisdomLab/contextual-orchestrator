"""Expose web search and advisory checks as Streamable HTTP MCP tools.

The official ``mcp`` SDK is the same deployment-provided package the Camoufox
client already uses. It is imported only when the server is built, so the rest
of the gateway keeps running where that package is absent.
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Sequence
from typing import Any

from .vulnerability_claim import assess_vulnerability_claim
from .web_search import web_search


def web_search_tool_payload(query: str) -> list[dict[str, Any]]:
    """Return bounded SearXNG rows for one MCP ``web_search`` call."""
    return [row.as_dict() for row in web_search(query)]


def vulnerability_claim_tool_payload(
    identifier: str,
    package_name: str,
    manifest_packages: Sequence[str],
) -> dict[str, str | None]:
    """Return a claim verdict. Callers must not report ``rejected`` or ``unverified``."""
    return assess_vulnerability_claim(identifier, package_name, manifest_packages).as_dict()


def build_web_search_mcp_server() -> Any:
    """Register the two tools on an official MCP server object.

    Raises:
        ImportError: The installed ``mcp`` package is missing or older than 2.x.
    """
    try:
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
            "with the identifier, the package name, and the repository manifest "
            "package names. Report a finding only when status is supported."
        ),
    )

    @server.tool(name="web_search", description="Search the configured SearXNG instance.")
    def web_search_tool(query: str) -> list[dict[str, Any]]:
        return web_search_tool_payload(query)

    @server.tool(
        name="assess_vulnerability_claim",
        description=(
            "Check a CVE or GHSA against the dependency manifest and an official "
            "record. status is supported, rejected, or unverified."
        ),
    )
    def assess_vulnerability_claim_tool(
        identifier: str,
        package_name: str,
        manifest_packages: list[str],
    ) -> dict[str, str | None]:
        return vulnerability_claim_tool_payload(identifier, package_name, manifest_packages)

    return server


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
