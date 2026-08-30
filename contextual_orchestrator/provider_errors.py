"""Provider failure taxonomy: typed, caller-actionable model errors.

Every upstream provider/model failure is classified into one OpenAI-compatible
error surface so callers learn *which* model failed, *why*, and *whether to
retry* — instead of receiving one opaque ``internal_error`` for every cause.

The classification derives from the upstream HTTP status (RFC 9110 semantics)
and the OpenAI error-code conventions used across compatible providers.
Provider response bodies are never surfaced raw: only a bounded, control-free
message field is kept, because provider diagnostics can embed secrets,
prompts, or internal topology (CWE-209).

References
----------
- Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP semantics*
  (RFC 9110). IETF. https://doi.org/10.17487/RFC9110
- OpenAI. (2026). *Error codes*. https://platform.openai.com/docs/guides/error-codes
"""

from __future__ import annotations

import json as _json
import re as _re
import socket
import ssl
import urllib.error
from typing import Any

__all__ = [
    "MAX_PROVIDER_ERROR_BODY_BYTES",
    "MAX_SAFE_MESSAGE_CHARS",
    "PROVIDER_STATUS_SURFACES",
    "ProviderUpstreamError",
    "classify_provider_failure",
    "provider_error_body",
    "safe_provider_message",
]

#: Upper bound for any provider-supplied message that reaches a caller.
MAX_SAFE_MESSAGE_CHARS = 300

#: Maximum provider response bytes inspected for one caller-safe diagnostic.
MAX_PROVIDER_ERROR_BODY_BYTES = 65_536

#: Provider-controlled text containing any likely secret, request content, URL,
#: or network address is discarded wholesale. Partial masking is unsafe because
#: adjacent diagnostic text can still identify credentials or private topology.
_SENSITIVE_PROVIDER_MESSAGE = _re.compile(
    r"(?ix)(?:"
    r"https?://|"
    r"(?:^|[^0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?:[^0-9]|$)|"
    r"\b(?:api[_ -]?key|authorization|bearer|password|secret|token|prompt|input|messages?)\b"
    r")"
)

#: Upstream HTTP status -> ``(client_status, error_code, retryable)`` surface.
#: The client status is what this gateway returns; ``error_code`` follows the
#: OpenAI-compatible vocabulary; ``retryable`` mirrors the gateway's own
#: transient-retry policy so callers can make consistent retry decisions.
PROVIDER_STATUS_SURFACES: dict[int, tuple[int, str, bool]] = {
    400: (400, "invalid_request_error", False),
    401: (401, "authentication_error", False),
    402: (402, "payment_required", False),
    403: (403, "permission_error", False),
    404: (404, "model_not_found", False),
    405: (502, "api_error", False),
    408: (504, "provider_timeout", True),
    409: (409, "conflict", True),
    410: (404, "model_not_found", False),
    413: (413, "request_too_large", False),
    415: (400, "invalid_request_error", False),
    422: (400, "invalid_request_error", False),
    425: (429, "rate_limit_exceeded", True),
    429: (429, "rate_limit_exceeded", True),
    500: (502, "api_error", True),
    501: (502, "api_error", False),
    502: (502, "api_error", True),
    503: (503, "service_unavailable", True),
    504: (504, "provider_timeout", True),
    529: (503, "service_unavailable", True),
}

#: Fallback surface for an upstream status that has no explicit mapping.
_UNMAPPED_UPSTREAM_SURFACE: tuple[int, str, bool] = (502, "api_error", False)


def provider_error_body(exc: urllib.error.HTTPError) -> bytes:
    """Read and cache one bounded upstream error body for all classifiers."""
    cache_key = "_contextual_orchestrator_provider_error_body"
    cached = getattr(exc, cache_key, None)
    if isinstance(cached, bytes):
        return cached
    body = exc.read(MAX_PROVIDER_ERROR_BODY_BYTES + 1)[:MAX_PROVIDER_ERROR_BODY_BYTES]
    try:
        setattr(exc, cache_key, body)
    except (AttributeError, TypeError):  # pragma: no cover - HTTPError is mutable
        pass
    return body


def _sanitize_provider_message_text(raw: object) -> str | None:
    """Collapse one provider diagnostic to a bounded caller-safe sentence."""
    collapsed = "".join(
        char
        if char == "\t" or not (ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F)
        else " "
        for char in str(raw)
    ).strip()
    collapsed = collapsed[:MAX_SAFE_MESSAGE_CHARS]
    if not collapsed or _SENSITIVE_PROVIDER_MESSAGE.search(collapsed):
        return None
    return collapsed


def safe_provider_message(exc: BaseException) -> str | None:
    """Extract one bounded, control-free diagnostic sentence from a failure.

    An HTTP error contributes only JSON ``error.message``-style fields. For
    non-HTTP exceptions, this low-level helper returns a bounded first argument
    or exception type for internal diagnostics; caller-facing classification
    deliberately replaces those values with package-owned sentences.
    Provider diagnostics can embed URLs, secrets, prompts, or internal topology,
    so raw exception text never reaches API callers.
    Control characters are collapsed so no body can smuggle log-formatting
    or header content downstream.
    """
    if isinstance(exc, urllib.error.HTTPError):
        try:
            payload = _json.loads(
                provider_error_body(exc).decode("utf-8", errors="replace")
            )
        except Exception:  # noqa: BLE001 - bodies are untrusted input
            return None
        raw: Any = None
        if isinstance(payload, dict):
            error_field = payload.get("error")
            if isinstance(error_field, dict):
                raw = error_field.get("message") or error_field.get("code")
            elif isinstance(error_field, str):
                raw = error_field
            else:
                raw = payload.get("message") or payload.get("detail") or payload.get("code")
        if not isinstance(raw, (str, int, float)) or raw == "":
            return None
    else:
        first_arg = next((part for part in exc.args[:1] if isinstance(part, str)), "")
        raw = first_arg or type(exc).__name__
    return _sanitize_provider_message_text(raw)


class ProviderUpstreamError(RuntimeError):
    """One classified upstream model/provider failure.

    Attributes carry the evidence a caller needs to act: which agent/model
    failed, the upstream status when one existed, the OpenAI-compatible code,
    whether retrying can help, and one bounded redacted message.
    """

    def __init__(
        self,
        *,
        agent_id: str,
        model: str,
        error_code: str,
        message: str,
        client_status: int,
        provider_status: int | None = None,
        retryable: bool = False,
        transport: str = "chat",
    ) -> None:
        self.agent_id = agent_id
        self.model = model
        self.error_code = error_code
        self.client_status = client_status
        self.provider_status = provider_status
        self.retryable = retryable
        self.transport = transport
        super().__init__(
            _sanitize_provider_message_text(message)
            or "provider diagnostic was redacted for safety"
        )

    @property
    def detail(self) -> dict[str, Any]:
        """Return the structured evidence attached to API error payloads."""
        return {
            "agent_id": self.agent_id,
            "model": self.model,
            "provider_status": self.provider_status,
            "retryable": self.retryable,
            "transport": self.transport,
        }


def classify_provider_failure(
    exc: BaseException | None,
    *,
    agent_id: str,
    model: str,
    transport: str = "chat",
) -> ProviderUpstreamError:
    """Map one provider-call exception onto the caller-facing error taxonomy.

    Messages stay package-owned and bounded: only an upstream JSON body's
    ``error.message``-style field may pass through (redacted); every other
    cause gets a fixed sentence so raw provider diagnostics (URLs, prompts,
    secrets) can never reach callers or logs.
    """
    if isinstance(exc, ProviderUpstreamError):
        return exc
    if isinstance(exc, urllib.error.HTTPError):
        status = exc.code
        client_status, error_code, retryable = PROVIDER_STATUS_SURFACES.get(
            status, _UNMAPPED_UPSTREAM_SURFACE
        )
        return ProviderUpstreamError(
            agent_id=agent_id,
            model=model,
            error_code=error_code,
            message=(
                safe_provider_message(exc)
                or f"provider rejected the request with HTTP {status}"
            ),
            client_status=client_status,
            provider_status=status,
            retryable=retryable,
            transport=transport,
        )
    if isinstance(exc, ssl.SSLCertVerificationError):
        return ProviderUpstreamError(
            agent_id=agent_id,
            model=model,
            error_code="tls_verification_failed",
            message=f"provider {agent_id} endpoint failed TLS certificate verification",
            client_status=502,
            provider_status=None,
            retryable=False,
            transport=transport,
        )
    if isinstance(exc, ssl.SSLError):
        return ProviderUpstreamError(
            agent_id=agent_id,
            model=model,
            error_code="tls_failure",
            message=f"a TLS error interrupted the provider {agent_id} connection",
            client_status=502,
            provider_status=None,
            retryable=True,
            transport=transport,
        )
    dns_error = exc if isinstance(exc, socket.gaierror) else getattr(exc, "__cause__", None)
    if isinstance(dns_error, socket.gaierror):
        return ProviderUpstreamError(
            agent_id=agent_id,
            model=model,
            error_code="provider_connection_error",
            message=f"the provider {agent_id} host could not be resolved",
            client_status=502,
            provider_status=None,
            retryable=dns_error.errno == socket.EAI_AGAIN,
            transport=transport,
        )
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError, socket.timeout)):
        return ProviderUpstreamError(
            agent_id=agent_id,
            model=model,
            error_code="provider_connection_error",
            message=f"the provider {agent_id} connection failed or did not finish in time",
            client_status=502,
            provider_status=None,
            retryable=True,
            transport=transport,
        )
    return ProviderUpstreamError(
        agent_id=agent_id,
        model=model,
        error_code="api_error",
        message=f"provider {agent_id} request failed",
        client_status=502,
        provider_status=None,
        retryable=False,
        transport=transport,
    )
