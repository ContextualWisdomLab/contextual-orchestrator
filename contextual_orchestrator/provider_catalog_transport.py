"""Hardened credentialed HTTPS transport for provider catalog and native calls.

The transport resolves a provider hostname once, rejects every non-global
address, dials only the approved IP set, and keeps the original hostname for TLS
SNI and certificate verification. It never consults ambient proxy settings or
follows redirects. Responses are size-bounded and parsed through the
repository's strict provider JSON-object boundary.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import http.client
import ipaddress
import json
import socket
import ssl
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from .provider_catalog import CatalogHttpError
from .provider_transport import _parse_provider_json_object_text


CATALOG_RESPONSE_MAX_BYTES = 8 * 1024 * 1024
"""Maximum bytes consumed from one provider catalog or native response."""

MAX_RETRY_AFTER_SECONDS = 30.0
"""Maximum delay authority granted to an untrusted Retry-After header."""

TRANSIENT_HTTP_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
"""HTTP statuses eligible for the caller's bounded retry policy."""


class _PinnedCatalogConnection(http.client.HTTPSConnection):  # pragma: no cover - real network adapter
    """Dial one validated IP while retaining the provider hostname for TLS."""

    def __init__(
        self,
        hostname: str,
        pinned_ip: str,
        port: int,
        timeout_seconds: float,
    ) -> None:
        super().__init__(
            hostname,
            port=port,
            timeout=timeout_seconds,
            context=ssl.create_default_context(),
        )
        self._pinned_ip = pinned_ip
        self._provider_hostname = hostname

    def connect(self) -> None:
        """Open a TLS socket to the approved IP with original-host verification."""
        raw_socket = socket.create_connection(
            (self._pinned_ip, self.port),
            self.timeout,
            self.source_address,
        )
        try:
            self.sock = self._context.wrap_socket(
                raw_socket,
                server_hostname=self._provider_hostname,
            )
        except Exception:
            raw_socket.close()
            raise


def parse_retry_after(
    value: str | None,
    *,
    now: datetime | None = None,
) -> float | None:
    """Parse RFC 9110 delta-seconds or HTTP-date and cap delay authority."""
    if value is None:
        return None
    token = value.strip()
    if not token:
        return None
    if token.isascii() and token.isdigit():
        return min(MAX_RETRY_AFTER_SECONDS, float(token))
    try:
        parsed = parsedate_to_datetime(token)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    seconds = max(0.0, (parsed - reference).total_seconds())
    return min(MAX_RETRY_AFTER_SECONDS, seconds)


def secure_json_request(  # pragma: no cover - real credentialed network boundary
    *,
    method: str,
    url: str,
    header_name: str,
    authorization: str,
    payload: Mapping[str, Any] | None,
    timeout_seconds: float,
    transient_status: Sequence[int] = tuple(TRANSIENT_HTTP_STATUS),
) -> dict[str, Any]:
    """Issue one direct DNS-pinned HTTPS request and return a strict JSON object.

    Every failure is translated to a stable code. Provider response bodies,
    credentials, URLs with user information, and low-level socket detail never
    appear in the public error string.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise CatalogHttpError("catalog_url_must_use_https")
    if parsed.username is not None or parsed.password is not None:
        raise CatalogHttpError("catalog_url_must_not_contain_userinfo")
    if parsed.fragment:
        raise CatalogHttpError("catalog_url_must_not_contain_fragment")
    if timeout_seconds <= 0:
        raise CatalogHttpError("catalog_timeout_invalid")
    if not _valid_header_name(header_name):
        raise CatalogHttpError("catalog_auth_header_invalid")
    if not authorization or "\r" in authorization or "\n" in authorization:
        raise CatalogHttpError("catalog_authorization_invalid")

    port = parsed.port or 443
    addresses = _validated_global_addresses(parsed.hostname, port)
    target = parsed.path or "/"
    if parsed.params:
        target = f"{target};{parsed.params}"
    if parsed.query:
        target = f"{target}?{parsed.query}"

    try:
        request_body = None if payload is None else json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise CatalogHttpError("catalog_request_json_invalid") from None

    headers = {
        header_name: authorization,
        "Accept": "application/json",
        "Connection": "close",
        "User-Agent": "contextual-orchestrator-provider-catalog/1",
    }
    if request_body is not None:
        headers["Content-Type"] = "application/json"

    last_network_error: BaseException | None = None
    for address in addresses:
        connection = _PinnedCatalogConnection(
            parsed.hostname,
            address,
            port,
            timeout_seconds,
        )
        response: http.client.HTTPResponse | None = None
        try:
            connection.request(method, target, body=request_body, headers=headers)
            response = connection.getresponse()
            if response.status >= 300:
                retry_after = parse_retry_after(response.getheader("Retry-After"))
                if response.status in {401, 403}:
                    raise CatalogHttpError("catalog_authentication_failed")
                raise CatalogHttpError(
                    f"catalog_http_{response.status}",
                    transient=response.status in transient_status,
                    retry_after_seconds=retry_after,
                )
            content_type = (response.getheader("Content-Type") or "").partition(";")[0].strip().lower()
            if content_type not in {"application/json", "application/problem+json"} and not content_type.endswith("+json"):
                raise CatalogHttpError("catalog_content_type_invalid")
            content_length = response.getheader("Content-Length")
            if content_length is not None and _declared_length_exceeds_limit(
                content_length,
                CATALOG_RESPONSE_MAX_BYTES,
            ):
                raise CatalogHttpError("catalog_response_too_large")
            raw_payload = response.read(CATALOG_RESPONSE_MAX_BYTES + 1)
            if len(raw_payload) > CATALOG_RESPONSE_MAX_BYTES:
                raise CatalogHttpError("catalog_response_too_large")
            try:
                text = raw_payload.decode("utf-8")
            except UnicodeDecodeError:
                raise CatalogHttpError("catalog_json_invalid") from None
            try:
                return _parse_provider_json_object_text(text)
            except RuntimeError:
                raise CatalogHttpError("catalog_json_invalid") from None
        except CatalogHttpError:
            raise
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            last_network_error = exc
        finally:
            if response is not None:
                with suppress(Exception):
                    response.close()
            with suppress(Exception):
                connection.close()
    raise CatalogHttpError("catalog_network_failure", transient=True) from last_network_error


def _validated_global_addresses(hostname: str, port: int) -> tuple[str, ...]:  # pragma: no cover - DNS boundary
    """Resolve, validate, and deduplicate globally routable provider addresses."""
    try:
        candidates = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise CatalogHttpError("catalog_dns_failure", transient=True) from None
    addresses: list[str] = []
    for candidate in candidates:
        address = ipaddress.ip_address(candidate[4][0])
        if (
            not address.is_global
            or address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
        ):
            raise CatalogHttpError("catalog_destination_not_public")
        text = str(address)
        if text not in addresses:
            addresses.append(text)
    if not addresses:
        raise CatalogHttpError("catalog_dns_empty", transient=True)
    return tuple(addresses)


def _valid_header_name(value: str) -> bool:
    """Return whether a configured HTTP header name is a safe RFC token subset."""
    if not value or not value.isascii():
        return False
    allowed = "!#$%&'*+-.^_`|~"
    return all(character.isalnum() or character in allowed for character in value)


def _declared_length_exceeds_limit(value: str, limit: int) -> bool:
    """Validate one Content-Length field and compare without integer overflow."""
    members: list[str] = []
    for member in value.split(","):
        token = member.strip(" \t")
        if not token or not token.isascii() or not token.isdigit():
            raise CatalogHttpError("catalog_content_length_invalid")
        members.append(token.lstrip("0") or "0")
    declared = members[0]
    if any(member != declared for member in members[1:]):
        raise CatalogHttpError("catalog_content_length_conflict")
    limit_text = str(limit)
    if len(declared) != len(limit_text):
        return len(declared) > len(limit_text)
    return declared > limit_text
