YªçŠx-®éÜj×¢ëiºÚ+Š§j[h‘éÜ¢éíßŽµç}÷ëMúo+^²‰¢¶×"""Runtime orchestration, workflow trace, governance, and audit primitives."""

from __future__ import annotations

from collections import Counter, deque, OrderedDict
from collections.abc import Iterable, Mapping
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar, copy_context
from .decision_receipts import observe_auxiliary_dispatch, record_answer_cache_hit, record_initial_selection
from concurrent.futures import ThreadPoolExecutor
import copy
import errno
import hashlib
from dataclasses import dataclass, replace
from decimal import Decimal
from functools import wraps
import http.client
import inspect
import io
import ipaddress
import json
import logging
import math
import os
from pathlib import Path
import random
import re
import select
import socket
import ssl
import sqlite3
import threading
import time
import uuid
from typing import Any, Callable, NoReturn
from urllib.parse import urlparse, urlunsplit
import urllib.error
import urllib.request

import certifi
from egressweave import EgressNotAllowedError, EgressPolicy, validate_egress_url_details
from jsonschema.validators import validator_for

from .chat_capability import (
    is_chat_compatible_model_id,
    is_general_chat_candidate,
    requires_non_text_input,
)
from .conventions import legacy_discovered_agent_id, require_object_name
from .credentials import NotConfigured, get_credential
from .release_authorization import evaluate_release_authorization
from .model_group import ModelGroupRouter, canonical_group_name
from .openrouter_uptime import OpenRouterUptimeCollector
from .benchmark_priors import resolve_quality_prior
from .endpoint_race import EndpointAttempt, EndpointEquivalenceContract, race_first_valid
from .reasoning_effort_profile import EffortProfileError
from .provider_errors import (
    PROVIDER_OUTCOME_UNKNOWN_CODE,
    MAX_PROVIDER_ERROR_BODY_BYTES,
    ProviderUpstreamError,
    classify_provider_failure,
    provider_error_body,
    rate_limited_storm_error,
    resolve_retry_after_seconds,
)
from .telemetry import (
    annotate_current_span,
    current_request_id,
    inject_trace_context,
    record_provider_usage,
    traced,
)
from .pii_protection import (
    DEFAULT_PII_KEY_NAME,
    ENCRYPTED_FIELDS_KEY,
    PiiFieldEncryptor,
    PiiProtectionError,
    is_encrypted_detail,
    load_pii_encryptor,
)
from .tool_fallback import (
    MAX_TOOL_RETRY_ATTEMPTS,
    ToolExecutionError,
    ToolFailureDecision,
    ToolFailureKind,
    ToolFallbackAction,
    ToolFallbackStoppedError,
    classify_provider_transport_failure,
    classify_tool_failure,
    downgrade_to_failover,
)
from .response_cache import ResponseCacheProvider, build_response_cache_key
from .psychometric_routing import PsychometricRoutingEvidence
from .reasoning_effort_profile import (
    ReasoningEffortProfile,
    apply_request_profile,
    snapshot_role_effort_catalog,
)
from .token_counting import (
    TokenCountUnavailable,
    build_token_counter,
    prompt_token_lower_bound as _prompt_token_lower_bound_evidence,
    shared_context_output_budget,
)


_REQUEST_EXECUTION_SNAPSHOT: ContextVar[
    tuple[object, object, OrchestrationPolicy] | None
] = ContextVar(
    "contextual_orchestrator_request_execution_snapshot", default=None
)
_REQUEST_SELECTION_ATTEMPTS: ContextVar[list | None] = ContextVar(
    "contextual_orchestrator_request_selection_attempts", default=None
)


def _request_execution_scoped(method: Callable) -> Callable:
    """Share policy and effort across nested calls without leaking suspended streams."""
    if inspect.isgeneratorfunction(method):
        @wraps(method)
        def scoped_stream(self, *args, **kwargs):
            """Advance and close a stream in its own captured request context."""
            with self._request_execution_scope():
                context = copy_context()
                stream = method(self, *args, **kwargs)
            exhausted = object()
            try:
                while True:
                    item = context.run(next, stream, exhausted)
                    if item is exhausted:
                        return
                    yield item
            finally:
                context.run(stream.close)

        return scoped_stream

    @wraps(method)
    def scoped_call(self, *args, **kwargs):
        """Restore the caller's context after a synchronous result or exception."""
        with self._request_execution_scope():
            return method(self, *args, **kwargs)

    return scoped_call


_REQUEST_ENDPOINT_AGENT_IDS: ContextVar[frozenset[str] | None] = ContextVar(
    "contextual_orchestrator_request_endpoint_agent_ids", default=None
)
_REQUEST_ENDPOINT_IDENTITY: ContextVar[str | None] = ContextVar(
    "contextual_orchestrator_request_endpoint_identity", default=None
)
_INVALID_REQUESTED_MODEL = object()


class EndpointUnavailableError(ValueError):
    """The requested configured endpoint cannot serve this request."""


def normalize_endpoint_selector(value: str) -> str:
    """Normalize an endpoint selector without ever using it as transport input."""
    try:
        parsed = urlparse(value)
        scheme = parsed.scheme.casefold()
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise EndpointUnavailableError("endpoint_unavailable") from exc
    if (
        scheme not in {"http", "https"}
        or not hostname
        or parsed.username
        or parsed.password
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise EndpointUnavailableError("endpoint_unavailable")
    host = hostname.casefold()
    if ":" in host:
        host = f"[{host}]"
    if port is not None and port != (443 if scheme == "https" else 80):
        host = f"{host}:{port}"
    path = parsed.path.rstrip("/").removesuffix("/v1")
    return urlunsplit((scheme, host, path, "", ""))


def _configured_endpoint_matches(value: str, normalized: str) -> bool:
    """Return exact normalized equality for one already-configured transport."""
    try:
        return normalize_endpoint_selector(value) == normalized
    except EndpointUnavailableError:
        return False


def _agent_matches_request_endpoint(agent: ModelAgent) -> bool:
    """Revalidate both agent id and configured endpoint for the active request."""
    endpoint_ids = _REQUEST_ENDPOINT_AGENT_IDS.get()
    endpoint_identity = _REQUEST_ENDPOINT_IDENTITY.get()
    if endpoint_ids is None or endpoint_identity is None:
        return endpoint_ids is None and endpoint_identity is None
    return agent.id in endpoint_ids and _configured_endpoint_matches(
        agent.base_url, endpoint_identity
    )


def _request_endpoint_partition() -> str:
    """Return a non-reversible cache partition for the configured endpoint."""
    identity = _REQUEST_ENDPOINT_IDENTITY.get()
    if identity is None:
        return "endpoint:auto"
    return "endpoint:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


# content is usually str; multimodal vision messages use OpenAI content-parts lists.
ChatMessage = dict[str, Any]
ProviderDestination = tuple[int, tuple[Any, ...]]
MAX_MODEL_TIMEOUT_SECONDS = 2_147_483_647.0
_LOGGER = logging.getLogger(__name__)
MAX_LOCAL_CONCURRENCY = 64
MAX_PROVIDER_RESPONSE_BYTES = 8 * 1024 * 1024
_PASSTHROUGH_UNAVAILABLE_STATUS = frozenset({404, 410, 413})
# RFC 9110 section 9.2.2 permits an automatic non-idempotent retry only when
# the client knows the original request was never applied. These statuses
# describe a request rejection; generic origin/gateway failures (500/502/504)
# and the non-standard 529 do not provide that evidence and stay sticky.
_PASSTHROUGH_REJECTED_STATUS = _PASSTHROUGH_UNAVAILABLE_STATUS | frozenset(
    {408, 409, 425, 429, 503}
)
_PROVIDER_ERROR_CHAIN_LIMIT = 8
_PROVIDER_TOOL_DESCRIPTION_LIMIT_MESSAGE = (
    "each tool.function.description must be at most 1024 characters"
)
_SINGLE_TOOL_CALL_LIMIT_MESSAGE = "this model only supports single tool-calls at once"
DEFAULT_PROVIDER_PROBE_TIMEOUT = 5.0
MODEL_CAPABILITIES = frozenset(
    {"text", "image", "video", "speech", "transcription", "embedding", "rerank", "audio"}
)
_SAFE_PROVIDER_PROBE_ERROR_TYPES = frozenset({
    "ConnectionError",
    "HTTPError",
    "OSError",
    "RuntimeError",
    "SSLError",
    "TimeoutError",
    "TypeError",
    "UnknownError",
    "URLError",
    "ValueError",
})


class _ProviderCancellation:
    """Close stdlib HTTP connections owned by one cancellable provider call."""

    def __init__(self) -> None:
        self._connections: set[http.client.HTTPConnection] = set()
        self._lock = threading.Lock()
        self._cancelled = False
        self._cancelled_event = threading.Event()

    def register(self, connection: http.client.HTTPConnection) -> None:
        """Register a live connection or reject it after cancellation."""
        with self._lock:
            if not self._cancelled:
                self._connections.add(connection)
                return
        try:
            connection.close()
        except Exception:
            pass
        raise _ProviderRequestCancelled("provider request was cancelled")

    def cancel(self) -> None:
        """Best-effort close every registered connection exactly once."""
        with self._lock:
            self._cancelled = True
            self._cancelled_event.set()
            connections = tuple(self._connections)
            self._connections.clear()
        for connection in connections:
            sock = connection.sock
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
            try:
                connection.close()
            except Exception:
                pass

    def raise_if_cancelled(self) -> None:
        """Abort a cancellable DNS or connect operation after explicit cancellation."""
        if self._cancelled_event.is_set():
            raise _ProviderRequestCancelled("provider request was cancelled")

    def run(self, call: Callable[[], Any]) -> Any:
        """Run one call and translate transport fallout from cancellation."""
        token = _PROVIDER_CANCELLATION.set(self)
        try:
            return call()
        except BaseException as exc:
            if self._cancelled:
                raise _ProviderRequestCancelled("provider request was cancelled") from exc
            raise
        finally:
            _PROVIDER_CANCELLATION.reset(token)
            self.cancel()


class _ProviderRequestCancelled(RuntimeError):
    """A provider attempt stopped because its equivalent race already completed."""


_PROVIDER_CANCELLATION: ContextVar[_ProviderCancellation | None] = ContextVar(
    "provider_cancellation", default=None
)
_PROVIDER_DNS_SLOTS = threading.BoundedSemaphore(4)


def _safe_provider_probe_error_type(exc: Exception) -> str:
    """Keep provider diagnostics package-owned instead of echoing exception classes."""
    name = type(exc).__name__
    return name if name in _SAFE_PROVIDER_PROBE_ERROR_TYPES else "UnknownError"


class BudgetExceededError(RuntimeError):
    """Raised when an operator-configured spend budget is already exhausted."""

    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.detail = detail or {}


class ProviderResponseError(RuntimeError):
    """Raised for a provider response that cannot become a safe completion."""

    def __init__(
        self,
        message: str,
        *,
        failure_kind: str = "invalid_provider_response",
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_kind = failure_kind
        self.detail = {
            **(dict(detail) if detail else {}),
            "provider_response_failure_kind": failure_kind,
        }


class StructuredOutputExhaustedError(ProviderResponseError):
    """Raised after every eligible structured candidate violates the contract."""

    def __init__(
        self,
        message: str,
        *,
        workflow_run_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.workflow_run_id = workflow_run_id
        self.detail = {"failure_kind": "structured_output_exhausted"}
        if workflow_run_id is not None:
            self.detail["workflow_run_id"] = workflow_run_id


class ProviderRequestTooLargeError(ProviderUpstreamError):
    """Preserve request-size taxonomy across transport and telemetry boundaries."""

    def __init__(
        self,
        message: str,
        *,
        agent_id: str = "",
        model: str = "",
        provider_status: int | None = None,
        transport: str = "chat",
    ) -> None:
        super().__init__(
            agent_id=agent_id,
            model=model,
            error_code="request_too_large",
            message=message,
            client_status=413,
            provider_status=provider_status,
            retryable=False,
            transport=transport,
        )


def _structured_output_error(
    content: str, response_format: object
) -> str | None:
    """Return a bounded contract error for JSON object or JSON Schema output."""
    if not isinstance(response_format, Mapping):
        return None
    response_type = response_format.get("type")
    if response_type not in {"json_object", "json_schema"}:
        return None
    specification = response_format.get("json_schema")
    schema = specification.get("schema") if isinstance(specification, Mapping) else None
    if response_type == "json_schema" and not isinstance(schema, Mapping):
        return "schema_missing"
    try:
        instance = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return "invalid_json"
    if response_type == "json_object":
        return None if isinstance(instance, Mapping) else "invalid_json_object"
    validator_type = validator_for(schema)
    try:
        validator_type.check_schema(schema)
        validator_type(schema).validate(instance)
    except Exception:  # noqa: BLE001 - untrusted schema/output boundary
        return "schema_violation"
    return None


def _bind_provider_file_ids(
    document: Any, replicas: Mapping[str, Mapping[str, str]], agent_id: str
) -> Any:
    """Replace opaque gateway file ids with one candidate's provider ids."""
    if isinstance(document, list):
        return [_bind_provider_file_ids(item, replicas, agent_id) for item in document]
    if not isinstance(document, dict):
        return document
    result: dict[str, Any] = {}
    for key, value in document.items():
        if key == "file_id" and isinstance(value, str) and value in replicas:
            replica = replicas[value].get(agent_id)
            if not isinstance(replica, str):
                raise RuntimeError("required file replica is unavailable")
            result[key] = replica
        else:
            result[key] = _bind_provider_file_ids(value, replicas, agent_id)
    return result


def _step_output_tokens(
    step: Mapping[str, Any], token_counter: Any, model: str
) -> tuple[int | None, str]:
    """Return reported or exact raw-output tokens with their evidence source."""
    usage = step.get("usage")
    if isinstance(usage, dict):
        for key in ("completion_tokens", "output_tokens"):
            reported = usage.get(key)
            if type(reported) is int and reported >= 0:
                return reported, "reported"
    output = step.get("output")
    if not isinstance(output, str):
        return None, "unavailable"
    try:
        return token_counter.count_text(output, model), "tokenizer"
    except TokenCountUnavailable:
        return None, "unavailable"


def _step_output_token_count(
    step: Mapping[str, Any], token_counter: Any, model: str
) -> int | None:
    """Return the authoritative output count for an in-flight budget check."""
    return _step_output_tokens(step, token_counter, model)[0]


def _context_window_exclusions(
    candidates: list[ModelAgent], lower_bound_tokens: int
) -> tuple[list[ModelAgent], list[str]]:
    """Drop candidates whose KNOWN context window cannot hold the prompt.

    Exclusion requires positive proof: ``agent.context_window`` must be a
    known positive int strictly smaller than ``lower_bound_tokens`` (itself a
    conservative lower bound that never overestimates -- see
    :func:`contextual_orchestrator.token_counting.prompt_token_lower_bound`).
    An unknown (``None``) window is absence of evidence, not evidence of a
    too-small window, so it never excludes a candidate (Ong et al., 2024;
    ADR 0133).
    """
    kept: list[ModelAgent] = []
    excluded: list[str] = []
    for candidate in candidates:
        window = candidate.context_window
        has_known_window = (
            isinstance(window, int) and not isinstance(window, bool) and window > 0
        )
        if has_known_window and lower_bound_tokens > window:
            excluded.append(candidate.id)
            continue
        kept.append(candidate)
    return kept, excluded


def _cost_usd_decimal(output_tokens: int, price_per_million: float) -> Decimal:
    """Return exact decimal USD for tokens at a USD-per-million price."""
    return Decimal(output_tokens) * Decimal(str(price_per_million)) / Decimal(1_000_000)


def _zdr_content_placeholder(value: str) -> dict[str, Any]:
    """Return a non-content stand-in for one persisted string under zdr_only.

    Only a content hash and byte size survive -- enough to prove two stored
    rows share (or differ in) content without ever storing the content
    itself.
    """
    encoded = value.encode("utf-8")
    return {
        "zdr_redacted": True,
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "byte_size": len(encoded),
    }


def _zdr_redact_tool_calls(tool_calls: Any) -> Any:
    """Redact function-call arguments in an assistant tool-call list."""
    if not isinstance(tool_calls, list):
        return tool_calls
    redacted = []
    for call in tool_calls:
        if not isinstance(call, dict):
            redacted.append(call)
            continue
        call = dict(call)
        function = call.get("function")
        if isinstance(function, dict) and isinstance(function.get("arguments"), str):
            function = dict(function)
            function["arguments"] = _zdr_content_placeholder(function["arguments"])
            call["function"] = function
        redacted.append(call)
    return redacted


_COMMERCIAL_REPORT_CACHE: ContextVar[dict[tuple[Any, Any, Any], dict[str, Any]] | None] = ContextVar(
    "commercial_report_cache",
    default=None,
)
_REQUEST_ZDR_ONLY: ContextVar[bool] = ContextVar("request_zdr_only", default=False)
# Set while an ``orchestrator/free`` request is triaged, so the triage call
# itself never falls back to a non-free agent.
_REQUEST_TRIAGE_FREE_ONLY: ContextVar[bool] = ContextVar("request_triage_free_only", default=False)


def _resolved_openrouter_provider(agent: ModelAgent) -> str:
    """Canonical provider identity for the ZDR-pin decision, base_url-first.

    ``ModelAgent.provider_name`` is free-text and unvalidated at construction
    (hand-authored JSON, ``model_discovery.py`` auto-discovery, or KV-driven
    config can all leave it empty or typo'd). Trusting it verbatim here would
    let an agent whose ``base_url`` is OpenRouter's own endpoint silently skip
    the ``provider.zdr=true`` enforcement pin under an explicit ``zdr_only``
    scope while still routing bytes to OpenRouter (base_url decides where the
    request goes; this function only decides whether the pin is applied) â€”
    a silent ZDR-policy bypass, not a crash (CodeRabbit review on #953,
    discussion_r3898471887). Treating the exact OpenRouter hostname as
    authoritative also covers a nonempty typo in that free-text field. Every
    call site that funnels through this shared choke point (chat, streaming,
    raw, binary media, and non-embedding batch JSONL) therefore gets the same
    protection the embedding batch path already has.
    """
    host = urlparse(agent.base_url).hostname or ""
    if host == "openrouter.ai":
        return "openrouter"
    return agent.provider_name or host


def _pin_openrouter_zdr(agent: ModelAgent, payload: dict[str, Any]) -> dict[str, Any]:
    """Force OpenRouter to enforce zero-data-retention at request time.

    OpenRouter can multiplex one model id across several backing providers;
    a discovery-time ZDR feed snapshot proves a route was ZDR-attested when
    it was fetched, not which provider actually serves a later request. Their
    documented ``provider: {"zdr": true}`` request field is OpenRouter's own
    server-side enforcement (https://openrouter.ai/docs/features/provider-routing)
    and is authoritative for the request being sent right now, so it is
    applied here rather than trusted to have been decided correctly upstream.
    A caller-supplied ``provider`` object (e.g. explicit routing preferences)
    is preserved and only gains the ``zdr`` key.

    ``provider`` is an optional caller passthrough field reaching this shared
    choke point unvalidated from every call site (chat, streaming, tools and
    binary-media passthrough, and the batch JSONL path). A malformed truthy
    non-mapping value (an int, bool, list, or string) must fail with a named,
    caller-actionable validation error here rather than an opaque ``TypeError``
    from ``dict()`` deep inside provider-transport code (Devin review on #953).

    The "is this agent OpenRouter" check itself goes through
    ``_resolved_openrouter_provider`` rather than a bare ``agent.provider_name``
    comparison, so a misconfigured agent (empty/wrong ``provider_name`` but a
    ``base_url`` that is actually OpenRouter's) still gets pinned instead of
    silently bypassing ZDR enforcement (CodeRabbit review on #953).
    """
    if not _REQUEST_ZDR_ONLY.get() or _resolved_openrouter_provider(agent) != "openrouter":
        return payload
    provider_routing = payload.get("provider")
    if provider_routing is not None and not isinstance(provider_routing, dict):
        raise ValueError("provider must be an object with optional OpenRouter routing keys")
    provider_routing = dict(provider_routing or {})
    provider_routing["zdr"] = True
    return {**payload, "provider": provider_routing}


SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|secret|password)(['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}"),
)

DEFAULT_COMMERCIAL_TARGET_VALUE_KRW = 2_000_000_000
MAX_MODEL_JUDGE_REPLY_CHARACTERS = 32_000
CONTEXTUAL_ORCHESTRATOR_CONTRACT_V1 = "contextual-orchestrator-contract-v1"


@dataclass(frozen=True)
class FastMLSIRMJudgeComponents:
    """Resolved fast-mlsirm symbols used by model verification."""

    judge_cls: type[Any]
    criterion_cls: type[Any]
    format_error: type[Exception]


def _resolve_fast_mlsirm_components() -> FastMLSIRMJudgeComponents | None:
    """Resolve the fast-mlsirm adapter symbols without importing unconditionally."""
    try:
        from fast_mlsirm import ContextualOrchestratorJudge, JudgeCriterion, JudgeFormatError
    except ModuleNotFoundError as exc:
        if exc.name == "fast_mlsirm":
            return None
        raise
    return FastMLSIRMJudgeComponents(ContextualOrchestratorJudge, JudgeCriterion, JudgeFormatError)


@dataclass
class _FastMLSIJudgeAdapter:
    """Adapter that exposes `complete()` for `ContextualOrchestratorJudge`."""

    orchestrator: "TaskOrchestrator"
    text: str
    judge: str
    served_agent_id: str | None = None
    served_model: str | None = None
    served_usage: dict[str, Any] | None = None
    served_output: str | None = None
    mode: str = "auto"
    allowed_agent_ids: set[str] | None = None
    excluded_agent_ids: set[str] | None = None

    @property
    def contextual_orchestrator_contract(self) -> str:
        """Declare the versioned gateway boundary required by fast-mlsirm."""
        return CONTEXTUAL_ORCHESTRATOR_CONTRACT_V1

    @property
    def client(self) -> ModelClient:
        """Expose the existing gateway client capability to fast-mlsirm."""
        return self.orchestrator.client

    def complete(self, messages: list[ChatMessage], mode: str | None = None) -> dict[str, Any]:
        """Return one judge completion through the constrained adapter."""
        if mode is not None and (type(mode) is not str or mode not in {"auto", "route", "conduct"}):
            raise ValueError("mode must be auto, route, or conduct")
        output, served_id, served_model, usage = self.orchestrator._invoke(
            self._agent(),
            messages,
            text=self.text,
            role="judge",
            allowed_agent_ids=self.allowed_agent_ids,
            eligibility_role="verifier",
            excluded_agent_ids=self.excluded_agent_ids,
        )
        return self._completion_payload(
            output, served_id, served_model, usage, self.mode if mode is None else mode
        )

    def complete_structured(
        self,
        messages: list[ChatMessage],
        mode: str | None = None,
        *,
        response_format: dict[str, Any],
    ) -> dict[str, Any]:
        """Route a Judge JSON-schema request through the existing gateway proxy."""
        if mode is not None and (type(mode) is not str or mode not in {"auto", "route", "conduct"}):
            raise ValueError("mode must be auto, route, or conduct")
        if not isinstance(response_format, dict):
            raise TypeError("response_format must be a mapping")
        agent = self._agent()
        request = {
            "model": agent.model,
            "messages": messages,
            "temperature": self.orchestrator.client.temperature,
            "response_format": response_format,
        }
        output_cap = self.orchestrator.client.effective_max_output_tokens(agent)
        if output_cap is not None:
            request["max_tokens"] = output_cap
        effort_profile = self.orchestrator._role_effort_profile("judge")
        if effort_profile is not None:
            request = self.orchestrator.client.apply_effort_profile(
                agent, request, effort_profile
            )
        request["stream"] = False
        response = self.orchestrator.client.proxy_send(
            agent, "chat/completions", request
        )
        # Captured immediately once the provider call itself returns, before
        # _response_content's own content validation gets a chance to raise
        # on a malformed structured response (Devin review on #961): that
        # billed call already happened by this point, and this accounting
        # must survive validation failing on how to interpret its result.
        self.served_agent_id = agent.id
        self.served_model = agent.model
        self.served_usage = (
            response.get("usage") if isinstance(response.get("usage"), dict) else None
        )
        output = ModelClient._response_content(agent, response)
        return self._completion_payload(
            output, agent.id, agent.model, self.served_usage, self.mode if mode is None else mode
        )

    def _completion_payload(
        self,
        output: str,
        served_id: str,
        served_model: str,
        usage: dict[str, Any] | None,
        mode: str,
    ) -> dict[str, Any]:
        """Build the bounded adapter response shared by normal and structured calls."""
        self.served_agent_id = served_id
        self.served_model = served_model
        self.served_usage = usage
        self.served_output = output
        trace = [
            {
                "id": 0,
                "role": "verifier",
                "agent_id": served_id,
                "subtask": "LLM-as-a-Judge evaluation",
                "output": output,
            }
        ]
        if usage is not None:
            trace[0]["usage"] = usage
        return {
            "answer": output,
            "mode": mode,
            "trace": trace,
        }

    def _agent(self) -> ModelAgent:
        return self.orchestrator._agent(self.judge)


def _parse_triage_reply(reply: str) -> bool:
    """Parse one exact ``{"workflow_required": bool}`` triage verdict.

    Rejects oversize replies, duplicate object keys, extra fields, and any
    non-boolean value so a chatty model can never smuggle a decision through.
    Raises ``ValueError`` on every violation; callers fail closed to the
    orchestrated path.
    """
    if not isinstance(reply, str) or len(reply) > MAX_MODEL_JUDGE_REPLY_CHARACTERS:
        raise ValueError("triage response is missing or exceeds the maximum size")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("triage response contains duplicate object keys")
            result[key] = value
        return result

    try:
        parsed = json.loads(reply, object_pairs_hook=reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise ValueError("triage response is not valid JSON") from exc
    if not isinstance(parsed, dict) or set(parsed) != {"workflow_required"}:
        raise ValueError("triage response must contain exactly workflow_required")
    if type(parsed["workflow_required"]) is not bool:
        raise ValueError("workflow_required must be a boolean")
    return parsed["workflow_required"]


def _parse_model_judge_reply(reply: str) -> tuple[str, str]:
    """Parse one exact, duplicate-free model-judge verdict."""
    if not isinstance(reply, str) or len(reply) > MAX_MODEL_JUDGE_REPLY_CHARACTERS:
        raise ValueError("judge response is missing or exceeds the maximum size")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("judge response contains duplicate object keys")
            result[key] = value
        return result

    try:
        decision = json.loads(reply.strip(), object_pairs_hook=reject_duplicate_keys)
    except (json.JSONDecodeError, RecursionError, TypeError):
        raise ValueError("judge response is not valid JSON") from None
    if not isinstance(decision, dict) or set(decision) != {"decision", "reason"}:
        raise ValueError("judge response must match the exact verdict schema")
    decision_value = decision["decision"]
    if not isinstance(decision_value, str) or decision_value not in {"ACCEPT", "REJECT"}:
        raise ValueError("judge decision is not an allowed enum value")
    reason = decision["reason"]
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("judge reason is missing")
    return decision_value, reason.strip()


_AGENT_POOL_INTEGER_MAX = 9_223_372_036_854_775_807


AUTH_SCHEME_RAW_TOKEN = "raw-token"
"""Sentinel ``auth_scheme`` for a provider whose Authorization header carries
the bare credential with no scheme word at all. Bytez documents its API as
``Authorization: <token>`` (https://docs.bytez.com/http-reference/list/models.md)
-- unlike ``Bearer``-style providers, it takes no prefix word before the key.
"""


def format_authorization_header(auth_scheme: str, api_key: str) -> str:
    """Return one provider's Authorization header value for a credential.

    Every provider except the :data:`AUTH_SCHEME_RAW_TOKEN` sentinel sends its
    credential behind a literal scheme word (``Bearer <key>``); that sentinel
    sends the bare credential instead, with no scheme word or separator.
    """
    if auth_scheme == AUTH_SCHEME_RAW_TOKEN:
        return api_key
    return f"{auth_scheme} {api_key}"


@dataclass(frozen=True)
class ModelAgent:
    """Configuration for one model-backed worker in the agent pool."""

    id: str
    model: str
    base_url: str = "mock://local"
    # Legacy field: kept for back-compat. When set, its STRING is treated as the
    # KV credential NAME (never read as an environment variable). Prefer
    # ``credential_key``. See docs/kv-credentials.md.
    api_key_env: str = ""
    credential_key: str = "OPENAI_API_KEY"
    tags: tuple[str, ...] = ()
    priority: int = 0
    disabled: bool = False
    provider_name: str = ""
    provider_exclusions: tuple[str, ...] = ()
    # Explicit KV credential for an authenticated loopback gateway. Keep this
    # separate from ``credential_key`` so mlx:// workers remain keyless.
    local_credential_key: str = ""
    # Authorization header scheme, e.g. "Bearer" (OpenAI-compatible default), or
    # the AUTH_SCHEME_RAW_TOKEN sentinel (Bytez) for a bare, prefix-free
    # credential. See format_authorization_header().
    auth_scheme: str = "Bearer"
    # Provider-published output ceiling for this exact deployment when known.
    max_output_tokens: int | None = None
    # Provider-published shared prompt+output context window when known.
    context_window: int | None = None
    # Optional measured-routing group: agents sharing a canonical group name are
    # one logical model whose members are ordered by observed speed/stability
    # (see model_group.ModelGroupRouter and planning ADR 0032).
    # Empty string means the agent is ungrouped.
    group_name: str = ""
    # ``None`` means provider support is unproven. Opt-in effort profiles then
    # fail closed unless the profile explicitly requests the safe ``omit`` fallback.
    reasoning_effort_supported: bool | None = None
    # Explicit reviewed replica contract. A group never races when this is absent.
    endpoint_equivalence: dict[str, Any] | None = None
    # Provider-declared support for the Chat Completions terminal usage frame.
    stream_usage_supported: bool = False
    # Administrator-owned execution policy; runtime admission is a separate gate.
    model_timeout_seconds: float | None = None
    model_timeout_revision: int = 0

    def __post_init__(self) -> None:
        require_object_name(self.id, "agent.id")
        if self.group_name:
            object.__setattr__(self, "group_name", canonical_group_name(self.group_name))
        if type(self.local_credential_key) is not str:
            raise TypeError("local_credential_key must be a string")
        if self.local_credential_key and urlparse(self.base_url).scheme != "local":
            raise ValueError("local_credential_key requires a local:// gateway URL")
        if not self.auth_scheme or type(self.auth_scheme) is not str:
            raise ValueError("auth_scheme must be a non-empty string")
        for field_name in ("max_output_tokens", "context_window"):
            value = getattr(self, field_name)
            if value is not None and (
                type(value) is not int
                or value <= 0
                or value > _AGENT_POOL_INTEGER_MAX
            ):
                raise TypeError(
                    f"{field_name} must be a positive integer <= {_AGENT_POOL_INTEGER_MAX} or null"
                )
        if self.reasoning_effort_supported is not None and type(self.reasoning_effort_supported) is not bool:
            raise TypeError("reasoning_effort_supported must be true, false, or null")
        if type(self.stream_usage_supported) is not bool:
            raise TypeError("stream_usage_supported must be a boolean")
        if self.model_timeout_seconds is not None:
            value = self.model_timeout_seconds
            if (
                type(value) not in (int, float)
                or not 0 < value <= MAX_MODEL_TIMEOUT_SECONDS
            ):
                raise ValueError(
                    "model_timeout_seconds must be finite positive seconds no greater "
                    f"than {MAX_MODEL_TIMEOUT_SECONDS:g}, or null"
                )
            object.__setattr__(self, "model_timeout_seconds", float(value))
        if type(self.model_timeout_revision) is not int or self.model_timeout_revision < 0:
            raise ValueError("model_timeout_revision must be a non-negative integer")
        if self.endpoint_equivalence is not None:
            contract = EndpointEquivalenceContract(**self.endpoint_equivalence)
            object.__setattr__(self, "endpoint_equivalence", dict(contract.__dict__))

    def to_config(self) -> dict[str, Any]:
        """Round-trippable agent configuration (from_dict(to_config(a)) == a)."""
        return {
            "id": self.id,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "credential_key": self.credential_key,
            "tags": list(self.tags),
            "priority": self.priority,
            "disabled": self.disabled,
            "provider_name": self.provider_name,
            "provider_exclusions": list(self.provider_exclusions),
            "local_credential_key": self.local_credential_key,
            "auth_scheme": self.auth_scheme,
            "max_output_tokens": self.max_output_tokens,
            "context_window": self.context_window,
            "group_name": self.group_name,
            "reasoning_effort_supported": self.reasoning_effort_supported,
            "endpoint_equivalence": self.endpoint_equivalence,
            "stream_usage_supported": self.stream_usage_supported,
            "model_timeout_seconds": self.model_timeout_seconds,
            "model_timeout_revision": self.model_timeout_revision,
        }

    @property
    def credential_name(self) -> str:
        """KV credential name for this agent's provider secret.

        Back-compat: a legacy ``api_key_env`` value is treated as the credential
        NAME (its string), not as an environment variable to read. Otherwise the
        modern ``credential_key`` is used.
        """
        return self.api_key_env or self.credential_key

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ModelAgent":  # pragma: no cover
        """Build an agent from JSON configuration with naming validation."""
        require_object_name(value["id"], "agent.id")
        return cls(
            id=value["id"],
            model=value["model"],
            base_url=value.get("base_url", "mock://local"),
            api_key_env=value.get("api_key_env", ""),
            credential_key=value.get("credential_key", "OPENAI_API_KEY"),
            tags=tuple(value.get("tags", ())),
            priority=int(value.get("priority", 0)),
            disabled=(
                value.get("disabled", False)
                if type(value.get("disabled", False)) is bool
                else True
            ),
            provider_name=value.get("provider_name", ""),
            provider_exclusions=tuple(value.get("provider_exclusions", value.get("provider_exclusion", ()))),
            local_credential_key=value.get("local_credential_key", ""),
            auth_scheme=value.get("auth_scheme", "Bearer"),
            max_output_tokens=value.get("max_output_tokens"),
            context_window=value.get("context_window"),
            group_name=value.get("group_name", ""),
            reasoning_effort_supported=value.get("reasoning_effort_supported"),
            endpoint_equivalence=value.get("endpoint_equivalence"),
            stream_usage_supported=value.get("stream_usage_supported", False),
            model_timeout_seconds=value.get("model_timeout_seconds"),
            model_timeout_revision=value.get("model_timeout_revision", 0),
        )


def agent_proves_reasoning_effort_support(agent: ModelAgent) -> bool:
    """Return whether ``agent`` has proven native ``reasoning_effort`` support.

    True only when the agent explicitly declares ``reasoning_effort_supported:
    true``, or when the agent is an in-process ``mock://`` harness agent (used
    by tests and evaluation, where support is trivially true). Ordinary
    real-provider agents -- including every shipped example config and every
    auto-discovered agent, neither of which set ``reasoning_effort_supported``
    today -- default to unproven (``None``) and are therefore NOT eligible
    until an operator explicitly marks per-agent support. See ADR 0021
    (``docs/planning/adrs/0021-reasoning-effort-profiles.md``): "An unknown
    provider fails closed unless the operator explicitly picks the omit
    fallback."
    """
    return agent.reasoning_effort_supported is True or (
        agent.reasoning_effort_supported is None and agent.base_url.startswith("mock://")
    )


def _eligible_role_effort_candidates(
    candidates: list[ModelAgent],
    profile: ReasoningEffortProfile | None,
) -> list[ModelAgent]:
    """Narrow ranked candidates to agents that prove reasoning-effort support.

    A profile that fails closed (``unsupported_provider_fallback`` other than
    ``"omit"``) must never hand ``apply_effort_profile`` an agent whose
    support is unproven -- that raises ``EffortProfileError``. Some call
    paths (``_invoke``'s generic tool-failure classification) already
    recover from that error by failing over to the next candidate, but
    others (``stream_route``, ``batch_route``, structured-synthesis
    passthrough) call the provider directly with no such recovery, so this
    filter is what keeps a mixed pool safe everywhere: only proven agents
    are even offered as the primary or a failover candidate. Falls back to
    the unfiltered candidates when none of them prove support (e.g. the
    pool's only supporting agent was excluded by a required tag or
    free-only filter upstream), so that edge case still gets an attempt and
    a clear failure/failover instead of a silently emptied candidate list.
    Mirrors the filter ``TaskOrchestrator.proxy_completion`` already applies
    for its own caller-supplied effort profile.
    """
    if profile is None or profile.unsupported_provider_fallback == "omit":
        return candidates
    supported = [
        candidate for candidate in candidates
        if agent_proves_reasoning_effort_support(candidate)
    ]
    return supported or candidates


def _is_general_chat_agent(agent: ModelAgent) -> bool:
    """Apply persisted provider capability tags before model-name fallback."""
    return "structured:blocked" not in agent.tags and is_general_chat_candidate(
        agent.model,
        capabilities=(
            tag.split(":", 1)[1]
            for tag in agent.tags
            if tag.startswith("capability:")
        ),
        output_modalities=(
            tag.split(":", 1)[1]
            for tag in agent.tags
            if tag.startswith("output:")
        ),
    )


def _validate_batch_results(
    requests: Mapping[str, list[ChatMessage]],
    results: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Reject incomplete batch output before it can become an accepted run."""
    if not isinstance(results, Mapping):
        raise TypeError("batch provider returned an invalid result map")
    if set(requests) != set(results):
        raise RuntimeError(
            "batch provider returned an incomplete or unexpected result set "
            f"(requested={len(requests)}, received={len(results)})"
        )
    invalid_count = sum(
        not isinstance(result, Mapping) or not isinstance(result.get("content"), str)
        for result in results.values()
    )
    if invalid_count:
        raise RuntimeError(
            f"batch provider returned {invalid_count} result(s) without assistant content"
        )
    return {custom_id: dict(result) for custom_id, result in results.items()}


@dataclass(frozen=True)
class WorkflowStep:
    """One visible step in a conducted orchestration workflow."""

    id: int
    role: str
    agent_id: str
    subtask: str
    access: tuple[int, ...] = ()
    latency_ms: float | None = None
    output: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize the workflow step for API and trace responses."""
        return {
            "id": self.id,
            "role": self.role,
            "agent_id": self.agent_id,
            "subtask": self.subtask,
            "access": list(self.access),
            "latency_ms": self.latency_ms,
            "output": self.output,
        }


@dataclass(frozen=True)
class OrchestrationPolicy:
    """Policy knobs that govern routing, verification, and admin visibility.

    Route-vs-conduct selection is evidence-based: one exact-schema model
    triage call (cached by content hash) replaces the former keyword-hint and
    character-length rules, which were hand-tuned heuristics with no
    literature or measured grounding.
    """

    route_p95_seconds: float = 2.5
    # Real-time answer judging on single-shot route paths. Verdicts feed the
    # quality ledger so measured accuracy steers subsequent routing.
    realtime_judge: bool = True
    verifier_required: bool = True
    # Conductor-style planning (arXiv:2512.04388): "generated" asks the planner model to
    # emit the workflow (subtasks, worker assignment, access lists); "template" keeps the
    # fixed 4-step plan. Generated plans that fail validation fall back to the template.
    workflow_planning: str = "template"
    # Validation bound for *generated* plans (prompt and parser both read it).
    # Origin: a product decision, not a paper value. The fixed template needs
    # four steps (thinker, worker, verifier, synthesizer); six leaves a
    # generated plan room for one extra worker and one repair/verify step
    # without letting the planner emit unbounded fan-out. It is deliberately
    # NOT the Fugu-Ultra report's "up to 5 steps" (arXiv:2606.21228 S3.2.3),
    # which is a training setting for that report's learned conductor, nor the
    # effort catalog's 4 (``reasoning_effort_profile``), which bounds
    # role compute under an explicit effort profile. Administrators change it
    # through OrchestrationPolicy; ablation of the value belongs to the #568
    # equal-budget lane, not to a test fixture.
    max_workflow_steps: int = 6
    # Verifier verdicts are structured model judgments. Keyword matching is intentionally
    # unsupported: it cannot handle negation, language, or a report that quotes a risk.
    verifier_judge: str = "model"

    def __post_init__(self) -> None:
        if self.verifier_judge != "model":
            raise ValueError("keyword-based verifier_judge modes are unsupported; use 'model'")
        if isinstance(self.realtime_judge, bool) is False:
            raise ValueError("realtime_judge must be a boolean")

    def as_dict(self) -> dict[str, Any]:
        """Return the API-safe policy snapshot for workflow records."""
        return {
            "route_p95_seconds": self.route_p95_seconds,
            "realtime_judge": self.realtime_judge,
            "verifier_required": self.verifier_required,
            "workflow_planning": self.workflow_planning,
            "verifier_judge": self.verifier_judge,
            "max_workflow_steps": self.max_workflow_steps,
            "workflow_steps": ["thinker", "worker", "verifier", "synthesizer"],
            "supported_locales": ["en", "ko"],
        }


# HTTP statuses worth retrying: request timeout, conflict, too-early, rate limit,
# and the standard upstream/gateway failures. Everything else (400/401/403/404 ...)
# is a caller or configuration error and must not be retried.
TRANSIENT_HTTP_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})
LOCAL_PROVIDER_SCHEMES = frozenset({"mlx", "local"})
LOCAL_PROVIDER_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

REQUEST_OUTCOME_ASSOCIATIONS_FIELD = "request_outcome_associations"
"""Reserved association field retained from PR #1126; export uses observations."""

ROUTE_DECISION_LATENCY_FIELD = "decision_latency_ms"
"""Trace-row field for the decision-only interval (#1110).

Distinct from ``latency_ms``: selection/queueing/write cost only, never
upstream generation. Until durable acknowledgement exists, report unavailable.
"""


def _http_error_payload(error: urllib.error.HTTPError) -> dict[str, Any] | None:
    """Read and cache one bounded JSON error body for downstream classifiers."""
    cache_key = "_contextual_orchestrator_http_error_payload"
    missing = object()
    cached = getattr(error, cache_key, missing)
    if cached is not missing:
        return cached if isinstance(cached, dict) else None
    try:
        payload = json.loads(provider_error_body(error).decode("utf-8"))
    except (
        AttributeError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
    ):
        payload = None
    result = payload if isinstance(payload, dict) else None
    try:
        setattr(error, cache_key, result)
    except (AttributeError, TypeError):  # pragma: no cover - HTTPError is mutable
        pass
    return result


def _is_tool_execution_stopped(error: urllib.error.HTTPError) -> bool:
    """Return whether an HTTP error carries the terminal tool-stop contract."""
    cache_key = "_contextual_orchestrator_tool_execution_stopped"
    cached = getattr(error, cache_key, None)
    if isinstance(cached, bool):
        return cached
    payload = _http_error_payload(error)
    details = payload.get("error") if isinstance(payload, dict) else None
    result = isinstance(details, dict) and details.get("code") == "tool_execution_stopped"
    try:
        setattr(error, cache_key, result)
    except (AttributeError, TypeError):  # pragma: no cover - HTTPError is mutable
        pass
    return result


def _provider_error_payload(error: urllib.error.HTTPError) -> dict[str, Any] | None:
    """Keep the older provider-error helper aligned with the shared cache."""
    return _http_error_payload(error)


def _is_provider_tool_description_limit_error(error: urllib.error.HTTPError) -> bool:
    """Recognize the provider capability error that is safe to fail over."""
    if error.code != 400:
        return False
    payload = _provider_error_payload(error)
    details = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(details, str):
        return _PROVIDER_TOOL_DESCRIPTION_LIMIT_MESSAGE in details.casefold()
    return (
        isinstance(details, dict)
        and details.get("code") == "invalid_tools"
        and details.get("message") == _PROVIDER_TOOL_DESCRIPTION_LIMIT_MESSAGE
    )


def _is_oversized_tool_description_error(error: urllib.error.HTTPError) -> bool:
    """Recognize the provider-specific 1,024-character tool-description cap."""
    if error.code != 400:
        return False
    payload = _http_error_payload(error)
    details = payload.get("error") if isinstance(payload, dict) else None
    message = (
        details.get("message")
        if isinstance(details, dict)
        else details
        if isinstance(details, str)
        else None
    )
    return (
        (isinstance(details, str) or (
            isinstance(details, dict) and details.get("code") == "invalid_tools"
        ))
        and isinstance(message, str)
        and "tool.function.description" in message.casefold()
        and "1024" in message
    )


# Positive discovery evidence that a model accepts only one tool call per turn;
# emitted by ``model_discovery.discovery_tool_call_tags`` and round-tripped by the
# provider catalog store. Its absence says nothing (ADR-0035 capability tags are
# positive declarations only), so selection never infers a limit from a missing tag.
SINGLE_TOOL_CALL_EVIDENCE_TAG = "tool_call:single"

# Discovery-stamped entitlement for chat requests that carry image_url
# parts. Prefer this over the legacy operator "vision" capability tag;
# both are accepted by _agent_supports_image_input so durable pools that
# only recorded "vision" keep working.
IMAGE_INPUT_EVIDENCE_TAG = "input:image"
LEGACY_VISION_CAPABILITY_TAG = "vision"


def _request_requires_parallel_tool_calls(body: Mapping[str, Any]) -> bool:
    """Return whether a chat body needs a model that accepts several tool calls at once.

    The only provider evidence behind ``tool_call:single`` is the discovery
    probe (``model_discovery.probe_discovered_model_tool_call_capability``): a
    request carrying several tools with ``parallel_tool_calls: true`` was
    rejected with the single-call 400 that ``_is_single_tool_call_limit_error``
    recognizes. This predicate therefore matches that shape and nothing wider:
    two or more tools without an explicit opt-out (the OpenAI default allows
    parallel calls), or an explicit ``parallel_tool_calls: true`` even with one
    tool. A single tool without the flag, or any request with
    ``parallel_tool_calls: false``, is not known to be rejected and stays on
    the existing failover path rather than being excluded on a guess.
    """
    tools = body.get("tools")
    if not isinstance(tools, list) or not tools:
        return False
    parallel_tool_calls = body.get("parallel_tool_calls")
    if parallel_tool_calls is False:
        return False
    return parallel_tool_calls is True or len(tools) > 1


def _is_single_tool_call_limit_error(error: urllib.error.HTTPError) -> bool:
    """Recognize a model that rejects a request making more than one tool call.

    Some NVIDIA NIM-hosted models (observed: a vision-capable Llama variant)
    reject any turn with more than one tool call, wrapping the sentence in a
    longer agent-prefixed message under the generic ``invalid_request_error``
    code rather than a distinct error code -- unlike the tool-description
    limit above, the message text is the only reliable signal here.
    """
    if error.code != 400:
        return False
    payload = _http_error_payload(error)
    details = payload.get("error") if isinstance(payload, dict) else None
    message = (
        details.get("message")
        if isinstance(details, dict)
        else details
        if isinstance(details, str)
        else None
    )
    return isinstance(message, str) and _SINGLE_TOOL_CALL_LIMIT_MESSAGE in message.casefold()


def _is_context_length_exceeded_error(error: urllib.error.HTTPError) -> bool:
    """Recognize a prompt that overflows the model's context window.

    A 400 rejection for exceeding the context window is a request-size
    rejection like the 413 and tool-description-limit cases above, not a
    generic caller error: the same prompt commonly fits the next
    capability-matched agent's larger context window, so it must fail over
    rather than count against the rejecting agent's health (Ong et al., 2024).

    Three provider shapes are recognized, in order:

    1. OpenAI's structured shape: ``error.code == "context_length_exceeded"``,
       regardless of message text.
    2. A message-text signal observed on OpenAI, vLLM, OpenRouter, and NVIDIA
       NIM passthrough responses, e.g. "This model's maximum context length
       is 8192 tokens. However, you requested 9001 tokens ...": the message
       (dict ``message`` or bare string body), casefolded, contains
       ``"maximum context length"``, or contains both ``"context length"``
       and ``"tokens"``.
    3. A message-text signal observed on Anthropic-compatible proxies:
       ``error.type == "invalid_request_error"`` with a message containing
       ``"prompt is too long"``.
    """
    if error.code != 400:
        return False
    payload = _http_error_payload(error)
    details = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(details, dict) and details.get("code") == "context_length_exceeded":
        return True
    message = (
        details.get("message")
        if isinstance(details, dict)
        else details
        if isinstance(details, str)
        else None
    )
    if not isinstance(message, str):
        return False
    folded = message.casefold()
    if "maximum context length" in folded:
        return True
    if "context length" in folded and "tokens" in folded:
        return True
    if isinstance(details, dict) and details.get("type") == "invalid_request_error":
        if "prompt is too long" in folded:
            return True
    return False


def _provider_tool_execution_stopped(agent: ModelAgent) -> ToolFallbackStoppedError:
    """Convert the provider's terminal tool-stop contract to the public safe error."""
    decision = classify_tool_failure(
        ToolExecutionError(
            "provider reported terminal tool execution state",
            tool_name="provider_tool_runtime",
            kind=ToolFailureKind.TRANSPORT_ERROR,
            outcome_unknown=True,
        )
    )
    return ToolFallbackStoppedError(agent.id, decision)


def _is_local_provider_url(base_url: str) -> bool:
    """Return whether a provider uses the explicit loopback-only local scheme."""
    parsed = urlparse(base_url)
    try:
        parsed.port
    except ValueError:
        return False
    return parsed.scheme in LOCAL_PROVIDER_SCHEMES and parsed.hostname in LOCAL_PROVIDER_HOSTS


def _is_direct_mlx_provider_url(base_url: str) -> bool:
    """Return whether a loopback provider is the direct mlx-lm transport."""
    return _is_local_provider_url(base_url) and urlparse(base_url).scheme == "mlx"


def _provider_credential_name(agent: ModelAgent) -> str | None:
    """Return the credential name allowed for this provider transport."""
    if not _is_local_provider_url(agent.base_url):
        return agent.credential_name
    # mlx-lm is intentionally keyless; only the explicit local:// gateway
    # transport may opt into a separately named loopback bearer credential.
    if urlparse(agent.base_url).scheme != "local":
        return None
    return agent.local_credential_key or None


def _provider_credential(agent: ModelAgent) -> str | None:
    """Resolve the transport-specific credential from the KV registry."""
    name = _provider_credential_name(agent)
    return get_credential(name) if name else None


class _LocalProviderState:
    """Coordinate model switching and bounded concurrency for one local endpoint."""

    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.active_model: str | None = None
        self.active = 0
        self.capacity = 1


_LOCAL_PROVIDER_STATES: dict[str, _LocalProviderState] = {}
_LOCAL_PROVIDER_STATES_GUARD = threading.Lock()


def _local_provider_state(base_url: str) -> _LocalProviderState:
    """Return the shared in-process coordinator for one loopback provider endpoint."""
    parsed = urlparse(base_url)
    key = urlunsplit(("http", (parsed.netloc or base_url).lower(), parsed.path.rstrip("/"), "", ""))
    with _LOCAL_PROVIDER_STATES_GUARD:
        return _LOCAL_PROVIDER_STATES.setdefault(key, _LocalProviderState())


class _LocalProviderAdmissionTimeout(TimeoutError):
    """A local slot expired before any upstream request could be sent."""


class _AdministratorModelTimeout(TimeoutError):
    """An explicit administrator-owned end-to-end model deadline expired."""


def _model_deadline(timeout: float | None) -> float | None:
    """Return one monotonic deadline for an explicit model timeout."""
    return None if timeout is None else time.monotonic() + float(timeout)


def _remaining_model_timeout(deadline: float | None) -> float | None:
    """Return remaining model time or raise the distinct administrator timeout."""
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _AdministratorModelTimeout("administrator model timeout elapsed")
    return remaining


def _administrator_timeout_error(
    agent: ModelAgent, transport: str
) -> ProviderUpstreamError:
    """Build the caller-safe non-retryable administrator-timeout surface."""
    return ProviderUpstreamError(
        agent_id=agent.id,
        model=agent.model,
        error_code="model_timeout",
        message="administrator-configured model timeout elapsed",
        client_status=504,
        provider_status=None,
        retryable=False,
        transport=transport,
    )


def _typed_attempt_entry(
    agent_id: str,
    model: str,
    classified: ProviderUpstreamError,
    *,
    request_too_large: bool = False,
) -> dict[str, Any]:
    """Build one typed per-attempt evidence entry shared by every fallback path.

    The structured-synthesis candidate loop
    (``_orchestrated_provider_completion``), the single-worker streaming
    fallback (``stream_route``), and non-streaming ``route_once``'s shared
    ``_invoke`` failover loop call this so a failed attempt carries the same
    fixed ``outcome`` vocabulary: ``request_too_large``,
    ``retryable_transport``, ``deadline_exceeded`` (the administrator model
    timeout introduced by PR #1053's ``model_timeout`` error code -- reused
    here rather than inventing a second vocabulary), or ``fail_closed``.
    """
    if request_too_large:
        outcome = "request_too_large"
    elif classified.error_code == "model_timeout":
        outcome = "deadline_exceeded"
    elif classified.retryable:
        outcome = "retryable_transport"
    else:
        outcome = "fail_closed"
    return {
        "agent_id": agent_id,
        "model": model,
        "outcome": outcome,
        "error_code": classified.error_code,
        "provider_status": classified.provider_status,
        "retryable": classified.retryable,
        "transport": classified.transport,
    }


def _append_tool_stop_route_attempt(
    attempts: list[dict[str, Any]],
    agent: ModelAgent,
    *,
    transport: str,
) -> None:
    """Record a terminal tool stop without borrowing a provider error code.

    ``_append_typed_route_failure`` classifies through the provider taxonomy
    and would label this attempt ``api_error``. The tool decision already
    rides on the enclosing ``ToolFallbackStoppedError``.
    """
    attempts.append(
        {
            "agent_id": agent.id,
            "model": agent.model,
            "outcome": "fail_closed",
            "retryable": False,
            "transport": transport,
        }
    )


def _append_typed_route_failure(
    attempts: list[dict[str, Any]],
    agent: ModelAgent,
    exc: BaseException,
    *,
    transport: str,
    request_too_large: bool = False,
) -> None:
    """Record one failed candidate before ``_invoke`` advances to the next agent."""
    classified = (
        exc
        if isinstance(exc, ProviderUpstreamError)
        else classify_provider_failure(
            exc,
            agent_id=agent.id,
            model=agent.model,
            transport=transport,
        )
    )
    if not isinstance(classified, ProviderUpstreamError):
        return
    attempts.append(
        _typed_attempt_entry(
            agent.id,
            agent.model,
            classified,
            request_too_large=request_too_large,
        )
    )


def _route_evidence_payload(
    *,
    eligible_agent_ids: list[str],
    attempted: list[dict[str, Any]],
    terminal_reason: str,
    stage: str | None = None,
) -> dict[str, Any]:
    """Build the shared ``orchestration.route`` evidence object."""
    evidence = {
        "eligible_agent_ids": eligible_agent_ids,
        "attempted": list(attempted),
        "terminal_reason": terminal_reason,
    }
    if stage is not None:
        evidence["stage"] = stage
    return evidence


def _attach_route_evidence_to_upstream_error(
    error: ProviderUpstreamError,
    route_payload: dict[str, Any],
) -> ProviderUpstreamError:
    """Attach ``route_payload`` without erasing a concrete error subtype."""
    error.extra_detail = {**error.extra_detail, "route": route_payload}
    return error


def _attach_route_evidence_to_response_error(
    error: ProviderResponseError,
    route_payload: dict[str, Any],
) -> ProviderResponseError:
    """Attach route evidence while preserving fail-closed response taxonomy."""
    error.detail = {**error.detail, "route": route_payload}
    return error


def _attach_route_evidence_to_tool_stop(
    error: ToolFallbackStoppedError,
    route_payload: dict[str, Any],
) -> ToolFallbackStoppedError:
    """Attach route evidence without converting a tool stop into another error."""
    error.detail = {**error.detail, "route": route_payload}
    return error


@contextmanager
def _local_provider_slot(
    agent: ModelAgent,
    capacity: int,
    timeout: float | None,
):
    """Bound local requests and serialize model switches on a shared endpoint."""
    if not _is_local_provider_url(agent.base_url):
        yield
        return

    state = _local_provider_state(agent.base_url)
    deadline = None if timeout is None else time.monotonic() + max(float(timeout), 0.0)
    with state.condition:
        while True:
            if state.active == 0:
                state.active_model = agent.model
                state.capacity = capacity
            elif state.active_model == agent.model:
                state.capacity = min(state.capacity, capacity)

            if state.active_model == agent.model and state.active < state.capacity:
                state.active += 1
                break

            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise _LocalProviderAdmissionTimeout("local provider endpoint is busy past its request deadline")
            state.condition.wait(remaining)

    try:
        yield
    finally:
        with state.condition:
            state.active -= 1
            if state.active == 0:
                state.active_model = None
                state.capacity = 1
            state.condition.notify_all()


def _responses_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "".join(parts)


def _responses_to_chat_payload(request: dict[str, Any]) -> dict[str, Any]:
    # ADR 0002: keep Codex Responses compatibility at the public control-plane
    # boundary; mlx-lm remains a local Chat Completions worker provider.
    messages: list[dict[str, Any]] = []
    instructions = _responses_text(request.get("instructions"))
    if instructions:
        messages.append({"role": "system", "content": instructions})

    raw_input = request.get("input", "")
    if isinstance(raw_input, list):
        items = raw_input
    elif isinstance(raw_input, str):
        items = [{"type": "message", "role": "user", "content": raw_input}]
    else:
        raise ValueError("local Responses input must be a string or item list")
    for item in items:
        if isinstance(item, str):
            messages.append({"role": "user", "content": item})
            continue
        if not isinstance(item, dict):
            raise ValueError("local Responses input items must be objects")
        item_type = item.get("type", "message")
        if item_type == "message":
            role = item.get("role", "user")
            if role == "developer":
                role = "system"
            if role not in {"system", "user", "assistant"}:
                raise ValueError(f"unsupported local Responses message role: {role}")
            raw_content = item.get("content")
            content: str | list[dict[str, Any]] = _responses_text(raw_content)
            if isinstance(raw_content, list):
                parts: list[dict[str, Any]] = []
                for part in raw_content:
                    if not isinstance(part, dict):
                        continue
                    part_type = part.get("type")
                    if part_type in {"input_text", "output_text", "text"} and isinstance(
                        part.get("text"), str
                    ):
                        parts.append({"type": "text", "text": part["text"]})
                    elif part_type in {"input_image", "image_url"}:
                        image_url = part.get("image_url")
                        if isinstance(image_url, str):
                            image_url = {
                                "url": image_url,
                                **(
                                    {"detail": part["detail"]}
                                    if isinstance(part.get("detail"), str)
                                    else {}
                                ),
                            }
                        if isinstance(image_url, dict):
                            parts.append({"type": "image_url", "image_url": image_url})
                if any(part.get("type") == "image_url" for part in parts):
                    content = parts
            if content:
                messages.append({"role": role, "content": content})
        elif item_type == "function_call_output":
            messages.append({
                "role": "tool",
                "tool_call_id": str(item.get("call_id", "")),
                "content": _responses_text(item.get("output", item.get("content", ""))),
            })
        elif item_type == "function_call":
            messages.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": str(item.get("call_id", "")),
                    "type": "function",
                    "function": {
                        "name": str(item.get("name", "")),
                        "arguments": str(item.get("arguments", "{}")),
                    },
                }],
            })
        elif item_type in {"input_file", "reasoning", "item_reference"}:
            continue
        else:
            raise ValueError(f"unsupported local Responses input item: {item_type}")

    payload: dict[str, Any] = {
        "model": request.get("model", "local-model"),
        "messages": messages,
        "stream": False,
    }
    for key in (
        "temperature", "top_p", "max_tokens", "stop", "seed", "presence_penalty",
        "frequency_penalty", "logit_bias", "logprobs", "top_logprobs", "user",
        "parallel_tool_calls", "tool_choice",
    ):
        if key in request:
            payload[key] = request[key]
    if "max_output_tokens" in request and "max_tokens" not in payload:
        payload["max_tokens"] = request["max_output_tokens"]

    response_format = _responses_text_format_to_chat_response_format(request.get("text"))
    if response_format is None and isinstance(request.get("response_format"), dict):
        response_format = request["response_format"]
    if response_format is not None:
        payload["response_format"] = response_format

    tools: list[dict[str, Any]] = []
    for tool in request.get("tools") or []:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        function = {
            key: tool[key]
            for key in ("name", "description", "parameters", "strict")
            if key in tool
        }
        tools.append({"type": "function", "function": function})
    if tools:
        payload["tools"] = tools

    tool_choice = payload.get("tool_choice")
    if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
        payload["tool_choice"] = {
            "type": "function",
            "function": {"name": tool_choice.get("name", "")},
        }
    return payload


def _responses_text_format_to_chat_response_format(
    text: Any,
) -> dict[str, Any] | None:
    """Translate a validated Responses text format for workflow evidence calls."""
    if not isinstance(text, dict) or not isinstance(text.get("format"), dict):
        return None
    fmt = text["format"]
    if fmt.get("type") in {"text", "json_object"}:
        return {"type": fmt["type"]}
    if fmt.get("type") != "json_schema":
        return None
    return {
        "type": "json_schema",
        "json_schema": {
            key: fmt[key]
            for key in ("name", "schema", "description", "strict")
            if key in fmt
        },
    }


def _canonical_provider_usage(
    usage: dict[str, Any], *, responses: bool
) -> dict[str, Any]:
    """Copy provider usage with aliases consumed by existing spend accounting."""
    canonical = dict(usage)
    if responses:
        for responses_key, chat_key in (
            ("input_tokens", "prompt_tokens"),
            ("output_tokens", "completion_tokens"),
        ):
            value = canonical.get(responses_key)
            if type(value) is int and value >= 0:
                canonical.setdefault(chat_key, value)
    return canonical


def _chat_to_responses_payload(data: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") if isinstance(choice, dict) else {}
    message = message if isinstance(message, dict) else {}
    content = message.get("content")
    if not isinstance(content, str):
        content = message.get("reasoning") if isinstance(message.get("reasoning"), str) else ""

    output: list[dict[str, Any]] = []
    if content or not message.get("tool_calls"):
        output.append({
            "id": f"msg_{uuid.uuid4().hex}",
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": content, "annotations": []}],
        })
    for tool_call in message.get("tool_calls", []):
        if not isinstance(tool_call, dict):
            continue
        function = tool_call.get("function") or {}
        output.append({
            "id": f"fc_{tool_call.get('id', uuid.uuid4().hex)}",
            "type": "function_call",
            "status": "completed",
            "call_id": str(tool_call.get("id", uuid.uuid4().hex)),
            "name": str(function.get("name", "")),
            "arguments": str(function.get("arguments", "{}")),
        })

    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    input_tokens = int(usage.get("prompt_tokens", 0) or 0)
    output_tokens = int(usage.get("completion_tokens", 0) or 0)
    response: dict[str, Any] = {
        "id": f"resp_{data.get('id', uuid.uuid4().hex)}",
        "object": "response",
        "created_at": int(data.get("created", time.time())),
        "model": data.get("model", request.get("model", "local-model")),
        "output": output,
        "output_text": content,
        "status": "completed" if choice.get("finish_reason") != "length" else "incomplete",
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": int(usage.get("total_tokens", input_tokens + output_tokens) or 0),
        },
    }
    if isinstance(reqÛ]µçkh‘éì¶»§q«^t€€€€€€€€€€€€€€€€‰É•Ù¥•Ý•ÈˆèÉ•Ù¥•Ý•È°(€€€€€€€€€€€€€€€€‰Í½ÕÉ•ÌˆèÍ½ÕÉ•Ì°(€€€€€€€€€€€€€€€€‰ÉÕ¹Ñ¥µ•}•¹‘Á½¥¹ÑÌˆèÉÕ¹Ñ¥µ•}•¹‘Á½¥¹ÑÌ°(€€€€€€€€€€€€€€€€‰•Ù¥‘•¹•}ÑåÁ”ˆè•Ù¥‘•¹•}ÑåÁ”°(€€€€€€€€€€€€€€€€‰½µÁ±•Ñ¥½¹}ÍÑ…Ñ”ˆè½µÁ±•Ñ¥½¹}ÍÑ…Ñ”°(€€€€€€€€€€€€€€€€‰•Ù¥‘•¹”ˆè•Ù¥‘•¹”°(€€€€€€€€€€€€€€€€‰‘¥±¥•¹•}ÅÕ•ÍÑ¥½¸ˆè‘¥±¥•¹•}ÅÕ•ÍÑ¥½¸°(€€€€€€€€€€€€€€€€‰¹•áÑ}…Ñ¥½¸ˆè¹•áÑ}…Ñ¥½¸°(€€€€€€€€€€€ô((€€€€€€€½¹É•Ñ•}‰±½­•ÉÌ€ô±¥ÍÐ (€€€€€€€€€€€‘¥Ð¹™É½µ­•åÌ (€€€€€€€€€€€€€€€ÁÕÉ¡…Í•l‰½¹É•Ñ•}‰±½­•ÉÌ‰t(€€€€€€€€€€€€€€€€¬ÁÉ½Á½Í…±l‰½¹É•Ñ•}‰±½­•ÉÌ‰t(€€€€€€€€€€€€€€€€¬½µÁ±•Ñ¥½¹l‰½¹É•Ñ•}‰±½­•ÉÌ‰t(€€€€€€€€€€€€€€€€¬‘•µ½l‰½¹É•Ñ•}‰±½­•ÉÌ‰t(€€€€€€€€€€€€€€€€¬‰Õå•É}Ý½É­™±½Ýl‰½¹É•Ñ•}‰±½­•ÉÌ‰t(€€€€€€€€€€€€¤(€€€€€€€€¤(€€€€€€€±½…±}ÉÕ¹Ñ¥µ•}ÍÑ…Ñ”€ô€ (€€€€€€€€€€€€‰‰±½­•ˆ(€€€€€€€€€€€¥˜ÁÕÉ¡…Í•l‰ÁÕÉ¡…Í•}…ÁÁÉ½Ù…±}ÍÑ…ÑÕÌ‰t€ôô€‰½µµ•É¥…±}ÁÕÉ¡…Í•}…ÁÁÉ½Ù…±}‰±½­•ˆ(€€€€€€€€€€€½ÈÁÉ½Á½Í…±l‰ÁÉ½Á½Í…±}ÍÑ…ÑÕÌ‰t€ôô€‰½µµ•É¥…±}ÁÉ½Á½Í…±}‰±½­•ˆ(€€€€€€€€€€€½È½µÁ±•Ñ¥½¹l‰½µÁ±•Ñ¥½¹}ÍÑ…ÑÕÌ‰t€ôô€‰½µµ•É¥…±}½µÁ±•Ñ¥½¹}‰±½­•ˆ(€€€€€€€€€€€½È‘•µ½l‰‘•µ½}ÍÑ…ÑÕÌ‰t€ôô€‰½µµ•É¥…±}‘•µ½}‰±½­•ˆ(€€€€€€€€€€€½È‰Õå•É}Ý½É­™±½Ýl‰Ý½É­™±½Ý}ÍÑ…ÑÕÌ‰t€ôô€‰‰Õå•É}…•ÁÑ…¹•}Ý½É­™±½Ý}‰±½­•ˆ(€€€€€€€€€€€½È½¹É•Ñ•}‰±½­•ÉÌ(€€€€€€€€€€€•±Í”€‰É•…‘äˆ(€€€€€€€€¤(€€€€€€€‘¥±¥•¹•}Í•Ñ¥½¹Ì€ôl(€€€€€€€€€€€Í•Ñ¥½¸ (€€€€€€€€€€€€€€€€‰ÁÕÉ¡…Í•}…ÁÁÉ½Ù…±}Á…­•Ðˆ°(€€€€€€€€€€€€€€€€‰AÕÉ¡…Í”…ÁÁÉ½Ù…°Á…­•Ðˆ°(€€€€€€€€€€€€€€€€‰AÕÉ¡…Í”½µµ¥ÑÑ•”ˆ°(€€€€€€€€€€€€€€€l‰‘½Ì½½µµ•É¥…±}ÁÕÉ¡…Í•}…ÁÁÉ½Ù…±}Á…­•Ð¹µˆ°€ˆ½…Á¤½ØÄ½½µµ•É¥…±}ÁÕÉ¡…Í•}…ÁÁÉ½Ù…±}Á…­•ÑÌ½±…Ñ•ÍÐ‰t°(€€€€€€€€€€€€€€€lˆ½…Á¤½ØÄ½½µµ•É¥…±}ÁÕÉ¡…Í•}…ÁÁÉ½Ù…±}Á…­•ÑÌ½±…Ñ•ÍÐˆ°€ˆ½…Á¤½ØÄ½½µµ•É¥…±}ÁÉ½Á½Í…±}Á…­•ÑÌ½±…Ñ•ÍÐ‰t°(€€€€€€€€€€€€€€€€‰É•Á½Í¥Ñ½Éå}…¹‘}ÉÕ¹Ñ¥µ•}…ÉÑ¥™…Ðˆ°(€€€€€€€€€€€€€€€±½…±}ÉÕ¹Ñ¥µ•}ÍÑ…Ñ”¥˜¡…Í}™¥±” ‰‘½Ì½½µµ•É¥…±}ÁÕÉ¡…Í•}…ÁÁÉ½Ù…±}Á…­•Ð¹µˆ¤•±Í”€‰‰±½­•ˆ°(€€€€€€€€€€€€€€€˜‰½µµ•É¥…±}ÁÕÉ¡…Í•}…ÁÁÉ½Ù…±}ÍÑ…ÑÕÌõíÁÕÉ¡…Í•lÁÕÉ¡…Í•}…ÁÁÉ½Ù…±}ÍÑ…ÑÕÌuôˆ°(€€€€€€€€€€€€€€€€‰…¸Ñ¡”‰Õå•ÈÉ•Ù¥•Ü½¹”…ÁÁÉ½Ù…°Á…­•Ð‰•™½É”‘¥±¥•¹”Í¥¸µ½™˜üˆ°(€€€€€€€€€€€€€€€€‰UÍ”Ñ¡”…ÁÁÉ½Ù…°Á…­•Ð…ÌÑ¡”‘¥±¥•¹”É½½´½Ù•È¥¹‘•à¸ˆ°(€€€€€€€€€€€€¤°(€€€€€€€€€€€Í•Ñ¥½¸ (€€€€€€€€€€€€€€€€‰ÉÕ¹Ñ¥µ•}…Á¥}•Ù¥‘•¹”ˆ°(€€€€€€€€€€€€€€€€‰IÕ¹Ñ¥µ”A$•Ù¥‘•¹”ˆ°(€€€€€€€€€€€€€€€€‰A±…Ñ™½É´É•Ù¥•Ý•Èˆ°(€€€€€€€€€€€€€€€l(€€€€€€€€€€€€€€€€€€€€‰‘½Ì½É•ÍÑ}…Á¥}‘•Í¥¸¹µˆ°(€€€€€€€€€€€€€€€€€€€€‰½¹Ñ•áÑÕ…±}½É¡•ÍÑÉ…Ñ½È½…Á¥}½¹ÑÉ…Ð¹Áäˆ°(€€€€€€€€€€€€€€€€€€€€‰I5¹µˆ°(€€€€€€€€€€€€€€€€€€€€ˆ½ØÄ½¡…Ð½½µÁ±•Ñ¥½¹Ìˆ°(€€€€€€€€€€€€€€€t°(€€€€€€€€€€€€€€€l(€€€€€€€€€€€€€€€€€€€€ˆ½ØÄ½¡…Ð½½µÁ±•Ñ¥½¹Ìˆ°(€€€€€€€€€€€€€€€€€€€€ˆ½…Á¤½ØÄ½Ý½É­™±½Ý}ÉÕ¹Ìˆ°(€€€€€€€€€€€€€€€€€€€€ˆ½…Á¤½ØÄ½…•ÍÍ}É•Á½ÉÑÌ½íÝ½É­™±½Ý}ÉÕ¹}¥‘ôˆ°(€€€€€€€€€€€€€€€€€€€€ˆ½…Á¤½ØÄ½½µµ•É¥…±}‘Õ•}‘¥±¥•¹•}É½½µÌ½±…Ñ•ÍÐˆ°(€€€€€€€€€€€€€€€t°(€€€€€€€€€€€€€€€€‰É•Á½Í¥Ñ½Éå}…¹‘}ÉÕ¹Ñ¥µ•}…ÉÑ¥™…Ðˆ°(€€€€€€€€€€€€€€€€‰É•…‘äˆ(€€€€€€€€€€€€€€€¥˜±½…±}ÉÕ¹Ñ¥µ•}ÍÑ…Ñ”€ôô€‰É•…‘äˆ(€€€€€€€€€€€€€€€…¹…±±}™¥±•Ì ‰‘½Ì½É•ÍÑ}…Á¥}‘•Í¥¸¹µˆ°€‰½¹Ñ•áÑÕ…±}½É¡•ÍÑÉ…Ñ½È½…Á¥}½¹ÑÉ…Ð¹Áäˆ°€‰I5¹µˆ¤(€€€€€€€€€€€€€€€…¹…‘µ¥¹}ÍÑ…Ñ•l‰…•¹ÑÌ‰t(€€€€€€€€€€€€€€€•±Í”€‰‰±½­•ˆ°(€€€€€€€€€€€€€€€˜‰…•¹Ñ}½Õ¹Ðõí±•¸¡…‘µ¥¹}ÍÑ…Ñ•l…•¹ÑÌt¥ôì…Á¥}½¹ÑÉ…Ñ}ÁÉ•Í•¹Ðõí¡…Í}™¥±” ½¹Ñ•áÑÕ…±}½É¡•ÍÑÉ…Ñ½È½…Á¥}½¹ÑÉ…Ð¹Áäœ¥ôˆ°(€€€€€€€€€€€€€€€€‰…¸Á±…Ñ™½É´É•Ù¥•Ý•ÉÌÙ•É¥™ä½µÁ…Ñ¥‰±”A$…¹•Ù¥‘•¹”•¹‘Á½¥¹ÑÌüˆ°(€€€€€€€€€€€€€€€€‰-••ÀA$½µÁ…Ñ¥‰¥±¥Ñä…¹•Ù¥‘•¹”•¹‘Á½¥¹ÑÌ¥¸Ñ¡”‘¥±¥•¹”¥¹‘•à¸ˆ°(€€€€€€€€€€€€¤°(€€€€€€€€€€€Í•Ñ¥½¸ (€€€€€€€€€€€€€€€€‰…‘µ¥¹}ÑÉ…•}•Ù¥‘•¹”ˆ°(€€€€€€€€€€€€€€€€‰‘µ¥¸ÑÉ…”•Ù¥‘•¹”ˆ°(€€€€€€€€€€€€€€€€‰=Á•É…Ñ½ÈÉ•Ù¥•Ý•Èˆ°(€€€€€€€€€€€€€€€l‰‘½Ì½ÍÉ••¹}‘•Í¥¸¹µˆ°€ˆ½…‘µ¥¸ˆ°€ˆ½…‘µ¥¸½ÍÑ…Ñ”ˆ°€‰Ý½É­™±½ÜÑÉ…”ˆ°€‰…•ÍÌÉ•Á½ÉÐ‰t°(€€€€€€€€€€€€€€€lˆ½…‘µ¥¸ˆ°€ˆ½…‘µ¥¸½ÍÑ…Ñ”ˆ°€ˆ½…Á¤½ØÄ½Ý½É­™±½Ý}ÉÕ¹Ìˆ°€ˆ½…Á¤½ØÄ½…•ÍÍ}É•Á½ÉÑÌ½íÝ½É­™±½Ý}ÉÕ¹}¥‘ô‰t°(€€€€€€€€€€€€€€€€‰É•Á½Í¥Ñ½Éå}…¹‘}ÉÕ¹Ñ¥µ•}…ÉÑ¥™…Ðˆ°(€€€€€€€€€€€€€€€€‰É•…‘äˆ(€€€€€€€€€€€€€€€¥˜…±±}™¥±•Ì ‰‘½Ì½ÍÉ••¹}‘•Í¥¸¹µˆ°€‰½¹Ñ•áÑÕ…±}½É¡•ÍÑÉ…Ñ½È½…‘µ¥¸¹Áäˆ¤(€€€€€€€€€€€€€€€…¹…‘µ¥¹}ÍÑ…Ñ•l‰…•¹ÑÌ‰t(€€€€€€€€€€€€€€€…¹…‘µ¥¹}ÍÑ…Ñ•l‰É••¹Ñ}Ý½É­™±½Ý}ÉÕ¹Ì‰t(€€€€€€€€€€€€€€€•±Í”€‰‰±½­•ˆ°(€€€€€€€€€€€€€€€˜‰É••¹Ñ}Ý½É­™±½Ý}ÉÕ¹}½Õ¹Ðõí±•¸¡…‘µ¥¹}ÍÑ…Ñ•lÉ••¹Ñ}Ý½É­™±½Ý}ÉÕ¹Ìt¥ôˆ°(€€€€€€€€€€€€€€€€‰…¸Ñ¡”½Á•É…Ñ½ÈÍ¡½ÜÑÉ…”…¹…•ÍÌµ±¥ÍÐ•Ù¥‘•¹”¥¸Ñ¡”…‘µ¥¸½¹Í½±”üˆ°(€€€€€€€€€€€€€€€€‰IÕ¸½¹”½¹‘ÕÐÝ½É­™±½Ü‰•™½É”„±¥Ù”‘¥±¥•¹”Ý…±­Ñ¡É½Õ ¸ˆ°(€€€€€€€€€€€€¤°(€€€€€€€€€€€Í•Ñ¥½¸ (€€€€€€€€€€€€€€€€‰Í•ÕÉ¥Ñå}…¹‘}½µÁ±¥…¹”ˆ°(€€€€€€€€€€€€€€€€‰M•ÕÉ¥Ñä…¹½µÁ±¥…¹”ˆ°(€€€€€€€€€€€€€€€€‰M•ÕÉ¥ÑäÉ•Ù¥•Ý•Èˆ°(€€€€€€€€€€€€€€€l‰MUI%Qd¹µˆ°€‰‘½Ì½½µµ•É¥…±}Í•ÕÉ¥Ñå}…ÑÑ•ÍÑ…Ñ¥½¸¹µˆ°€ˆ½…Á¤½ØÄ½½µµ•É¥…±}Í•ÕÉ¥Ñå}…ÑÑ•ÍÑ…Ñ¥½¹Ì½±…Ñ•ÍÐ‰t°(€€€€€€€€€€€€€€€lˆ½…Á¤½ØÄ½½µµ•É¥…±}Í•ÕÉ¥Ñå}…ÑÑ•ÍÑ…Ñ¥½¹Ì½±…Ñ•ÍÐ‰t°(€€€€€€€€€€€€€€€€‰É•Á½Í¥Ñ½Éå}…¹‘}ÉÕ¹Ñ¥µ•}…ÉÑ¥™…Ðˆ°(€€€€€€€€€€€€€€€€‰É•…‘äˆ(€€€€€€€€€€€€€€€¥˜Í•ÕÉ¥Ñål‰Í•ÕÉ¥Ñå}…ÑÑ•ÍÑ…Ñ¥½¹}ÍÑ…ÑÕÌ‰t€„ô€‰½µµ•É¥…±}Í•ÕÉ¥Ñå}…ÑÑ•ÍÑ…Ñ¥½¹}‰±½­•ˆ(€€€€€€€€€€€€€€€…¹…±±}™¥±•Ì ‰MUI%Qd¹µˆ°€‰‘½Ì½½µµ•É¥…±}Í•ÕÉ¥Ñå}…ÑÑ•ÍÑ…Ñ¥½¸¹µˆ¤(€€€€€€€€€€€€€€€•±Í”€‰‰±½­•ˆ°(€€€€€€€€€€€€€€€˜‰½µµ•É¥…±}Í•ÕÉ¥Ñå}…ÑÑ•ÍÑ…Ñ¥½¹}ÍÑ…ÑÕÌõíÍ•ÕÉ¥ÑålÍ•ÕÉ¥Ñå}…ÑÑ•ÍÑ…Ñ¥½¹}ÍÑ…ÑÕÌuôˆ°(€€€€€€€€€€€€€€€€‰…¸Í•ÕÉ¥ÑäÍ•Á…É…Ñ”É•Á¼µ±½…°½¹ÑÉ½±Ì™É½´•áÑ•É¹…°…ÑÑ•ÍÑ…Ñ¥½¸…ÁÌüˆ°(€€€€€€€€€€€€€€€€‰¼¹½Ð±…¥´Ñ¡¥ÉµÁ…ÉÑä•ÉÑ¥™¥…Ñ¥½¸Õ¹Ñ¥°ÍÕÁÁ±¥•¸ˆ°(€€€€€€€€€€€€¤°(€€€€€€€€€€€Í•Ñ¥½¸ (€€€€€€€€€€€€€€€€‰½µµ•É¥…±}Ñ•ÉµÌˆ°(€€€€€€€€€€€€€€€€‰½µµ•É¥…°Ñ•ÉµÌˆ°(€€€€€€€€€€€€€€€€‰1•…°…¹ÁÉ½ÕÉ•µ•¹ÐÉ•Ù¥•Ý•ÉÌˆ°(€€€€€€€€€€€€€€€l(€€€€€€€€€€€€€€€€€€€€‰‘½Ì½½µµ•É¥…±}½¹ÑÉ…Ñ}É•…‘¥¹•ÍÌ¹µˆ°(€€€€€€€€€€€€€€€€€€€€‰‘½Ì½½µµ•É¥…±}ÁÉ½ÕÉ•µ•¹Ñ}É•…‘¥¹•ÍÌ¹µˆ°(€€€€€€€€€€€€€€€€€€€€‰‘½Ì½½µµ•É¥…±}±½Í•}É•…‘¥¹•ÍÌ¹µˆ°(€€€€€€€€€€€€€€€t°(€€€€€€€€€€€€€€€l(€€€€€€€€€€€€€€€€€€€€ˆ½…Á¤½ØÄ½½µµ•É¥…±}½¹ÑÉ…Ñ}É•…‘¥¹•ÍÌ½±…Ñ•ÍÐˆ°(€€€€€€€€€€€€€€€€€€€€ˆ½…Á¤½ØÄ½½µµ•É¥…±}ÁÉ½ÕÉ•µ•¹Ñ}É•…‘¥¹•ÍÌ½±…Ñ•ÍÐˆ°(€€€€€€€€€€€€€€€€€€€€ˆ½…Á¤½ØÄ½½µµ•É¥…±}±½Í•}É•…‘¥¹•ÍÌ½±…Ñ•ÍÐˆ°(€€€€€€€€€€€€€€€t°(€€€€€€€€€€€€€€€€‰É•Á½Í¥Ñ½Éå}…¹‘}ÉÕ¹Ñ¥µ•}…ÉÑ¥™…Ðˆ°(€€€€€€€€€€€€€€€€‰É•…‘äˆ(€€€€€€€€€€€€€€€¥˜½¹ÑÉ…Ñl‰½¹ÑÉ…Ñ}ÍÑ…ÑÕÌ‰t€„ô€‰½µµ•É¥…±}½¹ÑÉ…Ñ}‰±½­•ˆ(€€€€€€€€€€€€€€€…¹ÁÉ½ÕÉ•µ•¹Ñl‰ÁÉ½ÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌ‰t€„ô€‰½µµ•É¥…±}ÁÉ½ÕÉ•µ•¹Ñ}‰±½­•ˆ(€€€€€€€€€€€€€€€…¹±½Í•l‰±½Í•}ÍÑ…ÑÕÌ‰t€„ô€‰½µµ•É¥…±}±½Í•}‰±½­•ˆ(€€€€€€€€€€€€€€€…¹…±±}™¥±•Ì (€€€€€€€€€€€€€€€€€€€€‰‘½Ì½½µµ•É¥…±}½¹ÑÉ…Ñ}É•…‘¥¹•ÍÌ¹µˆ°(€€€€€€€€€€€€€€€€€€€€‰‘½Ì½½µµ•É¥…±}ÁÉ½ÕÉ•µ•¹Ñ}É•…‘¥¹•ÍÌ¹µˆ°(€€€€€€€€€€€€€€€€€€€€‰‘½Ì½½µµ•É¥…±}±½Í•}É•…‘¥¹•ÍÌ¹µˆ°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€•±Í”€‰‰±½­•ˆ°(€€€€€€€€€€€€€€€€ (€€€€€€€€€€€€€€€€€€€˜‰½µµ•É¥…±}½¹ÑÉ…Ñ}ÍÑ…ÑÕÌõí½¹ÑÉ…Ñl½¹ÑÉ…Ñ}ÍÑ…ÑÕÌuôì€ˆ(€€€€€€€€€€€€€€€€€€€˜‰½µµ•É¥…±}ÁÉ½ÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌõíÁÉ½ÕÉ•µ•¹ÑlÁÉ½ÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌuôì€ˆ(€€€€€€€€€€€€€€€€€€€˜‰½µµ•É¥…±}±½Í•}ÍÑ…ÑÕÌõí±½Í•l±½Í•}ÍÑ…ÑÕÌuôˆ(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€‰…¸±•…°…¹ÁÉ½ÕÉ•µ•¹ÐÉ•Ù¥•ÜÑ•ÉµÌ°É¥¡ÑÌ°…¹±½Í”…Ù•…ÑÌÑ½•Ñ¡•Èüˆ°(€€€€€€€€€€€€€€€€‰ÑÑ… ‰Õå•ÈµÍÁ•¥™¥Œ½É‘•Èµ™½É´±…¹Õ…”½ÕÑÍ¥‘”Ñ¡”±½…°ÉÕ¹Ñ¥µ”±…¥´¸ˆ°(€€€€€€€€€€€€¤°(€€€€€€€€€€€Í•Ñ¥½¸ (€€€€€€€€€€€€€€€€‰Ù…±Õ•}…¹‘}…¹…±åÑ¥Ìˆ°(€€€€€€€€€€€€€€€€‰Y…±Õ”…¹…¹…±åÑ¥Ìˆ°(€€€€€€€€€€€€€€€€‰½¹½µ¥ŒÉ•Ù¥•Ý•Èˆ°(€€€€€€€€€€€€€€€l‰‘½Ì½½µµ•É¥…±}Ù…±Õ•}É•…‘¥¹•ÍÌ¹µˆ°€‰‘½Ì½…¹…±åÑ¥Í}ÍÁ•Œ¹µˆ°€ˆ½…Á¤½ØÄ½…¹…±åÑ¥Í}Í¹…ÁÍ¡½ÑÌ½±…Ñ•ÍÐ‰t°(€€€€€€€€€€€€€€€lˆ½…Á¤½ØÄ½½µµ•É¥…±}Ù…±Õ•}É•…‘¥¹•ÍÌ½±…Ñ•ÍÐˆ°€ˆ½…Á¤½ØÄ½…¹…±åÑ¥Í}Í¹…ÁÍ¡½ÑÌ½±…Ñ•ÍÐ‰t°(€€€€€€€€€€€€€€€€‰É•Á½Í¥Ñ½Éå}…¹‘}ÉÕ¹Ñ¥µ•}…ÉÑ¥™…Ðˆ°(€€€€€€€€€€€€€€€€‰É•…‘äˆ(€€€€€€€€€€€€€€€¥˜Ù…±Õ•l‰Ù…±Õ•}ÍÑ…ÑÕÌ‰t€„ô€‰½µµ•É¥…±}Ù…±Õ•}‰±½­•ˆ(€€€€€€€€€€€€€€€…¹…¹…±åÑ¥Íl‰µ•…ÍÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌ‰t€ôô€‰±½…±}ÉÕ¹Ñ¥µ•}Í¹…ÁÍ¡½Ðˆ(€€€€€€€€€€€€€€€…¹…±±}™¥±•Ì ‰‘½Ì½½µµ•É¥…±}Ù…±Õ•}É•…‘¥¹•ÍÌ¹µˆ°€‰‘½Ì½…¹…±åÑ¥Í}ÍÁ•Œ¹µˆ¤(€€€€€€€€€€€€€€€•±Í”€‰‰±½­•ˆ°(€€€€€€€€€€€€€€€˜‰½µµ•É¥…±}Ù…±Õ•}ÍÑ…ÑÕÌõíÙ…±Õ•lÙ…±Õ•}ÍÑ…ÑÕÌuôì…¹…±åÑ¥Í}µ•…ÍÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌõí…¹…±åÑ¥Ílµ•…ÍÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌuôˆ°(€€€€€€€€€€€€€€€€‰…¸™¥¹…¹”Ñ•±°µ•…ÍÕÉ•±½…°•Ù¥‘•¹”…Á…ÉÐ™É½´‰Õå•ÈI=$…ÍÍÕµÁÑ¥½¹Ìüˆ°(€€€€€€€€€€€€€€€€‰-••ÀÁÉ½Á½Í•-A$Ñ…É•ÑÌÍ•Á…É…Ñ”™É½´µ•…ÍÕÉ•±½…°ÉÕ¹Ñ¥µ”‘…Ñ„¸ˆ°(€€€€€€€€€€€€¤°(€€€€€€€€€€€Í•Ñ¥½¸ (€€€€€€€€€€€€€€€€‰¥µÁ±•µ•¹Ñ…Ñ¥½¹}É•…‘¥¹•ÍÌˆ°(€€€€€€€€€€€€€€€€‰%µÁ±•µ•¹Ñ…Ñ¥½¸É•…‘¥¹•ÍÌˆ°(€€€€€€€€€€€€€€€€‰%µÁ±•µ•¹Ñ…Ñ¥½¸…¹½Á•É…Ñ¥½¹ÌÉ•Ù¥•Ý•ÉÌˆ°(€€€€€€€€€€€€€€€l‰‘½Ì½½µµ•É¥…±}½¹‰½…É‘¥¹}É•…‘¥¹•ÍÌ¹µˆ°€‰‘½Ì½½µµ•É¥…±}½Á•É…Ñ¥½¹Í}É•…‘¥¹•ÍÌ¹µ‰t°(€€€€€€€€€€€€€€€lˆ½…Á¤½ØÄ½½µµ•É¥…±}½¹‰½…É‘¥¹}É•…‘¥¹•ÍÌ½±…Ñ•ÍÐˆ°€ˆ½…Á¤½ØÄ½½µµ•É¥…±}½Á•É…Ñ¥½¹Í}É•…‘¥¹•ÍÌ½±…Ñ•ÍÐ‰t°(€€€€€€€€€€€€€€€€‰É•Á½Í¥Ñ½Éå}…¹‘}ÉÕ¹Ñ¥µ•}…ÉÑ¥™…Ðˆ°(€€€€€€€€€€€€€€€€‰É•…‘äˆ(€€€€€€€€€€€€€€€¥˜½¹‰½…É‘¥¹l‰½¹‰½…É‘¥¹}ÍÑ…ÑÕÌ‰t€„ô€‰½µµ•É¥…±}½¹‰½…É‘¥¹}‰±½­•ˆ(€€€€€€€€€€€€€€€…¹½Á•É…Ñ¥½¹Íl‰½Á•É…Ñ¥½¹Í}ÍÑ…ÑÕÌ‰t€„ô€‰½µµ•É¥…±}½Á•É…Ñ¥½¹Í}‰±½­•ˆ(€€€€€€€€€€€€€€€…¹…±±}™¥±•Ì ‰‘½Ì½½µµ•É¥…±}½¹‰½…É‘¥¹}É•…‘¥¹•ÍÌ¹µˆ°€‰‘½Ì½½µµ•É¥…±}½Á•É…Ñ¥½¹Í}É•…‘¥¹•ÍÌ¹µˆ¤(€€€€€€€€€€€€€€€•±Í”€‰‰±½­•ˆ°(€€€€€€€€€€€€€€€˜‰½µµ•É¥…±}½¹‰½…É‘¥¹}ÍÑ…ÑÕÌõí½¹‰½…É‘¥¹l½¹‰½…É‘¥¹}ÍÑ…ÑÕÌuôì½µµ•É¥…±}½Á•É…Ñ¥½¹Í}ÍÑ…ÑÕÌõí½Á•É…Ñ¥½¹Íl½Á•É…Ñ¥½¹Í}ÍÑ…ÑÕÌuôˆ°(€€€€€€€€€€€€€€€€‰…¸¥µÁ±•µ•¹Ñ…Ñ¥½¸½Ý¹•ÉÌÍ•”½¹‰½…É‘¥¹œ°½Á•É…Ñ¥½¹Ì°¥¹¥‘•¹Ð°…¹¡…¹‘½™˜•Ù¥‘•¹”üˆ°(€€€€€€€€€€€€€€€€‰½¹Ù•ÉÐ‰Õå•È•¹Ù¥É½¹µ•¹ÐÍÁ•¥™¥Ì¥¹Ñ¼Ñ¡”Á…¥½¹‰½…É‘¥¹œÁ±…¸¸ˆ°(€€€€€€€€€€€€¤°(€€€€€€€€€€€Í•Ñ¥½¸ (€€€€€€€€€€€€€€€€‰™¥µ…}…¹‘}‘•Í¥¹}É•Ù¥•Üˆ°(€€€€€€€€€€€€€€€€‰¥µ„…¹‘•Í¥¸É•Ù¥•Üˆ°(€€€€€€€€€€€€€€€€‰AÉ½‘ÕÐ‘•Í¥¸É•Ù¥•Ý•Èˆ°(€€€€€€€€€€€€€€€l(€€€€€€€€€€€€€€€€€€€€‰‘½Ì½½µµ•É¥…±}‘Õ•}‘¥±¥•¹•}É½½´¹µˆ°(€€€€€€€€€€€€€€€€€€€€‰‘½Ì½™¥µ…}…ÉÑ¥™…ÑÌ¹µˆ°(€€€€€€€€€€€€€€€€€€€€‰‘½Ì½ÍÕÁ•ÉÁ½Ý•ÉÌ½Á±…¹Ì¼ÈÀÈØ´ÀÜ´ÀÈµ½µµ•É¥…°µ‘Õ”µ‘¥±¥•¹”µÉ½½´µÉÕ¹Ñ¥µ”¹µˆ°(€€€€€€€€€€€€€€€t°(€€€€€€€€€€€€€€€lˆ½…Á¤½ØÄ½½µµ•É¥…±}‘Õ•}‘¥±¥•¹•}É½½µÌ½±…Ñ•ÍÐ‰t°(€€€€€€€€€€€€€€€€‰É•Á½Í¥Ñ½Éå}…¹‘}ÉÕ¹Ñ¥µ•}…ÉÑ¥™…Ðˆ°(€€€€€€€€€€€€€€€€‰É•…‘äˆ(€€€€€€€€€€€€€€€¥˜…±±}™¥±•Ì (€€€€€€€€€€€€€€€€€€€€‰‘½Ì½½µµ•É¥…±}‘Õ•}‘¥±¥•¹•}É½½´¹µˆ°(€€€€€€€€€€€€€€€€€€€€‰‘½Ì½™¥µ…}…ÉÑ¥™…ÑÌ¹µˆ°(€€€€€€€€€€€€€€€€€€€€‰‘½Ì½ÍÕÁ•ÉÁ½Ý•ÉÌ½Á±…¹Ì¼ÈÀÈØ´ÀÜ´ÀÈµ½µµ•É¥…°µ‘Õ”µ‘¥±¥•¹”µÉ½½´µÉÕ¹Ñ¥µ”¹µˆ°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€•±Í”€‰‰±½­•ˆ°(€€€€€€€€€€€€€€€€‰Õ”‘¥±¥•¹”‘½Œ°¥)…´…ÉÑ¥™…ÐÉ•½É°…¹¥µÁ±•µ•¹Ñ…Ñ¥½¸Á±…¸…É”½µµ¥ÑÑ•¸ˆ°(€€€€€€€€€€€€€€€€‰…¸ÍÑ…­•¡½±‘•ÉÌ¥¹ÍÁ•ÐÑ¡”‘¥±¥•¹”É½½´…Ì‘½Ì°ÉÕ¹Ñ¥µ”)M=8°…¹¥)…´üˆ°(€€€€€€€€€€€€€€€€‰UÍ”¥)…´½¹±äì‘¼¹½ÐÕÍ”¥µ„½‘”½¹¹•Ð¸ˆ°(€€€€€€€€€€€€¤°(€€€€€€€€€€€Í•Ñ¥½¸ (€€€€€€€€€€€€€€€€‰‰Õå•É}…ÕÑ¡½É¥Ñå}‘½Õµ•¹ÑÌˆ°(€€€€€€€€€€€€€€€€‰	Õå•È…ÕÑ¡½É¥Ñä‘½Õµ•¹ÑÌˆ°(€€€€€€€€€€€€€€€€‰	Õå•ÈÍÁ½¹Í½Èˆ°(€€€€€€€€€€€€€€€l‰¹…µ•‰Õå•ÈÍ¥¹•Èˆ°€‰‰Õ‘•Ð½Ý¹•È…¹ÁÕÉ¡…Í”½É‘•Èˆ°€‰‰Õå•ÈA½ÈÁÉ¥Ù…ä…•ÁÑ…¹”‰t°(€€€€€€€€€€€€€€€mt°(€€€€€€€€€€€€€€€€‰ÁÉ½Á½Í•‘}Õ¹Ñ¥±}‰Õå•É}ÍÁ•¥™¥Œˆ°(€€€€€€€€€€€€€€€€‰Ý…É¹¥¹œˆ°(€€€€€€€€€€€€€€€€‰9…µ•Í¥¹•È°‰Õ‘•Ð½Ý¹•È°A<°…¹‰Õå•ÈÁÉ¥Ù…ä…•ÁÑ…¹”É•ÅÕ¥É”‰Õå•È…ÕÑ¡½É¥Ñä¸ˆ°(€€€€€€€€€€€€€€€€‰½•ÌÑ¡”‰Õå•È¡…Ù”…ÕÑ¡½É¥Ñä…ÉÑ¥™…ÑÌÉ•…‘ä™½È™¥¹…°‘¥±¥•¹”üˆ°(€€€€€€€€€€€€€€€€‰½±±•ÐÍ¥¹•È°A<°A½ÁÉ¥Ù…ä…•ÁÑ…¹”°½È•áÁ±¥¥ÐÝ…¥Ù•È¸ˆ°(€€€€€€€€€€€€¤°(€€€€€€€€€€€Í•Ñ¥½¸ (€€€€€€€€€€€€€€€€‰ÁÉ½‘ÕÑ¥½¹}•áÑ•É¹…±}…ÑÑ•ÍÑ…Ñ¥½¹Ìˆ°(€€€€€€€€€€€€€€€€‰AÉ½‘ÕÑ¥½¸…¹•áÑ•É¹…°…ÑÑ•ÍÑ…Ñ¥½¹Ìˆ°(€€€€€€€€€€€€€€€€‰AÉ½‘ÕÑ¥½¸…¹Í•ÕÉ¥Ñä½Ý¹•ÉÌˆ°(€€€€€€€€€€€€€€€l‰ÁÉ½‘ÕÑ¥½¸Ñ•±•µ•ÑÉäˆ°€‰Ñ¡¥ÉµÁ…ÉÑäÍ•ÕÉ¥Ñä…ÑÑ•ÍÑ…Ñ¥½¸ˆ°€‰¡½ÍÑ•Í…¸•Ù¥‘•¹”‰t°(€€€€€€€€€€€€€€€mt°(€€€€€€€€€€€€€€€€‰ÁÉ½Á½Í•‘}Õ¹Ñ¥±}‰Õå•É}ÍÁ•¥™¥Œˆ°(€€€€€€€€€€€€€€€€‰Ý…É¹¥¹œˆ°(€€€€€€€€€€€€€€€€‰AÉ½‘ÕÑ¥½¸Ñ•±•µ•ÑÉä…¹Ñ¡¥ÉµÁ…ÉÑä…ÑÑ•ÍÑ…Ñ¥½¹Ì…É”•áÑ•É¹…°•Ù¥‘•¹”°¹½Ð±½…°É•Á¼µ•…ÍÕÉ•µ•¹ÑÌ¸ˆ°(€€€€€€€€€€€€€€€€‰…¸Ñ¡”‰Õå•È‘¥ÍÑ¥¹Õ¥Í ±½…°É•…‘¥¹•ÍÌ™É½´ÁÉ½‘ÕÑ¥½¸…¹Ñ¡¥ÉµÁ…ÉÑä•Ù¥‘•¹”üˆ°(€€€€€€€€€€€€€€€€‰½±±•Ð¡½ÍÑ•Ñ•±•µ•ÑÉä…¹•áÑ•É¹…°…ÑÑ•ÍÑ…Ñ¥½¸…™Ñ•È•¹Ù¥É½¹µ•¹ÐÍ•±•Ñ¥½¸¸ˆ°(€€€€€€€€€€€€¤°(€€€€€€€t(€€€€€€€ÍÑ…Ñ•}½Õ¹ÑÌ€ô½Õ¹Ñ•È¡¥Ñ•µl‰½µÁ±•Ñ¥½¹}ÍÑ…Ñ”‰t™½È¥Ñ•´¥¸‘¥±¥•¹•}Í•Ñ¥½¹Ì¤(€€€€€€€‰±½­•‘}½Õ¹Ð€ôÍÑ…Ñ•}½Õ¹ÑÌ¹•Ð ‰‰±½­•ˆ°€À¤€¬±•¸¡½¹É•Ñ•}‰±½­•ÉÌ¤(€€€€€€€Ý…É¹¥¹}½Õ¹Ð€ôÍÑ…Ñ•}½Õ¹ÑÌ¹•Ð ‰Ý…É¹¥¹œˆ°€À¤(€€€€€€€¥˜‰±½­•‘}½Õ¹Ðè(€€€€€€€€€€€‘Õ•}‘¥±¥•¹•}ÍÑ…ÑÕÌ€ô€‰½µµ•É¥…±}‘Õ•}‘¥±¥•¹•}‰±½­•ˆ(€€€€€€€•±¥˜Ý…É¹¥¹}½Õ¹Ðè(€€€€€€€€€€€‘Õ•}‘¥±¥•¹•}ÍÑ…ÑÕÌ€ô€‰½µµ•É¥…±}‘Õ•}‘¥±¥•¹•}É•…‘å}Ý¥Ñ¡}Ý…É¹¥¹Ìˆ(€€€€€€€•±Í”è€€ŒÁÉ…µ„è¹¼½Ù•È€´Õ¹É•…¡…‰±”Ý¡¥±”Ñ¡¥ÌÉ•Á½ÉÐ…ÉÉ¥•Ì±¥Ñ•É…°‰Õå•ÈµÍÁ•¥™¥ŒÝ…É¹¥¹œÍ•Ñ¥½¹Ì(€€€€€€€€€€€‘Õ•}‘¥±¥•¹•}ÍÑ…ÑÕÌ€ô€‰½µµ•É¥…±}‘Õ•}‘¥±¥•¹•}É•…‘äˆ€€ŒÁÉ…µ„è¹¼½Ù•È(€€€€€€€É•ÅÕ¥É•‘}ÉÕ¹Ñ¥µ•}•¹‘Á½¥¹ÑÌ€ô±¥ÍÐ (€€€€€€€€€€€‘¥Ð¹™É½µ­•åÌ (€€€€€€€€€€€€€€€•¹‘Á½¥¹Ð(€€€€€€€€€€€€€€€™½È¥Ñ•´¥¸‘¥±¥•¹•}Í•Ñ¥½¹Ì(€€€€€€€€€€€€€€€™½È•¹‘Á½¥¹Ð¥¸¥Ñ•µl‰ÉÕ¹Ñ¥µ•}•¹‘Á½¥¹ÑÌ‰t(€€€€€€€€€€€€€€€¥˜•¹‘Á½¥¹Ð¹ÍÑ…ÉÑÍÝ¥Ñ  ˆ¼ˆ¤(€€€€€€€€€€€€¤(€€€€€€€€¤((€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€‰‘Õ•}‘¥±¥•¹•}ÍÑ…ÑÕÌˆè‘Õ•}‘¥±¥•¹•}ÍÑ…ÑÕÌ°(€€€€€€€€€€€€‰Ñ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜˆèÑ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜ°(€€€€€€€€€€€€‰Ñ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}‘¥ÍÁ±…äˆè˜‰-I\íÑ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜè±ôˆ°(€€€€€€€€€€€€‰µ•…ÍÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌˆè€‰±½…±}½µµ•É¥…±}‘Õ•}‘¥±¥•¹•}É½½´ˆ°(€€€€€€€€€€€€‰Í½ÕÉ•}¹½Ñ”ˆè€ (€€€€€€€€€€€€€€€€‰½µµ•É¥…°‘Õ”‘¥±¥•¹”É½½´Á…­…•ÌÉ•Á¼µ±½…°ÁÕÉ¡…Í”…ÁÁÉ½Ù…°°ÁÉ½Á½Í…°°ÉÕ¹Ñ¥µ”°€ˆ(€€€€€€€€€€€€€€€€‰…‘µ¥¸ÑÉ…”°Í•ÕÉ¥Ñä°½¹ÑÉ…Ð°Ù…±Õ”°½¹‰½…É‘¥¹œ°½Á•É…Ñ¥½¹Ì°…¹…±åÑ¥Ì°¥µ„°€ˆ(€€€€€€€€€€€€€€€€‰É•Ù¥•ÜµÁ½±¥ä°…¹Á…­…¥¹œ•Ù¥‘•¹”™½È-I\€È°ÀÀÀ°ÀÀÀ°ÀÀÀ‰Õå•È‘¥±¥•¹”ì¥Ð¥Ì€ˆ(€€€€€€€€€€€€€€€€‰¹½Ð„Ù…±Õ…Ñ¥½¸Õ…É…¹Ñ•”°ÁÕÉ¡…Í”½µµ¥Ñµ•¹Ð°Í¥¹•½É‘•È°±•…°½Á¥¹¥½¸°ÁÉ½‘ÕÑ¥½¸€ˆ(€€€€€€€€€€€€€€€€‰½µÁ±¥…¹”•ÉÑ¥™¥…Ñ”°Ñ¡¥ÉµÁ…ÉÑä…ÑÑ•ÍÑ…Ñ¥½¸°½ÈÉ•Ù•¹Õ”ÁÉ½½˜¸ˆ(€€€€€€€€€€€€¤°(€€€€€€€€€€€€‰‘¥±¥•¹•}¹…ÉÉ…Ñ¥Ù”ˆèì(€€€€€€€€€€€€€€€€‰Ñ¥Ñ±”ˆè€‰-I\€É½µµ•É¥…°‘Õ”‘¥±¥•¹”É½½´ˆ°(€€€€€€€€€€€€€€€€‰ÁÉ½µ¥Í”ˆè€ (€€€€€€€€€€€€€€€€€€€€‰¥Ù”™¥¹…¹”°ÁÉ½ÕÉ•µ•¹Ð°±•…°°Í•ÕÉ¥Ñä°ÁÉ½‘ÕÐ°…¹¥µÁ±•µ•¹Ñ…Ñ¥½¸É•Ù¥•Ý•ÉÌ€ˆ(€€€€€€€€€€€€€€€€€€€€‰½¹”•Ù¥‘•¹”É½½´Ñ¡…ÐÍ•Á…É…Ñ•Ìµ•…ÍÕÉ•±½…°ÁÉ½‘ÕÐ•Ù¥‘•¹”™É½´‰Õå•ÈµÍÁ•¥™¥Œ€ˆ(€€€€€€€€€€€€€€€€€€€€‰…¹•áÑ•É¹…°ÁÉ½‘ÕÑ¥½¸…ÉÑ¥™…ÑÌ¸ˆ(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€‰…Õ‘¥•¹”ˆèl(€€€€€€€€€€€€€€€€€€€€‰½¹½µ¥Œ‰Õå•Èˆ°(€€€€€€€€€€€€€€€€€€€€‰¥¹…¹”½Ý¹•Èˆ°(€€€€€€€€€€€€€€€€€€€€‰AÉ½ÕÉ•µ•¹Ð½Ý¹•Èˆ°(€€€€€€€€€€€€€€€€€€€€‰1•…°½Ý¹•Èˆ°(€€€€€€€€€€€€€€€€€€€€‰M•ÕÉ¥Ñä½Ý¹•Èˆ°(€€€€€€€€€€€€€€€€€€€€‰A±…Ñ™½É´É•Ù¥•Ý•Èˆ°(€€€€€€€€€€€€€€€€€€€€‰%µÁ±•µ•¹Ñ…Ñ¥½¸½Ý¹•Èˆ°(€€€€€€€€€€€€€€€t°(€€€€€€€€€€€ô°(€€€€€€€€€€€€‰‘¥±¥•¹•}ÍÕµµ…Éäˆèì(€€€€€€€€€€€€€€€€‰Í•Ñ¥½¹}½Õ¹Ðˆè±•¸¡‘¥±¥•¹•}Í•Ñ¥½¹Ì¤°(€€€€€€€€€€€€€€€€‰É•…‘å}½Õ¹ÐˆèÍÑ…Ñ•}½Õ¹ÑÌ¹•Ð ‰É•…‘äˆ°€À¤°(€€€€€€€€€€€€€€€€‰Ý…É¹¥¹}½Õ¹ÐˆèÝ…É¹¥¹}½Õ¹Ð°(€€€€€€€€€€€€€€€€‰‰±½­•‘}½Õ¹Ðˆè‰±½­•‘}½Õ¹Ð°(€€€€€€€€€€€€€€€€‰•¹‘Á½¥¹Ñ}½Õ¹Ðˆè±•¸¡É•ÅÕ¥É•‘}ÉÕ¹Ñ¥µ•}•¹‘Á½¥¹ÑÌ¤°(€€€€€€€€€€€€€€€€‰É•Ù¥•Ý}ÁÉ½•ÍÍ}¥Í}‰±½­•ÈˆèÁÕÉ¡…Í•l‰É•Ù¥•Ý}ÁÉ½•ÍÍ}Á½±¥ä‰ul‰¥Í}‰±½­•È‰t°(€€€€€€€€€€€€€€€€‰½‘•}½¹¹•Ñ}ÕÍ•ˆè…±Í”°(€€€€€€€€€€€ô°(€€€€€€€€€€€€‰‘¥±¥•¹•}Í•Ñ¥½¹Ìˆè‘¥±¥•¹•}Í•Ñ¥½¹Ì°(€€€€€€€€€€€€‰É•ÅÕ¥É•‘}ÉÕ¹Ñ¥µ•}•¹‘Á½¥¹ÑÌˆèÉ•ÅÕ¥É•‘}ÉÕ¹Ñ¥µ•}•¹‘Á½¥¹ÑÌ°(€€€€€€€€€€€€‰‰Õå•É}µ¥ÍÍ¥¹}…ÉÑ¥™…ÑÌˆèl(€€€€€€€€€€€€€€€€‰¹…µ•‰Õå•ÈÍ¥¹•Èˆ°(€€€€€€€€€€€€€€€€‰‰Õ‘•Ð½Ý¹•È…¹ÁÕÉ¡…Í”½É‘•Èˆ°(€€€€€€€€€€€€€€€€‰‰Õå•ÈA½ÈÁÉ¥Ù…ä…•ÁÑ…¹”ˆ°(€€€€€€€€€€€€€€€€‰ÁÉ½‘ÕÑ¥½¸Ñ•±•µ•ÑÉäˆ°(€€€€€€€€€€€€€€€€‰Ñ¡¥ÉµÁ…ÉÑäÍ•ÕÉ¥Ñä…ÑÑ•ÍÑ…Ñ¥½¸ˆ°(€€€€€€€€€€€t°(€€€€€€€€€€€€‰½¹É•Ñ•}‰±½­•ÉÌˆè½¹É•Ñ•}‰±½­•ÉÌ°(€€€€€€€€€€€€‰‘Õ•}‘¥±¥•¹•}ÍÑ…ÑÕÍ}ÉÕ±•Ìˆèl(€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€‰‘Õ•}‘¥±¥•¹•}ÍÑ…ÑÕÌˆè€‰½µµ•É¥…±}‘Õ•}‘¥±¥•¹•}É•…‘äˆ°(€€€€€€€€€€€€€€€€€€€€‰ÉÕ±”ˆè€‰…±°‘¥±¥•¹”Í•Ñ¥½¹Ì…É”É•…‘ä…¹¹¼‰Õå•È…ÕÑ¡½É¥Ñä°ÁÉ½‘ÕÑ¥½¸°½ÈÑ¡¥ÉµÁ…ÉÑä•Ù¥‘•¹”É•µ…¥¹Ì½Á•¸ˆ°(€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€‰‘Õ•}‘¥±¥•¹•}ÍÑ…ÑÕÌˆè€‰½µµ•É¥…±}‘Õ•}‘¥±¥•¹•}É•…‘å}Ý¥Ñ¡}Ý…É¹¥¹Ìˆ°(€€€€€€€€€€€€€€€€€€€€‰ÉÕ±”ˆè€‰É•Á¼µ±½…°‘¥±¥•¹”É½½´•Ù¥‘•¹”¥ÌÉ•…‘äÝ¡¥±”‰Õå•È…ÕÑ¡½É¥Ñä°ÁÉ½‘ÕÑ¥½¸Ñ•±•µ•ÑÉä°½È•áÑ•É¹…°…ÑÑ•ÍÑ…Ñ¥½¹ÌÉ•µ…¥¸•áÁ±¥¥ÐÝ…É¹¥¹Ìˆ°(€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€‰‘Õ•}‘¥±¥•¹•}ÍÑ…ÑÕÌˆè€‰½µµ•É¥…±}‘Õ•}‘¥±¥•¹•}‰±½­•ˆ°(€€€€€€€€€€€€€€€€€€€€‰ÉÕ±”ˆè€‰Í•ÕÉ¥Ñä™…¥±ÕÉ”°A$½¹ÑÉ…ÐÉ•É•ÍÍ¥½¸°‘½Õµ•¹Ðµ¥Íµ…Ñ °ÉÕ¹Ñ¥µ”‘•™•Ð°µ¥ÍÍ¥¹œ±½…°‘¥±¥•¹”•Ù¥‘•¹”°½È½‘”½¹¹•ÐÕÍ…”‰±½­Ì‰Õå•È‘¥±¥•¹”ˆ°(€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€t°(€€€€€€€€€€€€‰É•Ù¥•Ý}ÁÉ½•ÍÍ}Á½±¥äˆèÁÕÉ¡…Í•l‰É•Ù¥•Ý}ÁÉ½•ÍÍ}Á½±¥ä‰t°(€€€€€€€€€€€€‰É•±…Ñ•‘}ÉÕ¹Ñ¥µ•}É•Á½ÉÑÌˆèì(€€€€€€€€€€€€€€€€‰½µµ•É¥…±}ÁÕÉ¡…Í•}…ÁÁÉ½Ù…±}ÍÑ…ÑÕÌˆèÁÕÉ¡…Í•l‰ÁÕÉ¡…Í•}…ÁÁÉ½Ù…±}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰½µµ•É¥…±}ÁÉ½Á½Í…±}ÍÑ…ÑÕÌˆèÁÉ½Á½Í…±l‰ÁÉ½Á½Í…±}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰½µµ•É¥…±}½µÁ±•Ñ¥½¹}ÍÑ…ÑÕÌˆè½µÁ±•Ñ¥½¹l‰½µÁ±•Ñ¥½¹}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰½µµ•É¥…±}‘•µ½}ÍÑ…ÑÕÌˆè‘•µ½l‰‘•µ½}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰‰Õå•É}…•ÁÑ…¹•}Ý½É­™±½Ý}ÍÑ…ÑÕÌˆè‰Õå•É}Ý½É­™±½Ýl‰Ý½É­™±½Ý}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰½µµ•É¥…±}±½Í•}ÍÑ…ÑÕÌˆè±½Í•l‰±½Í•}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰½µµ•É¥…±}ÁÉ½ÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌˆèÁÉ½ÕÉ•µ•¹Ñl‰ÁÉ½ÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰½µµ•É¥…±}½¹ÑÉ…Ñ}ÍÑ…ÑÕÌˆè½¹ÑÉ…Ñl‰½¹ÑÉ…Ñ}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰½µµ•É¥…±}Ù…±Õ•}ÍÑ…ÑÕÌˆèÙ…±Õ•l‰Ù…±Õ•}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰½µµ•É¥…±}Í•ÕÉ¥Ñå}…ÑÑ•ÍÑ…Ñ¥½¹}ÍÑ…ÑÕÌˆèÍ•ÕÉ¥Ñål‰Í•ÕÉ¥Ñå}…ÑÑ•ÍÑ…Ñ¥½¹}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰½µµ•É¥…±}½¹‰½…É‘¥¹}ÍÑ…ÑÕÌˆè½¹‰½…É‘¥¹l‰½¹‰½…É‘¥¹}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰½µµ•É¥…±}½Á•É…Ñ¥½¹Í}ÍÑ…ÑÕÌˆè½Á•É…Ñ¥½¹Íl‰½Á•É…Ñ¥½¹Í}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰…¹…±åÑ¥Í}µ•…ÍÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌˆè…¹…±åÑ¥Íl‰µ•…ÍÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€ô°(€€€€€€€€€€€€‰±¥‰É…Éå}ÍÁ±¥Ñ}‘•¥Í¥½¸ˆèÁÕÉ¡…Í•l‰±¥‰É…Éå}ÍÁ±¥Ñ}‘•¥Í¥½¸‰t°(€€€€€€€€€€€€‰Á±Õ¥¹}ÑÉ…•…‰¥±¥ÑäˆèÁÕÉ¡…Í•l‰Á±Õ¥¹}ÑÉ…•…‰¥±¥Ñä‰t°(€€€€€€€€€€€€‰‘Õ•}‘¥±¥•¹•}±¥¹­Ìˆèì(€€€€€€€€€€€€€€€€‰™¥µ…}‘•Í¥¹}™¥±”ˆè€‰¡ÑÑÁÌè¼½ÝÝÜ¹™¥µ„¹½´½‘•Í¥¸½ÙÍi5á]ØÐÉ!IiÕ9]¬ˆ°(€€€€€€€€€€€€€€€€‰™¥©…µ}‰½…Éˆè€‰¡ÑÑÁÌè¼½ÝÝÜ¹™¥µ„¹½´½‰½…É½]Èá¥5±åM!­•É!M©ØÁA”Á4ˆ°(€€€€€€€€€€€€€€€€‰ÉÕ¹Ñ¥µ•}•¹‘Á½¥¹Ðˆè€ˆ½…Á¤½ØÄ½½µµ•É¥…±}‘Õ•}‘¥±¥•¹•}É½½µÌ½±…Ñ•ÍÐˆ°(€€€€€€€€€€€€€€€€‰‘½Õµ•¹Ñ…Ñ¥½¸ˆè€‰‘½Ì½½µµ•É¥…±}‘Õ•}‘¥±¥•¹•}É½½´¹µˆ°(€€€€€€€€€€€ô°(€€€€€€€ô((€€€‘•˜½µµ•É¥…±}¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}µ•µ½}É•Á½ÉÐ (€€€€€€€Í•±˜°(€€€€€€€Ñ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜè¥¹Ð€ôU1Q}=55I%1}QIQ}Y1U}-I\°(€€€€€€€±½…±•}‰Õ¹‘±•Ìè‘¥ÑmÍÑÈ°‘¥ÑmÍÑÈ°ÍÑÉutð9½¹”€ô9½¹”°(€€€€€€€Í•ÕÉ¥Ñå}ÁÉ½™¥±”è‘¥ÑmÍÑÈ°¹åtð9½¹”€ô9½¹”°(€€€€¤€´ø‘¥ÑmÍÑÈ°¹åtè(€€€€€€€€ˆˆ‰I•ÑÕÉ¸•á•ÕÑ¥Ù”¥¹Ù•ÍÑµ•¹Ð½µµ¥ÑÑ•”µ•µ¼Í•Ñ¥½¹Ì™½ÈÑ¡”-I\€ÉÍÑ…¹‘…É¸ˆˆˆ(€€€€€€€‘Õ•}‘¥±¥•¹”€ôÍ•±˜¹½µµ•É¥…±}‘Õ•}‘¥±¥•¹•}É½½µ}É•Á½ÉÐ (€€€€€€€€€€€Ñ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜõÑ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜ°(€€€€€€€€€€€±½…±•}‰Õ¹‘±•Ìõ±½…±•}‰Õ¹‘±•Ì°(€€€€€€€€€€€Í•ÕÉ¥Ñå}ÁÉ½™¥±”õÍ•ÕÉ¥Ñå}ÁÉ½™¥±”°(€€€€€€€€¤(€€€€€€€ÁÕÉ¡…Í”€ôÍ•±˜¹½µµ•É¥…±}ÁÕÉ¡…Í•}…ÁÁÉ½Ù…±}Á…­•Ñ}É•Á½ÉÐ (€€€€€€€€€€€Ñ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜõÑ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜ°(€€€€€€€€€€€±½…±•}‰Õ¹‘±•Ìõ±½…±•}‰Õ¹‘±•Ì°(€€€€€€€€€€€Í•ÕÉ¥Ñå}ÁÉ½™¥±”õÍ•ÕÉ¥Ñå}ÁÉ½™¥±”°(€€€€€€€€¤(€€€€€€€ÁÉ½Á½Í…°€ôÍ•±˜¹½µµ•É¥…±}ÁÉ½Á½Í…±}Á…­•Ñ}É•Á½ÉÐ (€€€€€€€€€€€Ñ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜõÑ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜ°(€€€€€€€€€€€±½…±•}‰Õ¹‘±•Ìõ±½…±•}‰Õ¹‘±•Ì°(€€€€€€€€€€€Í•ÕÉ¥Ñå}ÁÉ½™¥±”õÍ•ÕÉ¥Ñå}ÁÉ½™¥±”°(€€€€€€€€¤(€€€€€€€½µÁ±•Ñ¥½¸€ôÍ•±˜¹½µµ•É¥…±}½µÁ±•Ñ¥½¹}Í½É•…É‘}É•Á½ÉÐ (€€€€€€€€€€€Ñ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜõÑ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜ°(€€€€€€€€€€€±½…±•}‰Õ¹‘±•Ìõ±½…±•}‰Õ¹‘±•Ì°(€€€€€€€€€€€Í•ÕÉ¥Ñå}ÁÉ½™¥±”õÍ•ÕÉ¥Ñå}ÁÉ½™¥±”°(€€€€€€€€¤(€€€€€€€‘•µ¼€ôÍ•±˜¹½µµ•É¥…±}‘•µ½}Í•¹…É¥½}É•Á½ÉÐ (€€€€€€€€€€€Ñ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜõÑ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜ°(€€€€€€€€€€€±½…±•}‰Õ¹‘±•Ìõ±½…±•}‰Õ¹‘±•Ì°(€€€€€€€€€€€Í•ÕÉ¥Ñå}ÁÉ½™¥±”õÍ•ÕÉ¥Ñå}ÁÉ½™¥±”°(€€€€€€€€¤(€€€€€€€‰Õå•É}Ý½É­™±½Ü€ôÍ•±˜¹½µµ•É¥…±}‰Õå•É}…•ÁÑ…¹•}Ý½É­™±½Ý}É•Á½ÉÐ (€€€€€€€€€€€Ñ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜõÑ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜ°(€€€€€€€€€€€±½…±•}‰Õ¹‘±•Ìõ±½…±•}‰Õ¹‘±•Ì°(€€€€€€€€€€€Í•ÕÉ¥Ñå}ÁÉ½™¥±”õÍ•ÕÉ¥Ñå}ÁÉ½™¥±”°(€€€€€€€€¤(€€€€€€€±½Í”€ôÍ•±˜¹½µµ•É¥…±}±½Í•}É•…‘¥¹•ÍÍ}É•Á½ÉÐ (€€€€€€€€€€€Ñ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜõÑ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜ°(€€€€€€€€€€€±½…±•}‰Õ¹‘±•Ìõ±½…±•}‰Õ¹‘±•Ì°(€€€€€€€€€€€Í•ÕÉ¥Ñå}ÁÉ½™¥±”õÍ•ÕÉ¥Ñå}ÁÉ½™¥±”°(€€€€€€€€¤(€€€€€€€ÁÉ½ÕÉ•µ•¹Ð€ôÍ•±˜¹½µµ•É¥…±}ÁÉ½ÕÉ•µ•¹Ñ}É•…‘¥¹•ÍÍ}É•Á½ÉÐ (€€€€€€€€€€€Ñ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜõÑ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜ°(€€€€€€€€€€€±½…±•}‰Õ¹‘±•Ìõ±½…±•}‰Õ¹‘±•Ì°(€€€€€€€€€€€Í•ÕÉ¥Ñå}ÁÉ½™¥±”õÍ•ÕÉ¥Ñå}ÁÉ½™¥±”°(€€€€€€€€¤(€€€€€€€½¹ÑÉ…Ð€ôÍ•±˜¹½µµ•É¥…±}½¹ÑÉ…Ñ}É•…‘¥¹•ÍÍ}É•Á½ÉÐ (€€€€€€€€€€€Ñ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜõÑ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜ°(€€€€€€€€€€€±½…±•}‰Õ¹‘±•Ìõ±½…±•}‰Õ¹‘±•Ì°(€€€€€€€€€€€Í•ÕÉ¥Ñå}ÁÉ½™¥±”õÍ•ÕÉ¥Ñå}ÁÉ½™¥±”°(€€€€€€€€¤(€€€€€€€Ù…±Õ”€ôÍ•±˜¹½µµ•É¥…±}Ù…±Õ•}É•…‘¥¹•ÍÍ}É•Á½ÉÐ (€€€€€€€€€€€Ñ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜõÑ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜ°(€€€€€€€€€€€±½…±•}‰Õ¹‘±•Ìõ±½…±•}‰Õ¹‘±•Ì°(€€€€€€€€€€€Í•ÕÉ¥Ñå}ÁÉ½™¥±”õÍ•ÕÉ¥Ñå}ÁÉ½™¥±”°(€€€€€€€€¤(€€€€€€€Í•ÕÉ¥Ñä€ôÍ•±˜¹½µµ•É¥…±}Í•ÕÉ¥Ñå}…ÑÑ•ÍÑ…Ñ¥½¹}É•Á½ÉÐ (€€€€€€€€€€€Ñ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜõÑ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜ°(€€€€€€€€€€€±½…±•}‰Õ¹‘±•Ìõ±½…±•}‰Õ¹‘±•Ì°(€€€€€€€€€€€Í•ÕÉ¥Ñå}ÁÉ½™¥±”õÍ•ÕÉ¥Ñå}ÁÉ½™¥±”°(€€€€€€€€¤(€€€€€€€½¹‰½…É‘¥¹œ€ôÍ•±˜¹½µµ•É¥…±}½¹‰½…É‘¥¹}É•…‘¥¹•ÍÍ}É•Á½ÉÐ (€€€€€€€€€€€Ñ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜõÑ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜ°(€€€€€€€€€€€±½…±•}‰Õ¹‘±•Ìõ±½…±•}‰Õ¹‘±•Ì°(€€€€€€€€€€€Í•ÕÉ¥Ñå}ÁÉ½™¥±”õÍ•ÕÉ¥Ñå}ÁÉ½™¥±”°(€€€€€€€€¤(€€€€€€€½Á•É…Ñ¥½¹Ì€ôÍ•±˜¹½µµ•É¥…±}½Á•É…Ñ¥½¹Í}É•…‘¥¹•ÍÍ}É•Á½ÉÐ (€€€€€€€€€€€Ñ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜõÑ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜ°(€€€€€€€€€€€±½…±•}‰Õ¹‘±•Ìõ±½…±•}‰Õ¹‘±•Ì°(€€€€€€€€€€€Í•ÕÉ¥Ñå}ÁÉ½™¥±”õÍ•ÕÉ¥Ñå}ÁÉ½™¥±”°(€€€€€€€€¤(€€€€€€€…¹…±åÑ¥Ì€ôÍ•±˜¹…¹…±åÑ¥Í}Í¹…ÁÍ¡½Ð¡±½…±•}‰Õ¹‘±•Ìõ±½…±•}‰Õ¹‘±•Ì¤(€€€€€€€…‘µ¥¹}ÍÑ…Ñ”€ôÍ•±˜¹…‘µ¥¹}ÍÑ…Ñ” ¤(€€€€€€€É½½Ð€ôA…Ñ ¡}}™¥±•}|¤¹É•Í½±Ù” ¤¹Á…É•¹ÑÍlÅt((€€€€€€€‘•˜¡…Í}™¥±”¡Á…Ñ èÍÑÈ¤€´ø‰½½°è(€€€€€€€€€€€É•ÑÕÉ¸€¡É½½Ð€¼Á…Ñ ¤¹¥Í}™¥±” ¤((€€€€€€€‘•˜…±±}™¥±•Ì ©Á…Ñ¡ÌèÍÑÈ¤€´ø‰½½°è(€€€€€€€€€€€É•ÑÕÉ¸…±°¡¡…Í}™¥±”¡Á…Ñ ¤™½ÈÁ…Ñ ¥¸Á…Ñ¡Ì¤((€€€€€€€‘•˜Í•Ñ¥½¸ (€€€€€€€€€€€Í•Ñ¥½¹}¹…µ”èÍÑÈ°(€€€€€€€€€€€±…‰•°èÍÑÈ°(€€€€€€€€€€€É•Ù¥•Ý•ÈèÍÑÈ°(€€€€€€€€€€€Í½ÕÉ•Ìè±¥ÍÑmÍÑÉt°(€€€€€€€€€€€ÉÕ¹Ñ¥µ•}•¹‘Á½¥¹ÑÌè±¥ÍÑmÍÑÉt°(€€€€€€€€€€€•Ù¥‘•¹•}ÑåÁ”èÍÑÈ°(€€€€€€€€€€€½µÁ±•Ñ¥½¹}ÍÑ…Ñ”èÍÑÈ°(€€€€€€€€€€€•Ù¥‘•¹”èÍÑÈ°(€€€€€€€€€€€½µµ¥ÑÑ••}ÅÕ•ÍÑ¥½¸èÍÑÈ°(€€€€€€€€€€€¹•áÑ}…Ñ¥½¸èÍÑÈ°(€€€€€€€€¤€´ø‘¥ÑmÍÑÈ°¹åtè(€€€€€€€€€€€É•ÅÕ¥É•}½‰©•Ñ}¹…µ”¡Í•Ñ¥½¹}¹…µ”°€‰½µµ•É¥…±}¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ•”¹Í•Ñ¥½¹}¹…µ”ˆ¤(€€€€€€€€€€€¥˜½µÁ±•Ñ¥½¹}ÍÑ…Ñ”¹½Ð¥¸ì‰É•…‘äˆ°€‰Ý…É¹¥¹œˆ°€‰‰±½­•‰ôè€€ŒÁÉ…µ„è¹¼½Ù•È(€€€€€€€€€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È ‰½µµ•É¥…°¥¹Ù•ÍÑµ•¹Ð½µµ¥ÑÑ•”Í•Ñ¥½¸ÍÑ…Ñ”µÕÍÐ‰”É•…‘ä°Ý…É¹¥¹œ°½È‰±½­•ˆ¤(€€€€€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€€€€€‰Í•Ñ¥½¹}¹…µ”ˆèÍ•Ñ¥½¹}¹…µ”°(€€€€€€€€€€€€€€€€‰±…‰•°ˆè±…‰•°°(€€€€€€€€€€€€€€€€‰É•Ù¥•Ý•ÈˆèÉ•Ù¥•Ý•È°(€€€€€€€€€€€€€€€€‰Í½ÕÉ•ÌˆèÍ½ÕÉ•Ì°(€€€€€€€€€€€€€€€€‰ÉÕ¹Ñ¥µ•}•¹‘Á½¥¹ÑÌˆèÉÕ¹Ñ¥µ•}•¹‘Á½¥¹ÑÌ°(€€€€€€€€€€€€€€€€‰•Ù¥‘•¹•}ÑåÁ”ˆè•Ù¥‘•¹•}ÑåÁ”°(€€€€€€€€€€€€€€€€‰½µÁ±•Ñ¥½¹}ÍÑ…Ñ”ˆè½µÁ±•Ñ¥½¹}ÍÑ…Ñ”°(€€€€€€€€€€€€€€€€‰•Ù¥‘•¹”ˆè•Ù¥‘•¹”°(€€€€€€€€€€€€€€€€‰½µµ¥ÑÑ••}ÅÕ•ÍÑ¥½¸ˆè½µµ¥ÑÑ••}ÅÕ•ÍÑ¥½¸°(€€€€€€€€€€€€€€€€‰¹•áÑ}…Ñ¥½¸ˆè¹•áÑ}…Ñ¥½¸°(€€€€€€€€€€€ô((€€€€€€€½¹É•Ñ•}‰±½­•ÉÌ€ô±¥ÍÐ (€€€€€€€€€€€‘¥Ð¹™É½µ­•åÌ (€€€€€€€€€€€€€€€‘Õ•}‘¥±¥•¹•l‰½¹É•Ñ•}‰±½­•ÉÌ‰t(€€€€€€€€€€€€€€€€¬ÁÕÉ¡…Í•l‰½¹É•Ñ•}‰±½­•ÉÌ‰t(€€€€€€€€€€€€€€€€¬ÁÉ½Á½Í…±l‰½¹É•Ñ•}‰±½­•ÉÌ‰t(€€€€€€€€€€€€€€€€¬½µÁ±•Ñ¥½¹l‰½¹É•Ñ•}‰±½­•ÉÌ‰t(€€€€€€€€€€€€€€€€¬‘•µ½l‰½¹É•Ñ•}‰±½­•ÉÌ‰t(€€€€€€€€€€€€€€€€¬‰Õå•É}Ý½É­™±½Ýl‰½¹É•Ñ•}‰±½­•ÉÌ‰t(€€€€€€€€€€€€¤(€€€€€€€€¤(€€€€€€€±½…±}ÉÕ¹Ñ¥µ•}ÍÑ…Ñ”€ô€ (€€€€€€€€€€€€‰‰±½­•ˆ(€€€€€€€€€€€¥˜‘Õ•}‘¥±¥•¹•l‰‘Õ•}‘¥±¥•¹•}ÍÑ…ÑÕÌ‰t€ôô€‰½µµ•É¥…±}‘Õ•}‘¥±¥•¹•}‰±½­•ˆ(€€€€€€€€€€€½ÈÁÕÉ¡…Í•l‰ÁÕÉ¡…Í•}…ÁÁÉ½Ù…±}ÍÑ…ÑÕÌ‰t€ôô€‰½µµ•É¥…±}ÁÕÉ¡…Í•}…ÁÁÉ½Ù…±}‰±½­•ˆ(€€€€€€€€€€€½ÈÁÉ½Á½Í…±l‰ÁÉ½Á½Í…±}ÍÑ…ÑÕÌ‰t€ôô€‰½µµ•É¥…±}ÁÉ½Á½Í…±}‰±½­•ˆ(€€€€€€€€€€€½È½µÁ±•Ñ¥½¹l‰½µÁ±•Ñ¥½¹}ÍÑ…ÑÕÌ‰t€ôô€‰½µµ•É¥…±}½µÁ±•Ñ¥½¹}‰±½­•ˆ(€€€€€€€€€€€½È‘•µ½l‰‘•µ½}ÍÑ…ÑÕÌ‰t€ôô€‰½µµ•É¥…±}‘•µ½}‰±½­•ˆ(€€€€€€€€€€€½È‰Õå•É}Ý½É­™±½Ýl‰Ý½É­™±½Ý}ÍÑ…ÑÕÌ‰t€ôô€‰‰Õå•É}…•ÁÑ…¹•}Ý½É­™±½Ý}‰±½­•ˆ(€€€€€€€€€€€½È½¹É•Ñ•}‰±½­•ÉÌ(€€€€€€€€€€€•±Í”€‰É•…‘äˆ(€€€€€€€€¤(€€€€€€€µ•µ½}Í•Ñ¥½¹Ì€ôl(€€€€€€€€€€€Í•Ñ¥½¸ (€€€€€€€€€€€€€€€€‰•á•ÕÑ¥Ù•}É•½µµ•¹‘…Ñ¥½¸ˆ°(€€€€€€€€€€€€€€€€‰á•ÕÑ¥Ù”É•½µµ•¹‘…Ñ¥½¸ˆ°(€€€€€€€€€€€€€€€€‰%¹Ù•ÍÑµ•¹Ð½µµ¥ÑÑ•”¡…¥Èˆ°(€€€€€€€€€€€€€€€l(€€€€€€€€€€€€€€€€€€€€‰‘½Ì½½µµ•É¥…±}¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}µ•µ¼¹µˆ°(€€€€€€€€€€€€€€€€€€€€‰‘½Ì½™¥µ…}…ÉÑ¥™…ÑÌ¹µˆ°(€€€€€€€€€€€€€€€€€€€€‰‘½Ì½ÍÕÁ•ÉÁ½Ý•ÉÌ½Á±…¹Ì¼ÈÀÈØ´ÀÜ´ÀÈµ½µµ•É¥…°µ¥¹Ù•ÍÑµ•¹Ðµ½µµ¥ÑÑ•”µµ•µ¼µÉÕ¹Ñ¥µ”¹µˆ°(€€€€€€€€€€€€€€€t°(€€€€€€€€€€€€€€€lˆ½…Á¤½ØÄ½½µµ•É¥…±}¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}µ•µ½Ì½±…Ñ•ÍÐ‰t°(€€€€€€€€€€€€€€€€‰É•Á½Í¥Ñ½Éå}…¹‘}ÉÕ¹Ñ¥µ•}…ÉÑ¥™…Ðˆ°(€€€€€€€€€€€€€€€±½…±}ÉÕ¹Ñ¥µ•}ÍÑ…Ñ”(€€€€€€€€€€€€€€€¥˜…±±}™¥±•Ì (€€€€€€€€€€€€€€€€€€€€‰‘½Ì½½µµ•É¥…±}¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}µ•µ¼¹µˆ°(€€€€€€€€€€€€€€€€€€€€‰‘½Ì½™¥µ…}…ÉÑ¥™…ÑÌ¹µˆ°(€€€€€€€€€€€€€€€€€€€€‰‘½Ì½ÍÕÁ•ÉÁ½Ý•ÉÌ½Á±…¹Ì¼ÈÀÈØ´ÀÜ´ÀÈµ½µµ•É¥…°µ¥¹Ù•ÍÑµ•¹Ðµ½µµ¥ÑÑ•”µµ•µ¼µÉÕ¹Ñ¥µ”¹µˆ°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€•±Í”€‰‰±½­•ˆ°(€€€€€€€€€€€€€€€€‰%¹Ù•ÍÑµ•¹Ð½µµ¥ÑÑ•”µ•µ¼°¥)…´…ÉÑ¥™…ÐÉ•½É°…¹¥µÁ±•µ•¹Ñ…Ñ¥½¸Á±…¸…É”½µµ¥ÑÑ•¸ˆ°(€€€€€€€€€€€€€€€€‰…¸Ñ¡”½µµ¥ÑÑ•”É•½µµ•¹Ñ¡”-I\€ÉÁÕÉ¡…Í”Á…Ñ Ý¥Ñ •áÁ±¥¥Ð½¹‘¥Ñ¥½¹Ìüˆ°(€€€€€€€€€€€€€€€€‰UÍ”Ñ¡¥Ìµ•µ¼…ÌÑ¡”•á•ÕÑ¥Ù”‘•¥Í¥½¸½Ù•È…ÉÑ¥™…Ð¸ˆ°(€€€€€€€€€€€€¤°(€€€€€€€€€€€Í•Ñ¥½¸ (€€€€€€€€€€€€€€€€‰‘¥±¥•¹•}É½½µ}É•…‘äˆ°(€€€€€€€€€€€€€€€€‰Õ”‘¥±¥•¹”É½½´É•…‘äˆ°(€€€€€€€€€€€€€€€€‰¥±¥•¹”½Ý¹•Èˆ°(€€€€€€€€€€€€€€€l‰‘½Ì½½µµ•É¥…±}‘Õ•}‘¥±¥•¹•}É½½´¹µˆ°€ˆ½…Á¤½ØÄ½½µµ•É¥…±}‘Õ•}‘¥±¥•¹•}É½½µÌ½±…Ñ•ÍÐ‰t°(€€€€€€€€€€€€€€€lˆ½…Á¤½ØÄ½½µµ•É¥…±}‘Õ•}‘¥±¥•¹•}É½½µÌ½±…Ñ•ÍÐ‰t°(€€€€€€€€€€€€€€€€‰É•Á½Í¥Ñ½Éå}…¹‘}ÉÕ¹Ñ¥µ•}…ÉÑ¥™…Ðˆ°(€€€€€€€€€€€€€€€±½…±}ÉÕ¹Ñ¥µ•}ÍÑ…Ñ”¥˜¡…Í}™¥±” ‰‘½Ì½½µµ•É¥…±}‘Õ•}‘¥±¥•¹•}É½½´¹µˆ¤•±Í”€‰‰±½­•ˆ°(€€€€€€€€€€€€€€€˜‰½µµ•É¥…±}‘Õ•}‘¥±¥•¹•}ÍÑ…ÑÕÌõí‘Õ•}‘¥±¥•¹•l‘Õ•}‘¥±¥•¹•}ÍÑ…ÑÕÌuôˆ°(€€€€€€€€€€€€€€€€‰…¸Ñ¡”µ•µ¼Á½¥¹ÐÑ¼„½µÁ±•Ñ”‘¥±¥•¹”É½½´üˆ°(€€€€€€€€€€€€€€€€‰I•™•É•¹”‘Õ”‘¥±¥•¹”É½½´Í•Ñ¥½¹Ì¥¹ÍÑ•…½˜‘ÕÁ±¥…Ñ¥¹œ•Ù¥‘•¹”¸ˆ°(€€€€€€€€€€€€¤°(€€€€€€€€€€€Í•Ñ¥½¸ (€€€€€€€€€€€€€€€€‰ÁÕÉ¡…Í•}…ÁÁÉ½Ù…±}É•…‘äˆ°(€€€€€€€€€€€€€€€€‰AÕÉ¡…Í”…ÁÁÉ½Ù…°É•…‘äˆ°(€€€€€€€€€€€€€€€€‰AÕÉ¡…Í”ÍÁ½¹Í½Èˆ°(€€€€€€€€€€€€€€€l‰‘½Ì½½µµ•É¥…±}ÁÕÉ¡…Í•}…ÁÁÉ½Ù…±}Á…­•Ð¹µˆ°€ˆ½…Á¤½ØÄ½½µµ•É¥…±}ÁÕÉ¡…Í•}…ÁÁÉ½Ù…±}Á…­•ÑÌ½±…Ñ•ÍÐ‰t°(€€€€€€€€€€€€€€€lˆ½…Á¤½ØÄ½½µµ•É¥…±}ÁÕÉ¡…Í•}…ÁÁÉ½Ù…±}Á…­•ÑÌ½±…Ñ•ÍÐ‰t°(€€€€€€€€€€€€€€€€‰É•Á½Í¥Ñ½Éå}…¹‘}ÉÕ¹Ñ¥µ•}…ÉÑ¥™…Ðˆ°(€€€€€€€€€€€€€€€±½…±}ÉÕ¹Ñ¥µ•}ÍÑ…Ñ”¥˜¡…Í}™¥±” ‰‘½Ì½½µµ•É¥…±}ÁÕÉ¡…Í•}…ÁÁÉ½Ù…±}Á…­•Ð¹µˆ¤•±Í”€‰‰±½­•ˆ°(€€€€€€€€€€€€€€€˜‰½µµ•É¥…±}ÁÕÉ¡…Í•}…ÁÁÉ½Ù…±}ÍÑ…ÑÕÌõíÁÕÉ¡…Í•lÁÕÉ¡…Í•}…ÁÁÉ½Ù…±}ÍÑ…ÑÕÌuôˆ°(€€€€€€€€€€€€€€€€‰…¸Ñ¡”½µµ¥ÑÑ•”Í•”™¥¹…¹”°ÁÉ½ÕÉ•µ•¹Ð°±•…°°Í•ÕÉ¥Ñä°…¹¥µÁ±•µ•¹Ñ…Ñ¥½¸…Ñ•Ìüˆ°(€€€€€€€€€€€€€€€€‰UÍ”Ñ¡”ÁÕÉ¡…Í”…ÁÁÉ½Ù…°Á…­•Ð…Ì½µµ¥ÑÑ•”…ÁÁ•¹‘¥à¸ˆ°(€€€€€€€€€€€€¤°(€€€€€€€€€€€Í•Ñ¥½¸ (€€€€€€€€€€€€€€€€‰™¥¹…¹¥…±}…Í”ˆ°(€€€€€€€€€€€€€€€€‰¥¹…¹¥…°…Í”ˆ°(€€€€€€€€€€€€€€€€‰½¹½µ¥Œ‰Õå•Èˆ°(€€€€€€€€€€€€€€€l‰‘½Ì½½µµ•É¥…±}Ù…±Õ•}É•…‘¥¹•ÍÌ¹µˆ°€‰‘½Ì½…¹…±åÑ¥Í}ÍÁ•Œ¹µˆ°€ˆ½…Á¤½ØÄ½…¹…±åÑ¥Í}Í¹…ÁÍ¡½ÑÌ½±…Ñ•ÍÐ‰t°(€€€€€€€€€€€€€€€lˆ½…Á¤½ØÄ½½µµ•É¥…±}Ù…±Õ•}É•…‘¥¹•ÍÌ½±…Ñ•ÍÐˆ°€ˆ½…Á¤½ØÄ½…¹…±åÑ¥Í}Í¹…ÁÍ¡½ÑÌ½±…Ñ•ÍÐ‰t°(€€€€€€€€€€€€€€€€‰É•Á½Í¥Ñ½Éå}…¹‘}ÉÕ¹Ñ¥µ•}…ÉÑ¥™…Ðˆ°(€€€€€€€€€€€€€€€€‰É•…‘äˆ(€€€€€€€€€€€€€€€¥˜Ù…±Õ•l‰Ù…±Õ•}ÍÑ…ÑÕÌ‰t€„ô€‰½µµ•É¥…±}Ù…±Õ•}‰±½­•ˆ(€€€€€€€€€€€€€€€…¹…¹…±åÑ¥Íl‰µ•…ÍÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌ‰t€ôô€‰±½…±}ÉÕ¹Ñ¥µ•}Í¹…ÁÍ¡½Ðˆ(€€€€€€€€€€€€€€€…¹…±±}™¥±•Ì ‰‘½Ì½½µµ•É¥…±}Ù…±Õ•}É•…‘¥¹•ÍÌ¹µˆ°€‰‘½Ì½…¹…±åÑ¥Í}ÍÁ•Œ¹µˆ¤(€€€€€€€€€€€€€€€•±Í”€‰‰±½­•ˆ°(€€€€€€€€€€€€€€€˜‰½µµ•É¥…±}Ù…±Õ•}ÍÑ…ÑÕÌõíÙ…±Õ•lÙ…±Õ•}ÍÑ…ÑÕÌuôì…¹…±åÑ¥Í}µ•…ÍÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌõí…¹…±åÑ¥Ílµ•…ÍÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌuôˆ°(€€€€€€€€€€€€€€€€‰½•ÌÑ¡”µ•µ¼Í•Á…É…Ñ”µ•…ÍÕÉ•±½…°•Ù¥‘•¹”™É½´‰Õå•ÈI=$…ÍÍÕµÁÑ¥½¹Ìüˆ°(€€€€€€€€€€€€€€€€‰ÑÑ… ‰Õå•ÈI=$µ½‘•°½¹±ä…™Ñ•È‰Õå•È‘¥Í½Ù•ÉäÍÕÁÁ±¥•Ì¥Ð¸ˆ°(€€€€€€€€€€€€¤°(€€€€€€€€€€€Í•Ñ¥½¸ (€€€€€€€€€€€€€€€€‰É¥Í­}…¹‘}Í•ÕÉ¥Ñå}ÍÕµµ…Éäˆ°(€€€€€€€€€€€€€€€€‰I¥Í¬…¹Í•ÕÉ¥ÑäÍÕµµ…Éäˆ°(€€€€€€€€€€€€€€€€‰M•ÕÉ¥ÑäÉ•Ù¥•Ý•Èˆ°(€€€€€€€€€€€€€€€l‰MUI%Qd¹µˆ°€‰‘½Ì½½µµ•É¥…±}Í•ÕÉ¥Ñå}…ÑÑ•ÍÑ…Ñ¥½¸¹µˆ°€ˆ½…Á¤½ØÄ½½µµ•É¥…±}Í•ÕÉ¥Ñå}…ÑÑ•ÍÑ…Ñ¥½¹Ì½±…Ñ•ÍÐ‰t°(€€€€€€€€€€€€€€€lˆ½…Á¤½ØÄ½½µµ•É¥…±}Í•ÕÉ¥Ñå}…ÑÑ•ÍÑ…Ñ¥½¹Ì½±…Ñ•ÍÐ‰t°(€€€€€€€€€€€€€€€€‰É•Á½Í¥Ñ½Éå}…¹‘}ÉÕ¹Ñ¥µ•}…ÉÑ¥™…Ðˆ°(€€€€€€€€€€€€€€€€‰É•…‘äˆ(€€€€€€€€€€€€€€€¥˜Í•ÕÉ¥Ñål‰Í•ÕÉ¥Ñå}…ÑÑ•ÍÑ…Ñ¥½¹}ÍÑ…ÑÕÌ‰t€„ô€‰½µµ•É¥…±}Í•ÕÉ¥Ñå}…ÑÑ•ÍÑ…Ñ¥½¹}‰±½­•ˆ(€€€€€€€€€€€€€€€…¹…±±}™¥±•Ì ‰MUI%Qd¹µˆ°€‰‘½Ì½½µµ•É¥…±}Í•ÕÉ¥Ñå}…ÑÑ•ÍÑ…Ñ¥½¸¹µˆ¤(€€€€€€€€€€€€€€€•±Í”€‰‰±½­•ˆ°(€€€€€€€€€€€€€€€˜‰½µµ•É¥…±}Í•ÕÉ¥Ñå}…ÑÑ•ÍÑ…Ñ¥½¹}ÍÑ…ÑÕÌõíÍ•ÕÉ¥ÑålÍ•ÕÉ¥Ñå}…ÑÑ•ÍÑ…Ñ¥½¹}ÍÑ…ÑÕÌuôˆ°(€€€€€€€€€€€€€€€€‰É”Í•ÕÉ¥ÑäÉ¥Í­Ì•áÁ±¥¥ÐÝ¥Ñ¡½ÕÐ±…¥µ¥¹œ•áÑ•É¹…°•ÉÑ¥™¥…Ñ¥½¸üˆ°(€€€€€€€€€€€€€€€€‰-••ÀÑ¡¥ÉµÁ…ÉÑä…ÑÑ•ÍÑ…Ñ¥½¸½ÕÑÍ¥‘”µ•…ÍÕÉ•±½…°•Ù¥‘•¹”¸ˆ°(€€€€€€€€€€€€¤°(€€€€€€€€€€€Í•Ñ¥½¸ (€€€€€€€€€€€€€€€€‰½µµ•É¥…±}Ñ•ÉµÍ}ÍÕµµ…Éäˆ°(€€€€€€€€€€€€€€€€‰½µµ•É¥…°Ñ•ÉµÌÍÕµµ…Éäˆ°(€€€€€€€€€€€€€€€€‰1•…°…¹ÁÉ½ÕÉ•µ•¹ÐÉ•Ù¥•Ý•ÉÌˆ°(€€€€€€€€€€€€€€€l(€€€€€€€€€€€€€€€€€€€€‰‘½Ì½½µµ•É¥…±}½¹ÑÉ…Ñ}É•…‘¥¹•ÍÌ¹µˆ°(€€€€€€€€€€€€€€€€€€€€‰‘½Ì½½µµ•É¥…±}ÁÉ½ÕÉ•µ•¹Ñ}É•…‘¥¹•ÍÌ¹µˆ°(€€€€€€€€€€€€€€€€€€€€‰‘½Ì½½µµ•É¥…±}±½Í•}É•…‘¥¹•ÍÌ¹µˆ°(€€€€€€€€€€€€€€€t°(€€€€€€€€€€€€€€€l(€€€€€€€€€€€€€€€€€€€€ˆ½…Á¤½ØÄ½½µµ•É¥…±}½¹ÑÉ…Ñ}É•…‘¥¹•ÍÌ½±…Ñ•ÍÐˆ°(€€€€€€€€€€€€€€€€€€€€ˆ½…Á¤½ØÄ½½µµ•É¥…±}ÁÉ½ÕÉ•µ•¹Ñ}É•…‘¥¹•ÍÌ½±…Ñ•ÍÐˆ°(€€€€€€€€€€€€€€€€€€€€ˆ½…Á¤½ØÄ½½µµ•É¥…±}±½Í•}É•…‘¥¹•ÍÌ½±…Ñ•ÍÐˆ°(€€€€€€€€€€€€€€€t°(€€€€€€€€€€€€€€€€‰É•Á½Í¥Ñ½Éå}…¹‘}ÉÕ¹Ñ¥µ•}…ÉÑ¥™…Ðˆ°(€€€€€€€€€€€€€€€€‰É•…‘äˆ(€€€€€€€€€€€€€€€¥˜½¹ÑÉ…Ñl‰½¹ÑÉ…Ñ}ÍÑ…ÑÕÌ‰t€„ô€‰½µµ•É¥…±}½¹ÑÉ…Ñ}‰±½­•ˆ(€€€€€€€€€€€€€€€…¹ÁÉ½ÕÉ•µ•¹Ñl‰ÁÉ½ÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌ‰t€„ô€‰½µµ•É¥…±}ÁÉ½ÕÉ•µ•¹Ñ}‰±½­•ˆ(€€€€€€€€€€€€€€€…¹±½Í•l‰±½Í•}ÍÑ…ÑÕÌ‰t€„ô€‰½µµ•É¥…±}±½Í•}‰±½­•ˆ(€€€€€€€€€€€€€€€…¹…±±}™¥±•Ì (€€€€€€€€€€€€€€€€€€€€‰‘½Ì½½µµ•É¥…±}½¹ÑÉ…Ñ}É•…‘¥¹•ÍÌ¹µˆ°(€€€€€€€€€€€€€€€€€€€€‰‘½Ì½½µµ•É¥…±}ÁÉ½ÕÉ•µ•¹Ñ}É•…‘¥¹•ÍÌ¹µˆ°(€€€€€€€€€€€€€€€€€€€€‰‘½Ì½½µµ•É¥…±}±½Í•}É•…‘¥¹•ÍÌ¹µˆ°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€•±Í”€‰‰±½­•ˆ°(€€€€€€€€€€€€€€€€ (€€€€€€€€€€€€€€€€€€€˜‰½µµ•É¥…±}½¹ÑÉ…Ñ}ÍÑ…ÑÕÌõí½¹ÑÉ…Ñl½¹ÑÉ…Ñ}ÍÑ…ÑÕÌuôì€ˆ(€€€€€€€€€€€€€€€€€€€˜‰½µµ•É¥…±}ÁÉ½ÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌõíÁÉ½ÕÉ•µ•¹ÑlÁÉ½ÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌuôì€ˆ(€€€€€€€€€€€€€€€€€€€˜‰½µµ•É¥…±}±½Í•}ÍÑ…ÑÕÌõí±½Í•l±½Í•}ÍÑ…ÑÕÌuôˆ(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€‰…¸±•…°…¹ÁÉ½ÕÉ•µ•¹Ð½¹‘¥Ñ¥½¹Ì‰”…ÁÁÉ½Ù•½ÈÑÉ…­•üˆ°(€€€€€€€€€€€€€€€€‰ÑÑ… ½É‘•Èµ™½É´‘•Ñ…¥±Ì½¹±ä…™Ñ•È‰Õå•È±•…°É•Ù¥•Ü¸ˆ°(€€€€€€€€€€€€¤°(€€€€€€€€€€€Í•Ñ¥½¸ (€€€€€€€€€€€€€€€€‰¥µÁ±•µ•¹Ñ…Ñ¥½¹}É•…‘¥¹•ÍÍ}ÍÕµµ…Éäˆ°(€€€€€€€€€€€€€€€€‰%µÁ±•µ•¹Ñ…Ñ¥½¸É•…‘¥¹•ÍÌÍÕµµ…Éäˆ°(€€€€€€€€€€€€€€€€‰%µÁ±•µ•¹Ñ…Ñ¥½¸½Ý¹•Èˆ°(€€€€€€€€€€€€€€€l‰‘½Ì½½µµ•É¥…±}½¹‰½…É‘¥¹}É•…‘¥¹•ÍÌ¹µˆ°€‰‘½Ì½½µµ•É¥…±}½Á•É…Ñ¥½¹Í}É•…‘¥¹•ÍÌ¹µ‰t°(€€€€€€€€€€€€€€€lˆ½…Á¤½ØÄ½½µµ•É¥…±}½¹‰½…É‘¥¹}É•…‘¥¹•ÍÌ½±…Ñ•ÍÐˆ°€ˆ½…Á¤½ØÄ½½µµ•É¥…±}½Á•É…Ñ¥½¹Í}É•…‘¥¹•ÍÌ½±…Ñ•ÍÐ‰t°(€€€€€€€€€€€€€€€€‰É•Á½Í¥Ñ½Éå}…¹‘}ÉÕ¹Ñ¥µ•}…ÉÑ¥™…Ðˆ°(€€€€€€€€€€€€€€€€‰É•…‘äˆ(€€€€€€€€€€€€€€€¥˜½¹‰½…É‘¥¹l‰½¹‰½…É‘¥¹}ÍÑ…ÑÕÌ‰t€„ô€‰½µµ•É¥…±}½¹‰½…É‘¥¹}‰±½­•ˆ(€€€€€€€€€€€€€€€…¹½Á•É…Ñ¥½¹Íl‰½Á•É…Ñ¥½¹Í}ÍÑ…ÑÕÌ‰t€„ô€‰½µµ•É¥…±}½Á•É…Ñ¥½¹Í}‰±½­•ˆ(€€€€€€€€€€€€€€€…¹…±±}™¥±•Ì ‰‘½Ì½½µµ•É¥…±}½¹‰½…É‘¥¹}É•…‘¥¹•ÍÌ¹µˆ°€‰‘½Ì½½µµ•É¥…±}½Á•É…Ñ¥½¹Í}É•…‘¥¹•ÍÌ¹µˆ¤(€€€€€€€€€€€€€€€•±Í”€‰‰±½­•ˆ°(€€€€€€€€€€€€€€€˜‰½µµ•É¥…±}½¹‰½…É‘¥¹}ÍÑ…ÑÕÌõí½¹‰½…É‘¥¹l½¹‰½…É‘¥¹}ÍÑ…ÑÕÌuôì½µµ•É¥…±}½Á•É…Ñ¥½¹Í}ÍÑ…ÑÕÌõí½Á•É…Ñ¥½¹Íl½Á•É…Ñ¥½¹Í}ÍÑ…ÑÕÌuôˆ°(€€€€€€€€€€€€€€€€‰…¸¥µÁ±•µ•¹Ñ…Ñ¥½¸ÍÑ…ÉÐ…™Ñ•È‰Õå•È•¹Ù¥É½¹µ•¹Ð‘•Ñ…¥±Ì…É”ÍÕÁÁ±¥•üˆ°(€€€€€€€€€€€€€€€€‰½¹Ù•ÉÐ‰Õå•È•¹Ù¥É½¹µ•¹Ð‘•Ñ…¥±Ì¥¹Ñ¼Ñ¡”Á…¥½¹‰½…É‘¥¹œÁ±…¸¸ˆ°(€€€€€€€€€€€€¤°(€€€€€€€€€€€Í•Ñ¥½¸ (€€€€€€€€€€€€€€€€‰‘•Í¥¹}…¹‘}™¥µ…}É•Ù¥•Üˆ°(€€€€€€€€€€€€€€€€‰•Í¥¸…¹¥µ„É•Ù¥•Üˆ°(€€€€€€€€€€€€€€€€‰AÉ½‘ÕÐ‘•Í¥¸É•Ù¥•Ý•Èˆ°(€€€€€€€€€€€€€€€l‰‘½Ì½™¥µ…}…ÉÑ¥™…ÑÌ¹µˆ°€‰‘½Ì½½µµ•É¥…±}¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}µ•µ¼¹µ‰t°(€€€€€€€€€€€€€€€lˆ½…Á¤½ØÄ½½µµ•É¥…±}¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}µ•µ½Ì½±…Ñ•ÍÐ‰t°(€€€€€€€€€€€€€€€€‰É•Á½Í¥Ñ½Éå}…¹‘}ÉÕ¹Ñ¥µ•}…ÉÑ¥™…Ðˆ°(€€€€€€€€€€€€€€€€‰É•…‘äˆ¥˜…±±}™¥±•Ì ‰‘½Ì½™¥µ…}…ÉÑ¥™…ÑÌ¹µˆ°€‰‘½Ì½½µµ•É¥…±}¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}µ•µ¼¹µˆ¤•±Í”€‰‰±½­•ˆ°(€€€€€€€€€€€€€€€€‰¥)…´µ•µ¼™±½Ü…¹AÉ½‘ÕÐ•Í¥¸Í½Á”…É”É•½É‘•Ý¥Ñ¡½ÕÐ½‘”½¹¹•Ð¸ˆ°(€€€€€€€€€€€€€€€€‰…¸ÍÑ…­•¡½±‘•ÉÌ¥¹ÍÁ•ÐÑ¡”µ•µ¼™±½Ü¥¸¥)…´…¹ÉÕ¹Ñ¥µ”)M=8üˆ°(€€€€€€€€€€€€€€€€‰-••À¥µ„½‘”½¹¹•Ð½ÕÐ½˜Ñ¡”½µµ¥ÑÑ•”Ý½É­™±½Ü¸ˆ°(€€€€€€€€€€€€¤°(€€€€€€€€€€€Í•Ñ¥½¸ (€€€€€€€€€€€€€€€€‰‰Õå•É}™¥¹…±}…ÕÑ¡½É¥Ñäˆ°(€€€€€€€€€€€€€€€€‰	Õå•È™¥¹…°…ÕÑ¡½É¥Ñäˆ°(€€€€€€€€€€€€€€€€‰	Õå•ÈÍÁ½¹Í½Èˆ°(€€€€€€€€€€€€€€€l‰•á•ÕÑ¥Ù”ÍÁ½¹Í½È…ÁÁÉ½Ù…°ˆ°€‰¹…µ•Í¥¹•Èˆ°€‰‰Õ‘•Ð½Ý¹•Èˆ°€‰ÁÕÉ¡…Í”½É‘•È‰t°(€€€€€€€€€€€€€€€mt°(€€€€€€€€€€€€€€€€‰ÁÉ½Á½Í•‘}Õ¹Ñ¥±}‰Õå•É}ÍÁ•¥™¥Œˆ°(€€€€€€€€€€€€€€€€‰Ý…É¹¥¹œˆ°(€€€€€€€€€€€€€€€€‰á•ÕÑ¥Ù”ÍÁ½¹Í½È…ÁÁÉ½Ù…°°¹…µ•Í¥¹•È°‰Õ‘•Ð½Ý¹•È°…¹ÁÕÉ¡…Í”½É‘•ÈÉ•ÅÕ¥É”‰Õå•È…ÕÑ¡½É¥Ñä¸ˆ°(€€€€€€€€€€€€€€€€‰…¸Ñ¡”‰Õå•È…ÁÁÉ½Ù”Ñ¡”™¥¹…°-I\€ÉÁÕÉ¡…Í”…ÕÑ¡½É¥Ñäüˆ°(€€€€€€€€€€€€€€€€‰½±±•Ð™¥¹…°‰Õå•È…ÕÑ¡½É¥Ñä…ÉÑ¥™…ÑÌ½È•áÁ±¥¥ÐÝ…¥Ù•È¸ˆ°(€€€€€€€€€€€€¤°(€€€€€€€€€€€Í•Ñ¥½¸ (€€€€€€€€€€€€€€€€‰ÁÉ½‘ÕÑ¥½¹}•áÑ•É¹…±}•Ù¥‘•¹”ˆ°(€€€€€€€€€€€€€€€€‰AÉ½‘ÕÑ¥½¸…¹•áÑ•É¹…°•Ù¥‘•¹”ˆ°(€€€€€€€€€€€€€€€€‰AÉ½‘ÕÑ¥½¸…¹Í•ÕÉ¥Ñä½Ý¹•ÉÌˆ°(€€€€€€€€€€€€€€€l‰ÁÉ½‘ÕÑ¥½¸Ñ•±•µ•ÑÉäˆ°€‰Ñ¡¥ÉµÁ…ÉÑäÍ•ÕÉ¥Ñä…ÑÑ•ÍÑ…Ñ¥½¸ˆ°€‰¡½ÍÑ•Í…¸•Ù¥‘•¹”‰t°(€€€€€€€€€€€€€€€mt°(€€€€€€€€€€€€€€€€‰ÁÉ½Á½Í•‘}Õ¹Ñ¥±}‰Õå•É}ÍÁ•¥™¥Œˆ°(€€€€€€€€€€€€€€€€‰Ý…É¹¥¹œˆ°(€€€€€€€€€€€€€€€€‰AÉ½‘ÕÑ¥½¸Ñ•±•µ•ÑÉä°Ñ¡¥ÉµÁ…ÉÑäÍ•ÕÉ¥Ñä…ÑÑ•ÍÑ…Ñ¥½¸°…¹¡½ÍÑ•Í…¸•Ù¥‘•¹”…É”•áÑ•É¹…°¥¹ÁÕÑÌ¸ˆ°(€€€€€€€€€€€€€€€€‰…¸Ñ¡”½µµ¥ÑÑ•”…ÁÁÉ½Ù”Ý¥Ñ ÁÉ½‘ÕÑ¥½¸…¹•áÑ•É¹…°•Ù¥‘•¹”ÍÑ¥±°ÑÉ…­•…Ì½¹‘¥Ñ¥½¹Ìüˆ°(€€€€€€€€€€€€€€€€‰½±±•Ð¡½ÍÑ••Ù¥‘•¹”…™Ñ•È•¹Ù¥É½¹µ•¹ÐÍ•±•Ñ¥½¸¸ˆ°(€€€€€€€€€€€€¤°(€€€€€€€t(€€€€€€€ÍÑ…Ñ•}½Õ¹ÑÌ€ô½Õ¹Ñ•È¡¥Ñ•µl‰½µÁ±•Ñ¥½¹}ÍÑ…Ñ”‰t™½È¥Ñ•´¥¸µ•µ½}Í•Ñ¥½¹Ì¤(€€€€€€€‰±½­•‘}½Õ¹Ð€ôÍÑ…Ñ•}½Õ¹ÑÌ¹•Ð ‰‰±½­•ˆ°€À¤€¬±•¸¡½¹É•Ñ•}‰±½­•ÉÌ¤(€€€€€€€Ý…É¹¥¹}½Õ¹Ð€ôÍÑ…Ñ•}½Õ¹ÑÌ¹•Ð ‰Ý…É¹¥¹œˆ°€À¤(€€€€€€€¥˜‰±½­•‘}½Õ¹Ðè(€€€€€€€€€€€¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}ÍÑ…ÑÕÌ€ô€‰½µµ•É¥…±}¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}‰±½­•ˆ(€€€€€€€€€€€É•½µµ•¹‘…Ñ¥½¹}ÍÑ…ÑÕÌ€ô€‰‘½}¹½Ñ}É•½µµ•¹‘}Õ¹Ñ¥±}‰±½­•ÉÍ}±•…É•ˆ(€€€€€€€•±¥˜Ý…É¹¥¹}½Õ¹Ðè(€€€€€€€€€€€¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}ÍÑ…ÑÕÌ€ô€‰½µµ•É¥…±}¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}É•…‘å}Ý¥Ñ¡}Ý…É¹¥¹Ìˆ(€€€€€€€€€€€É•½µµ•¹‘…Ñ¥½¹}ÍÑ…ÑÕÌ€ô€‰É•½µµ•¹‘}Ý¥Ñ¡}‰Õå•É}½¹‘¥Ñ¥½¹Ìˆ(€€€€€€€•±Í”è€€ŒÁÉ…µ„è¹¼½Ù•È€´Õ¹É•…¡…‰±”Ý¡¥±”•áÑ•É¹…°µ•Ù¥‘•¹”Ý…É¹¥¹œÍ•Ñ¥½¹ÌÉ•µ…¥¸±¥Ñ•É…°(€€€€€€€€€€€¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}ÍÑ…ÑÕÌ€ô€‰½µµ•É¥…±}¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}É•…‘äˆ€€ŒÁÉ…µ„è¹¼½Ù•È(€€€€€€€€€€€É•½µµ•¹‘…Ñ¥½¹}ÍÑ…ÑÕÌ€ô€‰É•½µµ•¹ˆ€€ŒÁÉ…µ„è¹¼½Ù•È(€€€€€€€É•ÅÕ¥É•‘}ÉÕ¹Ñ¥µ•}•¹‘Á½¥¹ÑÌ€ô±¥ÍÐ (€€€€€€€€€€€‘¥Ð¹™É½µ­•åÌ (€€€€€€€€€€€€€€€•¹‘Á½¥¹Ð(€€€€€€€€€€€€€€€™½È¥Ñ•´¥¸µ•µ½}Í•Ñ¥½¹Ì(€€€€€€€€€€€€€€€™½È•¹‘Á½¥¹Ð¥¸¥Ñ•µl‰ÉÕ¹Ñ¥µ•}•¹‘Á½¥¹ÑÌ‰t(€€€€€€€€€€€€€€€¥˜•¹‘Á½¥¹Ð¹ÍÑ…ÉÑÍÝ¥Ñ  ˆ¼ˆ¤(€€€€€€€€€€€€¤(€€€€€€€€¤((€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€‰¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}ÍÑ…ÑÕÌˆè¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}ÍÑ…ÑÕÌ°(€€€€€€€€€€€€‰Ñ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜˆèÑ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜ°(€€€€€€€€€€€€‰Ñ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}‘¥ÍÁ±…äˆè˜‰-I\íÑ…É•Ñ}½¹ÑÉ…Ñ}Ù…±Õ•}­ÉÜè±ôˆ°(€€€€€€€€€€€€‰µ•…ÍÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌˆè€‰±½…±}½µµ•É¥…±}¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}µ•µ¼ˆ°(€€€€€€€€€€€€‰Í½ÕÉ•}¹½Ñ”ˆè€ (€€€€€€€€€€€€€€€€‰½µµ•É¥…°¥¹Ù•ÍÑµ•¹Ð½µµ¥ÑÑ•”µ•µ¼Á…­…•ÌÉ•Á¼µ±½…°‘Õ”‘¥±¥•¹”°ÁÕÉ¡…Í”…ÁÁÉ½Ù…°°€ˆ(€€€€€€€€€€€€€€€€‰ÁÉ½Á½Í…°°ÉÕ¹Ñ¥µ”°…‘µ¥¸ÑÉ…”°Í•ÕÉ¥Ñä°½¹ÑÉ…Ð°Ù…±Õ”°½¹‰½…É‘¥¹œ°½Á•É…Ñ¥½¹Ì°…¹…±åÑ¥Ì°€ˆ(€€€€€€€€€€€€€€€€‰¥µ„°É•Ù¥•ÜµÁ½±¥ä°…¹Á…­…¥¹œ•Ù¥‘•¹”™½È-I\€È°ÀÀÀ°ÀÀÀ°ÀÀÀ•á•ÕÑ¥Ù”É•Ù¥•Üì¥Ð¥Ì€ˆ(€€€€€€€€€€€€€€€€‰¹½Ð„Ù…±Õ…Ñ¥½¸Õ…É…¹Ñ•”°ÁÕÉ¡…Í”½µµ¥Ñµ•¹Ð°Í¥¹•½É‘•È°±•…°½Á¥¹¥½¸°ÁÉ½‘ÕÑ¥½¸€ˆ(€€€€€€€€€€€€€€€€‰½µÁ±¥…¹”•ÉÑ¥™¥…Ñ”°Ñ¡¥ÉµÁ…ÉÑä…ÑÑ•ÍÑ…Ñ¥½¸°½ÈÉ•Ù•¹Õ”ÁÉ½½˜¸ˆ(€€€€€€€€€€€€¤°(€€€€€€€€€€€€‰•á•ÕÑ¥Ù•}É•½µµ•¹‘…Ñ¥½¸ˆèì(€€€€€€€€€€€€€€€€‰Ñ¥Ñ±”ˆè€‰-I\€É½µµ•É¥…°¥¹Ù•ÍÑµ•¹Ð½µµ¥ÑÑ•”µ•µ¼ˆ°(€€€€€€€€€€€€€€€€‰É•½µµ•¹‘…Ñ¥½¹}ÍÑ…ÑÕÌˆèÉ•½µµ•¹‘…Ñ¥½¹}ÍÑ…ÑÕÌ°(€€€€€€€€€€€€€€€€‰É•½µµ•¹‘…Ñ¥½¸ˆè€ (€€€€€€€€€€€€€€€€€€€€‰I•½µµ•¹½µµ¥ÑÑ•”É•Ù¥•ÜÝ¥Ñ ‰Õå•È…ÕÑ¡½É¥Ñä°ÁÉ½‘ÕÑ¥½¸Ñ•±•µ•ÑÉä°…¹•áÑ•É¹…°€ˆ(€€€€€€€€€€€€€€€€€€€€‰…ÑÑ•ÍÑ…Ñ¥½¸½¹‘¥Ñ¥½¹ÌÑÉ…­•Í•Á…É…Ñ•±ä™É½´µ•…ÍÕÉ•±½…°ÁÉ½‘ÕÐ•Ù¥‘•¹”¸ˆ(€€€€€€€€€€€€€€€€€€€¥˜É•½µµ•¹‘…Ñ¥½¹}ÍÑ…ÑÕÌ€ôô€‰É•½µµ•¹‘}Ý¥Ñ¡}‰Õå•É}½¹‘¥Ñ¥½¹Ìˆ(€€€€€€€€€€€€€€€€€€€•±Í”€‰¼¹½ÐÉ•½µµ•¹Õ¹Ñ¥°½¹É•Ñ”‰±½­•ÉÌ…É”±•…É•¸ˆ(€€€€€€€€€€€€€€€€€€€¥˜É•½µµ•¹‘…Ñ¥½¹}ÍÑ…ÑÕÌ€ôô€‰‘½}¹½Ñ}É•½µµ•¹‘}Õ¹Ñ¥±}‰±½­•ÉÍ}±•…É•ˆ(€€€€€€€€€€€€€€€€€€€•±Í”€‰I•½µµ•¹½µµ¥ÑÑ•”…ÁÁÉ½Ù…°Ý¥Ñ ¹¼½Á•¸±½…°½È‰Õå•ÈµÍÁ•¥™¥Œ½¹‘¥Ñ¥½¹Ì¸ˆ(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€‰…Õ‘¥•¹”ˆèl(€€€€€€€€€€€€€€€€€€€€‰%¹Ù•ÍÑµ•¹Ð½µµ¥ÑÑ•”¡…¥Èˆ°(€€€€€€€€€€€€€€€€€€€€‰½¹½µ¥Œ‰Õå•Èˆ°(€€€€€€€€€€€€€€€€€€€€‰¥¹…¹”½Ý¹•Èˆ°(€€€€€€€€€€€€€€€€€€€€‰AÉ½ÕÉ•µ•¹Ð½Ý¹•Èˆ°(€€€€€€€€€€€€€€€€€€€€‰1•…°½Ý¹•Èˆ°(€€€€€€€€€€€€€€€€€€€€‰M•ÕÉ¥Ñä½Ý¹•Èˆ°(€€€€€€€€€€€€€€€€€€€€‰%µÁ±•µ•¹Ñ…Ñ¥½¸½Ý¹•Èˆ°(€€€€€€€€€€€€€€€t°(€€€€€€€€€€€ô°(€€€€€€€€€€€€‰µ•µ½}ÍÕµµ…Éäˆèì(€€€€€€€€€€€€€€€€‰Í•Ñ¥½¹}½Õ¹Ðˆè±•¸¡µ•µ½}Í•Ñ¥½¹Ì¤°(€€€€€€€€€€€€€€€€‰É•…‘å}½Õ¹ÐˆèÍÑ…Ñ•}½Õ¹ÑÌ¹•Ð ‰É•…‘äˆ°€À¤°(€€€€€€€€€€€€€€€€‰Ý…É¹¥¹}½Õ¹ÐˆèÝ…É¹¥¹}½Õ¹Ð°(€€€€€€€€€€€€€€€€‰‰±½­•‘}½Õ¹Ðˆè‰±½­•‘}½Õ¹Ð°(€€€€€€€€€€€€€€€€‰•¹‘Á½¥¹Ñ}½Õ¹Ðˆè±•¸¡É•ÅÕ¥É•‘}ÉÕ¹Ñ¥µ•}•¹‘Á½¥¹ÑÌ¤°(€€€€€€€€€€€€€€€€‰É•Ù¥•Ý}ÁÉ½•ÍÍ}¥Í}‰±½­•Èˆè‘Õ•}‘¥±¥•¹•l‰É•Ù¥•Ý}ÁÉ½•ÍÍ}Á½±¥ä‰ul‰¥Í}‰±½­•È‰t°(€€€€€€€€€€€€€€€€‰½‘•}½¹¹•Ñ}ÕÍ•ˆè…±Í”°(€€€€€€€€€€€ô°(€€€€€€€€€€€€‰µ•µ½}Í•Ñ¥½¹Ìˆèµ•µ½}Í•Ñ¥½¹Ì°(€€€€€€€€€€€€‰É•ÅÕ¥É•‘}ÉÕ¹Ñ¥µ•}•¹‘Á½¥¹ÑÌˆèÉ•ÅÕ¥É•‘}ÉÕ¹Ñ¥µ•}•¹‘Á½¥¹ÑÌ°(€€€€€€€€€€€€‰½µµ¥ÑÑ••}‘•¥Í¥½¹}ÅÕ•ÍÑ¥½¹Ìˆèl(€€€€€€€€€€€€€€€€‰%ÌÑ¡”ÁÉ½‘ÕÐ•Ù¥‘•¹”ÍÕ™™¥¥•¹Ð™½È-I\€É‰Õå•ÈÉ•Ù¥•Üüˆ°(€€€€€€€€€€€€€€€€‰É”‰Õå•È…ÕÑ¡½É¥Ñä‘½Õµ•¹ÑÌ¹…µ•…¹ÑÉ…­•üˆ°(€€€€€€€€€€€€€€€€‰É”ÁÉ½‘ÕÑ¥½¸…¹Ñ¡¥ÉµÁ…ÉÑä•Ù¥‘•¹”…ÁÌ•áÁ±¥¥ÐÝ…É¹¥¹Ìüˆ°(€€€€€€€€€€€€€€€€‰%Ì…¹ä½¹É•Ñ”‰±½­•ÈÁÉ•Í•¹Ðüˆ°(€€€€€€€€€€€t°(€€€€€€€€€€€€‰‰Õå•É}µ¥ÍÍ¥¹}…ÉÑ¥™…ÑÌˆè‘Õ•}‘¥±¥•¹•l‰‰Õå•É}µ¥ÍÍ¥¹}…ÉÑ¥™…ÑÌ‰t(€€€€€€€€€€€€¬l‰•á•ÕÑ¥Ù”ÍÁ½¹Í½È…ÁÁÉ½Ù…°ˆ°€‰¥¹Ù•ÍÑµ•¹Ð½µµ¥ÑÑ•”Í¥¸µ½™˜‰t°(€€€€€€€€€€€€‰½¹É•Ñ•}‰±½­•ÉÌˆè½¹É•Ñ•}‰±½­•ÉÌ°(€€€€€€€€€€€€‰¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}ÍÑ…ÑÕÍ}ÉÕ±•Ìˆèl(€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€‰¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}ÍÑ…ÑÕÌˆè€‰½µµ•É¥…±}¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}É•…‘äˆ°(€€€€€€€€€€€€€€€€€€€€‰ÉÕ±”ˆè€‰…±°µ•µ¼Í•Ñ¥½¹Ì…É”É•…‘ä…¹¹¼‰Õå•È…ÕÑ¡½É¥Ñä°ÁÉ½‘ÕÑ¥½¸°½ÈÑ¡¥ÉµÁ…ÉÑä•Ù¥‘•¹”É•µ…¥¹Ì½Á•¸ˆ°(€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€‰¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}ÍÑ…ÑÕÌˆè€‰½µµ•É¥…±}¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}É•…‘å}Ý¥Ñ¡}Ý…É¹¥¹Ìˆ°(€€€€€€€€€€€€€€€€€€€€‰ÉÕ±”ˆè€‰É•Á¼µ±½…°½µµ¥ÑÑ•”µ•µ¼•Ù¥‘•¹”¥ÌÉ•…‘äÝ¡¥±”‰Õå•È…ÕÑ¡½É¥Ñä°ÁÉ½‘ÕÑ¥½¸Ñ•±•µ•ÑÉä°½È•áÑ•É¹…°…ÑÑ•ÍÑ…Ñ¥½¹ÌÉ•µ…¥¸•áÁ±¥¥ÐÝ…É¹¥¹Ìˆ°(€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€‰¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}ÍÑ…ÑÕÌˆè€‰½µµ•É¥…±}¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}‰±½­•ˆ°(€€€€€€€€€€€€€€€€€€€€‰ÉÕ±”ˆè€‰Í•ÕÉ¥Ñä™…¥±ÕÉ”°A$½¹ÑÉ…ÐÉ•É•ÍÍ¥½¸°‘½Õµ•¹Ðµ¥Íµ…Ñ °ÉÕ¹Ñ¥µ”‘•™•Ð°µ¥ÍÍ¥¹œ±½…°µ•µ¼•Ù¥‘•¹”°½È½‘”½¹¹•ÐÕÍ…”‰±½­Ì½µµ¥ÑÑ•”É•½µµ•¹‘…Ñ¥½¸ˆ°(€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€t°(€€€€€€€€€€€€‰É•Ù¥•Ý}ÁÉ½•ÍÍ}Á½±¥äˆè‘Õ•}‘¥±¥•¹•l‰É•Ù¥•Ý}ÁÉ½•ÍÍ}Á½±¥ä‰t°(€€€€€€€€€€€€‰É•±…Ñ•‘}ÉÕ¹Ñ¥µ•}É•Á½ÉÑÌˆèì(€€€€€€€€€€€€€€€€‰½µµ•É¥…±}‘Õ•}‘¥±¥•¹•}ÍÑ…ÑÕÌˆè‘Õ•}‘¥±¥•¹•l‰‘Õ•}‘¥±¥•¹•}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰½µµ•É¥…±}ÁÕÉ¡…Í•}…ÁÁÉ½Ù…±}ÍÑ…ÑÕÌˆèÁÕÉ¡…Í•l‰ÁÕÉ¡…Í•}…ÁÁÉ½Ù…±}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰½µµ•É¥…±}ÁÉ½Á½Í…±}ÍÑ…ÑÕÌˆèÁÉ½Á½Í…±l‰ÁÉ½Á½Í…±}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰½µµ•É¥…±}½µÁ±•Ñ¥½¹}ÍÑ…ÑÕÌˆè½µÁ±•Ñ¥½¹l‰½µÁ±•Ñ¥½¹}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰½µµ•É¥…±}‘•µ½}ÍÑ…ÑÕÌˆè‘•µ½l‰‘•µ½}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰‰Õå•É}…•ÁÑ…¹•}Ý½É­™±½Ý}ÍÑ…ÑÕÌˆè‰Õå•É}Ý½É­™±½Ýl‰Ý½É­™±½Ý}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰½µµ•É¥…±}±½Í•}ÍÑ…ÑÕÌˆè±½Í•l‰±½Í•}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰½µµ•É¥…±}ÁÉ½ÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌˆèÁÉ½ÕÉ•µ•¹Ñl‰ÁÉ½ÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰½µµ•É¥…±}½¹ÑÉ…Ñ}ÍÑ…ÑÕÌˆè½¹ÑÉ…Ñl‰½¹ÑÉ…Ñ}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰½µµ•É¥…±}Ù…±Õ•}ÍÑ…ÑÕÌˆèÙ…±Õ•l‰Ù…±Õ•}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰½µµ•É¥…±}Í•ÕÉ¥Ñå}…ÑÑ•ÍÑ…Ñ¥½¹}ÍÑ…ÑÕÌˆèÍ•ÕÉ¥Ñål‰Í•ÕÉ¥Ñå}…ÑÑ•ÍÑ…Ñ¥½¹}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰½µµ•É¥…±}½¹‰½…É‘¥¹}ÍÑ…ÑÕÌˆè½¹‰½…É‘¥¹l‰½¹‰½…É‘¥¹}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰½µµ•É¥…±}½Á•É…Ñ¥½¹Í}ÍÑ…ÑÕÌˆè½Á•É…Ñ¥½¹Íl‰½Á•É…Ñ¥½¹Í}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰…¹…±åÑ¥Í}µ•…ÍÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌˆè…¹…±åÑ¥Íl‰µ•…ÍÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰…‘µ¥¹}…•¹Ñ}½Õ¹Ðˆè±•¸¡…‘µ¥¹}ÍÑ…Ñ•l‰…•¹ÑÌ‰t¤°(€€€€€€€€€€€ô°(€€€€€€€€€€€€‰±¥‰É…Éå}ÍÁ±¥Ñ}‘•¥Í¥½¸ˆè‘Õ•}‘¥±¥•¹•l‰±¥‰É…Éå}ÍÁ±¥Ñ}‘•¥Í¥½¸‰t°(€€€€€€€€€€€€‰Á±Õ¥¹}ÑÉ…•…‰¥±¥Ñäˆè‘Õ•}‘¥±¥•¹•l‰Á±Õ¥¹}ÑÉ…•…‰¥±¥Ñä‰t°(€€€€€€€€€€€€‰½µµ¥ÑÑ••}±¥¹­Ìˆèì(€€€€€€€€€€€€€€€€‰™¥µ…}‘•Í¥¹}™¥±”ˆè€‰¡ÑÑÁÌè¼½ÝÝÜ¹™¥µ„¹½´½‘•Í¥¸½ÙÍi5á]ØÐÉ!IiÕ9]¬ˆ°(€€€€€€€€€€€€€€€€‰™¥©…µ}‰½…Éˆè€‰¡ÑÑÁÌè¼½ÝÝÜ¹™¥µ„¹½´½‰½…É½]Èá¥5±åM!­•É!M©ØÁA”Á4ˆ°(€€€€€€€€€€€€€€€€‰ÉÕ¹Ñ¥µ•}•¹‘Á½¥¹Ðˆè€ˆ½…Á¤½ØÄ½½µµ•É¥…±}¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}µ•µ½Ì½±…Ñ•ÍÐˆ°(€€€€€€€€€€€€€€€€‰‘½Õµ•¹Ñ…Ñ¥½¸ˆè€‰‘½Ì½½µµ•É¥…±}¥¹Ù•ÍÑµ•¹Ñ}½µµ¥ÑÑ••}µ•µ¼¹µˆ°(€€€€€€€€€€€ô°(€€€€€€€ô((€€€‘•˜…‘µ¥¹}ÍÑ…Ñ” (€€€€€€€Í•±˜°(€€€€€€€½Ý¹•É}¥èÍÑÈð9½¹”€ô9½¹”°(€€€€€€€€¨°(€€€€€€€É½±”èÍÑÈð9½¹”€ô9½¹”°(€€€€€€€ÁÕÉÁ½Í”èÍÑÈð9½¹”€ô9½¹”°(€€€€¤€´ø‘¥ÑmÍÑÈ°¹åtè(€€€€€€€€ˆˆ‰	Õ¥±Ñ¡”…‘µ¥¸½¹Í½±”ÍÑ…Ñ”Á…å±½…™É½´…•¹ÑÌ°Á½±¥ä°…¹…Õ‘¥Ð‘…Ñ„¸ˆˆˆ(€€€€€€€…•¹Ñ}Á…•}Í¥é”€ôµ…à Ä°±•¸¡Í•±˜¹…¹‘¥‘…Ñ•Ì¤¤(€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€‰…•¹ÑÌˆèÍ•±˜¹±¥ÍÑ}…•¹ÑÌ¡Á…•}Í¥é”õ…•¹Ñ}Á…•}Í¥é”¤°(€€€€€€€€€€€€‰Á½±¥äˆèì(€€€€€€€€€€€€€€€€¨©Í•±˜¹Á½±¥ä¹…Í}‘¥Ð ¤°(€€€€€€€€€€€€€€€€‰É½±•Ìˆè±¥ÍÐ¡Í•±˜¹I=1}QL¤°(€€€€€€€€€€€ô°(€€€€€€€€€€€€‰É½ÕÑ¥¹}•Ù¥‘•¹”ˆèì(€€€€€€€€€€€€€€€€‰ÑÉ…¹ÍÁ½ÉÐˆèÍ•±˜¹}É½ÕÁ}É½ÕÑ•È¹Í¹…ÁÍ¡½Ð ¤°(€€€€€€€€€€€€€€€€‰ÅÕ…±¥ÑäˆèÍ•±˜¹}ÅÕ…±¥Ñå}É½ÕÑ•È¹Í¹…ÁÍ¡½Ð ¤°(€€€€€€€€€€€ô°(€€€€€€€€€€€€‰É••¹Ñ}Ý½É­™±½Ý}ÉÕ¹Ìˆèl(€€€€€€€€€€€€€€€Í•±˜¹}Í¡½ÉÑ•¹}ÉÕ¸¡ÉÕ¸¤(€€€€€€€€€€€€€€€™½ÈÉÕ¸¥¸Í•±˜¹±¥ÍÑ}É••¹Ñ}ÉÕ¹Ì (€€€€€€€€€€€€€€€€€€€Á…•}Í¥é”õµ…à Ä°±•¸¡Í•±˜¹}ÉÕ¹}½É‘•È¤¤°½Ý¹•É}¥õ½Ý¹•É}¥(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€t°(€€€€€€€€€€€€‰É••¹Ñ}…Õ‘¥Ñ}•Ù•¹ÑÌˆèÍ•±˜¹±¥ÍÑ}É••¹Ñ}…Õ‘¥Ñ}•Ù•¹ÑÌ¡É½±”õÉ½±”°ÁÕÉÁ½Í”õÁÕÉÁ½Í”¤°(€€€€€€€€€€€€‰É••¹Ñ}…ÕÑ¡½É¥é…Ñ¥½¹}‘•¥Í¥½¹ÌˆèÍ•±˜¹±¥ÍÑ}É••¹Ñ}…ÕÑ¡½É¥é…Ñ¥½¹}‘•¥Í¥½¹Ì ¤°(€€€€€€€€€€€€‰ÍÁ•¹ˆèÍ•±˜¹ÍÁ•¹‘}…¹…±åÑ¥Ì ¤°(€€€€€€€ô((€€€‘•˜}Í¡½ÉÑ•¹}ÉÕ¸¡Í•±˜°ÉÕ¸è‘¥ÑmÍÑÈ°¹åt¤€´ø‘¥ÑmÍÑÈ°¹åtè€€ŒÁÉ…µ„è¹¼½Ù•È(€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€‰Ý½É­™±½Ý}ÉÕ¹}¥ˆèÉÕ¹l‰Ý½É­™±½Ý}ÉÕ¹}¥‰t°(€€€€€€€€€€€€‰µ½‘”ˆèÉÕ¹l‰µ½‘”‰t°(€€€€€€€€€€€€‰Á½±¥å}µ½‘”ˆèÉÕ¹l‰Á½±¥å}µ½‘”‰t°(€€€€€€€€€€€€‰É•…Ñ•‘}…ÐˆèÉÕ¹l‰É•…Ñ•‘}…Ð‰t°(€€€€€€€ô((€€€‘•˜}¥Í}ÑÉ…•}½µÁ±•Ñ”¡Í•±˜°ÉÕ¸è‘¥ÑmÍÑÈ°¹åt¤€´ø‰½½°è(€€€€€€€ÑÉ…”€ôÉÕ¸¹•Ð ‰ÑÉ…”ˆ°mt¤(€€€€€€€¥˜¹½ÐÑÉ…”è(€€€€€€€€€€€É•ÑÕÉ¸…±Í”(€€€€€€€™½ÈÍÑ•À¥¸ÑÉ…”è(€€€€€€€€€€€¥˜¹½Ð…±°¡­•ä¥¸ÍÑ•À™½È­•ä¥¸€ ‰¥ˆ°€‰É½±”ˆ°€‰…•¹Ñ}¥ˆ°€‰ÍÕ‰Ñ…Í¬ˆ°€‰…•ÍÌˆ°€‰½ÕÑÁÕÐˆ¤¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸…±Í”(€€€€€€€€€€€¥˜¹½Ð¥Í¥¹ÍÑ…¹”¡ÍÑ•Ál‰…•ÍÌ‰t°±¥ÍÐ¤½ÈÍÑ•Ál‰½ÕÑÁÕÐ‰t¥Ì9½¹”è(€€€€€€€€€€€€€€€É•ÑÕÉ¸…±Í”(€€€€€€€Ù•É¥™¥…Ñ¥½¸€ôÉÕ¸¹•Ð ‰Ù•É¥™¥…Ñ¥½¸ˆ¤½Èíô(€€€€€€€É•ÑÕÉ¸‰½½°¡ÉÕ¸¹•Ð ‰…¹ÍÝ•Èˆ¤…¹€‰…•ÁÑ•ˆ¥¸Ù•É¥™¥…Ñ¥½¸…¹€‰É•…Í½¸ˆ¥¸Ù•É¥™¥…Ñ¥½¸¤((€€€‘•˜}¥Í}Á½±¥å}Í…™•}ÉÕ¸¡Í•±˜°ÉÕ¸è‘¥ÑmÍÑÈ°¹åt¤€´ø‰½½°è(€€€€€€€¥˜ÉÕ¹l‰µ½‘”‰t€ôô€‰½¹‘ÕÐˆ…¹ÉÕ¹l‰Á½±¥å}Í¹…ÁÍ¡½Ð‰t¹•Ð ‰Ù•É¥™¥•É}É•ÅÕ¥É•ˆ¤…¹¹½ÐÉÕ¸¹•Ð ‰Ù•É¥™¥…Ñ¥½¸ˆ¤è(€€€€€€€€€€€É•ÑÕÉ¸…±Í”(€€€€€€€É•ÑÕÉ¸Í•±˜¹}ÁÉ½Ù¥‘•É}•á±ÕÍ¥½¹}µ¥ÍÍ}½Õ¹Ð¡ÉÕ¸¤€ôô€À((€€€‘•˜}ÁÉ½Ù¥‘•É}•á±ÕÍ¥½¹}µ¥ÍÍ}½Õ¹Ð¡Í•±˜°ÉÕ¸è‘¥ÑmÍÑÈ°¹åt¤€´ø¥¹Ðè(€€€€€€€µ¥ÍÍ•Ì€ô€À(€€€€€€€™½ÈÍÑ•À¥¸ÉÕ¸¹•Ð ‰ÑÉ…”ˆ°mt¤è(€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€…•¹Ð€ôÍ•±˜¹}…•¹Ð¡ÍÑ•Ál‰…•¹Ñ}¥‰t¤(€€€€€€€€€€€•á•ÁÐ-•åÉÉ½Èè(€€€€€€€€€€€€€€€µ¥ÍÍ•Ì€¬ô€Ä(€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€¥˜ÍÑ•Ál‰É½±”‰t¥¸…•¹Ð¹ÁÉ½Ù¥‘•É}•á±ÕÍ¥½¹Ìè(€€€€€€€€€€€€€€€µ¥ÍÍ•Ì€¬ô€Ä(€€€€€€€É•ÑÕÉ¸µ¥ÍÍ•Ì((€€€‘•˜}±½…±•}­•å}Á…É¥Ñä¡Í•±˜°±½…±•}‰Õ¹‘±•Ìè‘¥ÑmÍÑÈ°‘¥ÑmÍÑÈ°ÍÑÉut¤€´ø‘¥ÑmÍÑÈ°¹åtè(€€€€€€€•¹±¥Í €ô±½…±•}‰Õ¹‘±•Ì¹•Ð ‰•¸ˆ°íô¤(€€€€€€€½Ñ¡•É}±½…±•}½‘•Ì€ôÍ½ÉÑ•¡½‘”™½È½‘”¥¸±½…±•}‰Õ¹‘±•Ì¥˜½‘”€„ô€‰•¸ˆ¤(€€€€€€€‘•¹½µ¥¹…Ñ½È€ô±•¸¡•¹±¥Í ¤€¨±•¸¡½Ñ¡•É}±½…±•}½‘•Ì¤(€€€€€€€µ¥ÍÍ¥¹œ€ôl(€€€€€€€€€€€˜‰í±½…±•}½‘•ô¹í­•åôˆ(€€€€€€€€€€€™½È±½…±•}½‘”¥¸½Ñ¡•É}±½…±•}½‘•Ì(€€€€€€€€€€€™½È­•ä¥¸Í½ÉÑ•¡•¹±¥Í ¤(€€€€€€€€€€€¥˜¹½Ð±½…±•}‰Õ¹‘±•Ím±½…±•}½‘•t¹•Ð¡­•ä¤(€€€€€€€t(€€€€€€€¹Õµ•É…Ñ½È€ô‘•¹½µ¥¹…Ñ½È€´±•¸¡µ¥ÍÍ¥¹œ¤(€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€‰¹Õµ•É…Ñ½Èˆè¹Õµ•É…Ñ½È°(€€€€€€€€€€€€‰‘•¹½µ¥¹…Ñ½Èˆè‘•¹½µ¥¹…Ñ½È°(€€€€€€€€€€€€‰Ù…±Õ•}Á•É•¹ÐˆèÍ•±˜¹}Á•É•¹Ð¡¹Õµ•É…Ñ½È°‘•¹½µ¥¹…Ñ½È¤°(€€€€€€€€€€€€‰µ¥ÍÍ¥¹}­•åÌˆèµ¥ÍÍ¥¹œ°(€€€€€€€ô((€€€‘•˜}Á•É•¹Ð¡Í•±˜°¹Õµ•É…Ñ½Èè¥¹Ð°‘•¹½µ¥¹…Ñ½Èè¥¹Ð¤€´ø™±½…Ðð9½¹”è(€€€€€€€¥˜‘•¹½µ¥¹…Ñ½È€ôô€Àè(€€€€€€€€€€€É•ÑÕÉ¸9½¹”(€€€€€€€É•ÑÕÉ¸É½Õ¹ ¡¹Õµ•É…Ñ½È€¼‘•¹½µ¥¹…Ñ½È¤€¨€ÄÀÀ°€È¤((€€€‘•˜}É¥Ñ•É¥½¸ (€€€€€€€Í•±˜°(€€€€€€€É¥Ñ•É¥½¹}¹…µ”èÍÑÈ°(€€€€€€€±…‰•°èÍÑÈ°(€€€€€€€ÍÑ…ÑÕÌèÍÑÈ°(€€€€€€€•Ù¥‘•¹”èÍÑÈ°(€€€€€€€É•µ•‘¥…Ñ¥½¸èÍÑÈ°(€€€€¤€´ø‘¥ÑmÍÑÈ°ÍÑÉtè(€€€€€€€É•ÅÕ¥É•}½‰©•Ñ}¹…µ”¡É¥Ñ•É¥½¹}¹…µ”°€‰Í…±•Í}É•…‘¥¹•ÍÌ¹É¥Ñ•É¥½¹}¹…µ”ˆ¤(€€€€€€€¥˜ÍÑ…ÑÕÌ¹½Ð¥¸ì‰Á…ÍÌˆ°€‰Ý…É¸ˆ°€‰™…¥°‰ôè€€ŒÁÉ…µ„è¹¼½Ù•È(€€€€€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È ‰Í…±•ÌÉ•…‘¥¹•ÍÌÍÑ…ÑÕÌµÕÍÐ‰”Á…ÍÌ°Ý…É¸°½È™…¥°ˆ¤(€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€‰É¥Ñ•É¥½¹}¹…µ”ˆèÉ¥Ñ•É¥½¹}¹…µ”°(€€€€€€€€€€€€‰ÍÑ…ÑÕÌˆèÍÑ…ÑÕÌ°(€€€€€€€€€€€€‰±…‰•°ˆè±…‰•°°(€€€€€€€€€€€€‰•Ù¥‘•¹”ˆè•Ù¥‘•¹”°(€€€€€€€€€€€€‰É•µ•‘¥…Ñ¥½¸ˆèÉ•µ•‘¥…Ñ¥½¸°(€€€€€€€ô((€€€‘•˜}‰Õå•É}•Ù¥‘•¹•}¥Ñ•´ (€€€€€€€Í•±˜°(€€€€€€€¥Ñ•µ}¹…µ”èÍÑÈ°(€€€€€€€±…‰•°èÍÑÈ°(€€€€€€€É•Ù¥•Ý•ÈèÍÑÈ°(€€€€€€€Í½ÕÉ•Ìè±¥ÍÑmÍÑÉt°(€€€€€€€•Ù¥‘•¹•}ÑåÁ”èÍÑÈ°(€€€€€€€½µÁ±•Ñ¥½¹}ÍÑ…Ñ”èÍÑÈ°(€€€€€€€•Ù¥‘•¹”èÍÑÈ°(€€€€€€€¹•áÑ}…Ñ¥½¸èÍÑÈ°(€€€€¤€´ø‘¥ÑmÍÑÈ°¹åtè(€€€€€€€É•ÅÕ¥É•}½‰©•Ñ}¹…µ”¡¥Ñ•µ}¹…µ”°€‰‰Õå•É}•Ù¥‘•¹•}µ…¹¥™•ÍÐ¹¥Ñ•µ}¹…µ”ˆ¤(€€€€€€€¥˜•Ù¥‘•¹•}ÑåÁ”¹½Ð¥¸ì(€€€€€€€€€€€€‰µ•…ÍÕÉ•‘}±½…°ˆ°(€€€€€€€€€€€€‰É•Á½Í¥Ñ½Éå}…ÉÑ¥™…Ðˆ°(€€€€€€€€€€€€‰™¥µ…}…ÉÑ¥™…Ðˆ°(€€€€€€€€€€€€‰ÁÉ½Á½Í•‘}Õ¹Ñ¥±}ÁÉ½‘ÕÑ¥½¸ˆ°(€€€€€€€€€€€€‰ÁÉ½Á½Í•‘}Õ¹Ñ¥±}‰Õå•É}ÍÁ•¥™¥Œˆ°(€€€€€€€ôè€€ŒÁÉ…µ„è¹¼½Ù•È(€€€€€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È ‰‰Õå•È•Ù¥‘•¹”ÑåÁ”¥Ì¥¹Ù…±¥ˆ¤(€€€€€€€¥˜½µÁ±•Ñ¥½¹}ÍÑ…Ñ”¹½Ð¥¸ì‰É•…‘äˆ°€‰Ý…É¹¥¹œˆ°€‰‰±½­•‰ôè€€ŒÁÉ…µ„è¹¼½Ù•È(€€€€€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È ‰‰Õå•È•Ù¥‘•¹”½µÁ±•Ñ¥½¸ÍÑ…Ñ”µÕÍÐ‰”É•…‘ä°Ý…É¹¥¹œ°½È‰±½­•ˆ¤(€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€‰¥Ñ•µ}¹…µ”ˆè¥Ñ•µ}¹…µ”°(€€€€€€€€€€€€‰±…‰•°ˆè±…‰•°°(€€€€€€€€€€€€‰É•Ù¥•Ý•ÈˆèÉ•Ù¥•Ý•È°(€€€€€€€€€€€€‰Í½ÕÉ•ÌˆèÍ½ÕÉ•Ì°(€€€€€€€€€€€€‰•Ù¥‘•¹•}ÑåÁ”ˆè•Ù¥‘•¹•}ÑåÁ”°(€€€€€€€€€€€€‰½µÁ±•Ñ¥½¹}ÍÑ…Ñ”ˆè½µÁ±•Ñ¥½¹}ÍÑ…Ñ”°(€€€€€€€€€€€€‰•Ù¥‘•¹”ˆè•Ù¥‘•¹”°(€€€€€€€€€€€€‰¹•áÑ}…Ñ¥½¸ˆè¹•áÑ}…Ñ¥½¸°(€€€€€€€ô((€€€‘•˜}‰Õå•É}µ…¹¥™•ÍÑ}ÍÕµµ…Éä¡Í•±˜°¥Ñ•µÌè±¥ÍÑm‘¥ÑmÍÑÈ°¹åut¤€´ø‘¥ÑmÍÑÈ°¹åtè(€€€€€€€½µÁ±•Ñ¥½¹}½Õ¹ÑÌ€ô½Õ¹Ñ•È¡¥Ñ•µl‰½µÁ±•Ñ¥½¹}ÍÑ…Ñ”‰t™½È¥Ñ•´¥¸¥Ñ•µÌ¤(€€€€€€€•Ù¥‘•¹•}½Õ¹ÑÌ€ô½Õ¹Ñ•È¡¥Ñ•µl‰•Ù¥‘•¹•}ÑåÁ”‰t™½È¥Ñ•´¥¸¥Ñ•µÌ¤(€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€‰Ñ½Ñ…±}¥Ñ•µÌˆè±•¸¡¥Ñ•µÌ¤°(€€€€€€€€€€€€‰‰å}½µÁ±•Ñ¥½¹}ÍÑ…Ñ”ˆèì(€€€€€€€€€€€€€€€€‰É•…‘äˆè½µÁ±•Ñ¥½¹}½Õ¹ÑÌ¹•Ð ‰É•…‘äˆ°€À¤°(€€€€€€€€€€€€€€€€‰Ý…É¹¥¹œˆè½µÁ±•Ñ¥½¹}½Õ¹ÑÌ¹•Ð ‰Ý…É¹¥¹œˆ°€À¤°(€€€€€€€€€€€€€€€€‰‰±½­•ˆè½µÁ±•Ñ¥½¹}½Õ¹ÑÌ¹•Ð ‰‰±½­•ˆ°€À¤°(€€€€€€€€€€€ô°(€€€€€€€€€€€€‰‰å}•Ù¥‘•¹•}ÑåÁ”ˆèì(€€€€€€€€€€€€€€€€‰µ•…ÍÕÉ•‘}±½…°ˆè•Ù¥‘•¹•}½Õ¹ÑÌ¹•Ð ‰µ•…ÍÕÉ•‘}±½…°ˆ°€À¤°(€€€€€€€€€€€€€€€€‰É•Á½Í¥Ñ½Éå}…ÉÑ¥™…Ðˆè•Ù¥‘•¹•}½Õ¹ÑÌ¹•Ð ‰É•Á½Í¥Ñ½Éå}…ÉÑ¥™…Ðˆ°€À¤°(€€€€€€€€€€€€€€€€‰™¥µ…}…ÉÑ¥™…Ðˆè•Ù¥‘•¹•}½Õ¹ÑÌ¹•Ð ‰™¥µ…}…ÉÑ¥™…Ðˆ°€À¤°(€€€€€€€€€€€€€€€€‰ÁÉ½Á½Í•‘}Õ¹Ñ¥±}ÁÉ½‘ÕÑ¥½¸ˆè•Ù¥‘•¹•}½Õ¹ÑÌ¹•Ð ‰ÁÉ½Á½Í•‘}Õ¹Ñ¥±}ÁÉ½‘ÕÑ¥½¸ˆ°€À¤°(€€€€€€€€€€€€€€€€‰ÁÉ½Á½Í•‘}Õ¹Ñ¥±}‰Õå•É}ÍÁ•¥™¥Œˆè•Ù¥‘•¹•}½Õ¹ÑÌ¹•Ð ‰ÁÉ½Á½Í•‘}Õ¹Ñ¥±}‰Õå•É}ÍÁ•¥™¥Œˆ°€À¤°(€€€€€€€€€€€ô°(€€€€€€€ô((€€€‘•˜}Í•ÕÉ¥Ñå}Á½ÍÑÕÉ•}É¥Ñ•É¥½¸¡Í•±˜°Í•ÕÉ¥Ñå}ÁÉ½™¥±”è‘¥ÑmÍÑÈ°¹åt¤€´ø‘¥ÑmÍÑÈ°ÍÑÉtè(€€€€€€€…ÕÑ¡}µ½‘”€ôÍ•ÕÉ¥Ñå}ÁÉ½™¥±”¹•Ð ‰…ÕÑ¡}µ½‘”ˆ°€‰±½½Á‰…­}¹½}…ÕÑ ˆ¤(€€€€€€€¥ÍÍÕ•Ìè±¥ÍÑmÍÑÉt€ômt(€€€€€€€Ý…É¹¥¹Ìè±¥ÍÑmÍÑÉt€ômt(€€€€€€€¥˜…ÕÑ¡}µ½‘”€ôô€‰Í¥¹±•}Ñ½­•¸ˆè(€€€€€€€€€€€Ý…É¹¥¹Ì¹…ÁÁ•¹ ‰Í¥¹±”‰•…É•ÈÑ½­•¸Í¡…É•‰ä…‘µ¥¸…¹¥¹™•É•¹”Í½Á•Ìˆ¤(€€€€€€€•±¥˜…ÕÑ¡}µ½‘”¹½Ð¥¸ì‰ÍÁ±¥Ñ}Ñ½­•¸ˆ°€‰•áÑ•É¹…±}‰•…É•É}Ù•É¥™¥•È‰ôè(€€€€€€€€€€€¥ÍÍÕ•Ì¹…ÁÁ•¹ ‰¹¼‰•…É•ÈÑ½­•¸½¹™¥ÕÉ•½ÕÑÍ¥‘”±½½Á‰…¬µ½¹±ä‘•Ù•±½Áµ•¹Ðˆ¤(€€€€€€€¥˜Í•ÕÉ¥Ñå}ÁÉ½™¥±”¹•Ð ‰…±±½Ý}ÁÕ‰±¥}‰¥¹ˆ¤è(€€€€€€€€€€€¥ÍÍÕ•Ì¹…ÁÁ•¹ ‰ÁÕ‰±¥Œ‰¥¹¥Ì•¹…‰±•ˆ¤(€€€€€€€¥˜Í•ÕÉ¥Ñå}ÁÉ½™¥±”¹•Ð ‰•áÁ½Í•}ÑÉ…•}‰å}‘•™…Õ±Ðˆ¤è(€€€€€€€€€€€¥ÍÍÕ•Ì¹…ÁÁ•¹ ‰ÑÉ…”•áÁ½ÍÕÉ”¥Ì•¹…‰±•‰ä‘•™…Õ±Ðˆ¤(€€€€€€€¥˜¥¹Ð¡Í•ÕÉ¥Ñå}ÁÉ½™¥±”¹•Ð ‰É…Ñ•}±¥µ¥Ñ}É•ÅÕ•ÍÑÌˆ¤½È€À¤€ðô€Àè(€€€€€€€€€€€¥ÍÍÕ•Ì¹…ÁÁ•¹ ‰É•ÅÕ•ÍÐÉ…Ñ”±¥µ¥Ñ¥¹œ¥Ì‘¥Í…‰±•ˆ¤(€€€€€€€¥˜¥¹Ð¡Í•ÕÉ¥Ñå}ÁÉ½™¥±”¹•Ð ‰µ…á}½¹ÕÉÉ•¹Ñ}ÉÕ¹Ìˆ¤½È€À¤€ðô€Àè(€€€€€€€€€€€¥ÍÍÕ•Ì¹…ÁÁ•¹ ‰ÉÕ¸½¹ÕÉÉ•¹ä±¥µ¥Ñ¥¹œ¥Ì‘¥Í…‰±•ˆ¤((€€€€€€€¥˜¥ÍÍÕ•Ìè(€€€€€€€€€€€ÍÑ…ÑÕÌ€ô€‰™…¥°ˆ(€€€€€€€€€€€•Ù¥‘•¹”€ô€ˆì€ˆ¹©½¥¸¡¥ÍÍÕ•Ì¤(€€€€€€€€€€€É•µ•‘¥…Ñ¥½¸€ô€‰I•ÅÕ¥É”‰•…É•È…ÕÑ °ÁÉ¥Ù…Ñ”‰¥¹‘•™…Õ±ÑÌ°¡¥‘‘•¸ÑÉ…•Ì°É…Ñ”±¥µ¥ÑÌ°…¹ÉÕ¸±¥µ¥ÑÌ¸ˆ(€€€€€€€•±¥˜Ý…É¹¥¹Ìè(€€€€€€€€€€€ÍÑ…ÑÕÌ€ô€‰Ý…É¸ˆ(€€€€€€€€€€€•Ù¥‘•¹”€ô€ˆì€ˆ¹©½¥¸¡Ý…É¹¥¹Ì¤(€€€€€€€€€€€É•µ•‘¥…Ñ¥½¸€ô€‰½È•¹Ñ•ÉÁÉ¥Í”Á¥±½ÑÌ°ÍÁ±¥Ð…‘µ¥¸…¹¥¹™•É•¹”Ñ½­•¹Ì‰•™½É”ÕÍÑ½µ•È•Ù…±Õ…Ñ¥½¸¸ˆ(€€€€€€€•±Í”è(€€€€€€€€€€€ÍÑ…ÑÕÌ€ô€‰Á…ÍÌˆ(€€€€€€€€€€€…ÕÑ¡}•Ù¥‘•¹”€ô€ (€€€€€€€€€€€€€€€€‰•áÑ•É¹…°‰•…É•ÈÙ•É¥™¥•Èˆ(€€€€€€€€€€€€€€€¥˜…ÕÑ¡}µ½‘”€ôô€‰•áÑ•É¹…±}‰•…É•É}Ù•É¥™¥•Èˆ(€€€€€€€€€€€€€€€•±Í”€‰ÍÁ±¥ÐÑ½­•¹Ìˆ(€€€€€€€€€€€€¤(€€€€€€€€€€€•Ù¥‘•¹”€ô˜‰í…ÕÑ¡}•Ù¥‘•¹•ô°ÁÉ¥Ù…Ñ”‰¥¹‘•™…Õ±Ð°¡¥‘‘•¸ÑÉ…•Ì°É…Ñ”±¥µ¥ÑÌ°…¹ÉÕ¸±¥µ¥ÑÌ…É”½¹™¥ÕÉ•ˆ(€€€€€€€€€€€É•µ•‘¥…Ñ¥½¸€ô€‰-••ÀÑ¡•Í”½¹ÑÉ½±Ì•¹…‰±•™½ÈÕÍÑ½µ•Èµ™…¥¹œÁ¥±½ÑÌ¸ˆ((€€€€€€€É•ÑÕÉ¸Í•±˜¹}É¥Ñ•É¥½¸ ‰Í•ÕÉ¥Ñå}Á½ÍÑÕÉ”ˆ°€‰M•ÕÉ¥ÑäÁ½ÍÑÕÉ”ˆ°ÍÑ…ÑÕÌ°•Ù¥‘•¹”°É•µ•‘¥…Ñ¥½¸¤((€€€‘•˜}±½…±•}É•…‘¥¹•ÍÍ}É¥Ñ•É¥½¸¡Í•±˜°…¹…±åÑ¥Ìè‘¥ÑmÍÑÈ°¹åt¤€´ø‘¥ÑmÍÑÈ°ÍÑÉtè(€€€€€€€±½…±•}µ•ÑÉ¥Œ€ô¹•áÐ (€€€€€€€€€€€µ•ÑÉ¥Œ™½Èµ•ÑÉ¥Œ¥¸…¹…±åÑ¥Íl‰Õ…É‘É…¥±Ì‰t¥˜µ•ÑÉ¥l‰µ•ÑÉ¥}¹…µ”‰t€ôô€‰±½…±•}­•å}Á…É¥Ñäˆ(€€€€€€€€¤(€€€€€€€µ¥ÍÍ¥¹œ€ô±½…±•}µ•ÑÉ¥Œ¹•Ð ‰µ¥ÍÍ¥¹}­•åÌˆ°mt¤(€€€€€€€Á…É¥Ñä€ô±½…±•}µ•ÑÉ¥Œ¹•Ð ‰Ù…±Õ•}Á•É•¹Ðˆ¤(€€€€€€€¥˜Á…É¥Ñä€ôô€ÄÀÀ¸Àè(€€€€€€€€€€€ÍÑ…ÑÕÌ€ô€‰Á…ÍÌˆ(€€€€€€€€€€€•Ù¥‘•¹”€ô€‰¹±¥Í …¹-½É•…¸…‘µ¥¸±½…±”­•åÌ…É”…±¥¹•ˆ(€€€€€€€€€€€É•µ•‘¥…Ñ¥½¸€ô€‰-••À±½…±”Á…É¥ÑäÑ•ÍÑÌÕÁ‘…Ñ•Ý¡•¸…‘‘¥¹œ½Á•É…Ñ½È½Áä¸ˆ(€€€€€€€•±Í”è(€€€€€€€€€€€ÍÑ…ÑÕÌ€ô€‰Ý…É¸ˆ¥˜µ¥ÍÍ¥¹œ•±Í”€‰™…¥°ˆ(€€€€€€€€€€€•Ù¥‘•¹”€ô˜‰íÁ…É¥Ñåô”±½…±”­•äÁ…É¥Ñäìµ¥ÍÍ¥¹œ­•åÌèìœ°€œ¹©½¥¸¡µ¥ÍÍ¥¹œ¤½È€±½…±”‰Õ¹‘±•Ì…‰Í•¹Ðôˆ(€€€€€€€€€€€É•µ•‘¥…Ñ¥½¸€ô€‰¥±°µ¥ÍÍ¥¹œ-½É•…¸…¹¹±¥Í ½Á•É…Ñ½È±…‰•±Ì‰•™½É”ÕÍÑ½µ•ÈÉ•Ù¥•Ü¸ˆ(€€€€€€€É•ÑÕÉ¸Í•±˜¹}É¥Ñ•É¥½¸ ‰±½…±•}É•…‘¥¹•ÍÌˆ°€‰1½…±”É•…‘¥¹•ÍÌˆ°ÍÑ…ÑÕÌ°•Ù¥‘•¹”°É•µ•‘¥…Ñ¥½¸¤((€€€‘•˜}ÁÉ½Ù¥‘•É}•É•ÍÍ}É¥Ñ•É¥½¸¡Í•±˜¤€´ø‘¥ÑmÍÑÈ°ÍÑÉtè(€€€€€€€Õ¹Í…™”€ômt(€€€€€€€É•µ½Ñ”€ômt(€€€€€€€™½È…•¹Ð¥¸Í•±˜¹…•¹ÑÌè(€€€€€€€€€€€¥˜…•¹Ð¹‰…Í•}ÕÉ°¹ÍÑ…ÉÑÍÝ¥Ñ  ‰µ½¬è¼¼ˆ¤è(€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€¥˜}¥Í}±½…±}ÁÉ½Ù¥‘•É}ÕÉ°¡…•¹Ð¹‰…Í•}ÕÉ°¤è(€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€É•µ½Ñ”¹…ÁÁ•¹¡…•¹Ð¹¥¤(€€€€€€€€€€€Á…ÉÍ•€ôÕÉ±Á…ÉÍ”¡…•¹Ð¹‰…Í•}ÕÉ°¤(€€€€€€€€€€€¥˜Á…ÉÍ•¹Í¡•µ”€„ô€‰¡ÑÑÁÌˆ½È¹½Ð…•¹Ð¹É•‘•¹Ñ¥…±}¹…µ”è(€€€€€€€€€€€€€€€Õ¹Í…™”¹…ÁÁ•¹¡…•¹Ð¹¥¤(€€€€€€€¥˜Õ¹Í…™”è(€€€€€€€€€€€ÍÑ…ÑÕÌ€ô€‰™…¥°ˆ(€€€€€€€€€€€•Ù¥‘•¹”€ô˜‰Õ¹Í…™”ÁÉ½Ù¥‘•È•É•ÍÌ½¹™¥œ™½È…•¹ÑÌèìœ°€œ¹©½¥¸¡Í½ÉÑ•¡Õ¹Í…™”¤¥ôˆ(€€€€€€€€€€€É•µ•‘¥…Ñ¥½¸€ô€‰UÍ”¡ÑÑÁÌÁÉ½Ù¥‘•È•¹‘Á½¥¹ÑÌÝ¥Ñ „¹…µ•-XÉ•‘•¹Ñ¥…°‰•™½É”•¹…‰±¥¹œÉ•µ½Ñ”•É•ÍÌ¸ˆ(€€€€€€€•±Í”è(€€€€€€€€€€€ÍÑ…ÑÕÌ€ô€‰Á…ÍÌˆ(€€€€€€€€€€€•Ù¥‘•¹”€ô€ (€€€€€€€€€€€€€€€€‰µ½¬ÁÉ½Ù¥‘•ÉÌ½¹±äˆ(€€€€€€€€€€€€€€€¥˜¹½ÐÉ•µ½Ñ”(€€€€€€€€€€€€€€€•±Í”˜‰í±•¸¡É•µ½Ñ”¥ôÉ•µ½Ñ”ÁÉ½Ù¥‘•ÉÌÕÍ”¡ÑÑÁÌ…¹„¹…µ•-XÉ•‘•¹Ñ¥…°ˆ(€€€€€€€€€€€€¤(€€€€€€€€€€€É•µ•‘¥…Ñ¥½¸€ô€‰-••ÀÁÉ½Ù¥‘•È…±±½Üµ±¥ÍÐ•¹™½É•µ•¹Ð•¹…‰±•™½È¹½¸µµ½¬ÁÉ½Ù¥‘•ÉÌ¸ˆ(€€€€€€€É•ÑÕÉ¸Í•±˜¹}É¥Ñ•É¥½¸ ‰ÁÉ½Ù¥‘•É}•É•ÍÍ}Í…™•Ñäˆ°€‰AÉ½Ù¥‘•È•É•ÍÌÍ…™•Ñäˆ°ÍÑ…ÑÕÌ°•Ù¥‘•¹”°É•µ•‘¥…Ñ¥½¸¤((€€€‘•˜}É¥Ñ•É¥…}‰å}¹…µ”¡Í•±˜°É¥Ñ•É¥„è±¥ÍÑm‘¥ÑmÍÑÈ°ÍÑÉut¤€´ø‘¥ÑmÍÑÈ°‘¥ÑmÍÑÈ°ÍÑÉutè(€€€€€€€É•ÑÕÉ¸íÉ½Ýl‰É¥Ñ•É¥½¹}¹…µ”‰tèÉ½Ü™½ÈÉ½Ü¥¸É¥Ñ•É¥…ô((€€€‘•˜}µ•ÑÉ¥Í}‰å}¹…µ”¡Í•±˜°µ•ÑÉ¥Ìè±¥ÍÑm‘¥ÑmÍÑÈ°¹åut¤€´ø‘¥ÑmÍÑÈ°‘¥ÑmÍÑÈ°¹åutè(€€€€€€€É•ÑÕÉ¸íÉ½Ýl‰µ•ÑÉ¥}¹…µ”‰tèÉ½Ü™½ÈÉ½Ü¥¸µ•ÑÉ¥Íô((€€€‘•˜}½µµ•É¥…±}‘½Õµ•¹Ñ…Ñ¥½¹}ÁÉ½™¥±”¡Í•±˜¤€´ø‘¥ÑmÍÑÈ°¹åtè(€€€€€€€É½½Ð€ôA…Ñ ¡}}™¥±•}|¤¹É•Í½±Ù” ¤¹Á…É•¹ÑÍlÅt(€€€€€€€É•ÅÕ¥É•‘}‘½Õµ•¹ÑÌ€ôl(€€€€€€€€€€€€‰I5¹µˆ°(€€€€€€€€€€€€‰MUI%Qd¹µˆ°(€€€€€€€€€€€€‰‘½Ì½ÁÉ½‘ÕÑ}Á±…¹¹¥¹œ¹µˆ°(€€€€€€€€€€€€‰‘½Ì½É•ÍÑ}…Á¥}‘•Í¥¸¹µˆ°(€€€€€€€€€€€€‰‘½Ì½…¹…±åÑ¥Í}ÍÁ•Œ¹µˆ°(€€€€€€€€€€€€‰‘½Ì½½µµ•É¥…±}É•…‘¥¹•ÍÌ¹µˆ°(€€€€€€€t(€€€€€€€µ¥ÍÍ¥¹}‘½Õµ•¹ÑÌ€ôl(€€€€€€€€€€€‘½Õµ•¹Ñ}Á…Ñ (€€€€€€€€€€€™½È‘½Õµ•¹Ñ}Á…Ñ ¥¸É•ÅÕ¥É•‘}‘½Õµ•¹ÑÌ(€€€€€€€€€€€¥˜¹½Ð€¡É½½Ð€¼‘½Õµ•¹Ñ}Á…Ñ ¤¹¥Í}™¥±” ¤(€€€€€€€t(€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€‰É•ÅÕ¥É•‘}‘½Õµ•¹ÑÌˆèÉ•ÅÕ¥É•‘}‘½Õµ•¹ÑÌ°(€€€€€€€€€€€€‰µ¥ÍÍ¥¹}‘½Õµ•¹ÑÌˆèµ¥ÍÍ¥¹}‘½Õµ•¹ÑÌ°(€€€€€€€€€€€€‰ÁÉ•Í•¹Ñ}½Õ¹Ðˆè±•¸¡É•ÅÕ¥É•‘}‘½Õµ•¹ÑÌ¤€´±•¸¡µ¥ÍÍ¥¹}‘½Õµ•¹ÑÌ¤°(€€€€€€€€€€€€‰É•ÅÕ¥É•‘}½Õ¹Ðˆè±•¸¡É•ÅÕ¥É•‘}‘½Õµ•¹ÑÌ¤°(€€€€€€€€€€€€‰¡…Í}Í•ÕÉ¥Ñå}Á½±¥äˆè€¡É½½Ð€¼€‰MUI%Qd¹µˆ¤¹¥Í}™¥±” ¤°(€€€€€€€€€€€€‰Í½ÕÉ”ˆè€‰É•Á½Í¥Ñ½Éä‘½Õµ•¹Ñ…Ñ¥½¸™¥±•Ìˆ°(€€€€€€€ô((€€€‘•˜}É¥Ñ•É¥…}ÍÕµµ…Éä¡Í•±˜°É¥Ñ•É¥„è±¥ÍÑm‘¥ÑmÍÑÈ°ÍÑÉut¤€´ø‘¥ÑmÍÑÈ°¥¹Ñtè(€€€€€€€½Õ¹ÑÌ€ô½Õ¹Ñ•È¡É½Ýl‰ÍÑ…ÑÕÌ‰t™½ÈÉ½Ü¥¸É¥Ñ•É¥„¤(€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€‰Á…ÍÌˆè½Õ¹ÑÌ¹•Ð ‰Á…ÍÌˆ°€À¤°(€€€€€€€€€€€€‰Ý…É¸ˆè½Õ¹ÑÌ¹•Ð ‰Ý…É¸ˆ°€À¤°(€€€€€€€€€€€€‰™…¥°ˆè½Õ¹ÑÌ¹•Ð ‰™…¥°ˆ°€À¤°(€€€€€€€ô(()‘•˜É•‘…Ñ}Ñ•áÐ¡Ñ•áÐèÍÑÈ¤€´øÍÑÈè(€€€€ˆˆ‰5…Í¬É•‘•¹Ñ¥…°Í¡…Á•Ì€¡A$­•åÌ°Ñ½­•¹Ì°Á…ÍÍÝ½É‘Ì°‰•…É•È¡•…‘•ÉÌ¤™É½´ÑÉ…•Ì¸((€€€½•Ì¹½Ðµ…Í¬A%$€¡•µ…¥°…‘‘É•ÍÍ•Ì°¹…µ•Ì°•ÑŒ¸¤èÁ•È½Ù•É¹…¹”µÉ¥Í¬µ½µÁ±¥…¹”Á½±¥ä°(€€€A%$¥ÌÁÉ½Ñ•Ñ•‰äÁÕÉÁ½Í”µ±¥µ¥Ñ•…ÕÑ¡½É¥é…Ñ¥½¸°•¹ÉåÁÑ¥½¸°…¹…Õ‘¥Ð±½¥¹œ°¹½Ð‰ä(€€€‘•ÍÑÉ½å¥¹œ¥Ð¥¸•Ù•ÉäÉ•ÍÁ½¹Í”€´´‰±…¹­•ÐA%$µ…Í­¥¹œ¡•É”‰É½­”•Ù•Éä‘½Ý¹ÍÑÉ•…´(€€€½¹ÍÕµ•ÈÑ¡…Ð¹••‘ÌÑ¡”É•…°½¹Ñ•¹Ð€¡”¹œ¸…¸•µ…¥°±¥•¹ÐÉ•¹‘•É¥¹œ…ÑÕ…°…‘‘É•ÍÍ•Ì¤¸(€€€€ˆˆˆ(€€€É•‘…Ñ•€ôÑ•áÐ(€€€™½ÈÁ…ÑÑ•É¸¥¸MIQ}AQQI9Lè(€€€€€€€¥˜Á…ÑÑ•É¸¹Á…ÑÑ•É¸¹±½Ý•È ¤¹ÍÑ…ÉÑÍÝ¥Ñ  ˆ ý¤¤¡…Á¤ˆ¤è(€€€€€€€€€€€É•‘…Ñ•€ôÁ…ÑÑ•É¸¹ÍÕˆ¡±…µ‰‘„µ…Ñ è˜‰íµ…Ñ ¹É½ÕÀ Ä¥õíµ…Ñ ¹É½ÕÀ È¥õmIQtˆ°É•‘…Ñ•¤(€€€€€€€•±Í”è(€€€€€€€€€€€É•‘…Ñ•€ôÁ…ÑÑ•É¸¹ÍÕˆ¡±…µ‰‘„µ…Ñ è˜‰íµ…Ñ ¹É½ÕÀ Ä¥õmIQtˆ°É•‘…Ñ•¤(€€€É•ÑÕÉ¸É•‘…Ñ•(()‘•˜É•‘…Ñ}Ù…±Õ”¡Ù…±Õ”è¹ä¤€´ø¹äè(€€€€ˆˆ‰I•ÕÉÍ¥Ù•±äÉ•‘…ÐÍÑÉ¥¹œÙ…±Õ•ÌÝ¡¥±”ÁÉ•Í•ÉÙ¥¹œÉ•ÍÁ½¹Í”Í¡…Á”¸ˆˆˆ(€€€¥˜¥Í¥¹ÍÑ…¹”¡Ù…±Õ”°ÍÑÈ¤è(€€€€€€€É•ÑÕÉ¸É•‘…Ñ}Ñ•áÐ¡Ù…±Õ”¤(€€€¥˜¥Í¥¹ÍÑ…¹”¡Ù…±Õ”°±¥ÍÐ¤è(€€€€€€€É•ÑÕÉ¸mÉ•‘…Ñ}Ù…±Õ”¡¥Ñ•´¤™½È¥Ñ•´¥¸Ù…±Õ•t(€€€¥˜¥Í¥¹ÍÑ…¹”¡Ù…±Õ”°‘¥Ð¤è(€€€€€€€É•ÑÕÉ¸í­•äèÉ•‘…Ñ}Ù…±Õ”¡¥Ñ•´¤™½È­•ä°¥Ñ•´¥¸Ù…±Õ”¹¥Ñ•µÌ ¥ô(€€€É•ÑÕÉ¸Ù…±Õ”()‘•˜}™É••é•}É•Á½ÉÑ}…¡•}Ù…±Õ”¡Ù…±Õ”è¹ä¤€´ø¹äè(€€€¥˜¥Í¥¹ÍÑ…¹”¡Ù…±Õ”°‘¥Ð¤è(€€€€€€€É•ÑÕÉ¸ÑÕÁ±” (€€€€€€€€€€€Í½ÉÑ• (€€€€€€€€€€€€€€€€¡ÍÑÈ¡­•ä¤°}™É••é•}É•Á½ÉÑ}…¡•}Ù…±Õ”¡¥Ñ•´¤¤(€€€€€€€€€€€€€€€™½È­•ä°¥Ñ•´¥¸Ù…±Õ”¹¥Ñ•µÌ ¤(€€€€€€€€€€€€¤(€€€€€€€€¤(€€€¥˜¥Í¥¹ÍÑ…¹”¡Ù…±Õ”°€¡±¥ÍÐ°ÑÕÁ±”¤¤è(€€€€€€€É•ÑÕÉ¸ÑÕÁ±”¡}™É••é•}É•Á½ÉÑ}…¡•}Ù…±Õ”¡¥Ñ•´¤™½È¥Ñ•´¥¸Ù…±Õ”¤(€€€¥˜¥Í¥¹ÍÑ…¹”¡Ù…±Õ”°Í•Ð¤è(€€€€€€€É•ÑÕÉ¸ÑÕÁ±”¡Í½ÉÑ•¡}™É••é•}É•Á½ÉÑ}…¡•}Ù…±Õ”¡¥Ñ•´¤™½È¥Ñ•´¥¸Ù…±Õ”¤¤(€€€ÑÉäè(€€€€€€€¡…Í ¡Ù…±Õ”¤(€€€•á•ÁÐQåÁ•ÉÉ½Èè(€€€€€€€É•ÑÕÉ¸É•ÁÈ¡Ù…±Õ”¤(€€€É•ÑÕÉ¸Ù…±Õ”(()‘•˜}…¡•‘}½µµ•É¥…±}É•Á½ÉÐ¡µ•Ñ¡½è¹ä¤€´ø¹äè(€€€ÝÉ…ÁÌ¡µ•Ñ¡½¤(€€€‘•˜ÝÉ…ÁÁ•È¡Í•±˜èQ…Í­=É¡•ÍÑÉ…Ñ½È°€©…ÉÌè¹ä°€¨©­Ý…ÉÌè¹ä¤€´ø‘¥ÑmÍÑÈ°¹åtè(€€€€€€€…¡”€ô}=55I%1}IA=IQ}!¹•Ð ¤(€€€€€€€Ñ½­•¸€ô9½¹”(€€€€€€€¥˜…¡”¥Ì9½¹”è(€€€€€€€€€€€…¡”€ôíô(€€€€€€€€€€€Ñ½­•¸€ô}=55I%1}IA=IQ}!¹Í•Ð¡…¡”¤(€€€€€€€ÑÉäè(€€€€€€€€€€€­•ä€ô€ (€€€€€€€€€€€€€€€µ•Ñ¡½¹}}¹…µ•}|°(€€€€€€€€€€€€€€€}™É••é•}É•Á½ÉÑ}…¡•}Ù…±Õ”¡…ÉÌ¤°(€€€€€€€€€€€€€€€}™É••é•}É•Á½ÉÑ}…¡•}Ù…±Õ”¡­Ý…ÉÌ¤°(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜­•ä¹½Ð¥¸…¡”è(€€€€€€€€€€€€€€€…¡•m­•åt€ôµ•Ñ¡½¡Í•±˜°€©…ÉÌ°€¨©­Ý…ÉÌ¤(€€€€€€€€€€€É•ÑÕÉ¸…¡•m­•åt(€€€€€€€™¥¹…±±äè(€€€€€€€€€€€¥˜Ñ½­•¸¥Ì¹½Ð9½¹”è(€€€€€€€€€€€€€€€}=55I%1}IA=IQ}!¹É•Í•Ð¡Ñ½­•¸¤((€€€É•ÑÕÉ¸ÝÉ…ÁÁ•È(()™½È}½µµ•É¥…±}É•Á½ÉÑ}¹…µ”°}½µµ•É¥…±}É•Á½ÉÑ}µ•Ñ¡½¥¸±¥ÍÐ¡Q…Í­=É¡•ÍÑÉ…Ñ½È¹}}‘¥Ñ}|¹¥Ñ•µÌ ¤¤è(€€€¥˜€ (€€€€€€€}½µµ•É¥…±}É•Á½ÉÑ}¹…µ”¹ÍÑ…ÉÑÍÝ¥Ñ  ‰½µµ•É¥…±|ˆ¤(€€€€€€€…¹}½µµ•É¥…±}É•Á½ÉÑ}¹…µ”¹•¹‘ÍÝ¥Ñ  ‰}É•Á½ÉÐˆ¤(€€€€€€€…¹…±±…‰±”¡}½µµ•É¥…±}É•Á½ÉÑ}µ•Ñ¡½¤(€€€€¤è(€€€€€€€Í•Ñ…ÑÑÈ (€€€€€€€€€€€Q…Í­=É¡•ÍÑÉ…Ñ½È°(€€€€€€€€€€€}½µµ•É¥…±}É•Á½ÉÑ}¹…µ”°(€€€€€€€€€€€}…¡•‘}½µµ•É¥…±}É•Á½ÉÐ¡}½µµ•É¥…±}É•Á½ÉÑ}µ•Ñ¡½¤°(€€€€€€€€¤(()‘•˜}Á…É•Ñ½}™É½¹Ð¡É•ÍÕ±ÑÌè±¥ÍÑm‘¥ÑmÍÑÈ°¹åut¤€´ø±¥ÍÑm‘¥ÑmÍÑÈ°¹åutè(€€€€ˆˆ‰½¹™¥Ì¹½Ð‘½µ¥¹…Ñ•½¸€¡ÅÕ…±¥ÑäÕÀ°½ÍÐ‘½Ý¸¤¸ˆˆˆ(€€€µ•…ÍÕÉ•€ômÉ½Ü™½ÈÉ½Ü¥¸É•ÍÕ±ÑÌ¥˜É½Ü¹•Ð ‰½ÍÑ}ÕÍˆ¤¥Ì¹½Ð9½¹•t(€€€™É½¹Ðè±¥ÍÑm‘¥ÑmÍÑÈ°¹åut€ômt(€€€™½È„¥¸µ•…ÍÕÉ•è(€€€€€€€‘½µ¥¹…Ñ•€ô…¹ä (€€€€€€€€€€€ˆ¥Ì¹½Ð„(€€€€€€€€€€€…¹‰l‰ÅÕ…±¥Ñä‰t€øô…l‰ÅÕ…±¥Ñä‰t(€€€€€€€€€€€…¹‰l‰½ÍÑ}ÕÍ‰t€ðô…l‰½ÍÑ}ÕÍ‰t(€€€€€€€€€€€…¹€¡‰l‰ÅÕ…±¥Ñä‰t€ø…l‰ÅÕ…±¥Ñä‰t½È‰l‰½ÍÑ}ÕÍ‰t€ð…l‰½ÍÑ}ÕÍ‰t¤(€€€€€€€€€€€™½Èˆ¥¸µ•…ÍÕÉ•(€€€€€€€€¤(€€€€€€€¥˜¹½Ð‘½µ¥¹…Ñ•è(€€€€€€€€€€€™É½¹Ð¹…ÁÁ•¹¡„¤(€€€É•ÑÕÉ¸™É½¹Ð(()‘•˜}É•½µµ•¹‘}½¹™¥œ¡É•ÍÕ±ÑÌè±¥ÍÑm‘¥ÑmÍÑÈ°¹åut°½ÍÑ}‰Õ‘•Ñ}ÕÍè™±½…Ðð9½¹”¤€´ø‘¥ÑmÍÑÈ°¹åtð9½¹”è(€€€µ•…ÍÕÉ•€ômÉ½Ü™½ÈÉ½Ü¥¸É•ÍÕ±ÑÌ¥˜É½Ü¹•Ð ‰½ÍÑ}ÕÍˆ¤¥Ì¹½Ð9½¹•t(€€€¥˜¹½Ðµ•…ÍÕÉ•è(€€€€€€€É•ÑÕÉ¸9½¹”(€€€¥˜½ÍÑ}‰Õ‘•Ñ}ÕÍ¥Ì¹½Ð9½¹”è(€€€€€€€…™™½É‘…‰±”€ômÈ™½ÈÈ¥¸µ•…ÍÕÉ•¥˜Él‰½ÍÑ}ÕÍ‰t€ðô½ÍÑ}‰Õ‘•Ñ}ÕÍ‘t(€€€€€€€¥˜…™™½É‘…‰±”è(€€€€€€€€€€€‰•ÍÐ€ôµ…à¡…™™½É‘…‰±”°­•äõ±…µ‰‘„Èè€¡Él‰ÅÕ…±¥Ñä‰t°€µÉl‰½ÍÑ}ÕÍ‰t¤¤(€€€€€€€€€€€É•…Í½¸€ô€‰¡¥¡•ÍÐÅÕ…±¥ÑäÝ¥Ñ¡¥¸½ÍÐ‰Õ‘•Ðˆ(€€€€€€€•±Í”è(€€€€€€€€€€€‰•ÍÐ€ôµ¥¸¡µ•…ÍÕÉ•°­•äõ±…µ‰‘„ÈèÉl‰½ÍÑ}ÕÍ‰t¤(€€€€€€€€€€€É•…Í½¸€ô€‰¹¼½¹™¥œÝ¥Ñ¡¥¸‰Õ‘•Ðì¡•…Á•ÍÐ¥¹ÍÑ•…ˆ(€€€•±Í”è(€€€€€€€€Œ5…á¥µ¥é”Á•É™½Éµ…¹”™¥ÉÍÐ°µ¥¹¥µ¥é”½ÍÐ…ÌÑ¡”Ñ¥”µ‰É•…¬€¡¡•…Á•ÍÐ…µ½¹œÑ¡”(€€€€€€€€Œ‰•ÍÐµÅÕ…±¥Ñä½¹™¥Ì¤ƒŠPÑ¡”¡½¹•ÍÐÉ•…‘¥¹œ½˜€‰µ…àÅÕ…±¥ÑäÝ¡¥±”µ¥¸½ÍÐˆ¸(€€€€€€€‰•ÍÐ€ôµ…à¡µ•…ÍÕÉ•°­•äõ±…µ‰‘„Èè€¡Él‰ÅÕ…±¥Ñä‰t°€µÉl‰½ÍÑ}ÕÍ‰t¤¤(€€€€€€€É•…Í½¸€ô€‰¡¥¡•ÍÐÅÕ…±¥Ñäì¡•…Á•ÍÐ…µ½¹œ•ÅÕ…°µÅÕ…±¥Ñä½¹™¥Ìˆ(€€€É•ÑÕÉ¸ì‰¹…µ”ˆè‰•ÍÑl‰¹…µ”‰t°€‰ÅÕ…±¥Ñäˆè‰•ÍÑl‰ÅÕ…±¥Ñä‰t°€‰½ÍÑ}ÕÍˆè‰•ÍÑl‰½ÍÑ}ÕÍ‰t°€‰É•…Í½¸ˆèÉ•…Í½¹ô(()‘•˜}½ÁÑ¥µ¥é•É}ÕÍ…•}Í¹…ÁÍ¡½Ð¡½É¡•ÍÑÉ…Ñ½Èè¹ä°•Ù…±Õ…Ñ¥½¹}¥¹‘•àè¥¹Ð¤€´ø‘¥ÑmÍÑÈ°¹åtè(€€€€ˆˆ‰…ÁÑÕÉ”ÕµÕ±…Ñ¥Ù”•¹¥¹”Ñ½Ñ…±ÌÝ¥Ñ¡½ÕÐÁÉ½µÁÑÌ°½¹™¥ÕÉ…Ñ¥½¸°½Èµ½‘•°¥‘•¹Ñ¥™¥•ÉÌ¸ˆˆˆ(€€€Ñ½Ñ…±Ì€ô½É¡•ÍÑÉ…Ñ½È¹ÍÁ•¹‘}…¹…±åÑ¥Ì ¥l‰Ñ½Ñ…±Ì‰t(€€€É•ÑÕÉ¸ì(€€€€€€€€‰•Ù…±Õ…Ñ¥½¹}¥¹‘•àˆè•Ù…±Õ…Ñ¥½¹}¥¹‘•à°(€€€€€€€€‰Í½Á”ˆè€‰ÕµÕ±…Ñ¥Ù•}•¹¥¹•}Í¹…ÁÍ¡½Ðˆ°(€€€€€€€€‰Í¹…ÁÍ¡½Ñ}ÍÑ…ÑÕÌˆè€‰…Ù…¥±…‰±”ˆ°(€€€€€€€€‰Ñ½Ñ…±Ìˆèí­•äèÑ½Ñ…±Ì¹•Ð¡­•ä¤™½È­•ä¥¸€ (€€€€€€€€€€€€‰ÉÕ¹}½Õ¹Ðˆ°€‰ÁÉ½µÁÑ}Ñ½­•¹Ìˆ°€‰½ÕÑÁÕÑ}Ñ½­•¹Ìˆ°€‰ÁÉ½µÁÑ}Ñ½­•¹Í}Í½ÕÉ”ˆ°€‰½ÍÑ}ÕÍˆ°€‰ÕÉÉ•¹äˆ(€€€€€€€€¥ôðì‰½ÍÑ}ÕÍˆèÑ½Ñ…±Íl‰½ÍÑ}ÕÍ‰uô°(€€€ô(()‘•˜}Í½É•}½¹™¥œ¡½É¡•ÍÑÉ…Ñ½Èè¹ä°Ñ…Í­Ìè±¥ÍÑm‘¥ÑmÍÑÈ°¹åut°ÅÕ…±¥Ñå}™¸è¹ä°µ½‘”èÍÑÈ°ÕÍ•}‰…Ñ è‰½½°°(€€€€€€€€€€€€€€€€€ÕÍ…•}É••¥ÁÑÌè±¥ÍÑm‘¥ÑmÍÑÈ°¹åut¤€´øÑÕÁ±•m™±½…Ð°±¥ÍÑm™±½…Ñutè(€€€€ˆˆ‰I•ÑÕÉ¸Ñ¡”•á¥ÍÑ¥¹œµ•…¸…¹½É‘•É•Ñ…Í¬Í½É•ÌÝ¥Ñ¡½ÕÐ¡…¹¥¹œÍ•±•Ñ¥½¸Á½±¥ä¸ˆˆˆ(€€€ÑÉäè(€€€€€€€¥˜ÕÍ•}‰…Ñ …¹µ½‘”€ôô€‰É½ÕÑ”ˆè(€€€€€€€€€€€É•½É‘Ì€ô½É¡•ÍÑÉ…Ñ½È¹‰…Ñ¡}É½ÕÑ”¡mÑ…Í­l‰ÁÉ½µÁÐ‰t™½ÈÑ…Í¬¥¸Ñ…Í­Ít¤(€€€€€€€€€€€¥˜±•¸¡É•½É‘Ì¤€„ô±•¸¡Ñ…Í­Ì¤è(€€€€€€€€€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È ‰‰…Ñ É•ÍÕ±Ð½Õ¹ÐµÕÍÐµ…Ñ Ñ…Í¬½Õ¹Ðˆ¤(€€€€€€€€€€€Í½É•Ì€ôm™±½…Ð¡ÅÕ…±¥Ñå}™¸¡Ñ…Í¬°É•½É‘l‰…¹ÍÝ•È‰t½È€ˆˆ¤¤™½ÈÑ…Í¬°É•½É¥¸é¥À¡Ñ…Í­Ì°É•½É‘Ì¥t(€€€€€€€•±Í”è(€€€€€€€€€€€Í½É•Ì€ôl(€€€€€€€€€€€€€€€™±½…Ð¡ÅÕ…±¥Ñå}™¸¡Ñ…Í¬°½É¡•ÍÑÉ…Ñ½È¹ÉÕ¸¡mì‰É½±”ˆè€‰ÕÍ•Èˆ°€‰½¹Ñ•¹ÐˆèÑ…Í­l‰ÁÉ½µÁÐ‰uõt°µ½‘”õµ½‘”¥l‰…¹ÍÝ•È‰t¤¤(€€€€€€€€€€€€€€€™½ÈÑ…Í¬¥¸Ñ…Í­Ì(€€€€€€€€€€€t(€€€€€€€¥˜…¹ä¡¹½Ðµ…Ñ ¹¥Í™¥¹¥Ñ”¡Í½É”¤½È¹½Ð€À¸À€ðôÍ½É”€ðô€Ä¸À™½ÈÍ½É”¥¸Í½É•Ì¤è(€€€€€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È ‰ÅÕ…±¥ÑäÍ½É•ÌµÕÍÐ‰”™¥¹¥Ñ”…¹¥¸lÀ°€Åtˆ¤(€€€€€€€ÕÍ…•}É••¥ÁÑÌ¹…ÁÁ•¹¡}½ÁÑ¥µ¥é•É}ÕÍ…•}Í¹…ÁÍ¡½Ð¡½É¡•ÍÑÉ…Ñ½È°±•¸¡ÕÍ…•}É••¥ÁÑÌ¤¤¤(€€€€€€€É•ÑÕÉ¸€¡ÍÕ´¡Í½É•Ì¤€¼±•¸¡Í½É•Ì¤¥˜Í½É•Ì•±Í”€À¸À¤°Í½É•Ì(€€€•á•ÁÐá•ÁÑ¥½¸…Ì•Ù…±Õ…Ñ¥½¹}•ÉÉ½Èè(€€€€€€€ÑÉäè(€€€€€€€€€€€™…¥±•‘}ÕÍ…”€ô}½ÁÑ¥µ¥é•É}ÕÍ…•}Í¹…ÁÍ¡½Ð¡½É¡•ÍÑÉ…Ñ½È°±•¸¡ÕÍ…•}É••¥ÁÑÌ¤¤(€€€€€€€•á•ÁÐá•ÁÑ¥½¸è(€€€€€€€€€€€™…¥±•‘}ÕÍ…”€ôì‰•Ù…±Õ…Ñ¥½¹}¥¹‘•àˆè±•¸¡ÕÍ…•}É••¥ÁÑÌ¤°€‰Í½Á”ˆè€‰ÕµÕ±…Ñ¥Ù•}•¹¥¹•}Í¹…ÁÍ¡½Ðˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰Í¹…ÁÍ¡½Ñ}ÍÑ…ÑÕÌˆè€‰Õ¹…Ù…¥±…‰±”ˆ°€‰Ñ½Ñ…±Ìˆè9½¹•ô(€€€€€€€½µÁ±•Ñ•‘}ÕÍ…”€ôÑÕÁ±”¡l©ÕÍ…•}É••¥ÁÑÌ°™…¥±•‘}ÕÍ…•t¤(€€€€€€€Ù…ÉÌ¡•Ù…±Õ…Ñ¥½¹}•ÉÉ½È¥l‰½ÁÑ¥µ¥é•É}ÕÍ…”‰t€ô½µÁ±•Ñ•‘}ÕÍ…”(€€€€€€€É…¥Í”(()‘•˜}É•ÅÕ¥É•}É•±•…Í•‘}½ÁÑ¥µ¥é•É}Í•±•Ñ¥½¹}½¹ÑÉ…Ð ¤€´ø9½¹”è(€€€€ˆˆ‰…¥°±½Í•Õ¹Ñ¥°™…ÍÐµµ±Í¥É´É•±•…Í•Ì…¹‘¥‘…Ñ”µÍ•±•Ñ¥½¸…ÕÑ¡½É¥Ñä¸ˆˆˆ(€€€É…¥Í”IÕ¹Ñ¥µ•ÉÉ½È (€€€€€€€€‰½ÁÑ¥µ¥é•ÈÍ•±•Ñ¥½¸É•ÅÕ¥É•Ì„É•±•…Í•™…ÍÐµµ±Í¥É´…¹‘¥‘…Ñ”µÍ•±•Ñ¥½¸½¹ÑÉ…Ðˆ(€€€€¤(()‘•˜½ÁÑ¥µ¥é•}½É¡•ÍÑÉ…Ñ¥½¸ (€€€…¹‘¥‘…Ñ•Ìè±¥ÍÑm‘¥ÑmÍÑÈ°¹åut°(€€€Ñ…Í­Ìè±¥ÍÑm‘¥ÑmÍÑÈ°¹åut°(€€€ÅÕ…±¥Ñå}™¸è¹ä°(€€€½ÍÑ}‰Õ‘•Ñ}ÕÍè™±½…Ðð9½¹”€ô9½¹”°(€€€ÕÍ•}‰…Ñ è‰½½°€ô…±Í”°(¤€´ø‘¥ÑmÍÑÈ°¹åtè(€€€€ˆˆ‰M•…É ½É¡•ÍÑÉ…Ñ¥½¸½¹™¥Ì™½Èµ…á¥µÕ´ÅÕ…±¥Ñä…Ðµ¥¹¥µÕ´½ÍÐ€¡Ñ¡”ÕÔÑÉ…‘•½™˜¤¸((€€€€´…¹‘¥‘…Ñ•Í€èmì‰¹…µ”ˆèÍÑÈ°€‰½É¡•ÍÑÉ…Ñ½ÈˆèQ…Í­=É¡•ÍÑÉ…Ñ½È°€‰µ½‘”ˆèÍÑÉõu€¸(€€€€€… ½É¡•ÍÑÉ…Ñ½ÈÍ¡½Õ±‰”™É•Í Í¼¥ÑÌÍÁ•¹É•™±•ÑÌ½¹±äÑ¡¥ÌÍ•…É ¸(€€€€´Ñ…Í­Í€èmì‰ÁÉ½µÁÐˆèÍÑÈ°€¸¸¹õu€ƒŠPÑ¡”•Ù…°Í•Ðì•… Ñ…Í¬€¬Ñ¡”ÁÉ½‘Õ•(€€€€€…¹ÍÝ•È¥ÌÁ…ÍÍ•Ñ¼ÅÕ…±¥Ñå}™¹€¸(€€€€´ÅÕ…±¥Ñå}™¸¡Ñ…Í¬°…¹ÍÝ•É}Ñ•áÐ¤€´ø™±½…Ñ€¥¸lÀ°€ÅtƒŠPÑ¡”…±±•ÈÌÉ•…°ÅÕ…±¥Ñä(€€€€€Í¥¹…°€¡”¹œ¸¡•­…‰±”…¹ÍÝ•ÉÌ½È„©Õ‘”¤¸Q¡¥Ì™Õ¹Ñ¥½¸‘½•Ì¹½Ð™…‰É¥…Ñ”ÅÕ…±¥Ñä¸(€€€€´½ÍÑ}‰Õ‘•Ñ}ÕÍ‘€è½ÁÑ¥½¹…°…À¸I•½µµ•¹‘…Ñ¥½¸€ô¡¥¡•ÍÐµÅÕ…±¥Ñä½¹™¥œÝ¥Ñ¡¥¸(€€€€€‰Õ‘•Ð°•±Í”Ñ¡”¡•…Á•ÍÐìÝ¥Ñ ¹¼‰Õ‘•Ð°¡¥¡•ÍÐÅÕ…±¥ÑäÑ¡•¸¡•…Á•ÍÐ¸((€€€I•ÑÕÉ¹ÌÁ•Èµ½¹™¥œµ•…ÍÕÉ•ÅÕ…±¥Ñä€¬É•…°½ÍÐ°Ñ¡”A…É•Ñ¼™É½¹Ð°…¹„É•½µµ•¹‘…Ñ¥½¸¸(€€€… É•ÍÕ±Ð…±Í¼É•Ñ…¥¹ÌÍ½É•}½‰Í•ÉÙ…Ñ¥½¹Í€¥¸¥¹ÁÕÐµÑ…Í¬½É‘•È°‰•™½É”(€€€µ•…¸É½Õ¹‘¥¹œ¸Q¡¥Ì‘•ÍÉ¥ÁÑ¥Ù”•Ù¥‘•¹”‘½•Ì¹½Ð•ÍÑ…‰±¥Í …±¥‰É…Ñ¥½¸½È(€€€…ÁÁ±¥…‰¥±¥Ñä½˜Ñ¡”•á¥ÍÑ¥¹œÍ•±•Ñ¥½¸Á½±¥ä¸(€€€€ˆˆˆ(€€€}É•ÅÕ¥É•}É•±•…Í•‘}½ÁÑ¥µ¥é•É}Í•±•Ñ¥½¹}½¹ÑÉ…Ð ¤(€€€É•ÍÕ±ÑÌè±¥ÍÑm‘¥ÑmÍÑÈ°¹åut€ômt(€€€ÕÍ…•}É••¥ÁÑÌè±¥ÍÑm‘¥ÑmÍÑÈ°¹åut€ômt(€€€™½È…¹‘¥‘…Ñ”¥¸…¹‘¥‘…Ñ•Ìè(€€€€€€€½É¡•ÍÑÉ…Ñ½È€ô…¹‘¥‘…Ñ•l‰½É¡•ÍÑÉ…Ñ½È‰t(€€€€€€€µ½‘”€ô…¹‘¥‘…Ñ”¹•Ð ‰µ½‘”ˆ°€‰…ÕÑ¼ˆ¤(€€€€€€€ÅÕ…±¥Ñä°Í½É•}½‰Í•ÉÙ…Ñ¥½¹Ì€ô}Í½É•}½¹™¥œ¡½É¡•ÍÑÉ…Ñ½È°Ñ…Í­Ì°ÅÕ…±¥Ñå}™¸°µ½‘”°ÕÍ•}‰…Ñ °ÕÍ…•}É••¥ÁÑÌ¤(€€€€€€€½ÍÐ€ôÕÍ…•}É••¥ÁÑÍl´Åul‰Ñ½Ñ…±Ì‰ul‰½ÍÑ}ÕÍ‰t(€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì(€€€€€€€€€€€€‰¹…µ”ˆè…¹‘¥‘…Ñ•l‰¹…µ”‰t°(€€€€€€€€€€€€‰µ½‘”ˆèµ½‘”°(€€€€€€€€€€€€‰ÅÕ…±¥ÑäˆèÉ½Õ¹¡ÅÕ…±¥Ñä°€Ð¤°(€€€€€€€€€€€€‰Í½É•}½‰Í•ÉÙ…Ñ¥½¹ÌˆèÍ½É•}½‰Í•ÉÙ…Ñ¥½¹Ì°(€€€€€€€€€€€€‰½ÍÑ}ÕÍˆèÉ½Õ¹¡½ÍÐ°€Ø¤¥˜½ÍÐ¥Ì¹½Ð9½¹”•±Í”9½¹”°(€€€€€€€€€€€€‰ÅÕ…±¥Ñå}Á•É}ÕÍˆè€ (€€€€€€€€€€€€€€€É½Õ¹¡ÅÕ…±¥Ñä€¼½ÍÐ°€È¤¥˜½ÍÐ¥Ì¹½Ð9½¹”…¹½ÍÐ€ø€À•±Í”9½¹”(€€€€€€€€€€€€¤°(€€€€€€€€€€€€‰Ñ…Í­}½Õ¹Ðˆè±•¸¡Ñ…Í­Ì¤°(€€€€€€€ô¤((€€€É•ÑÕÉ¸ì(€€€€€€€€‰½‰©•Ñ¥Ù”ˆè€‰µ…á¥µ¥é”ÅÕ…±¥Ñä°µ¥¹¥µ¥é”½ÍÐˆ°(€€€€€€€€‰½ÍÑ}‰Õ‘•Ñ}ÕÍˆè½ÍÑ}‰Õ‘•Ñ}ÕÍ°(€€€€€€€€‰É•ÍÕ±ÑÌˆèÍ½ÉÑ• (€€€€€€€€€€€É•ÍÕ±ÑÌ°(€€€€€€€€€€€­•äõ±…µ‰‘„Èè€ (€€€€€€€€€€€€€€€€µÉl‰ÅÕ…±¥Ñä‰t°(€€€€€€€€€€€€€€€Él‰½ÍÑ}ÕÍ‰t¥Ì9½¹”°(€€€€€€€€€€€€€€€Él‰½ÍÑ}ÕÍ‰t¥˜Él‰½ÍÑ}ÕÍ‰t¥Ì¹½Ð9½¹”•±Í”™±½…Ð ‰¥¹˜ˆ¤°(€€€€€€€€€€€€¤°(€€€€€€€€¤°(€€€€€€€€‰Á…É•Ñ½}™É½¹ÐˆèmÉl‰¹…µ”‰t™½ÈÈ¥¸}Á…É•Ñ½}™É½¹Ð¡É•ÍÕ±ÑÌ¥t°(€€€€€€€€‰É•½µµ•¹‘•ˆè}É•½µµ•¹‘}½¹™¥œ¡É•ÍÕ±ÑÌ°½ÍÑ}‰Õ‘•Ñ}ÕÍ¤°(€€€ô(()‘•˜•Ù½±Ù•}½É¡•ÍÑÉ…Ñ¥½¸ (€€€‰Õ¥±‘}½É¡•ÍÑÉ…Ñ½Èè¹ä°(€€€Í•…É¡}ÍÁ…”è‘¥ÑmÍÑÈ°±¥ÍÑm¹åut°(€€€Ñ…Í­Ìè±¥ÍÑm‘¥ÑmÍÑÈ°¹åut°(€€€ÅÕ…±¥Ñå}™¸è¹ä°(€€€•¹•É…Ñ¥½¹Ìè¥¹Ð€ô€Ð°(€€€Á½ÁÕ±…Ñ¥½¸è¥¹Ð€ô€Ø°(€€€½ÍÑ}‰Õ‘•Ñ}ÕÍè™±½…Ðð9½¹”€ô9½¹”°(€€€Í••è¥¹Ð€ô€Ü°(€€€ÕÍ•}‰…Ñ è‰½½°€ô…±Í”°(¤€´ø‘¥ÑmÍÑÈ°¹åtè(€€€€ˆˆ‰Ù½±Ù”½É¡•ÍÑÉ…Ñ¥½¸½¹™¥ÌÑ½Ý…Éµ…àÅÕ…±¥Ñä…Ðµ¥¸½ÍÐ€¡QI%9%QdµÍÑå±”Í•…É ¤¸((€€€½ÈÍ•…É ÍÁ…•ÌÑ½¼±…É”Ñ¼•¹Õµ•É…Ñ”è„Í••‘•µÕÑ…Ñ¥½¸­Í•±•Ñ¥½¸±½½À½Ù•È(€€€Í•…É¡}ÍÁ…•€€¡Á…É…´€´ø…¹‘¥‘…Ñ”Ù…±Õ•Ì¤¸‰Õ¥±‘}½É¡•ÍÑÉ…Ñ½È¡½¹™¥œ¥€É•ÑÕÉ¹Ì„(€€€™É•Í Q…Í­=É¡•ÍÑÉ…Ñ½È™½È„½¹™¥œ€¡Ñ¡”…±±•È½Ý¹ÌÁÉ½Ù¥‘•ÈÝ¥É¥¹œ¤ì•… ½¹™¥œ¥Ì(€€€•Ù…±Õ…Ñ•=9…¹…¡•ƒŠPÉ¥Ñ¥…°Ý¡•¸•Ù…±Õ…Ñ¥½¸½ÍÑÌÉ•…°A$µ½¹•ä¸((€€€¥Ñ¹•ÍÌµ…á¥µ¥é•Ìµ•…ÍÕÉ•ÅÕ…±¥Ñä°Ñ¡•¸µ¥¹¥µ¥é•Ìµ•…ÍÕÉ•½ÍÐì½¹™¥ÌÝ¡½Í”½ÍÐ(€€€•á••‘Ì½ÍÑ}‰Õ‘•Ñ}ÕÍ‘€É…¹¬‰•±½Ü…±°…™™½É‘…‰±”½¹•Ì¸EÕ…±¥Ñä½µ•Ì™É½´Ñ¡”(€€€…±±•ÈÌÅÕ…±¥Ñå}™¸¡Ñ…Í¬°…¹ÍÝ•È¤€´ølÀ°Åu€ƒŠP¹•Ù•È™…‰É¥…Ñ•¸(€€€A•Èµ½¹™¥œÍ½É•}½‰Í•ÉÙ…Ñ¥½¹Í€É•Ñ…¥¸¥¹ÁÕÐµÑ…Í¬½É‘•È‰•™½É”µ•…¸É½Õ¹‘¥¹œ¸(€€€Q¡•¥È…Ù…¥±…‰¥±¥Ñä‘½•Ì¹½ÐÅÕ…±¥™äÑ¡”•á¥ÍÑ¥¹œ™¥Ñ¹•ÍÌÁ½±¥äÁÍå¡½µ•ÑÉ¥…±±ä¸(€€€€ˆˆˆ(€€€}É•ÅÕ¥É•}É•±•…Í•‘}½ÁÑ¥µ¥é•É}Í•±•Ñ¥½¹}½¹ÑÉ…Ð ¤(€€€É¹œ€ôÉ…¹‘½´¹I…¹‘½´¡Í••¤(€€€Á…É…µÌ€ôÍ½ÉÑ•¡Í•…É¡}ÍÁ…”¤((€€€‘•˜É…¹‘½µ}½¹™¥œ ¤€´ø‘¥ÑmÍÑÈ°¹åtè(€€€€€€€É•ÑÕÉ¸íÀèÉ¹œ¹¡½¥”¡Í•…É¡}ÍÁ…•mÁt¤™½ÈÀ¥¸Á…É…µÍô((€€€‘•˜µÕÑ…Ñ”¡½¹™¥œè‘¥ÑmÍÑÈ°¹åt¤€´ø‘¥ÑmÍÑÈ°¹åtè(€€€€€€€¡¥±€ô‘¥Ð¡½¹™¥œ¤(€€€€€€€•¹”€ôÉ¹œ¹¡½¥”¡Á…É…µÌ¤(€€€€€€€¡½¥•Ì€ômØ™½ÈØ¥¸Í•…É¡}ÍÁ…•m•¹•t¥˜Ø€„ô½¹™¥m•¹•ut½ÈÍ•…É¡}ÍÁ…•m•¹•t(€€€€€€€¡¥±‘m•¹•t€ôÉ¹œ¹¡½¥”¡¡½¥•Ì¤(€€€€€€€É•ÑÕÉ¸¡¥±((€€€‘•˜­•ä¡½¹™¥œè‘¥ÑmÍÑÈ°¹åt¤€´øÍÑÈè(€€€€€€€É•ÑÕÉ¸©Í½¸¹‘ÕµÁÌ¡íÀè½¹™¥mÁt™½ÈÀ¥¸Á…É…µÍô°Í½ÉÑ}­•åÌõQÉÕ”°•¹ÍÕÉ•}…Í¥¤õ…±Í”¤((€€€•Ù…±Õ…Ñ•è‘¥ÑmÍÑÈ°‘¥ÑmÍÑÈ°¹åut€ôíô(€€€ÕÍ…•}É••¥ÁÑÌè±¥ÍÑm‘¥ÑmÍÑÈ°¹åut€ômt((€€€‘•˜•Ù…±Õ…Ñ”¡½¹™¥œè‘¥ÑmÍÑÈ°¹åt¤€´ø‘¥ÑmÍÑÈ°¹åtè(€€€€€€€½¹™¥}­•ä€ô­•ä¡½¹™¥œ¤(€€€€€€€¥˜½¹™¥}­•ä¥¸•Ù…±Õ…Ñ•è(€€€€€€€€€€€É•ÑÕÉ¸•Ù…±Õ…Ñ•‘m½¹™¥}­•åt(€€€€€€€½É¡•ÍÑÉ…Ñ½È€ô‰Õ¥±‘}½É¡•ÍÑÉ…Ñ½È¡½¹™¥œ¤(€€€€€€€µ½‘”€ô½¹™¥œ¹•Ð ‰µ½‘”ˆ°€‰…ÕÑ¼ˆ¤(€€€€€€€ÅÕ…±¥Ñä°Í½É•}½‰Í•ÉÙ…Ñ¥½¹Ì€ô}Í½É•}½¹™¥œ¡½É¡•ÍÑÉ…Ñ½È°Ñ…Í­Ì°ÅÕ…±¥Ñå}™¸°µ½‘”°ÕÍ•}‰…Ñ °ÕÍ…•}É••¥ÁÑÌ¤(€€€€€€€½ÍÐ€ôÕÍ…•}É••¥ÁÑÍl´Åul‰Ñ½Ñ…±Ì‰ul‰½ÍÑ}ÕÍ‰t(€€€€€€€É•ÍÕ±Ð€ôì(€€€€€€€€€€€€‰¹…µ”ˆè½¹™¥}­•ä°(€€€€€€€€€€€€‰½¹™¥œˆè‘¥Ð¡½¹™¥œ¤°(€€€€€€€€€€€€‰ÅÕ…±¥ÑäˆèÉ½Õ¹¡ÅÕ…±¥Ñä°€Ð¤°(€€€€€€€€€€€€‰Í½É•}½‰Í•ÉÙ…Ñ¥½¹ÌˆèÍ½É•}½‰Í•ÉÙ…Ñ¥½¹Ì°(€€€€€€€€€€€€‰½ÍÑ}ÕÍˆèÉ½Õ¹¡½ÍÐ°€Ø¤¥˜½ÍÐ¥Ì¹½Ð9½¹”•±Í”9½¹”°(€€€€€€€€€€€€‰ÅÕ…±¥Ñå}Á•É}ÕÍˆè€ (€€€€€€€€€€€€€€€É½Õ¹¡ÅÕ…±¥Ñä€¼½ÍÐ°€È¤¥˜½ÍÐ¥Ì¹½Ð9½¹”…¹½ÍÐ€ø€À•±Í”9½¹”(€€€€€€€€€€€€¤°(€€€€€€€€€€€€‰Ñ…Í­}½Õ¹Ðˆè±•¸¡Ñ…Í­Ì¤°(€€€€€€€ô(€€€€€€€•Ù…±Õ…Ñ•‘m½¹™¥}­•åt€ôÉ•ÍÕ±Ð(€€€€€€€É•ÑÕÉ¸É•ÍÕ±Ð((€€€‘•˜™¥Ñ¹•ÍÌ¡É½Üè‘¥ÑmÍÑÈ°¹åt¤€´øÑÕÁ±•m¥¹Ð°™±½…Ð°™±½…Ñtè(€€€€€€€¥˜É½Ýl‰½ÍÑ}ÕÍ‰t¥Ì9½¹”è(€€€€€€€€€€€É•ÑÕÉ¸€ À°É½Ýl‰ÅÕ…±¥Ñä‰t°™±½…Ð ˆµ¥¹˜ˆ¤¤(€€€€€€€…™™½É‘…‰±”€ô€Ä¥˜½ÍÑ}‰Õ‘•Ñ}ÕÍ¥Ì9½¹”½ÈÉ½Ýl‰½ÍÑ}ÕÍ‰t€ðô½ÍÑ}‰Õ‘•Ñ}ÕÍ•±Í”€À(€€€€€€€É•ÑÕÉ¸€¡…™™½É‘…‰±”°É½Ýl‰ÅÕ…±¥Ñä‰t°€µÉ½Ýl‰½ÍÑ}ÕÍ‰t¤((€€€€ŒM••Á½ÁÕ±…Ñ¥½¸€¡‘•‘ÕÀ­•åÌÍ¼„Ñ¥¹äÍÁ…”‘½•Í¸ÐÝ…ÍÑ”•Ù…±Õ…Ñ¥½¹Ì¤¸(€€€Á½½°è±¥ÍÑm‘¥ÑmÍÑÈ°¹åut€ômt(€€€Í••¸èÍ•ÑmÍÑÉt€ôÍ•Ð ¤(€€€Ý¡¥±”±•¸¡Á½½°¤€ðÁ½ÁÕ±…Ñ¥½¸…¹±•¸¡Í••¸¤€ðµ¥¸¡Á½ÁÕ±…Ñ¥½¸€¨€Ð°}ÍÁ…•}Í¥é”¡Í•…É¡}ÍÁ…”¤¤è(€€€€€€€½¹™¥œ€ôÉ…¹‘½µ}½¹™¥œ ¤(€€€€€€€¥˜­•ä¡½¹™¥œ¤¹½Ð¥¸Í••¸è(€€€€€€€€€€€Í••¸¹…‘¡­•ä¡½¹™¥œ¤¤(€€€€€€€€€€€Á½½°¹…ÁÁ•¹¡½¹™¥œ¤((€€€¡¥ÍÑ½Éäè±¥ÍÑm‘¥ÑmÍÑÈ°¹åut€ômt(€€€™½È•¹•É…Ñ¥½¸¥¸É…¹”¡•¹•É…Ñ¥½¹Ì¤è(€€€€€€€É½ÝÌ€ôm•Ù…±Õ…Ñ”¡½¹™¥œ¤™½È½¹™¥œ¥¸Á½½±t(€€€€€€€É½ÝÌ¹Í½ÉÐ¡­•äõ™¥Ñ¹•ÍÌ°É•Ù•ÉÍ”õQÉÕ”¤(€€€€€€€ÍÕÉÙ¥Ù½ÉÌ€ôÉ½ÝÍlèµ…à Ä°±•¸¡É½ÝÌ¤€¼¼€È¥t(€€€€€€€¡¥ÍÑ½Éä¹…ÁÁ•¹¡ì(€€€€€€€€€€€€‰•¹•É…Ñ¥½¸ˆè•¹•É…Ñ¥½¸°(€€€€€€€€€€€€‰‰•ÍÐˆèì‰½¹™¥œˆèÍÕÉÙ¥Ù½ÉÍlÁul‰½¹™¥œ‰t°€‰ÅÕ…±¥ÑäˆèÍÕÉÙ¥Ù½ÉÍlÁul‰ÅÕ…±¥Ñä‰t°€‰½ÍÑ}ÕÍˆèÍÕÉÙ¥Ù½ÉÍlÁul‰½ÍÑ}ÕÍ‰uô°(€€€€€€€€€€€€‰•Ù…±Õ…Ñ•‘}Ñ½Ñ…°ˆè±•¸¡•Ù…±Õ…Ñ•¤°(€€€€€€€ô¤(€€€€€€€Á½½°€ôm‘¥Ð¡É½Ýl‰½¹™¥œ‰t¤™½ÈÉ½Ü¥¸ÍÕÉÙ¥Ù½ÉÍt(€€€€€€€Ý¡¥±”±•¸¡Á½½°¤€ðÁ½ÁÕ±…Ñ¥½¸è(€€€€€€€€€€€Á½½°¹…ÁÁ•¹¡µÕÑ…Ñ”¡É¹œ¹¡½¥”¡ÍÕÉÙ¥Ù½ÉÌ¥l‰½¹™¥œ‰t¤¤((€€€É•ÍÕ±ÑÌ€ôÍ½ÉÑ•¡•Ù…±Õ…Ñ•¹Ù…±Õ•Ì ¤°­•äõ™¥Ñ¹•ÍÌ°É•Ù•ÉÍ”õQÉÕ”¤(€€€É•ÑÕÉ¸ì(€€€€€€€€‰½‰©•Ñ¥Ù”ˆè€‰µ…á¥µ¥é”ÅÕ…±¥Ñä°µ¥¹¥µ¥é”½ÍÐ€¡•Ù½±ÕÑ¥½¹…ÉäÍ•…É ¤ˆ°(€€€€€€€€‰½ÍÑ}‰Õ‘•Ñ}ÕÍˆè½ÍÑ}‰Õ‘•Ñ}ÕÍ°(€€€€€€€€‰•¹•É…Ñ¥½¹Ìˆè•¹•É…Ñ¥½¹Ì°(€€€€€€€€‰•Ù…±Õ…Ñ¥½¹Ìˆè±•¸¡•Ù…±Õ…Ñ•¤°(€€€€€€€€‰ÍÁ…•}Í¥é”ˆè}ÍÁ…•}Í¥é”¡Í•…É¡}ÍÁ…”¤°(€€€€€€€€‰É•ÍÕ±ÑÌˆèÉ•ÍÕ±ÑÌ°(€€€€€€€€‰Á…É•Ñ½}™É½¹ÐˆèmÉ½Ýl‰¹…µ”‰t™½ÈÉ½Ü¥¸}Á…É•Ñ½}™É½¹Ð¡É•ÍÕ±ÑÌ¥t°(€€€€€€€€‰É•½µµ•¹‘•ˆè}É•½µµ•¹‘}½¹™¥œ¡É•ÍÕ±ÑÌ°½ÍÑ}‰Õ‘•Ñ}ÕÍ¤°(€€€€€€€€‰¡¥ÍÑ½Éäˆè¡¥ÍÑ½Éä°(€€€ô(()‘•˜}ÍÁ…•}Í¥é”¡Í•…É¡}ÍÁ…”è‘¥ÑmÍÑÈ°±¥ÍÑm¹åut¤€´ø¥¹Ðè(€€€Í¥é”€ô€Ä(€€€™½ÈÙ…±Õ•Ì¥¸Í•…É¡}ÍÁ…”¹Ù…±Õ•Ì ¤è(€€€€€€€Í¥é”€¨ôµ…à Ä°±•¸¡Ù…±Õ•Ì¤¤(€€€É•ÑÕÉ¸Í¥é”(()‘•˜¡…Ñ}½µÁ±•Ñ¥½¹}É•ÍÁ½¹Í” (€€€É•ÍÕ±Ðè‘¥ÑmÍÑÈ°¹åt°(€€€µ½‘•°èÍÑÈ€ô€‰½¹Ñ•áÑÕ…°µ½É¡•ÍÑÉ…Ñ½Èˆ°(€€€¥¹±Õ‘•}ÑÉ…”è‰½½°€ô…±Í”°(€€€ÕÍ…”è‘¥ÑmÍÑÈ°¥¹Ñtð9½¹”€ô9½¹”°(€€€ÁÉ½µÁÑ}½Õ¹Ñ}Í½ÕÉ”èÍÑÈð9½¹”€ô9½¹”°(€€€Í¡…É•‘}½¹Ñ•áÑ}‰Õ‘•Ðè‘¥ÑmÍÑÈ°¹åtð9½¹”€ô9½¹”°(¤€´ø‘¥ÑmÍÑÈ°¹åtè€€ŒÁÉ…µ„è¹¼½Ù•È(€€€€ˆˆ‰]É…À½É¡•ÍÑÉ…Ñ¥½¸½ÕÑÁÕÐ¥¸…¸=Á•¹$µ½µÁ…Ñ¥‰±”¡…Ð½µÁ±•Ñ¥½¸É•ÍÁ½¹Í”¸((€€€ÕÍ…•€…ÉÉ¥•Ìµ•…ÍÕÉ•Ñ½­•¸½Õ¹ÑÌ¸‰Í•¹”É•µ…¥¹Ì•áÁ±¥¥Ð…¹¹Õ±°¸(€€€ÁÉ½µÁÑ}½Õ¹Ñ}Í½ÕÉ•€É•½É‘ÌÁÉ½Ù•¹…¹”€¡”¹œ¸€‰ÁÉ½Ù•¹…¹•}•á…Ð‰€¤(€€€½¹±äÝ¡•¸…¸…ÕÑ¡½É¥Ñ…Ñ¥Ù”ÁÉ½µÁÐµµ•ÍÍ…”Ñ½­•¸½Õ¹ÐÝ…Ì½‰Ñ…¥¹•™½È(€€€Ñ¡¥Ì•á…ÐÍ•ÉÙ•É•ÅÕ•ÍÐ½É½ÕÑ”É•Ù¥Í¥½¸ì¥Ð¥Ì½µ¥ÑÑ•É…Ñ¡•ÈÑ¡…¸(€€€™…‰É¥…Ñ•Ý¡•¸¹¼ÍÕ ½Õ¹Ð•á¥ÍÑÌ¸Í¡…É•‘}½¹Ñ•áÑ}‰Õ‘•Ñ€É•½É‘Ì(€€€Ñ¡”Ñ½­•¹}½Õ¹Ñ¥¹œ¹Í¡…É•‘}½¹Ñ•áÑ}½ÕÑÁÕÑ}‰Õ‘•Ñ€•Ù¥‘•¹”(€€€€¡½¹Ñ•áÑ}Ý¥¹‘½Ý€½ÁÉ½µÁÑ}Ñ½­•¹Í€½½ÕÑÁÕÑ}•¥±¥¹€½Í½ÕÉ•€¤™½È(€€€Ñ¡”…•¹ÐÑ¡…Ð…ÑÕ…±±äÍ•ÉÙ•Ñ¡¥ÌÉ•ÅÕ•ÍÐ°¹•áÐÑ¼(€€€ÁÉ½µÁÑ}½Õ¹Ñ}Í½ÕÉ•€ì¥Ð¥Ì½µ¥ÑÑ•Ý¡•¸¹¼ÍÕ ‘•¥Í¥½¸Ý…Ìµ…‘”¸(€€€€ˆˆˆ(€€€½É¡•ÍÑÉ…Ñ¥½¸€ôì(€€€€€€€€‰Ý½É­™±½Ý}ÉÕ¹}¥ˆèÉ•ÍÕ±Ð¹•Ð ‰Ý½É­™±½Ý}ÉÕ¹}¥ˆ¤°(€€€€€€€€‰µ½‘”ˆèÉ•ÍÕ±Ñl‰µ½‘”‰t°(€€€€€€€€‰Ù•É¥™¥…Ñ¥½¸ˆèÉ•ÍÕ±Ð¹•Ð ‰Ù•É¥™¥…Ñ¥½¸ˆ¤°(€€€€€€€€‰¡…¹¹•°ˆèÉ•ÍÕ±Ð¹•Ð ‰¡…¹¹•°ˆ¤°(€€€€€€€€‰É½ÕÑ¥¹}É•…Í½¸ˆèÉ•ÍÕ±Ð¹•Ð ‰É½ÕÑ¥¹}É•…Í½¸ˆ¤°(€€€€€€€€‰ÕÍ…•}É•½É‘}¥ˆèÉ•ÍÕ±Ð¹•Ð ‰ÕÍ…•}É•½É‘}¥ˆ¤°(€€€€€€€€‰½ÍÐˆèÉ•ÍÕ±Ð¹•Ð ‰½ÍÐˆ¤°(€€€€€€€€‰Ñ½½±}±½½Á}É½ÕÑ”ˆèÉ•ÍÕ±Ð¹•Ð ‰Ñ½½±}±½½Á}É½ÕÑ”ˆ¤°(€€€€€€€€‰Ñ½½±}±½½Á}…•¹Ñ}¥ˆèÉ•ÍÕ±Ð¹•Ð ‰Ñ½½±}±½½Á}…•¹Ñ}¥ˆ¤°(€€€€€€€€‰É•ÅÕ•ÍÑ•‘}½ÕÑÁÕÑ}Ñ½­•¹ÌˆèÉ•ÍÕ±Ð¹•Ð ‰É•ÅÕ•ÍÑ•‘}½ÕÑÁÕÑ}Ñ½­•¹Ìˆ¤°(€€€€€€€€‰•™™•Ñ¥Ù•}½ÕÑÁÕÑ}Ñ½­•¹ÌˆèÉ•ÍÕ±Ð¹•Ð ‰•™™•Ñ¥Ù•}½ÕÑÁÕÑ}Ñ½­•¹Ìˆ¤°(€€€€€€€€‰½ÕÑÁÕÑ}‰Õ‘•Ñ}±…µÁ•ˆèÉ•ÍÕ±Ð¹•Ð ‰½ÕÑÁÕÑ}‰Õ‘•Ñ}±…µÁ•ˆ¤°(€€€€€€€€‰ÁÉ½µÁÑ}Ñ½­•¹}±½Ý•É}‰½Õ¹ˆèÉ•ÍÕ±Ð¹•Ð ‰ÁÉ½µÁÑ}Ñ½­•¹}±½Ý•É}‰½Õ¹ˆ¤°(€€€€€€€€‰ÁÉ½µÁÑ}Ñ½­•¹}‰½Õ¹‘}Í½ÕÉ”ˆèÉ•ÍÕ±Ð¹•Ð ‰ÁÉ½µÁÑ}Ñ½­•¹}‰½Õ¹‘}Í½ÕÉ”ˆ¤°(€€€€€€€€‰½¹Ñ•áÑ}Ý¥¹‘½Ý}•á±Õ‘•ˆèÉ•ÍÕ±Ð¹•Ð ‰½¹Ñ•áÑ}Ý¥¹‘½Ý}•á±Õ‘•ˆ¤½È9½¹”°(€€€€€€€€‰É½ÕÑ”ˆèÉ•ÍÕ±Ð¹•Ð ‰É½ÕÑ”ˆ¤°(€€€ô(€€€¥˜¥¹±Õ‘•}ÑÉ…”è(€€€€€€€½É¡•ÍÑÉ…Ñ¥½¹l‰ÑÉ…”‰t€ôÉ•‘…Ñ}Ù…±Õ”¡É•ÍÕ±Ñl‰ÑÉ…”‰t¤(€€€µ•ÍÍ…”è‘¥ÑmÍÑÈ°¹åt€ôì‰É½±”ˆè€‰…ÍÍ¥ÍÑ…¹Ðˆ°€‰½¹Ñ•¹ÐˆèÉ•ÍÕ±Ñl‰…¹ÍÝ•È‰uô(€€€Ñ½½±}…±±Ì€ôÉ•ÍÕ±Ð¹•Ð ‰Ñ½½±}…±±Ìˆ¤(€€€¥˜Ñ½½±}…±±Ìè(€€€€€€€µ•ÍÍ…•l‰Ñ½½±}…±±Ì‰t€ôÑ½½±}…±±Ì(€€€€€€€¥˜¹½ÐÉ•ÍÕ±Ð¹•Ð ‰…¹ÍÝ•Èˆ¤è(€€€€€€€€€€€µ•ÍÍ…•l‰½¹Ñ•¹Ð‰t€ô9½¹”(€€€™¥¹¥Í¡}É•…Í½¸€ôÉ•ÍÕ±Ð¹•Ð ‰™¥¹¥Í¡}É•…Í½¸ˆ¤½È€ ‰Ñ½½±}…±±Ìˆ¥˜Ñ½½±}…±±Ì•±Í”€‰ÍÑ½Àˆ¤(€€€É•ÍÁ½¹Í”è‘¥ÑmÍÑÈ°¹åt€ôì(€€€€€€€€‰¥ˆè}¹•Ý}¡…Ñ}½µÁ±•Ñ¥½¹}¥ ¤°(€€€€€€€€‰½‰©•Ðˆè€‰¡…Ð¹½µÁ±•Ñ¥½¸ˆ°(€€€€€€€€‰É•…Ñ•ˆè¥¹Ð¡Ñ¥µ”¹Ñ¥µ” ¤¤°(€€€€€€€€‰µ½‘•°ˆèµ½‘•°°(€€€€€€€€‰¡½¥•Ìˆèl(€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€‰¥¹‘•àˆè€À°(€€€€€€€€€€€€€€€€‰µ•ÍÍ…”ˆèµ•ÍÍ…”°(€€€€€€€€€€€€€€€€‰™¥¹¥Í¡}É•…Í½¸ˆè™¥¹¥Í¡}É•…Í½¸°(€€€€€€€€€€€ô(€€€€€€€t°(€€€€€€€€‰ÕÍ…”ˆèÕÍ…”°(€€€€€€€€‰ÕÍ…•}µ•…ÍÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌˆè€‰µ•…ÍÕÉ•ˆ¥˜ÕÍ…”¥Ì¹½Ð9½¹”•±Í”€‰Õ¹…Ù…¥±…‰±”ˆ°(€€€€€€€€‰½É¡•ÍÑÉ…Ñ¥½¸ˆèí­•äèÙ…±Õ”™½È­•ä°Ù…±Õ”¥¸½É¡•ÍÑÉ…Ñ¥½¸¹¥Ñ•µÌ ¤¥˜Ù…±Õ”¥Ì¹½Ð9½¹•ô°(€€€ô(€€€¥˜ÁÉ½µÁÑ}½Õ¹Ñ}Í½ÕÉ”¥Ì¹½Ð9½¹”è(€€€€€€€É•ÍÁ½¹Í•l‰ÁÉ½µÁÑ}½Õ¹Ñ}Í½ÕÉ”‰t€ôÁÉ½µÁÑ}½Õ¹Ñ}Í½ÕÉ”(€€€¥˜Í¡…É•‘}½¹Ñ•áÑ}‰Õ‘•Ð¥Ì¹½Ð9½¹”è(€€€€€€€É•ÍÁ½¹Í•l‰Í¡…É•‘}½¹Ñ•áÑ}‰Õ‘•Ð‰t€ôÍ¡…É•‘}½¹Ñ•áÑ}‰Õ‘•Ð(€€€É•ÑÕÉ¸É•ÍÁ½¹Í”(()‘•˜Ñ•áÑ}½µÁ±•Ñ¥½¹}É•ÍÁ½¹Í” (€€€É•ÍÕ±Ðè‘¥ÑmÍÑÈ°¹åt°(€€€µ½‘•°èÍÑÈ€ô€‰½¹Ñ•áÑÕ…°µ½É¡•ÍÑÉ…Ñ½Èˆ°(€€€ÕÍ…”è‘¥ÑmÍÑÈ°¥¹Ñtð9½¹”€ô9½¹”°(¤€´ø‘¥ÑmÍÑÈ°¹åtè€€ŒÁÉ…µ„è¹¼½Ù•È(€€€€ˆˆ‰]É…À½É¡•ÍÑÉ…Ñ¥½¸½ÕÑÁÕÐ…Ì=Á•¹$±•…äÑ•áÑ}½µÁ±•Ñ¥½¹€€¡€½ØÄ½½µÁ±•Ñ¥½¹Í€¤¸ˆˆˆ(€€€É•ÑÕÉ¸ì(€€€€€€€€‰¥ˆè˜‰µÁ°µí¥¹Ð¡Ñ¥µ”¹Ñ¥µ” ¤€¨€ÄÀÀÀ¥ôˆ°(€€€€€€€€‰½‰©•Ðˆè€‰Ñ•áÑ}½µÁ±•Ñ¥½¸ˆ°(€€€€€€€€‰É•…Ñ•ˆè¥¹Ð¡Ñ¥µ”¹Ñ¥µ” ¤¤°(€€€€€€€€‰µ½‘•°ˆèµ½‘•°°(€€€€€€€€‰¡½¥•Ìˆèl(€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€‰¥¹‘•àˆè€À°(€€€€€€€€€€€€€€€€‰Ñ•áÐˆèÉ•ÍÕ±Ñl‰…¹ÍÝ•È‰t°(€€€€€€€€€€€€€€€€‰±½ÁÉ½‰Ìˆè9½¹”°(€€€€€€€€€€€€€€€€‰™¥¹¥Í¡}É•…Í½¸ˆè€‰ÍÑ½Àˆ°(€€€€€€€€€€€ô(€€€€€€€t°(€€€€€€€€‰ÕÍ…”ˆèÕÍ…”°(€€€€€€€€‰ÕÍ…•}µ•…ÍÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌˆè€‰µ•…ÍÕÉ•ˆ¥˜ÕÍ…”¥Ì¹½Ð9½¹”•±Í”€‰Õ¹…Ù…¥±…‰±”ˆ°(€€€ô(()}MQI5}!U9-}M%i€ô€ÌÈ(()‘•˜¡…Ñ}½µÁ±•Ñ¥½¹}¡Õ¹­Ì (€€€É•ÍÕ±Ðè‘¥ÑmÍÑÈ°¹åt°(€€€µ½‘•°èÍÑÈ€ô€‰½¹Ñ•áÑÕ…°µ½É¡•ÍÑÉ…Ñ½Èˆ°(€€€¥¹±Õ‘•}ÑÉ…”è‰½½°€ô…±Í”°(€€€¥¹±Õ‘•}ÕÍ…”è‰½½°€ô…±Í”°(¤€´ø±¥ÍÑm‘¥ÑmÍÑÈ°¹åutè(€€€€ˆˆ‰É…µ”…¸½É¡•ÍÑÉ…Ñ¥½¸É•ÍÕ±Ð…Ì=Á•¹$µ½µÁ…Ñ¥‰±”¡…Ð½µÁ±•Ñ¥½¸¡Õ¹­Ì¸((€€€=¹±äÁÉ½Ù¥‘•ÈµÉ•Á½ÉÑ•ÕÍ…”µ…ä‰”•µ¥ÑÑ•¸…Ñ•Ý…ä•ÍÑ¥µ…Ñ•ÌÉ•µ…¥¸¥¹Ñ•É¹…°(€€€‰•…ÕÍ”ÁÉ•Í•¹Ñ¥¹œ•ÍÑ¥µ…Ñ•Ì…ÌÁÉ½Ù¥‘•ÈÕÍ…”Ý½Õ±Ù¥½±…Ñ”Ñ¡”Ý¥É”½¹ÑÉ…Ð¸(€€€€ˆˆˆ(€€€…¹ÍÝ•È€ôÉ•ÍÕ±Ð¹•Ð ‰…¹ÍÝ•Èˆ°€ˆˆ¤(€€€½µÁ±•Ñ¥½¹}¥€ô}¹•Ý}¡…Ñ}½µÁ±•Ñ¥½¹}¥ ¤(€€€É•…Ñ•€ô¥¹Ð¡Ñ¥µ”¹Ñ¥µ” ¤¤(€€€‰…Í”€ôì(€€€€€€€€‰¥ˆè½µÁ±•Ñ¥½¹}¥°(€€€€€€€€‰½‰©•Ðˆè€‰¡…Ð¹½µÁ±•Ñ¥½¸¹¡Õ¹¬ˆ°(€€€€€€€€‰É•…Ñ•ˆèÉ•…Ñ•°(€€€€€€€€‰µ½‘•°ˆèµ½‘•°°(€€€ô(€€€¥˜¥¹±Õ‘•}ÕÍ…”è(€€€€€€€‰…Í•l‰ÕÍ…”‰t€ô9½¹”((€€€¡Õ¹­Ìè±¥ÍÑm‘¥ÑmÍÑÈ°¹åut€ôl(€€€€€€€ì(€€€€€€€€€€€€¨©‰…Í”°(€€€€€€€€€€€€‰¡½¥•Ìˆèl(€€€€€€€€€€€€€€€ì‰¥¹‘•àˆè€À°€‰‘•±Ñ„ˆèì‰É½±”ˆè€‰…ÍÍ¥ÍÑ…¹Ð‰ô°€‰™¥¹¥Í¡}É•…Í½¸ˆè9½¹•ô(€€€€€€€€€€€t°(€€€€€€€ô(€€€t(€€€™½È½™™Í•Ð¥¸É…¹” À°±•¸¡…¹ÍÝ•È¤°}MQI5}!U9-}M%i¤è(€€€€€€€Á¥•”€ô…¹ÍÝ•Ém½™™Í•Ð€è½™™Í•Ð€¬}MQI5}!U9-}M%it(€€€€€€€¡Õ¹­Ì¹…ÁÁ•¹ (€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€¨©‰…Í”°(€€€€€€€€€€€€€€€€‰¡½¥•Ìˆèl(€€€€€€€€€€€€€€€€€€€ì‰¥¹‘•àˆè€À°€‰‘•±Ñ„ˆèì‰½¹Ñ•¹ÐˆèÁ¥••ô°€‰™¥¹¥Í¡}É•…Í½¸ˆè9½¹•ô(€€€€€€€€€€€€€€€t°(€€€€€€€€€€€ô(€€€€€€€€¤(€€€Ñ½½±}…±±Ì€ôÉ•ÍÕ±Ð¹•Ð ‰Ñ½½±}…±±Ìˆ¤(€€€¥˜Ñ½½±}…±±Ìè(€€€€€€€¡Õ¹­Ì¹…ÁÁ•¹ (€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€¨©‰…Í”°(€€€€€€€€€€€€€€€€‰¡½¥•Ìˆèl(€€€€€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€€€€€‰¥¹‘•àˆè€À°(€€€€€€€€€€€€€€€€€€€€€€€€‰‘•±Ñ„ˆèì(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰Ñ½½±}…±±Ìˆèl(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ì‰¥¹‘•àˆè¥¹‘•à°€¨©…±±ô(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€™½È¥¹‘•à°…±°¥¸•¹Õµ•É…Ñ”¡Ñ½½±}…±±Ì¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€t(€€€€€€€€€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€€€€€€€€€€€€€€‰™¥¹¥Í¡}É•…Í½¸ˆè9½¹”°(€€€€€€€€€€€€€€€€€€€ô(€€€€€€€€€€€€€€€t°(€€€€€€€€€€€ô(€€€€€€€€¤((€€€½É¡•ÍÑÉ…Ñ¥½¸€ôì(€€€€€€€€‰Ý½É­™±½Ý}ÉÕ¹}¥ˆèÉ•ÍÕ±Ð¹•Ð ‰Ý½É­™±½Ý}ÉÕ¹}¥ˆ¤°(€€€€€€€€‰µ½‘”ˆèÉ•ÍÕ±Ð¹•Ð ‰µ½‘”ˆ¤°(€€€€€€€€‰Ù•É¥™¥…Ñ¥½¸ˆèÉ•ÍÕ±Ð¹•Ð ‰Ù•É¥™¥…Ñ¥½¸ˆ¤°(€€€€€€€€‰Ñ½½±}±½½Á}É½ÕÑ”ˆèÉ•ÍÕ±Ð¹•Ð ‰Ñ½½±}±½½Á}É½ÕÑ”ˆ¤°(€€€€€€€€‰Ñ½½±}±½½Á}…•¹Ñ}¥ˆèÉ•ÍÕ±Ð¹•Ð ‰Ñ½½±}±½½Á}…•¹Ñ}¥ˆ¤°(€€€€€€€€‰É•ÅÕ•ÍÑ•‘}½ÕÑÁÕÑ}Ñ½­•¹ÌˆèÉ•ÍÕ±Ð¹•Ð ‰É•ÅÕ•ÍÑ•‘}½ÕÑÁÕÑ}Ñ½­•¹Ìˆ¤°(€€€€€€€€‰•™™•Ñ¥Ù•}½ÕÑÁÕÑ}Ñ½­•¹ÌˆèÉ•ÍÕ±Ð¹•Ð ‰•™™•Ñ¥Ù•}½ÕÑÁÕÑ}Ñ½­•¹Ìˆ¤°(€€€€€€€€‰½ÕÑÁÕÑ}‰Õ‘•Ñ}±…µÁ•ˆèÉ•ÍÕ±Ð¹•Ð ‰½ÕÑÁÕÑ}‰Õ‘•Ñ}±…µÁ•ˆ¤°(€€€ô(€€€¥˜¥¹±Õ‘•}ÑÉ…”…¹€‰ÑÉ…”ˆ¥¸É•ÍÕ±Ðè(€€€€€€€½É¡•ÍÑÉ…Ñ¥½¹l‰ÑÉ…”‰t€ôÉ•‘…Ñ}Ù…±Õ”¡É•ÍÕ±Ñl‰ÑÉ…”‰t¤((€€€™¥¹¥Í¡}É•…Í½¸€ôÉ•ÍÕ±Ð¹•Ð ‰™¥¹¥Í¡}É•…Í½¸ˆ¤½È€ (€€€€€€€€‰Ñ½½±}…±±Ìˆ¥˜Ñ½½±}…±±Ì•±Í”€‰ÍÑ½Àˆ(€€€€¤(€€€™¥¹…°€ôì(€€€€€€€€¨©‰…Í”°(€€€€€€€€‰¡½¥•Ìˆèmì‰¥¹‘•àˆè€À°€‰‘•±Ñ„ˆèíô°€‰™¥¹¥Í¡}É•…Í½¸ˆè™¥¹¥Í¡}É•…Í½¹õt°(€€€€€€€€‰½É¡•ÍÑÉ…Ñ¥½¸ˆèì(€€€€€€€€€€€­•äèÙ…±Õ”™½È­•ä°Ù…±Õ”¥¸½É¡•ÍÑÉ…Ñ¥½¸¹¥Ñ•µÌ ¤¥˜Ù…±Õ”¥Ì¹½Ð9½¹”(€€€€€€€ô°(€€€ô(€€€¡Õ¹­Ì¹…ÁÁ•¹¡™¥¹…°¤((€€€ÕÍ…”€ôÉ•ÍÕ±Ð¹•Ð ‰ÕÍ…”ˆ¤(€€€½ÍÐ€ôÉ•ÍÕ±Ð¹•Ð ‰½ÍÐˆ¤(€€€¥˜¥¹±Õ‘•}ÕÍ…”è(€€€€€€€µ•…ÍÕÉ•€ô€ (€€€€€€€€€€€¥Í¥¹ÍÑ…¹”¡½ÍÐ°‘¥Ð¤(€€€€€€€€€€€…¹½ÍÐ¹•Ð ‰µ•…ÍÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌˆ¤€ôô€‰µ•…ÍÕÉ•ˆ(€€€€€€€€€€€…¹¥Í¥¹ÍÑ…¹”¡ÕÍ…”°‘¥Ð¤(€€€€€€€€¤(€€€€€€€¡Õ¹­Ì¹…ÁÁ•¹ (€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€¨©‰…Í”°(€€€€€€€€€€€€€€€€‰¡½¥•Ìˆèmt°(€€€€€€€€€€€€€€€€‰ÕÍ…”ˆèÕÍ…”¥˜µ•…ÍÕÉ••±Í”9½¹”°(€€€€€€€€€€€€€€€€‰ÕÍ…•}µ•…ÍÕÉ•µ•¹Ñ}ÍÑ…ÑÕÌˆè€‰µ•…ÍÕÉ•ˆ¥˜µ•…ÍÕÉ••±Í”€‰Õ¹…Ù…¥±…‰±”ˆ°(€€€€€€€€€€€ô(€€€€€€€€¤(€€€É•ÑÕÉ¸¡Õ¹­Ì(()‘•˜}¹•Ý}¡…Ñ}½µÁ±•Ñ¥½¹}¥ ¤€´øÍÑÈè(€€€€ˆˆ‰É•…Ñ”„½±±¥Í¥½¸µÉ•Í¥ÍÑ…¹Ð=Á•¹$µ½µÁ…Ñ¥‰±”½µÁ±•Ñ¥½¸¥‘•¹Ñ¥™¥•È¸ˆˆˆ(€€€É•ÑÕÉ¸˜‰¡…ÑµÁ°µíÕÕ¥¹ÕÕ¥Ð ¤¹¡•áôˆ(()‘•˜ÍÍ•}ÍÑÉ•…µ}‰½‘ä¡¡Õ¹­Ìè±¥ÍÑm‘¥ÑmÍÑÈ°¹åut¤€´øÍÑÈè(€€€€ˆˆ‰M•É¥…±¥é”¡…Ð½µÁ±•Ñ¥½¸¡Õ¹­Ì…Ì„M•ÉÙ•ÈµM•¹ÐÙ•¹ÑÌ‰½‘äÑ•Éµ¥¹…Ñ•‰äm=9u€¸ˆˆˆ(€€€™É…µ•Ì€ôm˜‰‘…Ñ„èí©Í½¸¹‘ÕµÁÌ¡¡Õ¹¬°•¹ÍÕÉ•}…Í¥¤õ…±Í”¥õq¹q¸ˆ™½È¡Õ¹¬¥¸¡Õ¹­Ít(€€€™É…µ•Ì¹…ÁÁ•¹ ‰‘…Ñ„èm=9uq¹q¸ˆ¤(€€€É•ÑÕÉ¸€ˆˆ¹©½¥¸¡™É…µ•Ì¤(