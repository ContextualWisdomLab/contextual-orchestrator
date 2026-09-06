Added `contextual_orchestrator.web_search.web_search()`, a KV-credential-configured
client for a self-hosted SearXNG(-compatible) metasearch instance's JSON API.
Reuses the existing SSRF-safe transport boundary (`ModelClient._validate_provider`
/ `_open_provider`) rather than a new HTTP dependency. This is slice 1 of
ADR 0123 (`docs/adr/0123-web-search-mcp-a2a-gateway-foundation.md`), which also
records the still-unbuilt MCP Gateway, A2A Gateway, and Camoufox-browsing design.
