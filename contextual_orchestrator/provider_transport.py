"""DNS-pinned HTTPS primitives for validated model-provider egress.

``ModelClient`` owns policy validation and request dispatch directly. This
module contains only focused connection, response-cleanup, bounded-consumption,
strict provider-response decoding, and public-address validation helpers, so
importing the package never mutates another class.
"""

from __future__ import annotations

from contextlib import suppress
import http.client
import ipaddress
import json
import math
import socket
import ssl
from typing import Any, Iterator

from .credentials import NotConfigured


PROVIDER_RESPONSE_MAX_BYTES = 8 * 1024 * 1024
"""Maximum bytes consumed from one untrusted provider HTTP response."""


def _reject_non_finite_json_constant(_value: str) -> None:
    """Reject Python JSON extensions that RFC 8259 does not permit."""
    raise ValueError("non-finite JSON number")


def _parse_finite_json_float(value: str) -> float:
    """Decode one JSON float while rejecting overflow into a non-finite value."""
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite JSON number")
    return parsed


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build one JSON object while rejecting ambiguous duplicate member names."""
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate JSON member name")
        result[name] = value
    return result


def _parse_provider_json_object_text(text: str) -> dict[str, Any]:
    """Parse strict RFC 8259 JSON text and require one top-level object.

    Python's default decoder intentionally accepts ``NaN`` and infinities and
    silently keeps the final value of duplicate object members. Provider
    responses cross a trust boundary, so those extensions and finite-syntax
    numbers that overflow Python's runtime float representation are rejected
    before orchestration code can interpret ambiguous data. Decoder exceptions
    are replaced without chaining because ``JSONDecodeError`` retains the entire
    untrusted document in its ``doc`` attribute.
    """
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_non_finite_json_constant,
            parse_float=_parse_finite_json_float,
        )
    except (ValueError, RecursionError):
        raise RuntimeError("provider JSON response is malformed") from None
    if not isinstance(value, dict):
        raise RuntimeError("provider JSON response must be an object")
    return value


def _decode_provider_json_object(payload: bytes) -> dict[str, Any]:
    """Decode one strict UTF-8 provider JSON object with redacted failures."""
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise RuntimeError("provider JSON response is malformed") from None
    return _parse_provider_json_object_text(text)


def _encode_provider_json_object(payload: bytes) -> bytes:
    """Return canonical UTF-8 bytes after strict provider-object validation."""
    value = _decode_provider_json_object(payload)
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise RuntimeError("provider JSON response is malformed") from None


def _encode_provider_json_lines(payload: bytes) -> bytes:
    """Validate and canonicalize an OpenAI Batch API JSON Lines response.

    Every non-empty line must independently be a strict UTF-8 JSON object. The
    returned bytes remain line-addressable for the existing batch parser, but a
    malformed provider document is rejected here before a later ``json.loads``
    exception can retain private response content.
    """
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise RuntimeError("provider JSON Lines response is malformed") from None
    normalized_lines: list[str] = []
    try:
        for line in text.splitlines():
            if not line.strip():
                continue
            value = json.loads(
                line,
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_non_finite_json_constant,
                parse_float=_parse_finite_json_float,
            )
            if not isinstance(value, dict):
                raise ValueError("JSON Lines row must be an object")
            normalized_lines.append(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                )
            )
    except (TypeError, ValueError, RecursionError):
        raise RuntimeError("provider JSON Lines response is malformed") from None
    if not normalized_lines:
        raise RuntimeError("provider JSON Lines response is malformed")
    return "\n".join(normalized_lines).encode("utf-8")


def _is_batch_output_content_path(request_path: str) -> bool:
    """Return whether a validated target is a provider file-content endpoint."""
    path = request_path.partition("?")[0]
    segments = [segment for segment in path.split("/") if segment]
    return (
        len(segments) >= 3
        and segments[-3] == "files"
        and segments[-1] == "content"
    )


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

    def request(
        self,
        method: str,
        url: str,
        body: Any = None,
        headers: dict[str, str] | None = None,
        *,
        encode_chunked: bool = False,
    ) -> None:
        """Require a current non-empty Bearer credential before any socket can open.

        Provider credentials are resolved immediately before request construction.
        A credential can still be revoked between DNS validation and dispatch, in
        which case ``ModelClient`` produces an empty Bearer value. This last
        pre-socket boundary therefore rejects missing or empty authorization so a
        revoked secret can never degrade into unauthenticated provider egress.

        The exact request target is also retained on this connection. The paired
        response wrapper uses that already-validated target to distinguish normal
        JSON objects from the Batch API's JSON Lines file-content response without
        asking orchestration call sites to duplicate transport trust policy.
        """
        request_headers = headers or {}
        authorization = next(
            (
                str(value)
                for name, value in request_headers.items()
                if name.lower() == "authorization"
            ),
            "",
        )
        scheme, separator, credential = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator or not credential.strip():
            self.close()
            raise NotConfigured(
                "provider HTTPS egress requires a current non-empty Bearer credential"
            )
        self._provider_request_path = url
        super().request(
            method,
            url,
            body=body,
            headers=request_headers,
            encode_chunked=encode_chunked,
        )

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


def _content_length_exceeds_budget(value: str, max_bytes: int) -> bool:
    """Validate one Content-Length field and compare without integer overflow."""
    canonical_members: list[str] = []
    for member in value.split(","):
        token = member.strip(" \t")
        if not token or not token.isascii() or not token.isdigit():
            raise ValueError("invalid Content-Length")
        canonical_members.append(token.lstrip("0") or "0")
    declared = canonical_members[0]
    if any(member != declared for member in canonical_members[1:]):
        raise ValueError("conflicting Content-Length")
    limit = str(max_bytes)
    if len(declared) > len(limit):
        return True
    if len(declared) < len(limit):
        return False
    return declared > limit


class _ProviderHTTPResponse:
    """Bound provider bytes and deterministically close response resources."""

    def __init__(
        self,
        response: Any,
        connection: Any,
        max_bytes: int = PROVIDER_RESPONSE_MAX_BYTES,
    ) -> None:
        """Retain resources and initialize one cumulative response-byte budget."""
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError("provider response byte limit must be a positive integer")
        self._response = response
        self._connection = connection
        self._max_bytes = max_bytes
        self._bytes_read = 0
        try:
            self._validate_response_framing()
        except Exception:
            with suppress(Exception):
                self.close()
            raise

    def _validate_response_framing(self) -> None:
        """Reject malformed, ambiguous, or already over-budget HTTP framing."""
        if not isinstance(self._response, http.client.HTTPResponse):
            return
        try:
            content_length = self._response.getheader("Content-Length")
            transfer_encoding = self._response.getheader("Transfer-Encoding")
        except Exception:
            raise RuntimeError(
                "provider response headers could not be validated"
            ) from None
        if content_length is not None and transfer_encoding is not None:
            raise RuntimeError("provider response framing is ambiguous")
        if transfer_encoding is not None:
            if transfer_encoding.lower() != "chunked":
                raise RuntimeError("provider response transfer encoding is unsupported")
            return
        if content_length is None:
            return
        try:
            exceeds_budget = _content_length_exceeds_budget(
                content_length,
                self._max_bytes,
            )
        except ValueError:
            raise RuntimeError(
                "provider response content length is invalid"
            ) from None
        if exceeds_budget:
            raise RuntimeError("provider response byte limit exceeded")

    def __enter__(self) -> "_ProviderHTTPResponse":
        """Return this response wrapper from a context manager."""
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        """Close the response and its connection when leaving the context."""
        self.close()

    def __iter__(self) -> Iterator[bytes]:
        """Yield only bounded, valid server-sent-event response lines.

        Real ``HTTPResponse`` iteration is reserved for provider streaming. It
        therefore requires the standardized ``text/event-stream`` media type
        before consuming any body bytes, then uses size-limited ``readline``
        calls so one pathological line cannot allocate beyond the remaining
        budget before inspection. Every ``data:`` frame must contain a strict
        JSON object until the OpenAI-compatible terminal ``[DONE]`` marker
        arrives. A missing or incorrect media type, malformed data, or end-of-file
        before that marker fails closed instead of turning a non-stream or partial
        model answer into successful orchestration output. Lightweight non-HTTP
        test doubles retain ordinary iteration while still receiving cumulative
        byte accounting.
        """
        if isinstance(self._response, http.client.HTTPResponse):
            try:
                content_type = self._response.getheader("Content-Type", "")
            except Exception:
                raise RuntimeError(
                    "provider stream content type could not be validated"
                ) from None
            media_type = content_type.partition(";")[0].strip().lower()
            if media_type != "text/event-stream":
                raise RuntimeError(
                    "provider stream requires text/event-stream content type"
                )
            while True:
                line = self._response.readline(self._remaining_bytes() + 1)
                if not line:
                    raise RuntimeError("provider stream terminated before [DONE]")
                bounded_line = self._account(line)
                try:
                    text = bounded_line.decode("utf-8").strip()
                except UnicodeDecodeError:
                    raise RuntimeError("malformed provider stream event") from None
                if text.startswith("data:"):
                    data = text[len("data:") :].strip()
                    if data == "[DONE]":
                        return
                    try:
                        _parse_provider_json_object_text(data)
                    except RuntimeError:
                        raise RuntimeError(
                            "malformed provider stream event"
                        ) from None
                yield bounded_line
        else:
            for line in self._response:
                yield self._account(line)

    def __getattr__(self, name: str) -> Any:
        """Delegate response metadata such as status and headers."""
        return getattr(self._response, name)

    def _remaining_bytes(self) -> int:
        """Return bytes still available before the response must fail closed."""
        return self._max_bytes - self._bytes_read

    def _account(self, chunk: bytes) -> bytes:
        """Charge one consumed chunk to the cumulative response-byte budget."""
        next_total = self._bytes_read + len(chunk)
        if next_total > self._max_bytes:
            raise RuntimeError("provider response byte limit exceeded")
        self._bytes_read = next_total
        return chunk

    def _read_bounded_bytes(self, amt: int | None = None) -> bytes:
        """Consume no more than the remaining response-byte budget."""
        remaining = self._remaining_bytes()
        if amt is None or amt < 0 or amt > remaining:
            requested = remaining + 1
        else:
            requested = amt
        return self._account(self._response.read(requested))

    def read_json_object(self) -> dict[str, Any]:
        """Read one bounded provider body as a strict UTF-8 JSON object.

        This explicit method is useful to focused transport callers and tests.
        Normal validated HTTPS model-client reads receive the same protection
        automatically through ``read`` using the request path captured by
        ``_PinnedHTTPSConnection``.
        """
        return _decode_provider_json_object(self._read_bounded_bytes())

    def read(self, amt: int | None = None) -> bytes:
        """Read bounded bytes and validate complete validated-provider documents.

        Explicit partial reads remain byte-oriented. A complete response from a
        DNS-pinned HTTPS request is normalized only after strict validation: Batch
        file-content endpoints are JSON Lines, while all other non-stream provider
        endpoints used by ``ModelClient`` return one JSON object. Connections that
        do not carry a validated request target (lightweight tests and the explicit
        loopback integration seam) preserve the historical bounded-byte behavior.
        """
        payload = self._read_bounded_bytes(amt)
        request_path = getattr(self._connection, "_provider_request_path", None)
        if not isinstance(request_path, str) or not request_path:
            return payload
        if amt is not None and amt >= 0:
            return payload
        if _is_batch_output_content_path(request_path):
            return _encode_provider_json_lines(payload)
        return _encode_provider_json_object(payload)

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
