"""Query a self-hosted, SearXNG-compatible metasearch engine for grounded web results.

This is slice 1 of the MCP/A2A web-search gateway design in
``docs/adr/0123-web-search-mcp-a2a-gateway-foundation.md``. That ADR covers the
full vision (an MCP gateway surface, an A2A gateway surface, and an isolated
Camoufox browsing capability gated on ``ContextualWisdomLab/quarantine-sandbox-runtime``
reaching a real HTTP/CLI surface). Only the search half ships here: a
credential-configured HTTP call to a SearXNG JSON API. It needs no browser and
no sandbox, so it can run today.

Like :func:`contextual_orchestrator.privacy_policy_analysis.crawl_policy_document`,
this module reuses :class:`~contextual_orchestrator.orchestrator.ModelClient`'s
validated-transport primitives (``_validate_provider`` / ``_open_provider``)
purely for their SSRF-safe HTTP boundary -- rejecting non-HTTPS hosts, private/
loopback/link-local/reserved destination IPs, and userinfo/query/fragment
smuggling in a configured URL -- not for any chat/completions semantics. The
SearXNG base URL and optional bearer token are resolved from the same KV
credential registry as every other provider secret in this repository (see
``docs/kv-credentials.md``); nothing is read from ``os.getenv``.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
import urllib.request
from urllib.parse import urlencode, urlsplit, urlunsplit

from .credentials import get_credential
from .orchestrator import ModelAgent, ModelClient

#: Hard ceiling on the query string this module will send to a search engine.
MAX_QUERY_LENGTH = 512
#: Hard ceiling on how many results a caller may request back.
MAX_RESULTS = 20
#: Default result count when a caller does not specify one.
DEFAULT_MAX_RESULTS = 10
#: Hard ceiling on the search response body this module will read into memory.
MAX_RESPONSE_BYTES = 1024 * 1024
#: Bounds on the caller-supplied ``timeout`` (seconds), mirroring the pattern in
#: :func:`contextual_orchestrator.orchestrator._validate_provider_probe_timeout`.
MIN_TIMEOUT_SECONDS = 0.1
MAX_TIMEOUT_SECONDS = 60.0

#: KV credential name for the SearXNG (or SearXNG-API-compatible) instance's base URL.
SEARXNG_URL_CREDENTIAL = "SEARXNG_URL"
#: KV credential name for an optional bearer token (e.g. for a reverse-proxy-protected
#: instance). Vanilla SearXNG has no native API key, so this is opt-in.
SEARXNG_TOKEN_CREDENTIAL = "SEARXNG_TOKEN"

#: Search engines this module can query today. See the ADR for evaluated-but-not-yet-
#: implemented alternatives (YaCy) and why one candidate (Whoogle) was rejected.
SUPPORTED_ENGINES = ("searxng",)


@dataclass(frozen=True)
class WebSearchResult:
    """One grounded result row from a metasearch engine."""

    url: str
    title: str
    content: str
    engine: str
    score: float | None = None
    published_date: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-ready result."""
        return {
            "url": self.url,
            "title": self.title,
            "content": self.content,
            "engine": self.engine,
            "score": self.score,
            "published_date": self.published_date,
        }


def _searxng_origins() -> tuple[str, str]:
    """Resolve and validate the configured SearXNG URL.

    Returns a ``(agent_base_url, request_base_url)`` pair. ``agent_base_url``
    is fed to :meth:`ModelClient._validate_provider` for the SSRF-safe host
    check (HTTPS is required unless the host is an explicit loopback address,
    mirroring the Wardnet policy-fetch boundary). ``request_base_url`` is the
    real origin -- including any deployment path prefix (e.g. an instance
    reverse-proxied under ``/searxng``) -- used to build the outgoing request
    URL, so a subpath-deployed instance is queried at its own ``/search``
    rather than at the host root.
    """
    configured = get_credential(SEARXNG_URL_CREDENTIAL)
    if not configured:
        raise ValueError("SearXNG is not configured in the credential registry")
    parsed = urlsplit(configured.strip().rstrip("/"))
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("SEARXNG_URL is invalid")
    request_base_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    if parsed.scheme == "http":
        # Loopback-only local:// mapping, same boundary crawl_policy_document
        # uses for a plaintext Wardnet URL: ModelClient._validate_provider only
        # accepts http for an explicit loopback host.
        agent_base_url = urlunsplit(("local", parsed.netloc, "", "", ""))
    else:
        agent_base_url = request_base_url
    return agent_base_url, request_base_url


def _parse_results(payload: Any, max_results: int) -> list[WebSearchResult]:
    """Parse a SearXNG JSON envelope into bounded, type-checked results.

    Malformed rows (missing/wrong-typed ``url`` or ``title``) are skipped
    rather than raised on, since one bad row from a federated engine should
    not fail an otherwise-usable search; a malformed envelope (not a dict, or
    missing the ``results`` list entirely) is a transport-contract violation
    and still raises.
    """
    if not isinstance(payload, dict):
        raise TypeError("SearXNG returned an invalid JSON envelope")
    rows = payload.get("results")
    if not isinstance(rows, list):
        raise TypeError("SearXNG response omitted a results list")

    results: list[WebSearchResult] = []
    for row in rows:
        if len(results) >= max_results:
            break
        if not isinstance(row, dict):
            continue
        url = row.get("url")
        title = row.get("title")
        if not isinstance(url, str) or not url or not isinstance(title, str):
            continue
        content = row.get("content")
        engine = row.get("engine")
        score = row.get("score")
        published_date = row.get("publishedDate")
        results.append(
            WebSearchResult(
                url=url,
                title=title,
                content=content if isinstance(content, str) else "",
                engine=engine if isinstance(engine, str) else "",
                score=score if isinstance(score, (int, float)) and not isinstance(score, bool) else None,
                published_date=published_date if isinstance(published_date, str) else None,
            )
        )
    return results


def web_search(
    query: str,
    *,
    engine: str = "searxng",
    categories: str = "general",
    language: str = "all",
    max_results: int = DEFAULT_MAX_RESULTS,
    timeout: float = 10.0,
) -> list[WebSearchResult]:
    """Search a configured metasearch engine and return bounded, grounded results.

    Requires ``SEARXNG_URL`` (and optionally ``SEARXNG_TOKEN``) registered in
    the KV credential registry; see ``docs/kv-credentials.md``. Fails closed:
    a missing/invalid configuration, an oversized response, or a malformed
    JSON envelope raises rather than returning an empty or partial result set
    silently. Individual malformed result rows are skipped (see
    :func:`_parse_results`), since SearXNG itself federates multiple upstream
    engines and one upstream's bad row should not fail the whole query.
    """
    if engine not in SUPPORTED_ENGINES:
        raise ValueError(f"unsupported search engine {engine!r}; supported: {SUPPORTED_ENGINES}")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if len(query) > MAX_QUERY_LENGTH:
        raise ValueError(f"query exceeds {MAX_QUERY_LENGTH} characters")
    if not isinstance(categories, str) or not categories:
        raise ValueError("categories must be a non-empty string")
    if not isinstance(language, str) or not language:
        raise ValueError("language must be a non-empty string")
    if isinstance(max_results, bool) or not isinstance(max_results, int) or not 1 <= max_results <= MAX_RESULTS:
        raise ValueError(f"max_results must be an integer between 1 and {MAX_RESULTS}")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        # A bounds check against finite MIN/MAX already excludes NaN and
        # +/-infinity (every comparison with them is False), and unlike
        # math.isfinite() it never raises OverflowError on an int too large
        # to convert to a C double.
        or not MIN_TIMEOUT_SECONDS <= timeout <= MAX_TIMEOUT_SECONDS
    ):
        raise ValueError(
            f"timeout must be a finite number between {MIN_TIMEOUT_SECONDS:g} and {MAX_TIMEOUT_SECONDS:g} seconds"
        )

    agent_base_url, request_base_url = _searxng_origins()
    agent = ModelAgent("web_search_searxng", "web-search-searxng", base_url=agent_base_url, credential_key="")
    client = ModelClient(timeout=max(1, int(timeout)))
    destination = client._validate_provider(agent)

    query_string = urlencode({"q": query, "format": "json", "categories": categories, "language": language})
    headers = {"accept": "application/json"}
    token = get_credential(SEARXNG_TOKEN_CREDENTIAL)
    if token:
        headers["authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{request_base_url}/search?{query_string}",
        headers=headers,
        method="GET",
    )
    with client._open_provider(request, destination, timeout=timeout) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("SearXNG response exceeds the size limit")
    payload = json.loads(raw.decode("utf-8"))
    return _parse_results(payload, max_results)
