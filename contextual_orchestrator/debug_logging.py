"""Stdlib-only verbose/debug logging: level resolution, lazy DEBUG helpers, and a
handler-level redaction safety net.

No new dependency. `logging` (the standard library module) is the only thing
this uses -- see the Ponytail entry in `docs/library_research.md`. This module
is a leaf: it imports nothing else from `contextual_orchestrator`, so
`orchestrator.py`, `model_discovery.py`, and `server.py` can all import it
without creating a cycle.

Redaction here is deliberately a *safety net*, not the primary control. Call
sites that log caller- or provider-derived content must already redact it
(e.g. via `contextual_orchestrator.orchestrator.redact_text`/`redact_value`)
before it reaches a log call; `configure_logging`'s optional `redactor`
re-applies the same redaction over the final rendered message in case a call
site ever forgets. It never touches PII -- see `redact_text`'s own docstring
for why PII is out of scope here too.
"""

from __future__ import annotations

import json
import logging
from typing import Callable

#: Redaction marker used in place of any value found under a credential-shaped
#: JSON key. Matches the marker `redact_value`/`redact_text` already use
#: elsewhere in this codebase, so a reader sees one consistent redaction
#: convention regardless of which pass caught a given secret.
REDACTED_MARKER = "[REDACTED]"

#: Dict key names (case-insensitive, exact match) treated as always carrying
#: a credential, regardless of what the value looks like. This is
#: deliberately broad and shape-agnostic: `redact_value`/`redact_text` only
#: catch secrets by pattern-matching the *value*'s in-string shape (e.g.
#: "api_key=..." or "Bearer ..."), so they never look at the JSON key a
#: string is nested under -- a field like {"private_key": "-----BEGIN
#: PRIVATE KEY-----..."} or {"key": "AIzaSy..."} sails through unredacted.
#: This set closes that blind spot at the JSON-structure level instead.
CREDENTIAL_SHAPED_KEY_NAMES = frozenset(
    {
        "key",
        "api_key",
        "apikey",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "client_secret",
        "password",
        "credential",
        "credentials",
        "auth",
        "authorization",
        "private_key",
        "public_key",
        "signing_key",
        "pem",
    }
)

#: Recognized stdlib logging level names, most to least verbose.
LOG_LEVEL_NAMES: tuple[str, ...] = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

#: Today's de facto stdlib default, kept unchanged so existing stderr-parsing
#: does not see new output just from upgrading to a version with this module.
DEFAULT_LOG_LEVEL_NAME = "WARNING"


def parse_log_level_name(level_name: str) -> str:
    """Normalize a case-insensitive logging level name to its canonical spelling.

    Args:
        level_name: A level name such as ``"debug"``, ``"Warning"``, or
            ``"ERROR"`` (surrounding whitespace is ignored).

    Returns:
        The canonical uppercase level name, one of :data:`LOG_LEVEL_NAMES`.

    Raises:
        ValueError: If ``level_name`` does not name a recognized stdlib
            logging level.
    """
    normalized = level_name.strip().upper()
    if normalized not in LOG_LEVEL_NAMES:
        allowed = ", ".join(LOG_LEVEL_NAMES)
        raise ValueError(f"invalid log level {level_name!r}; choose one of {allowed}")
    return normalized


class _RedactingLogFilter(logging.Filter):
    """Re-run a redactor over every record's fully rendered message.

    Attached to the handler `configure_logging` installs, never to a Logger
    object: a Logger-level filter is skipped while a record propagates in
    from a child logger, so only a handler-level filter reliably sees every
    record this process ever emits, regardless of which logger created it.
    """

    def __init__(self, redactor: Callable[[str], str]) -> None:
        """Store the redactor callable applied to every record this filters."""
        super().__init__()
        self._redactor = redactor

    def filter(self, record: logging.LogRecord) -> bool:
        """Rewrite ``record`` in place with its rendered message redacted.

        Renders ``record``'s message (applying any `%`-style args) first, so
        the redactor sees the final text a handler would emit, then clears
        ``args`` since the redacted text is no longer a format string.
        Always returns ``True``: this filter redacts, it never drops records.
        """
        record.msg = self._redactor(record.getMessage())
        record.args = ()
        return True


def configure_logging(
    level_name: str,
    *,
    redactor: Callable[[str], str] | None = None,
) -> None:
    """Configure the root logger's level and, optionally, a redaction safety net.

    Uses ``logging.basicConfig(..., force=True)`` so repeated in-process calls
    actually take effect. Plain `logging.basicConfig` is a no-op after the
    first call in a process -- a classic stdlib footgun that would otherwise
    make every subsequent in-process CLI invocation (this repo's own test
    convention, and every real process that calls `main()` more than once
    per interpreter) silently keep the first level it was ever given.

    Args:
        level_name: A level name accepted by :func:`parse_log_level_name`.
        redactor: Optional callable re-applied to every record's rendered
            message before it reaches a handler. This is a defense-in-depth
            safety net, not the primary redaction step -- see the module
            docstring.

    Raises:
        ValueError: If ``level_name`` is invalid. Nothing is configured in
            that case; the previous configuration is left untouched.
    """
    level = getattr(logging, parse_log_level_name(level_name))
    logging.basicConfig(level=level, force=True)
    if redactor is None:
        return
    redacting_filter = _RedactingLogFilter(redactor)
    for handler in logging.getLogger().handlers:
        handler.addFilter(redacting_filter)


def log_debug_event(logger: logging.Logger, message: str, *args: object) -> None:
    """Emit one DEBUG record, without formatting ``args`` unless DEBUG is enabled.

    `logging.Logger.debug` already defers `%`-style formatting internally,
    but only for the formatting call itself -- it cannot save a caller from
    eagerly building an expensive argument before passing it in. This helper
    makes the guard explicit and independently testable: call sites that
    already have cheap-to-construct args may still prefer this over
    `logger.debug(...)` directly for that explicitness. Call sites that would
    otherwise do nontrivial work to build one argument (e.g. redacting and
    truncating a large value) should guard that work themselves with
    ``logger.isEnabledFor(logging.DEBUG)`` rather than rely on this helper,
    since the expensive part happens before any function call sees it.

    Args:
        logger: The logger to emit on.
        message: A `%`-style format string.
        *args: Positional arguments substituted into ``message``.
    """
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(message, *args)


def summarize_request_for_log(
    *,
    method: str,
    path: str,
    status: int | None,
    latency_ms: float,
    session_id_hash: str | None = None,
) -> str:
    """Format one body-free HTTP request/response summary line for INFO logging.

    Carries method, path, status, and latency only -- never headers, a query
    string beyond the raw path, or a request/response body. Any query string
    on ``path`` is stripped here, defensively, regardless of what the caller
    passed in: a caller could plausibly put a token in a query parameter (a
    common client habit) even though this server's own auth is header-only,
    so this helper never trusts a caller to have already done that stripping
    -- it enforces its own "body-free" contract itself.

    Args:
        method: The HTTP method, e.g. ``"POST"``.
        path: The request path as received (already excludes any body), with
            or without a query string -- either is accepted, but only the
            bare path before any ``?`` is ever logged.
        status: The HTTP status code that was sent, or ``None`` when a
            response was never sent (e.g. the connection dropped first).
        latency_ms: Elapsed wall-clock time for the request, in milliseconds.
        session_id_hash: The bounded correlation hash already computed by
            `contextual_orchestrator.telemetry` (ADR 0122), or ``None``. The
            raw session id itself must never be passed here.

    Returns:
        One single-line, `%`-free summary string ready to hand to a logger.
    """
    bare_path = path.split("?", 1)[0]
    return (
        f"http_request method={method} path={bare_path} "
        f"status={'-' if status is None else status} "
        f"latency_ms={latency_ms:.1f} "
        f"session_id_hash={session_id_hash or '-'}"
    )


def redact_credential_shaped_keys(value: object) -> object:
    """Recursively replace any dict value whose key looks like a credential.

    This is a separate, additional pass from
    `contextual_orchestrator.orchestrator.redact_value`/`redact_text`, which
    only pattern-match a secret's in-string *value* shape (e.g.
    ``api_key=...`` or ``Bearer ...``) and never inspect the JSON key a
    string is nested under. A logging call site should apply both: this
    catches ``{"private_key": "-----BEGIN PRIVATE KEY-----..."}``,
    ``{"key": "AIzaSy..."}``, ``{"auth": "sk-live..."}``, or
    ``{"credential": "..."}`` regardless of whether the value happens to
    match any known secret pattern; `redact_value`/`redact_text` still catch
    secret-shaped values nested under an unremarkable key name.

    A matched key's entire value is replaced with :data:`REDACTED_MARKER`
    regardless of its shape or content -- a nested dict or list under a
    credential-shaped key is not recursed into and explained away as
    "probably fine": it is dropped wholesale, since a credential-shaped key
    has no legitimate reason to carry structured data a log line needs.

    Args:
        value: A JSON-like structure -- some combination of ``dict``,
            ``list``, ``str``, ``int``, ``float``, ``bool``, and ``None``.
            Any other type is returned unchanged.

    Returns:
        A new structure of the same shape, with every credential-shaped
        dict key's value replaced. The input is never mutated in place, so
        it remains safe to keep using the original for anything other than
        logging (e.g. the actual HTTP response body).
    """
    if isinstance(value, dict):
        return {
            key: (
                REDACTED_MARKER
                if isinstance(key, str) and key.strip().casefold() in CREDENTIAL_SHAPED_KEY_NAMES
                else redact_credential_shaped_keys(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_credential_shaped_keys(item) for item in value]
    return value


def summarize_payload_for_log(
    label: str,
    safe_payload: object,
    *,
    max_characters: int = 500,
) -> str:
    """Bound an already-redacted request/response payload to one DEBUG log line.

    ``safe_payload`` must already be redacted by the caller (e.g. via
    `contextual_orchestrator.orchestrator.redact_value`) before it reaches
    this function -- it only serializes and truncates; it performs no
    redaction of its own, so it must never be handed a payload that still
    carries secrets.

    Args:
        label: A short label identifying the payload, e.g. ``"request"`` or
            ``"response"``.
        safe_payload: The already-redacted value to summarize.
        max_characters: Maximum length of the serialized body before it is
            truncated (default 500).

    Returns:
        A ``"{label}_summary {body}"`` string, truncated with a trailing
        marker when ``safe_payload``'s serialization exceeds
        ``max_characters``.
    """
    try:
        serialized = json.dumps(safe_payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        # e.g. a circular reference -- fall back to repr rather than raise
        # out of a logging call site.
        serialized = str(safe_payload)
    if len(serialized) > max_characters:
        serialized = f"{serialized[:max_characters]}...<truncated>"
    return f"{label}_summary {serialized}"
