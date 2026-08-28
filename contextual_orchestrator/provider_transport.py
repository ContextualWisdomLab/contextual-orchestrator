"""DNS-pinned HTTPS primitives for validated model-provider egress.

``ModelClient`` owns policy validation and request dispatch directly. This
module contains only focused connection, response-cleanup, and public-address
validation helpers, so importing the package never mutates another class.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl


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
