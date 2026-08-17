"""Shared provider destination policy for chat and catalog discovery.

Chat (``ModelClient._validate_provider``) and default catalog discovery
must refuse the same destinations before a Bearer credential is attached.
This module is the extracted second implementation of that check (Ponytail:
extract when a second real caller exists). It does **not** open sockets:
production GET uses ``ModelClient.fetch_provider_json`` so there is no
second urllib client. See ``docs/doctoring/priced-selection.md``.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler

_NON_PUBLIC_FLAGS = (
    "is_private",
    "is_loopback",
    "is_link_local",
    "is_multicast",
    "is_reserved",
)
_LOOPBACK_HOSTNAMES = frozenset({"localhost", "localhost.localdomain"})


class RefuseRedirectHandler(HTTPRedirectHandler):
    """Fail closed on any 3xx so Bearer tokens are never replayed to a new host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, N802
        """Refuse the redirect instead of issuing a follow-up request."""
        del req, fp, code, msg, headers, newurl
        raise RuntimeError("provider redirect refused")


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
    Injected test fetchers pass ``resolve_dns=False`` so compose stays offline
    while ``https://127.0.0.1`` and metadata IPs still fail closed. DNS
    pinning lives in ``ModelClient._validate_provider``. Does not attach or
    transmit credentials. Does not read the environment; callers pass the
    chat allowlist.
    """
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.hostname:
        return "base_url must use https"
    hostname = parsed.hostname.lower()
    if hostname in _LOOPBACK_HOSTNAMES:
        return "provider resolves to non-public address"
    hosts = allowed_hosts or set()
    if hosts and hostname not in hosts:
        return "provider host is not allowlisted"
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        return _non_public_reason(literal)
    # DNS / public-IP pinning stays in ModelClient._validate_provider so this
    # module is not a second socket client. resolve_dns is kept for callers.
    del resolve_dns
    return None
