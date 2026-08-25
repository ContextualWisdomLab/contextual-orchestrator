"""Prompt-safe OpenTelemetry and session correlation for the gateway."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

try:
    from opentelemetry import trace
    from opentelemetry.context import attach as _otel_attach
    from opentelemetry.context import detach as _otel_detach
    from opentelemetry.trace import SpanKind, Status, StatusCode
    from opentelemetry.trace.propagation.tracecontext import (
        TraceContextTextMapPropagator,
    )

    _trace_context = TraceContextTextMapPropagator()
    _otel_extract = _trace_context.extract
    _otel_inject = _trace_context.inject
except ImportError:  # pragma: no cover - dependency is declared by the project
    trace = None  # type: ignore[assignment]
    _otel_attach = None
    _otel_detach = None
    _otel_extract = None
    _otel_inject = None
    SpanKind = None  # type: ignore[assignment,misc]
    Status = None  # type: ignore[assignment,misc]
    StatusCode = None  # type: ignore[assignment,misc]

_LOGGER = logging.getLogger(__name__)
_CURRENT_SESSION: ContextVar[str | None] = ContextVar(
    "contextual_orchestrator_session_id", default=None
)
_CONFIGURED = False
_ALLOWED_ATTRIBUTE_KEYS = frozenset(
    {
        "gen_ai.operation.name",
        "gen_ai.provider.name",
        "gen_ai.request.model",
        "contextual_orchestrator.agent_id",
        "contextual_orchestrator.session_id_hash",
        "server.address",
        "server.port",
        "error.type",
    }
)


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
    normalized_headers = {str(key).lower(): value for key, value in headers.items()}
    return _normalize_session_id(
        normalized_headers.get("x-lineageweave-session-id")
        or normalized_headers.get("x-session-id")
    )


def session_id_from_metadata(metadata: Mapping[str, Any] | None) -> str | None:
    """Read a session value from compatible OpenAI metadata fields."""
    if metadata is None:
        return None
    return _normalize_session_id(
        metadata.get("lineageweave_post_session_id") or metadata.get("session_id")
    )


def session_id_from_request(
    headers: Mapping[str, str],
    *metadata_values: Mapping[str, Any] | None,
) -> str | None:
    """Choose the canonical header session before compatible metadata values."""
    header_session = session_id_from_headers(headers)
    if header_session is not None:
        return header_session
    for metadata in metadata_values:
        metadata_session = session_id_from_metadata(metadata)
        if metadata_session is not None:
            return metadata_session
    return None


def current_session_id() -> str | None:
    """Return the request-scoped correlation value, if one is bound."""
    return _CURRENT_SESSION.get()


def set_session_id(value: object) -> Token[str | None]:
    """Bind one session to the current request context."""
    return _CURRENT_SESSION.set(_normalize_session_id(value))


def reset_session_id(token: Token[str | None]) -> None:
    """Restore the context value that preceded a request."""
    _CURRENT_SESSION.reset(token)


def attach_trace_context(headers: Mapping[str, str]) -> Any:
    """Attach an inbound W3C trace context and return its reset token."""
    if _otel_extract is None or _otel_attach is None:
        return None
    carrier = {str(key).lower(): str(value) for key, value in headers.items()}
    return _otel_attach(_otel_extract(carrier))


def detach_trace_context(token: Any) -> None:
    """Detach an inbound W3C trace context after one HTTP request."""
    if token is not None and _otel_detach is not None:
        _otel_detach(token)


def inject_trace_context(headers: dict[str, str]) -> None:
    """Inject the active W3C trace context into one provider request."""
    if _otel_inject is not None:
        _otel_inject(headers)


def _safe_attributes(
    attributes: Mapping[str, Any] | None,
) -> dict[str, str | int | float | bool]:
    """Keep only approved scalar span attributes; prompts and secrets never enter OTLP."""
    result: dict[str, str | int | float | bool] = {}
    for key, value in (attributes or {}).items():
        if (
            not isinstance(key, str)
            or not key
            or key not in _ALLOWED_ATTRIBUTE_KEYS
            or isinstance(value, (dict, list, tuple, set))
        ):
            continue
        if isinstance(value, str):
            result[key] = value[:256]
        elif isinstance(value, (bool, int, float)):
            result[key] = value
    session_id = current_session_id()
    if session_id:
        result["contextual_orchestrator.session_id_hash"] = hashlib.sha256(
            session_id.encode("utf-8")
        ).hexdigest()
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
    if str(_config_value(config, "sdk_disabled", "")).lower() == "true":
        _CONFIGURED = True
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
    _CONFIGURED = True


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
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except Exception as exc:
            if Status is not None and StatusCode is not None:
                span.set_attribute("error.type", type(exc).__name__)
                span.set_status(Status(StatusCode.ERROR))
            _LOGGER.warning(
                "telemetry.operation_failed operation=%s error_type=%s",
                name,
                type(exc).__name__,
            )
            raise
