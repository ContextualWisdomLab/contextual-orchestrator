"""Prompt-safe OpenTelemetry and session correlation for the gateway."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

try:
    from opentelemetry import trace
    from opentelemetry.trace import SpanKind, Status, StatusCode
except ImportError:  # pragma: no cover - dependency is declared by the project
    trace = None  # type: ignore[assignment]
    SpanKind = None  # type: ignore[assignment,misc]
    Status = None  # type: ignore[assignment,misc]
    StatusCode = None  # type: ignore[assignment,misc]

_LOGGER = logging.getLogger(__name__)
_CURRENT_SESSION: ContextVar[str | None] = ContextVar(
    "contextual_orchestrator_session_id", default=None
)
_CONFIGURED = False


def _otlp_trace_endpoint(endpoint: str) -> str:
    """Turn an OTLP base endpoint into the explicit HTTP traces endpoint."""
    normalized = endpoint.rstrip("/")
    if normalized.casefold().endswith("/v1/traces"):
        return normalized
    return f"{normalized}/v1/traces"


def _config_value(config: Any | None, key: str, default: Any = None) -> Any:
    """Read one telemetry setting from the injected KV configuration."""
    if config is None:
        return default
    return config.get("telemetry", key, default)


def _normalize_session_id(value: object) -> str | None:
    """Accept a bounded correlation value without accepting a bearer token."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 128 or any(ord(char) < 0x20 for char in value):
        return None
    return value


def session_id_from_headers(headers: Mapping[str, str]) -> str | None:
    """Read the LineageWeave correlation header from an HTTP request."""
    return _normalize_session_id(
        headers.get("x-lineageweave-session-id") or headers.get("x-session-id")
    )


def session_id_from_metadata(metadata: Mapping[str, Any] | None) -> str | None:
    """Read a session value from compatible OpenAI metadata fields."""
    if metadata is None:
        return None
    return _normalize_session_id(
        metadata.get("lineageweave_post_session_id") or metadata.get("session_id")
    )


def current_session_id() -> str | None:
    """Return the request-scoped correlation value, if one is bound."""
    return _CURRENT_SESSION.get()


def set_session_id(value: object) -> Token[str | None]:
    """Bind one session to the current request context."""
    return _CURRENT_SESSION.set(_normalize_session_id(value))


def reset_session_id(token: Token[str | None]) -> None:
    """Restore the context value that preceded a request."""
    _CURRENT_SESSION.reset(token)


def _safe_attributes(
    attributes: Mapping[str, Any] | None,
) -> dict[str, str | int | float | bool]:
    """Keep span attributes scalar and exclude prompt, answer, and secret content."""
    result: dict[str, str | int | float | bool] = {}
    for key, value in (attributes or {}).items():
        if (
            not isinstance(key, str)
            or not key
            or isinstance(value, (dict, list, tuple, set))
        ):
            continue
        if isinstance(value, str):
            result[key] = value[:256]
        elif isinstance(value, (bool, int, float)):
            result[key] = value
    session_id = current_session_id()
    if session_id:
        result.setdefault("contextual_orchestrator.session_id", session_id)
    return result


def configure_telemetry(
    service_name: str = "contextual-orchestrator",
    *,
    config: Any | None = None,
) -> None:
    """Configure OTLP export from the injected KV configuration only."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    if config is None:
        _LOGGER.debug("OpenTelemetry is not configured without a KV store")
        return
    _CONFIGURED = True
    if str(_config_value(config, "sdk_disabled", "")).lower() == "true":
        return
    endpoint = str(_config_value(config, "exporter_otlp_endpoint", "")).strip()
    if trace is None or not endpoint:
        return
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:  # pragma: no cover - guarded by the runtime dependency
        _LOGGER.warning("OpenTelemetry SDK/exporter is unavailable")
        return

    configured_service_name = str(
        _config_value(config, "service_name", service_name)
    ).strip() or service_name
    resource = Resource.create({
        "service.name": configured_service_name,
        "service.namespace": "contextualwisdomlab",
    })
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=_otlp_trace_endpoint(endpoint))
        )
    )
    trace.set_tracer_provider(provider)


@contextmanager
def traced(
    name: str,
    attributes: Mapping[str, Any] | None = None,
) -> Iterator[Any]:
    """Trace one provider CLIENT operation and preserve all failures."""
    if trace is None:  # pragma: no cover - dependency is declared by the project
        yield None
        return
    tracer = trace.get_tracer("contextual-orchestrator")
    safe = _safe_attributes(attributes)
    with tracer.start_as_current_span(
        name,
        kind=SpanKind.CLIENT,
        attributes=safe,
    ) as span:
        try:
            yield span
        except Exception as exc:
            if Status is not None and StatusCode is not None:
                span.record_exception(exc)
                span.set_attribute("error.type", type(exc).__name__)
                span.set_status(Status(StatusCode.ERROR))
            _LOGGER.warning(
                "telemetry.operation_failed operation=%s error_type=%s session_id=%s",
                name,
                type(exc).__name__,
                safe.get("contextual_orchestrator.session_id", ""),
            )
            raise
