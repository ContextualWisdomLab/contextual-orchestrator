"""Crawl provider policies and analyze them with an already-discovered ZDR route."""

from __future__ import annotations

import asyncio
import base64
import json
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .credentials import get_credential
from .model_discovery import DiscoveredModel, agent_from_discovered
from .orchestrator import ModelAgent, ModelClient

MAX_POLICY_BYTES = 512 * 1024
MAX_POLICY_CHARACTERS = 24_000
MAX_POLICY_SOURCES = 8
MAX_ANALYZER_CANDIDATES = 4
WARDNET_API_URL_CREDENTIAL = "WARDNET_API_URL"
WARDNET_ADMIN_TOKEN_CREDENTIAL = "WARDNET_ADMIN_TOKEN"
WARDNET_EGRESS_PROXY_URL_CREDENTIAL = "WARDNET_EGRESS_PROXY_URL"
WARDNET_EGRESS_PROXY_TOKEN_CREDENTIAL = "WARDNET_EGRESS_PROXY_TOKEN"
CAMOUFOX_MCP_URL_CREDENTIAL = "CAMOUFOX_MCP_URL"
CAMOUFOX_MCP_TOKEN_CREDENTIAL = "CAMOUFOX_MCP_TOKEN"


@dataclass(frozen=True)
class PrivacyPolicyAssessment:
    """One grounded structured assessment of an official policy source."""

    subject_provider: str
    subject_credential: str
    subject_model: str
    source_url: str
    zero_data_retention_available: bool | None
    supports_no_training: bool | None
    supports_no_prompt_retention: bool | None
    evidence_quote: str
    analyzer_provider: str
    analyzer_model: str
    observed_at: datetime

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-ready assessment without credentials or policy text."""
        return {
            "subject_provider": self.subject_provider,
            "subject_model": self.subject_model,
            "source_url": self.source_url,
            "zero_data_retention_available": self.zero_data_retention_available,
            "no_training": self.supports_no_training,
            "no_prompt_retention": self.supports_no_prompt_retention,
            "evidence_quote": self.evidence_quote,
            "analyzer_provider": self.analyzer_provider,
            "analyzer_model": self.analyzer_model,
            "observed_at": self.observed_at.isoformat(),
        }


class _PolicyTextExtractor(HTMLParser):
    """Extract visible document text with the standard library HTML parser."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Suppress text from non-visible element subtrees."""
        del attrs
        if tag in {"script", "style", "svg", "noscript"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        """Resume extraction after a hidden element subtree closes."""
        if tag in {"script", "style", "svg", "noscript"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        """Collect normalized visible text nodes."""
        if not self._hidden_depth and (text := " ".join(data.split())):
            self.parts.append(text)


def _mcp_text_payload(result: Any) -> dict[str, Any]:
    """Decode one JSON text result from the Camoufox MCP server."""
    if getattr(result, "is_error", False):
        raise ValueError("Camoufox MCP tool failed")
    for item in getattr(result, "content", ()):
        text = getattr(item, "text", None)
        if isinstance(text, str):
            payload = json.loads(text)
            if isinstance(payload, dict):
                return payload
    raise ValueError("Camoufox MCP tool returned no JSON text")


def _wardnet_browser_proxy() -> dict[str, str]:
    """Build Camoufox's proxy override from credential-registry values."""
    proxy_url = get_credential(WARDNET_EGRESS_PROXY_URL_CREDENTIAL)
    token = get_credential(WARDNET_EGRESS_PROXY_TOKEN_CREDENTIAL)
    if not proxy_url or not token:
        raise ValueError("Wardnet browser egress is not configured")
    proxy = urlsplit(proxy_url)
    if (
        proxy.scheme != "http"
        or not proxy.hostname
        or proxy.port is None
        or proxy.username
        or proxy.password
        or proxy.path not in {"", "/"}
        or proxy.query
        or proxy.fragment
    ):
        raise ValueError("Wardnet egress proxy URL is invalid")
    return {
        "host": proxy.hostname,
        "port": str(proxy.port),
        "username": "wardnet",
        "password": token,
    }


async def _render_policy_document_with_camoufox(url: str) -> str:
    """Render one Wardnet-approved policy URL through the configured Camoufox MCP."""
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    mcp_url = get_credential(CAMOUFOX_MCP_URL_CREDENTIAL)
    token = get_credential(CAMOUFOX_MCP_TOKEN_CREDENTIAL)
    if not mcp_url or not token:
        raise ValueError("Camoufox MCP is not configured in the credential registry")
    parsed = urlsplit(mcp_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Camoufox MCP URL is invalid")
    headers = {"authorization": f"Bearer {token}"}
    async with create_mcp_http_client(headers=headers) as http_client:
        transport = streamable_http_client(mcp_url, http_client=http_client)
        async with Client(transport) as client:
            created = _mcp_text_payload(
                await client.call_tool(
                    "create_tab",
                    {
                        "url": url,
                        "proxy": _wardnet_browser_proxy(),
                    },
                )
            )
            tab_id = created.get("tabId")
            if not isinstance(tab_id, str) or not tab_id:
                raise ValueError("Camoufox MCP omitted the tab id")
            try:
                rendered = _mcp_text_payload(
                    await client.call_tool("camofox_get_page_html", {"tabId": tab_id})
                )
            finally:
                await client.call_tool("close_tab", {"tabId": tab_id})
    html = rendered.get("html")
    if not isinstance(html, str):
        raise TypeError("Camoufox MCP omitted rendered HTML")
    return html


def crawl_policy_document(
    url: str,
    *,
    timeout: float = 15.0,
    camoufox_renderer: Callable[[str], str] | None = None,
) -> str:
    """Fetch one policy through Wardnet's DNS-pinned outbound boundary."""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("policy source must be a credential-free HTTPS URL")
    wardnet_url = get_credential(WARDNET_API_URL_CREDENTIAL)
    admin_token = get_credential(WARDNET_ADMIN_TOKEN_CREDENTIAL)
    if not wardnet_url or not admin_token:
        raise ValueError("Wardnet policy fetch is not configured in the credential registry")
    wardnet = urlsplit(wardnet_url.strip().rstrip("/"))
    if (
        wardnet.scheme not in {"http", "https"}
        or not wardnet.hostname
        or wardnet.username
        or wardnet.password
        or wardnet.query
        or wardnet.fragment
    ):
        raise ValueError("Wardnet API URL is invalid")
    payload = json.dumps({"url": url, "max_bytes": MAX_POLICY_BYTES}).encode("utf-8")
    request = urllib.request.Request(
        f"{wardnet_url.strip().rstrip('/')}/api/outbound/fetch",
        data=payload,
        headers={
            "content-type": "application/json",
            "accept": "application/json",
            "x-admin-token": admin_token,
        },
        method="POST",
    )
    client = ModelClient(timeout=max(1, int(timeout)), allowed_provider_hosts={wardnet.hostname})
    if wardnet.scheme == "http":
        origin = urlunsplit(("local", wardnet.netloc, "", "", ""))
        agent = ModelAgent(
            "wardnet_policy_fetch",
            "wardnet-policy-fetch",
            base_url=origin,
            credential_key="",
        )
    else:
        origin = urlunsplit(("https", wardnet.netloc, "", "", ""))
        agent = ModelAgent(
            "wardnet_policy_fetch",
            "wardnet-policy-fetch",
            base_url=origin,
            credential_key=WARDNET_ADMIN_TOKEN_CREDENTIAL,
        )
    destination = client._validate_provider(agent)
    with client._open_provider(request, destination, timeout=timeout) as response:
        envelope = json.loads(response.read((MAX_POLICY_BYTES * 2) + 65_536).decode("utf-8"))
    if not isinstance(envelope, dict):
        raise TypeError("Wardnet policy fetch returned an invalid envelope")
    status = envelope.get("status")
    if isinstance(status, bool) or not isinstance(status, int) or not 200 <= status < 300:
        raise ValueError("policy source did not return a successful response")
    final_url = envelope.get("final_url")
    final = urlsplit(final_url) if isinstance(final_url, str) else None
    if (
        final is None
        or final.scheme != "https"
        or not final.hostname
        or final.username
        or final.password
        or final.fragment
    ):
        raise ValueError("Wardnet policy fetch omitted a safe final URL")
    content_type = str(envelope.get("content_type", "")).split(";", 1)[0].strip().casefold()
    if content_type not in {"text/html", "text/plain", "application/xhtml+xml"}:
        raise ValueError("policy source did not return supported text")
    encoded = envelope.get("body_base64")
    if not isinstance(encoded, str):
        raise TypeError("Wardnet policy fetch omitted its bounded body")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Wardnet policy fetch returned invalid base64") from exc
    if len(raw) > MAX_POLICY_BYTES:
        raise ValueError("policy source exceeds the size limit")
    text = raw.decode("utf-8", errors="replace")
    if all(
        get_credential(name)
        for name in (
            CAMOUFOX_MCP_URL_CREDENTIAL,
            CAMOUFOX_MCP_TOKEN_CREDENTIAL,
            WARDNET_EGRESS_PROXY_URL_CREDENTIAL,
            WARDNET_EGRESS_PROXY_TOKEN_CREDENTIAL,
        )
    ):
        try:
            rendered = (
                camoufox_renderer(url)
                if camoufox_renderer is not None
                else asyncio.run(_render_policy_document_with_camoufox(url))
            )
        except (ImportError, OSError, RuntimeError, TypeError, ValueError):
            rendered = ""
        if rendered:
            text = rendered[:MAX_POLICY_BYTES]
            content_type = "text/html"
    if content_type == "text/plain":
        return " ".join(text.split())[:MAX_POLICY_CHARACTERS]
    parser = _PolicyTextExtractor()
    parser.feed(text)
    return "\n".join(parser.parts)[:MAX_POLICY_CHARACTERS]


_POLICY_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "privacy_policy_assessment",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "assessments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "source_url": {"type": "string"},
                            "zero_data_retention_available": {"type": ["boolean", "null"]},
                            "no_training": {"type": ["boolean", "null"]},
                            "no_prompt_retention": {"type": ["boolean", "null"]},
                            "evidence_quote": {"type": "string"},
                        },
                        "required": [
                            "source_url",
                            "zero_data_retention_available",
                            "no_training",
                            "no_prompt_retention",
                            "evidence_quote",
                        ],
                    },
                }
            },
            "required": ["assessments"],
        },
    },
}


def _call_analyzer(
    candidate: DiscoveredModel,
    documents: dict[str, str],
    client: ModelClient,
) -> Any:
    """Ask one ZDR-capable route for a strict, quote-grounded assessment."""
    agent = agent_from_discovered(candidate)
    prompt = {
        "task": (
            "Analyze only the supplied provider policy documents. Distinguish optional ZDR "
            "availability from ZDR actually enabled for an account. Use null when the document "
            "does not establish a field. evidence_quote must be a verbatim substring of the "
            "corresponding document. Never infer a policy from provider or model names."
        ),
        "documents": [
            {"source_url": source_url, "text": text}
            for source_url, text in documents.items()
        ],
    }
    response = client.proxy_send_once(
        agent,
        "chat/completions",
        {
            "model": agent.model,
            "messages": [{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
            "temperature": 0,
            "max_tokens": 1600,
            "response_format": _POLICY_SCHEMA,
            "stream": False,
        },
    )
    return json.loads(ModelClient._response_content(agent, response))


def analyze_discovered_privacy_policies(
    models: Sequence[DiscoveredModel],
    *,
    crawler: Callable[[str], str] = crawl_policy_document,
    analyzer: Callable[[DiscoveredModel, dict[str, str]], Any] | None = None,
) -> tuple[list[DiscoveredModel], list[PrivacyPolicyAssessment]]:
    """Enrich policy fields using a discovered ZDR route and grounded source quotes."""
    candidates = sorted(
        (
            model
            for model in models
            if model.supports_zero_data_retention is True and "chat" in model.capabilities
        ),
        key=lambda model: (not model.is_free, model.provider_name, model.model_id),
    )[:MAX_ANALYZER_CANDIDATES]
    source_urls = sorted({url for model in models for url in model.privacy_policy_urls})[
        :MAX_POLICY_SOURCES
    ]
    if not candidates or not source_urls:
        return list(models), []

    documents: dict[str, str] = {}
    for url in source_urls:
        try:
            text = crawler(url)
        except (OSError, TimeoutError, TypeError, ValueError):
            continue
        if text:
            documents[url] = text
    if not documents:
        return list(models), []

    client = ModelClient(max_retries=0)
    analyzer_model: DiscoveredModel | None = None
    grounded_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            payload = (
                analyzer(candidate, documents)
                if analyzer is not None
                else _call_analyzer(candidate, documents, client)
            )
        except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
            continue
        rows = payload.get("assessments") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            continue
        grounded_rows = [
            row
            for row in rows
            if isinstance(row, dict)
            and isinstance(row.get("source_url"), str)
            and row["source_url"] in documents
            and isinstance(row.get("evidence_quote"), str)
            and bool(row["evidence_quote"])
            and row["evidence_quote"] in documents[row["source_url"]]
            and all(
                value is None or isinstance(value, bool)
                for value in (
                    row.get("zero_data_retention_available"),
                    row.get("no_training"),
                    row.get("no_prompt_retention"),
                )
            )
        ]
        if grounded_rows:
            analyzer_model = candidate
            break
    if analyzer_model is None:
        return list(models), []

    source_assessments: list[PrivacyPolicyAssessment] = []
    observed_at = datetime.now(timezone.utc)
    for row in grounded_rows:
        source_url = row.get("source_url")
        evidence_quote = row.get("evidence_quote")
        values = [
            row.get("zero_data_retention_available"),
            row.get("no_training"),
            row.get("no_prompt_retention"),
        ]
        source_assessments.append(
            PrivacyPolicyAssessment(
                subject_provider="",
                subject_credential="",
                subject_model="",
                source_url=source_url,
                zero_data_retention_available=values[0],
                supports_no_training=values[1],
                supports_no_prompt_retention=values[2],
                evidence_quote=evidence_quote,
                analyzer_provider=analyzer_model.provider_name,
                analyzer_model=analyzer_model.model_id,
                observed_at=observed_at,
            )
        )

    by_url: dict[str, PrivacyPolicyAssessment] = {}
    ambiguous_urls: set[str] = set()
    for assessment in source_assessments:
        if assessment.source_url in by_url:
            ambiguous_urls.add(assessment.source_url)
            by_url.pop(assessment.source_url)
        elif assessment.source_url not in ambiguous_urls:
            by_url[assessment.source_url] = assessment

    def inferred_consensus(
        values: list[bool | None],
        *,
        expected_sources: int,
        provider_value: bool | None,
    ) -> bool | None:
        """Preserve provider truth; infer only from complete, unanimous policy evidence."""
        if provider_value is not None:
            return provider_value
        if len(values) != expected_sources or any(value is None for value in values):
            return None
        known = set(values)
        return known.pop() if len(known) == 1 else None

    enriched: list[DiscoveredModel] = []
    for model in models:
        evidence = [by_url[url] for url in model.privacy_policy_urls if url in by_url]
        no_training = [item.supports_no_training for item in evidence]
        no_retention = [item.supports_no_prompt_retention for item in evidence]
        enriched.append(
            replace(
                model,
                supports_no_training=inferred_consensus(
                    no_training,
                    expected_sources=len(model.privacy_policy_urls),
                    provider_value=model.supports_no_training,
                ),
                supports_no_prompt_retention=inferred_consensus(
                    no_retention,
                    expected_sources=len(model.privacy_policy_urls),
                    provider_value=model.supports_no_prompt_retention,
                ),
            )
        )
    assessments = [
        replace(
            by_url[url],
            subject_provider=model.provider_name,
            subject_credential=model.credential_name,
            subject_model=model.model_id,
        )
        for model in models
        for url in model.privacy_policy_urls
        if url in by_url
    ]
    return enriched, assessments
