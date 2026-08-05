"""DNS-pinned HTTPS transport for validated model-provider egress.

The legacy orchestration module validates provider DNS answers before sending a
request. A normal URL opener resolves the hostname again during connection,
which leaves a time-of-check/time-of-use gap if DNS changes between validation
and socket creation. This module installs a narrow transport extension on
``ModelClient``: the second validation answer is retained, the socket connects
only to one of those approved addresses, TLS still verifies the original
hostname, environment proxies are bypassed, and redirects are rejected.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from typing import Any, Iterator
import urllib.error
import urllib.request
from urllib.parse import urlparse


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to one validated IP while retaining the provider hostname for TLS."""

    def __init__(
        self,
        server_hostname: str,
        pinned_ip: str,
        port: int,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        """Configure a direct TLS connection to a previously validated address."""
        super().__init__(server_hostname, port=port, timeout=timeout, context=context)
        self._pinned_ip = pinned_ip
        self._server_hostname = server_hostname

    def connect(self) -> None:
        """Dial the pinned IP and verify the certificate against the original host."""
        raw_socket = socket.create_connection(
            (self._pinned_ip, self.port),
            self.timeout,
            self.source_address,
        )
        try:
            self.sock = self._context.wrap_socket(
                raw_socket,
                server_hostname=self._server_hostname,
            )
        except Exception:  # noqa: BLE001 - close the raw socket, then preserve the TLS failure.
            raw_socket.close()
            raise


class _ProviderHTTPResponse:
    """Provider response wrapper that deterministically closes its connection."""

    def __init__(self, response: Any, connection: Any) -> None:
        """Retain the response and direct connection for context-managed cleanup."""
        self._response = response
        self._connection = connection

    def __enter__(self) -> "_ProviderHTTPResponse":
        """Return this response wrapper from a context manager."""
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        """Close the response and its connection when leaving the context."""
        self.close()

    def __iter__(self) -> Iterator[bytes]:
        """Iterate raw response lines for server-sent-event streaming."""
        return iter(self._response)

    def __getattr__(self, name: str) -> Any:
        """Delegate response metadata such as status and headers."""
        return getattr(self._response, name)

    def read(self, *args: Any, **kwargs: Any) -> bytes:
        """Read bytes from the underlying provider response."""
        return self._response.read(*args, **kwargs)

    def close(self) -> None:
        """Close both resources even when response cleanup raises."""
        try:
            self._response.close()
        finally:
            self._connection.close()


def _validated_public_addresses(hostname: str, port: int, provider_label: str) -> tuple[str, ...]:
    """Resolve, validate, and deduplicate addresses approved for one connection."""
    validated_addresses: list[str] = []
    for address in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM):
        resolved_address = ipaddress.ip_address(address[4][0])
        if (
            not resolved_address.is_global
            or resolved_address.is_private
            or resolved_address.is_loopback
            or resolved_address.is_link_local
            or resolved_address.is_multicast
            or resolved_address.is_reserved
        ):
            raise RuntimeError(f"{provider_label} provider resolves to non-public address")
        normalized_address = str(resolved_address)
        if normalized_address not in validated_addresses:
            validated_addresses.append(normalized_address)
    if not validated_addresses:
        raise RuntimeError(f"{provider_label} provider host did not resolve")
    return tuple(validated_addresses)


def install_provider_transport(model_client_type: type[Any]) -> None:
    """Install DNS-pinned HTTPS validation and connection methods exactly once."""
    if getattr(model_client_type, "_dns_pinned_transport_installed", False):
        return

    original_validate_provider = model_client_type._validate_provider

    def validate_provider(self: Any, agent: Any) -> None:
        """Validate provider policy, then retain the exact public DNS answer used."""
        parsed = urlparse(agent.base_url)
        hostname = parsed.hostname.lower() if parsed.hostname else ""
        port = parsed.port or 443
        pin_key = (hostname, port)
        pins = getattr(self._local, "provider_address_pins", {})
        pins.pop(pin_key, None)
        self._local.provider_address_pins = pins

        original_validate_provider(self, agent)
        addresses = _validated_public_addresses(hostname, port, agent.id)
        pins[pin_key] = addresses

    def open_provider(self: Any, request: urllib.request.Request) -> Any:
        """Open a request on a validation-time address without following redirects.

        Public provider methods require HTTPS and invoke ``validate_provider``
        before this transport. Plain HTTP remains delegated to urllib only for
        the repository's private loopback integration helpers; the public policy
        boundary rejects HTTP before provider egress.
        """
        parsed = urlparse(request.full_url)
        if parsed.scheme == "http":
            return urllib.request.urlopen(  # nosec B310 - public validation rejects HTTP; private loopback test seam only. nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
                request,
                timeout=self.timeout,
            )
        if parsed.scheme != "https" or not parsed.hostname:
            raise RuntimeError("provider request URL must use http(s)")

        port = parsed.port or 443
        pin_key = (parsed.hostname.lower(), port)
        pins = getattr(self._local, "provider_address_pins", {})
        addresses = pins.get(pin_key)
        if not addresses:
            raise RuntimeError("provider request has no validated address pin")

        target = parsed.path or "/"
        if parsed.params:
            target = f"{target};{parsed.params}"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        headers = dict(request.header_items())
        headers["Connection"] = "close"

        last_error: BaseException | None = None
        connection_type = getattr(self, "_https_connection_class", _PinnedHTTPSConnection)
        for pinned_ip in addresses:
            connection = connection_type(
                parsed.hostname,
                pinned_ip,
                port,
                self.timeout,
                self._ssl_context,
            )
            try:
                connection.request(
                    request.get_method(),
                    target,
                    body=request.data,
                    headers=headers,
                )
                response = connection.getresponse()
            except (OSError, http.client.HTTPException) as exc:
                connection.close()
                last_error = exc
                continue
            if response.status >= 300:
                status = response.status
                reason = response.reason
                response_headers = response.headers
                response.close()
                connection.close()
                raise urllib.error.HTTPError(
                    request.full_url,
                    status,
                    reason,
                    response_headers,
                    None,
                )
            return _ProviderHTTPResponse(response, connection)
        raise urllib.error.URLError(last_error or "provider connection failed")

    model_client_type._validate_provider = validate_provider
    model_client_type._open_provider = open_provider
    model_client_type._dns_pinned_transport_installed = True
