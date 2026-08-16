"""Shared provider egress policy for chat and catalog discovery.

Chat (``ModelClient._validate_provider``) and default catalog discovery
must refuse the same destinations before a Bearer credential is attached.
A second urllib client that only checks ``https`` + hostname is not enough:
stdlib ``urlopen`` follows redirects and re-sends ``Authorization``.

This module is the extracted second implementation of that check (Ponytail:
extract when a second real caller exists). See
``docs/doctoring/priced-selection.md``.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
from typing import Any
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

_NON_PUBLIC_FLAGS = (
    "is_private",
    "is_loopback",
    "is_link_local",
    "is_multicast",
    "is_reserved",
)


class RefuseRedirectHandler(HTTPRedirectHandler):
    """Fail closed on any 3xx so Bearer tokens are never replayed to a new host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, N802
        """Refuse the redirect instead of issuing a follow-up request."""
        del req, fp, code, msg, headers, newurl
        raise RuntimeError("provider redirect refused")


def allowed_provider_hosts() -> set[str]:
    """Return the operator host allowlist used by chat validation.

    This is the pre-existing ``CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS``
    bootstrap transport already read by ``ModelClient``. Discovery must honor
    the same list so catalog compose cannot bypass the chat allowlist.
    """
    raw = os.environ.get("CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS", "")
    return {host.strip().lower() for host in raw.split(",") if host.strip()}


def _non_public_reason(ip_address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    """Return a rejection reason when ``ip_address`` is not globally routable."""
    if any(getattr(ip_address, flag) for flag in _NON_PUBLIC_FLAGS):
        return "provider resolves to non-public address"
    return None


def provider_base_url_rejection(
    base_url: str,
    *,
    allowed_hosts: set[str] | None = None,
    resolve_dns: bool = True,
) -> str | None:
    """Return a rejection reason, or ``None`` when the URL may be fetched.

    Requires HTTPS, a hostname, optional allowlist membership, and
    validation-time globally routable addresses (no private, loopback,
    link-local, multicast, or reserved). Literal IPs are always checked.
    Hostname DNS is checked when ``resolve_dns`` is true (production fetch).
    Injected test fetchers pass ``resolve_dns=False`` so compose stays offline
    while ``https://127.0.0.1`` and metadata IPs still fail closed. DNS
    failure is a rejection, not a fetch. Does not attach or transmit credentials.
    """
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.hostname:
        return "base_url must use https"
    hostname = parsed.hostname.lower()
    hosts = allowed_hosts if allowed_hosts is not None else allowed_provider_hosts()
    if hosts and hostname not in hosts:
        return "provider host is not allowlisted"
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        return _non_public_reason(literal)
    if not resolve_dns:
        return None
    try:
        resolved = socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError:
        return "provider host could not be resolved"
    for address in resolved:
        ip_address = ipaddress.ip_address(address[4][0])
        reason = _non_public_reason(ip_address)
        if reason:
            return reason
    return None


def no_redirect_models_fetch(url: str, headers: dict[str, str], timeout: float) -> Any:
    """GET ``url`` without following redirects; JSON-decode a bounded body.

    Callers must run ``provider_base_url_rejection`` on the origin first.
    A 3xx response raises ``RuntimeError`` so the KV Bearer is not replayed.
    """
    request = Request(url, headers=headers, method="GET")
    opener = build_opener(RefuseRedirectHandler)
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read(1_048_576).decode("utf-8"))
