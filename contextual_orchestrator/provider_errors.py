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

import datetime as _dt
import json as _json
import math as _math
import re as _re
import http.client
import socket
import ssl
import time as _time
import urllib.error
from email.utils import parsedate_to_datetime
from typing import Any

__all__ = [
    "PROVIDER_OUTCOME_UNKNOWN_CODE",
    "PROVIDER_RATE_LIMITED_CODE",
    "MAX_PROVIDER_ERROR_BODY_BYTES",
    "MAX_SAFE_MESSAGE_CHARS",
    "PROVIDER_STATUS_SURFACES",
    "ProviderUpstreamError",
    "classify_provider_failure",
    "parse_retry_after",
    "provider_error_body",
    "provider_limit_evidence",
    "rate_limited_storm_error",
    "resolve_retry_after_seconds",
    "safe_provider_message",
]

PROVIDER_OUTCOME_UNKNOWN_CODE = "provider_outcome_unknown"

#: Honest-429 error code for the rate-limit-storm case: every eligible
#: candidate is quota-limited and the caller's wait budget cannot cover the
#: earliest known cooldown. Distinct from the ordinary ``rate_limit_exceeded``
#: single-candidate surface (429 -> retryable) so callers can tell "one
#: provider throttled you, failover already tried the rest" apart from
#: "the whole pool is out of quota right now."
PROVIDER_RATE_LIMITED_CODE = "provider_rate_limited"

#: Provider ``x-ratelimit-reset*`` headers this gateway will read as a
#: fallback when ``Retry-After`` is absent. Only a plain numeric
#: seconds-until-reset value is accepted (the common OpenAI-compatible
#: convention); a non-numeric provider-specific duration format (e.g. "6m0s")
#: is left as "unknown" rather than guessed at.
_RATE_LIMIT_RESET_HEADERS = (
    "x-ratelimit-reset-requests",
    "x-ratelimit-reset-tokens",
    "x-ratelimit-reset",
)

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
    r"\b(?:api[_ -]?key|authorization|bearer|password|secret|token|prompt|input|messages?|content)\b"
    r")"
)
_SAFE_SCHEMA_DIAGNOSTIC = _re.compile(
    r"['\"]?messages['\"]? must contain the word ['\"]?json['\"]?"
    r"(?: in some form,)? to use "
    r"(?:['\"]?response_format['\"]? of type ['\"]?json_object['\"]?|json_object)"
    r"(?:\.|$)",
    _re.IGNORECASE,
)
_SAFE_SCHEMA_ERROR_SUMMARY = "messages must mention json when response_format is json_object"

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
    """Read and cache one bounded upstream error body for all classifiers.

    The read is untrusted network I/O: a stalled or dropped connection can
    raise ``http.client.IncompleteRead`` (not an ``OSError`` subclass) or
    other transport failures mid-read. A classifier's body inspection must
    never abort its caller over an unreadable body, so any read failure
    here degrades to an empty body rather than propagating.
    """
    cache_key = "_contextual_orchestrator_provider_error_body"
    cached = getattr(exc, cache_key, None)
    if isinstance(cached, bytes):
        return cached
    try:
        body = exc.read(MAX_PROVIDER_ERROR_BODY_BYTES + 1)[:MAX_PROVIDER_ERROR_BODY_BYTES]
    except Exception:  # noqa: BLE001 - bodies are untrusted input; a read failure is not fatal
        body = b""
    try:
        setattr(exc, cache_key, body)
    except (AttributeError, TypeError):  # pragma: no cover - HTTPError is mutable
        pass
    return body


def provider_limit_evidence(exc: urllib.error.HTTPError) -> dict[str, str]:
    """Return bounded limit-classification fields from a cached HTTP error body.

    Only identifier-like values survive (see
    ``domain.provider_limits.limit_evidence_from_payload``); an unreadable or
    non-JSON body yields ``{}``.
    """
    from .domain.provider_limits import limit_evidence_from_payload

    try:
        payload = _json.loads(provider_error_body(exc).decode("utf-8", errors="replace"))
    except (ValueError, TypeError):
        return {}
    return limit_evidence_from_payload(payload)


def parse_retry_after(value: str | None, *, now: float | None = None) -> float | None:
    """Parse a ``Retry-After`` header value into non-negative seconds from now.

    Accepts either RFC 9110 10.2.3 form: delta-seconds (a plain non-negative
    integer) or an HTTP-date. Returns ``None`` -- "unknown" -- for a missing,
    empty, or unparseable value; callers must never guess a cooldown for an
    unknown value.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.isdigit():
        try:
            return float(int(stripped))
        except (ValueError, OverflowError):
            return None
    try:
        target = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, IndexError):
        return None
    if target is None:
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=_dt.timezone.utc)
    reference = _dt.datetime.fromtimestamp(
        now if now is not None else _time.time(), tz=_dt.timezone.utc
    )
    return max((target - reference).total_seconds(), 0.0)


def resolve_retry_after_seconds(exc: urllib.error.HTTPError) -> float | None:
    """Resolve a provider-declared cooldown, in seconds, from a 429/503 response.

    Prefers the standard ``Retry-After`` header. When absent, falls back to a
    plain-numeric ``x-ratelimit-reset*`` header if the provider sent one.
    Returns ``None`` ("unknown") when neither is present or parseable -- an
    unknown cooldown must never be treated as zero or guessed at.
    """
    headers = getattr(exc, "headers", None)
    if headers is None:
        return None
    parsed = parse_retry_after(headers.get("Retry-After"))
    if parsed is not None:
        return parsed
    for name in _RATE_LIMIT_RESET_HEADERS:
        raw = headers.get(name)
        if raw is None:
            continue
        try:
            value = float(raw.strip())
        except (ValueError, AttributeError):
            continue
        if _math.isfinite(value) and value >= 0:
            return value
    return None


def rate_limited_storm_error(
    *,
    agent_id: str,
    model: str,
    retry_after_seconds: float,
    transport: str = "passthrough",
    cooldown_source: str = "provider",
) -> ProviderUpstreamError:
    """Build the honest 429 for a rate-limit storm the caller's budget can't wait out.

    Raised only when every eligible candidate is currently quota-limited and
    the earliest known cooldown exceeds the request's remaining wait budget
    (the administrator-owned model deadline, or the documented
    ``rate_limit_wait_seconds`` fallback). This is quota exhaustion, not a
    connection failure, so it is deliberately kept out of the
    ``provider_connection_error`` / 502 surface and marked retryable: the
    caller can retry after ``retry_after_seconds``.

    ``cooldown_source`` is ``"provider"`` when ``retry_after_seconds`` came
    from the provider's own ``Retry-After``/``x-ratelimit-reset*`` header, or
    ``"assumed"`` when the provider stated no cooldown at all and
    ``retry_after_seconds`` is instead the administrator-owned
    ``rate_limit_unknown_cooldown_seconds`` default -- surfaced so the caller
    can tell a measured wait apart from a guessed one.
    """
    assumed_note = (
        " (the provider stated no cooldown; this is an assumed wait)"
        if cooldown_source == "assumed"
        else ""
    )
    return ProviderUpstreamError(
        agent_id=agent_id,
        model=model,
        error_code=PROVIDER_RATE_LIMITED_CODE,
        message=(
            "every eligible provider is rate-limited past this request's "
            f"wait budget{assumed_note}"
        ),
        client_status=429,
        provider_status=429,
        retryable=True,
        transport=transport,
        extra_detail={
            "retry_after_seconds": retry_after_seconds,
            "cooldown_source": cooldown_source,
        },
    )


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
    collapsed = "".join(
        char
        if char == "\t" or not (ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F)
        else " "
        for char in str(raw)
    ).strip()
    collapsed = collapsed[:MAX_SAFE_MESSAGE_CHARS]
    if _SAFE_SCHEMA_DIAGNOSTIC.search(collapsed):
        return _SAFE_SCHEMA_ERROR_SUMMARY
    if not collapsed or _SENSITIVE_PROVIDER_MESSAGE.search(collapsed):
        return None
    return collapsed


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
        extra_detail: dict[str, Any] | None = None,
        limit_evidence: dict[str, str] | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.model = model
        self.error_code = error_code
        self.client_status = client_status
        self.provider_status = provider_status
        self.retryable = retryable
        self.transport = transport
        self.extra_detail = dict(extra_detail or {})
        # Bounded identifier fields from the upstream error body (never free
        # text) for the spend guard's provider-limit rule; not caller-facing.
        self.limit_evidence = dict(limit_evidence or {})
        super().__init__(message)

    @property
    def detail(self) -> dict[str, Any]:
        """Return the structured evidence attached to API error payloads."""
        payload = {
            "agent_id": self.agent_id,
            "model": self.model,
            "provider_status": self.provider_status,
            "retryable": self.retryable,
            "transport": self.transport,
        }
        selected_candidate_ids = getattr(self, "selected_candidate_ids", None)
        if isinstance(selected_candidate_ids, (list, tuple)) and selected_candidate_ids:
            payload["selected_candidate_ids"] = list(selected_candidate_ids)
        attempts = getattr(self, "attempts", None)
        if isinstance(attempts, (list, tuple)) and attempts:
            payload["attempts"] = [dict(item) for item in attempts if isinstance(item, dict)]
        terminal_reason = getattr(self, "terminal_reason", None)
        if isinstance(terminal_reason, str) and terminal_reason:
            payload["terminal_reason"] = terminal_reason
        payload.update(self.extra_detail)
        return payload


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
        if exc.transport == transport:
            return exc
        return ProviderUpstreamError(
            agent_id=exc.agent_id,
            model=exc.model,
            error_code=exc.error_code,
            message=str(exc),
            client_status=exc.client_status,
            provider_status=exc.provider_status,
            retryable=exc.retryable,
            transport=transport,
            extra_detail=exc.extra_detail,
            limit_evidence=getattr(exc, "limit_evidence", None),
        )
    if isinstance(exc, urllib.error.HTTPError):
        status = exc.code
        client_status, error_code, retryable = PROVIDER_STATUS_SURFACES.get(
            status, _UNMAPPED_UPSTREAM_SURFACE
        )
        # Quota-cooldown evidence, kept on every 429/503 classification (not
        # just the passthrough transport's own header walk) so any caller
        # holding just the classified ProviderUpstreamError -- e.g. _invoke's
        # chat transport -- can still record and wait out the same cooldown.
        extra_detail: dict[str, Any] = {}
        if status in (429, 503):
            retry_after = resolve_retry_after_seconds(exc)
            if retry_after is not None:
                extra_detail["retry_after_seconds"] = retry_after
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
            extra_detail=extra_detail,
            limit_evidence=provider_limit_evidence(exc),
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
    # http.client.HTTPException (IncompleteRead, BadStatusLine) is not an
    # OSError but is the same event -- a stalled or dropped connection
    # mid-read, as provider_error_body already notes -- so it shares the
    # retryable connection classification instead of the opaque default.
    if isinstance(
        exc,
        (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            socket.timeout,
            http.client.HTTPException,
        ),
    ):
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
