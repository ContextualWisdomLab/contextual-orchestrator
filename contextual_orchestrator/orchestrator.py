Warning: truncated output (original token count: 247595)
Total output lines: 20073

"""Runtime orchestration, workflow trace, governance, and audit primitives."""

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
from typing import Any, Callable
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
    EffortCatalogSnapshot,
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
    tuple[object, EffortCatalogSnapshot | None, OrchestrationPolicy] | None
] = ContextVar("contextual_orchestrator_request_execution_snapshot", default=None)


def _request_execution_scoped(method: Callable) -> Callable:
    """Keep one policy and effort revision across nested and suspended calls."""
    if inspect.isgeneratorfunction(method):
        @wraps(method)
        def scoped_stream(self, *args, **kwargs):
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


def _resolved_openrouter_provider(agent: ModelAgent) -> str:
    """Canonical provider identity for the ZDR-pin decision, base_url-first.

    ``ModelAgent.provider_name`` is free-text and unvalidated at construction
    (hand-authored JSON, ``model_discovery.py`` auto-discovery, or KV-driven
    config can all leave it empty or typo'd). Trusting it verbatim here would
    let an agent whose ``base_url`` is OpenRouter's own endpoint silently skip
    the ``provider.zdr=true`` enforcement pin under an explicit ``zdr_only``
    scope while still routing bytes to OpenRouter (base_url decides where the
    request goes; this function only decides whether the pin is applied) —
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

    Both the structured-synthesis candidate loop
    (``_orchestrated_provider_completion``) and the single-worker streaming
    fallback (``stream_route``) call this so a failed attempt carries the
    same fixed ``outcome`` vocabulary: ``request_too_large``,
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
    if isinstance(request.get("metadata"), dict):
        response["metadata"] = request["metadata"]
    return response


def is_transient_error(exc: BaseException) -> bool:
    """Return True when a provider call failure is worth retrying with backoff."""
    if isinstance(exc, urllib.error.HTTPError):
        if _is_tool_execution_stopped(exc):
            return False
        return exc.code in TRANSIENT_HTTP_STATUS
    # urlopen wraps a TLS handshake's ssl.SSLCertVerificationError as
    # URLError(reason=...), not as a bare ssl.SSLError -- unwrap it here so a
    # bad trust boundary is never retried as if it were a network fault. The
    # isinstance(exc, ssl.SSLError) check further below never reaches this
    # case, since it never sees the wrapping URLError.
    if isinstance(exc, urllib.error.URLError) and isinstance(
        exc.reason, ssl.SSLCertVerificationError
    ):
        return False
    # Network-level failures (DNS, connection reset, read timeout) are transient.
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError, socket.timeout)):
        return True
    if isinstance(exc, socket.gaierror):
        return exc.errno == socket.EAI_AGAIN
    # ModelClient._resolve_addresses wraps a DNS resolution failure as plain
    # RuntimeError (not a socket.gaierror subclass) with the original
    # exception chained as __cause__, so a temporary DNS hiccup (EAI_AGAIN)
    # is still worth retrying through that wrapper. Any other RuntimeError
    # (a malformed URL, no resolvable stream address) has no such cause and
    # falls through to the non-transient default below.
    if isinstance(exc, RuntimeError) and isinstance(exc.__cause__, socket.gaierror):
        return exc.__cause__.errno == socket.EAI_AGAIN
    # A VPN/socket path can surface as an SSL EOF or SSL_ERROR_SYSCALL. Keep
    # certificate verification failures non-transient so a bad trust boundary
    # is never retried as if it were a network fault.
    if isinstance(exc, ssl.SSLError):
        return not isinstance(exc, ssl.SSLCertVerificationError)
    return False


def _log_provider_attempt(agent: ModelAgent, attempt: int, retry_limit: int) -> None:
    """DEBUG-log one provider call attempt before it is made."""
    if _LOGGER.isEnabledFor(logging.DEBUG):
        _LOGGER.debug(
            "provider_attempt agent_id=%s model=%s attempt=%d/%d request_id=%s",
            agent.id,
            agent.model,
            attempt + 1,
            retry_limit + 1,
            current_request_id() or "-",
        )


def _log_provider_attempt_failed(
    agent: ModelAgent, attempt: int, exc: Exception, transient: bool
) -> None:
    """DEBUG-log typed status evidence without reading or stringifying provider content."""
    if _LOGGER.isEnabledFor(logging.DEBUG):
        provider_status = (
            exc.code if isinstance(exc, urllib.error.HTTPError)
            else exc.provider_status if isinstance(exc, ProviderUpstreamError)
            else None
        )
        if type(provider_status) is not int or not 100 <= provider_status <= 599:
            provider_status = None
        _LOGGER.debug(
            "provider_attempt_failed agent_id=%s model=%s attempt=%d error_type=%s transient=%s provider_status=%s request_id=%s error_message=<omitted>",
            agent.id,
            agent.model,
            attempt + 1,
            type(exc).__name__,
            transient,
            provider_status,
            current_request_id() or "-",
        )


def _log_provider_backoff(agent: ModelAgent, attempt: int, delay: float) -> None:
    """DEBUG-log one backoff sleep before the next retry attempt."""
    if _LOGGER.isEnabledFor(logging.DEBUG):
        _LOGGER.debug(
            "provider_backoff agent_id=%s attempt=%d delay_seconds=%.3f request_id=%s",
            agent.id,
            attempt + 1,
            delay,
            current_request_id() or "-",
        )


def _log_provider_exhausted(agent: ModelAgent, attempts: int, last_error: Exception) -> None:
    """WARNING-log a provider call that failed after using its full retry budget.

    Fires by default (no --verbose needed): a provider call that ultimately
    failed is an actionable operational event, not just internal reasoning.
    Only fires when a *real, non-zero* retry budget was configured and
    actually exhausted. Two distinct, more precise events cover the cases
    this must not be confused with: :func:`_log_provider_rejected_permanent`
    (a real budget existed, but the failure was judged non-retryable before
    it ran out) and :func:`_log_provider_no_retry_budget` (no retry budget
    was ever configured at all, so there was never anything to exhaust,
    regardless of whether the error itself was transient or not) -- so an
    operator scanning WARNING output never mistakes "gave up after using its
    full retry budget" for either "was never going to be retried in the
    first place" or "was never allowed to be retried at all".
    """
    _LOGGER.warning(
        "provider_exhausted agent_id=%s model=%s attempts=%s final_error_type=%s request_id=%s",
        agent.id,
        agent.model,
        attempts,
        type(last_error).__name__,
        current_request_id() or "-",
    )


def _log_provider_no_retry_budget(
    agent: ModelAgent, attempts: int, last_error: Exception, *, transient: bool
) -> None:
    """WARNING-log a provider call that failed with no retry budget configured at all.

    Fires by default (no --verbose needed), mirroring
    :func:`_log_provider_exhausted`'s default visibility, but under a
    distinct event name for the case where the agent's configured retry
    limit is 0: there was never any retry budget to exhaust or to give up
    on early, regardless of whether the error itself was transient or not
    (``attempts`` is then always exactly 1). "No retry budget was
    configured" and "this error is non-retryable by nature" are two
    different, independent facts -- collapsing every zero-budget failure
    into :func:`_log_provider_rejected_permanent` would misleadingly imply
    the error type itself was judged permanent, even for a transient error
    (e.g. an HTTP 503) that simply never got a chance to retry. ``transient``
    carries the error's own classification explicitly so an operator can
    still tell "this might have succeeded on retry, but none was allowed"
    from "this wouldn't have been retried anyway" from this one event name.
    """
    _LOGGER.warning(
        "provider_no_retry_budget agent_id=%s model=%s attempts=%s final_error_type=%s transient=%s request_id=%s",
        agent.id,
        agent.model,
        attempts,
        type(last_error).__name__,
        transient,
        current_request_id() or "-",
    )


def _log_provider_one_shot_call_failed(
    agent: ModelAgent, attempts: int, last_error: Exception, *, transient: bool
) -> None:
    """WARNING-log a provider call that failed under a caller-forced single-attempt policy.

    Fires by default (no --verbose needed), mirroring
    :func:`_log_provider_no_retry_budget`'s default visibility, but under a
    distinct event name for a materially different situation: this call was
    not made against an agent with no configured retry budget at all -- it
    was ``ModelClient._send_raw_with_retry(..., allow_transient_retries=False)``
    deliberately restricting *this one call* to exactly one attempt (e.g.
    ``proxy_send_once``, used so an already-failing-over passthrough request
    cannot itself amplify load with a nested retry loop). The agent's real
    ``_retry_limit`` may well be non-zero; it simply was never consulted for
    this call. Reusing :func:`_log_provider_no_retry_budget` here would tell
    an operator the agent has no retry budget configured, which may be false
    and is misleading either way -- the true reason this call did not retry
    was the caller's one-shot policy, not the agent's configuration.
    ``attempts`` is always exactly 1 by construction, mirroring
    :func:`_log_provider_no_retry_budget`.
    """
    _LOGGER.warning(
        "provider_one_shot_call_failed agent_id=%s model=%s attempts=%s final_error_type=%s transient=%s request_id=%s",
        agent.id,
        agent.model,
        attempts,
        type(last_error).__name__,
        transient,
        current_request_id() or "-",
    )


def _log_provider_rejected_permanent(agent: ModelAgent, attempts: int, last_error: Exception) -> None:
    """WARNING-log a provider call that stopped on a non-transient failure with budget left.

    Fires by default (no --verbose needed), mirroring
    :func:`_log_provider_exhausted`'s default visibility, but under a
    distinct event name: a real, non-zero retry budget was configured, and
    the retry loop stopped early -- before that budget ran out -- because
    ``is_transient_error`` classified the final failure as permanent (e.g. a
    401/403/malformed-request response). See :func:`_log_provider_no_retry_budget`
    for the separate case where no retry budget was configured at all.
    """
    _LOGGER.warning(
        "provider_rejected_permanent agent_id=%s model=%s attempts=%s final_error_type=%s request_id=%s",
        agent.id,
        agent.model,
        attempts,
        type(last_error).__name__,
        current_request_id() or "-",
    )


def _log_retry_outcome(
    agent: ModelAgent,
    attempt: int,
    retry_limit: int,
    last_error: Exception,
    *,
    transient: bool,
    allow_transient_retries: bool = True,
) -> None:
    """Log a terminated retry loop's outcome under its correct distinct event name.

    ``ModelClient._send_with_retry`` and ``ModelClient._send_raw_with_retry``
    run this identical classification (no retry budget at all / a caller-
    forced single attempt / budget exhausted / stopped early on a
    non-transient error) once their retry loop ends. It used to be
    duplicated verbatim in both methods, and that duplication already caused
    a real regression once -- a fix landed in one copy but was missed in the
    other (see ``tests/test_orchestrator_debug_logging.py``'s
    ``test_send_raw_with_retry_*`` tests, which exist specifically to catch
    that class of drift). Extracting the shared logic here makes it
    impossible for the two call sites to diverge again.

    ``allow_transient_retries`` distinguishes *why* ``retry_limit`` came out
    as 0. ``_send_raw_with_retry`` computes
    ``retry_limit = self._retry_limit(agent) if allow_transient_retries else 0``:
    when the caller passed ``allow_transient_retries=False`` (``proxy_send_once``,
    a deliberate one-shot call so an already-failing-over passthrough request
    cannot itself amplify load with a nested retry loop), a zero here says
    nothing about whether the agent actually has a configured retry budget --
    it was simply never consulted. Logging that case as
    :func:`_log_provider_no_retry_budget` would misreport a real,
    possibly-non-zero budget as absent; :func:`_log_provider_one_shot_call_failed`
    names the true reason instead. ``_send_with_retry`` has no such
    caller-forced restriction and always passes the default ``True``, so its
    zero-budget case is unaffected and still reaches
    :func:`_log_provider_no_retry_budget`.
    """
    if retry_limit == 0:
        if allow_transient_retries:
            _log_provider_no_retry_budget(agent, attempt + 1, last_error, transient=transient)
        else:
            _log_provider_one_shot_call_failed(agent, attempt + 1, last_error, transient=transient)
    elif attempt >= retry_limit:
        _log_provider_exhausted(agent, attempt + 1, last_error)
    else:
        _log_provider_rejected_permanent(agent, attempt + 1, last_error)


def _record_provider_response_telemetry(data: Any, started_monotonic: float) -> None:
    """Annotate the active provider span with one response's concrete evidence.

    Records GenAI semantic-convention usage counts, the served model name,
    the finish reason, and request latency so traces carry real per-call
    telemetry instead of transport metadata alone.
    """
    if not isinstance(data, dict):
        return
    attributes: dict[str, Any] = {
        "contextual_orchestrator.latency_ms": round((time.monotonic() - started_monotonic) * 1000, 2)
    }
    served_model = data.get("model")
    if isinstance(served_model, str) and served_model:
        attributes["gen_ai.response.model"] = served_model
    choices = data.get("choices")
    finish_reasons = (
        [
            choice["finish_reason"]
            for choice in choices
            if isinstance(choice, dict)
            and isinstance(choice.get("finish_reason"), str)
            and choice["finish_reason"]
        ]
        if isinstance(choices, list)
        else []
    )
    if finish_reasons:
        attributes["gen_ai.response.finish_reasons"] = finish_reasons
    annotate_current_span(attributes)
    record_provider_usage(data.get("usage"))


_PASSTHROUGH_TRIGGER_KEYS = (
    "response_format",
    "tools",
    "tool_choice",
    "functions",
    "function_call",
)


def _is_omit_equivalent_control(key: str, value: Any) -> bool:
    """Mirror the HTTP-boundary treat-as-omit rules for optional provider controls.

    ``response_format`` / ``tool_choice`` / ``function_call`` treat JSON null,
    empty objects, and blank strings as omit; the choice keys additionally treat
    the honest no-op keywords ``"none"`` / ``"auto"`` as omit. ``tools`` /
    ``functions`` treat JSON null and empty arrays as omit. A trigger key
    carrying only such a value is omit-equivalent to the key being absent, so it
    must not select the conducted-evidence + synthesis path on its own (parity
    with the ``_validate_chat_*`` boundary rules in ``server.py``).
    """
    if value is None:
        return True
    if key in ("tools", "functions"):
        return isinstance(value, list) and not value
    if isinstance(value, dict):
        return not value
    if isinstance(value, str):
        stripped = value.strip().casefold()
        if not stripped:
            return True
        return key in ("tool_choice", "function_call") and stripped in ("none", "auto")
    return False


def _is_request_too_large_error(exc: BaseException) -> bool:
    """Recognize request-size rejection through a bounded exception chain."""
    current: BaseException | None = exc
    seen: set[int] = set()
    for _ in range(_PROVIDER_ERROR_CHAIN_LIMIT):
        if current is None or id(current) in seen:
            return False
        seen.add(id(current))
        if isinstance(current, ProviderRequestTooLargeError) or (
            isinstance(current, urllib.error.HTTPError)
            and (
                current.code == 413
                or _is_oversized_tool_description_error(current)
                or _is_context_length_exceeded_error(current)
            )
        ):
            return True
        if current.__cause__ is not None:
            current = current.__cause__
        elif current.__suppress_context__:
            return False
        else:
            current = current.__context__
    return False


def _is_passthrough_failover_error(exc: BaseException) -> bool:
    """Recognize failures proving that a passthrough request was not accepted."""
    if isinstance(exc, _LocalProviderAdmissionTimeout):
        return True
    if _is_request_too_large_error(exc):
        return True
    current: BaseException | None = exc
    seen: set[int] = set()
    for _ in range(_PROVIDER_ERROR_CHAIN_LIMIT):
        if current is None or id(current) in seen:
            return False
        seen.add(id(current))
        if isinstance(current, ProviderUpstreamError):
            if current.provider_status in _PASSTHROUGH_REJECTED_STATUS:
                return True
        if (
            isinstance(current, urllib.error.HTTPError)
            and current.code in _PASSTHROUGH_REJECTED_STATUS
        ):
            return True
        if (
            isinstance(current, urllib.error.HTTPError)
            and _is_provider_tool_description_limit_error(current)
        ):
            return True
        if (
            isinstance(current, urllib.error.HTTPError)
            and _is_single_tool_call_limit_error(current)
        ):
            return True
        if isinstance(current, socket.gaierror) and current.errno == socket.EAI_AGAIN:
            return True
        if current.__cause__ is not None:
            current = current.__cause__
        elif current.__suppress_context__:
            return False
        else:
            current = current.__context__
    return False


def _is_ambiguous_passthrough_transport_failure(exc: BaseException) -> bool:
    """Recognize a transport failure whose provider outcome is unknown.

    A read or connect timeout, a reset or truncated connection, or a URL-level
    failure that carries no HTTP status may follow provider acceptance. It is
    always a failure *of this candidate*: the breaker must learn it and the
    caller must receive a non-retryable ``502 provider_outcome_unknown`` -- not
    the bare exception, which the HTTP handler could only answer with
    ``500 internal_error`` (Strix run 33993155419: 83 such responses, ~90 s
    apart, the same never-recorded first-ranked route every time; #1045).

    Whether the *request* may then move on to another candidate depends on
    who chose this one:

    * An explicit concrete model was named by the caller, so there is no
      other candidate it is safe to substitute -- the request fails closed
      on this single attempt and is never replayed
      (``test_ambiguous_timeout_on_explicit_model_is_not_replayed``).
    * A virtual selector (``None``/``GATEWAY_DEFAULT_MODEL``/``AUTO_MODEL``/
      ``FREE_MODEL``) means the caller delegated candidate selection to the
      gateway, so the gateway also owns failover across this ambiguous
      attempt -- consistent with ``_orchestrated_provider_completion``,
      whose docstring already states that virtual selectors advance across
      retryable transport failures (502/429/timeout). Fixed by #1166 (Strix
      run 34754423834 attempt 2): three ready free-pool candidates went
      uncalled after one candidate's read timeout, even though the caller
      (a virtual ``orchestrator/free`` request) never pinned a single
      provider.

    A URLError around a DNS failure is not ambiguous (nothing was sent) and
    keeps its existing handling.
    """
    current: BaseException | None = exc
    seen: set[int] = set()
    for _ in range(_PROVIDER_ERROR_CHAIN_LIMIT):
        if current is None or id(current) in seen:
            return False
        seen.add(id(current))
        if isinstance(current, (TimeoutError, ConnectionError, http.client.HTTPException)):
            return True
        if (
            isinstance(current, urllib.error.URLError)
            and not isinstance(current, urllib.error.HTTPError)
            and not isinstance(current.reason, socket.gaierror)
        ):
            return True
        if current.__cause__ is not None:
            current = current.__cause__
        elif current.__suppress_context__:
            return False
        else:
            current = current.__context__
    return False


def _is_timeout_transport_failure(exc: BaseException) -> bool:
    """Recognize a timeout through a bounded exception chain."""
    current: BaseException | None = exc
    seen: set[int] = set()
    for _ in range(_PROVIDER_ERROR_CHAIN_LIMIT):
        if current is None or id(current) in seen:
            return False
        seen.add(id(current))
        if isinstance(current, TimeoutError):
            return True
        if current.__cause__ is not None:
            current = current.__cause__
        elif current.__suppress_context__:
            return False
        else:
            current = current.__context__
    return False


def _is_capability_mismatch_failover_error(exc: BaseException) -> bool:
    """Recognize a structural capability mismatch, not a reliability failure.

    A model rejecting a request shape it can never support (too many tool
    descriptions, more than one tool call per turn) says nothing about that
    model's health for a differently-shaped future request -- unlike an
    oversized-payload rejection (already exempted via
    _is_request_too_large_error), this failure is not size-dependent, but the
    same principle applies: it must not trip the circuit breaker or count as
    a failed stability observation for the model or its group (Codex Review,
    ContextualWisdomLab/contextual-orchestrator#986).
    """
    current: BaseException | None = exc
    seen: set[int] = set()
    for _ in range(_PROVIDER_ERROR_CHAIN_LIMIT):
        if current is None or id(current) in seen:
            return False
        seen.add(id(current))
        if isinstance(current, urllib.error.HTTPError) and (
            _is_provider_tool_description_limit_error(current)
            or _is_single_tool_call_limit_error(current)
        ):
            return True
        if current.__cause__ is not None:
            current = current.__cause__
        elif current.__suppress_context__:
            return False
        else:
            current = current.__context__
    return False


def _passthrough_failure_phase(exc: ProviderUpstreamError) -> str:
    """Map one classified passthrough failure onto a bounded lifecycle phase."""
    if exc.error_code in {"tls_failure", "tls_verification_failed"}:
        return "connecting"
    if exc.error_code == "provider_connection_error":
        return "transport"
    if exc.error_code == "request_too_large":
        return "request_validation"
    return "provider_response"


def _passthrough_attempt_record(
    exc: ProviderUpstreamError,
    *,
    provider_name: str,
    attempt_number: int,
    failover_decision: str,
) -> dict[str, Any]:
    """Return the public attempt receipt for one classified passthrough failure."""
    return {
        "agent_id": exc.agent_id,
        "model": exc.model,
        "provider_name": provider_name,
        "attempt_number": attempt_number,
        "error_code": exc.error_code,
        "client_status": exc.client_status,
        "provider_status": exc.provider_status,
        "retryable": exc.retryable,
        "transport": exc.transport,
        "phase": _passthrough_failure_phase(exc),
        "failover_decision": failover_decision,
    }


def _set_passthrough_attempt_evidence(
    exc: ProviderUpstreamError,
    *,
    selected_candidate_ids: list[str],
    attempts: list[dict[str, Any]],
    terminal_reason: str,
) -> ProviderUpstreamError:
    """Attach bounded request-scoped passthrough evidence to one final error."""
    exc.selected_candidate_ids = tuple(selected_candidate_ids)
    exc.attempts = tuple(dict(item) for item in attempts)
    exc.terminal_reason = terminal_reason
    return exc


def _assistant_message_extras(data: dict[str, Any]) -> dict[str, Any] | None:
    """Keep provider tool_calls/finish_reason beside the text-only chat() result."""
    choices = data.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else None
    if not isinstance(choice, dict):
        return None
    extras: dict[str, Any] = {}
    message = choice.get("message")
    if isinstance(message, dict) and message.get("tool_calls"):
        extras["tool_calls"] = message["tool_calls"]
    finish_reason = choice.get("finish_reason")
    if isinstance(finish_reason, str) and finish_reason:
        extras["finish_reason"] = finish_reason
    return extras or None


def _notify_progress(
    progress: Callable[..., Any] | None,
    role: str,
    status: str,
    output: str = "",
) -> None:
    """Call a conduct progress hook without breaking two-argument callers."""
    if progress is None:
        return
    try:
        parameters = inspect.signature(progress).parameters
    except (TypeError, ValueError):
        parameters = {}
    if "output" in parameters and parameters["output"].kind is inspect.Parameter.KEYWORD_ONLY:
        progress(role, status, output=output)
        return
    accepts_output = sum(
        parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
        for parameter in parameters.values()
    ) >= 3 or any(
        parameter.kind is inspect.Parameter.VAR_POSITIONAL for parameter in parameters.values()
    )
    if accepts_output:
        progress(role, status, output)
        return
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        progress(role, status, output=output)
        return
    progress(role, status)


class ModelClient:
    """Small chat-completions client with retry, backoff, and mock support."""

    def __init__(
        self,
        timeout: float | None = None,
        max_output_tokens: int | None = None,
        max_retries: int = 0,
        local_max_retries: int = 0,
        retry_backoff: float = 0.5,
        retry_backoff_cap: float = 8.0,
        temperature: float = 0.2,
        local_concurrency: int = 1,
        chat_template_args: dict[str, Any] | None = None,
        ca_bundle: str | None = None,
        verify_tls: bool = True,
        allowed_provider_hosts: Iterable[str] | None = None,
        token_counter: Any = None,
        *,
        connect_timeout: float | None = None,
    ) -> None:
        # No deadline is selected by default. Explicit legacy caller limits remain
        # compatible; review workflows and readiness paths never supply them.
        self.timeout = timeout
        if connect_timeout is not None and connect_timeout <= 0:
            raise ValueError("connect_timeout must be positive")
        self.connect_timeout = None if connect_timeout is None else float(connect_timeout)
        # Optional authoritative counter for the shared-context output-budget
        # decision (see ``token_counting.shared_context_output_budget``).
        # ``None`` means no decision is ever made here, not an estimate.
        self.token_counter = token_counter
        if max_output_tokens is not None and (
            type(max_output_tokens) is not int or max_output_tokens <= 0
        ):
            raise ValueError("max_output_tokens must be a positive integer or None")
        # ``None`` keeps the ceiling unknown so the selected model's published
        # maximum (or the provider default) governs instead of a fixed cap.
        self.max_output_tokens = max_output_tokens
        if isinstance(max_retries, bool) or max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        self.default_temperature = temperature
        self.default_top_p: float | None = None
        self.default_presence_penalty: float | None = None
        self.default_frequency_penalty: float | None = None
        self.max_retries = max_retries
        if isinstance(local_max_retries, bool) or local_max_retries < 0:
            raise ValueError("local_max_retries must be >= 0")
        self.local_max_retries = int(local_max_retries)
        self.retry_backoff = retry_backoff
        self.retry_backoff_cap = retry_backoff_cap
        self.temperature = temperature
        self.ca_bundle = ca_bundle
        if type(local_concurrency) is not int or not 1 <= local_concurrency <= MAX_LOCAL_CONCURRENCY:
            raise ValueError(
                f"local_concurrency must be an integer in 1..{MAX_LOCAL_CONCURRENCY}"
            )
        self.local_concurrency = local_concurrency
        self.chat_template_args = dict(chat_template_args or {})
        self.allowed_provider_hosts = self._normalize_allowed_provider_hosts(allowed_provider_hosts)
        # Seam so tests can observe/skip real sleeping during backoff.
        self._sleep = time.sleep
        # Per-thread usage from the most recent chat() (the server is threaded).
        self._local = threading.local()

        if not verify_tls:
            raise ValueError("provider TLS verification cannot be disabled; configure a trusted ca_bundle")
        # TLS trust for provider egress. The system trust store is the default;
        # ca_bundle points at a custom CA for a reviewed corporate gateway.
        self._ssl_context = self._build_ssl_context(ca_bundle)

    @staticmethod
    def cancellable_call(call: Callable[[], Any]) -> tuple[Callable[[], Any], Callable[[], None]]:
        """Wrap one provider call with socket-closing cooperative cancellation."""
        cancellation = _ProviderCancellation()
        return lambda: cancellation.run(call), cancellation.cancel

    @staticmethod
    def _build_ssl_context(ca_bundle: str | None) -> ssl.SSLContext:
        if ca_bundle:
            if not os.path.isfile(ca_bundle):
                raise ValueError(f"provider CA bundle does not exist: {ca_bundle}")
            try:
                return ssl.create_default_context(cafile=ca_bundle)
            except OSError as exc:
                raise ValueError(f"provider CA bundle could not be loaded: {ca_bundle}") from exc
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=certifi.where())
        return context

    @staticmethod
    def _normalize_allowed_provider_hosts(hosts: Iterable[str] | None) -> frozenset[str]:
        """Normalize an explicit provider-host policy once at client construction."""
        if hosts is None:
            return frozenset()
        if isinstance(hosts, (str, bytes)):
            raise ValueError("allowed_provider_hosts must be an iterable of host strings")
        normalized: set[str] = set()
        try:
            values = iter(hosts)
        except TypeError as exc:
            raise ValueError("allowed_provider_hosts must be an iterable of host strings") from exc
        for host in values:
            if type(host) is not str:
                raise ValueError("allowed_provider_hosts must contain only strings")
            value = host.strip().lower()
            if not value or any(character in value for character in "/?#"):
                raise ValueError("allowed_provider_hosts entries must be bare host names")
            normalized.add(value)
        return frozenset(normalized)

    def take_usage(self) -> dict[str, Any] | None:
        """Return and clear provider-reported usage from the most recent chat() on this thread."""
        usage = getattr(self._local, "usage", None)
        self._local.usage = None
        return usage

    def take_assistant_message(self) -> dict[str, Any] | None:
        """Return and clear tool_calls/finish_reason from the most recent chat() on this thread."""
        extras = getattr(self._local, "assistant_message", None)
        self._local.assistant_message = None
        return extras if isinstance(extras, dict) else None

    def take_shared_context_budget(self) -> dict[str, Any] | None:
        """Return and clear the most recent chat() call's shared-context budget evidence.

        ``None`` unless the most recent ``chat()`` on this thread made an
        authoritative :func:`token_counting.shared_context_output_budget`
        decision (see that function for exactly which inputs must be known).
        """
        evidence = getattr(self._local, "shared_context_budget", None)
        self._local.shared_context_budget = None
        return evidence if isinstance(evidence, dict) else None

    def take_output_budget(self) -> dict[str, Any] | None:
        """Return and clear this thread's most recent output-budget clamp evidence.

        ``None`` means the request carried no explicit ``max_tokens`` /
        ``max_completion_tokens`` / ``max_output_tokens`` for the clamp to
        evaluate. Otherwise the dict always names ``requested_output_tokens``,
        ``effective_output_tokens``, and whether the agent's published
        ``max_output_tokens`` ceiling forced the request down -- see ADR 0130.
        """
        budget = getattr(self._local, "output_budget", None)
        self._local.output_budget = None
        return budget if isinstance(budget, dict) else None

    def request_settings_snapshot(self) -> dict[str, Any]:
        """Return this thread's effective request-scoped provider settings."""
        scoped = getattr(self._local, "request_settings", {})
        snapshot = {
            "temperature": scoped.get("temperature", self.default_temperature),
            "top_p": scoped.get("top_p", self.default_top_p),
            "presence_penalty": scoped.get("presence_penalty", self.default_presence_penalty),
            "frequency_penalty": scoped.get("frequency_penalty", self.default_frequency_penalty),
            "max_output_tokens": scoped.get("max_output_tokens", self.max_output_tokens),
        }
        for key in ("tools", "tool_choice", "parallel_tool_calls"):
            if key in scoped:
                snapshot[key] = scoped[key]
        return snapshot

    def effective_max_output_tokens(self, agent: ModelAgent | None = None) -> int | None:
        """Resolve the output ceiling with request scope winning over model metadata.

        Priority: an explicit request-scoped value, then an explicit client-level
        value, then the selected agent's provider-published ``max_output_tokens``.
        ``None`` means no ceiling is known anywhere, so callers must leave the
        provider default in place rather than impose a fixed cap.
        """
        scoped = getattr(self._local, "request_settings", {})
        value = scoped.get("max_output_tokens")
        if value is None:
            value = self.max_output_tokens
        if value is None and agent is not None:
            value = agent.max_output_tokens
        return value

    @contextmanager
    def suppress_request_tools(self):
        """Hide caller tools from non-worker roles on this thread."""
        scoped = getattr(self._local, "request_settings", None)
        if not isinstance(scoped, dict) or not any(
            key in scoped for key in ("tools", "tool_choice", "parallel_tool_calls")
        ):
            yield
            return
        previous = dict(scoped)
        for key in ("tools", "tool_choice", "parallel_tool_calls"):
            scoped.pop(key, None)
        try:
            yield
        finally:
            self._local.request_settings = previous

    @contextmanager
    def request_settings(self, **overrides: Any):
        """Apply provider settings to only the current server request thread."""
        previous = getattr(self._local, "request_settings", None)
        current = self.request_settings_snapshot()
        current.update({key: value for key, value in overrides.items() if value is not None})
        self._local.request_settings = current
        try:
            yield
        finally:
            if previous is None:
                del self._local.request_settings
            else:
                self._local.request_settings = previous

    @contextmanager
    def single_attempt_transport(self):
        """Suppress this thread's own transient-retry-with-backoff in ``chat()``.

        A caller that already runs its own agent-level retry-then-failover
        decision (``TaskOrchestrator._invoke``'s ``RETRY_SAME_AGENT`` /
        ``FAILOVER_AGENT`` classification) must not also have
        ``_send_with_retry`` replay the identical transient failure with its
        own backoff underneath it: stacking both layers turns one caller-level
        "give this agent one more try" decision into
        ``(this agent's own retry budget + 1)`` real network attempts before
        the caller's own failover ever gets a turn -- exactly the
        already-known-flaky-route amplification that let one retryable 5xx
        route consume most of a request's real time budget before a cleanly
        ready sibling was ever tried (ContextualWisdomLab/.github PR #1912).
        Scoped to the current thread only, mirroring :meth:`request_settings`,
        so a concurrent request on another thread sharing this client is
        unaffected.
        """
        previous = getattr(self._local, "allow_transient_retries", True)
        self._local.allow_transient_retries = False
        try:
            yield
        finally:
            self._local.allow_transient_retries = previous

    #: Deterministic vector dimension for mock-provider embeddings (test fixture
    #: only; production providers always return their own dimensionality).
    MOCK_EMBEDDING_DIMENSION = 8

    def embed(self, agent: ModelAgent, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input string from an OpenAI-compatible endpoint.

        Real providers receive a standard ``/embeddings`` request. The
        ``mock://`` transport derives a deterministic BLAKE2b-based unit-sphere
        vector so unit tests can exercise cosine ordering without network
        access; this fixture is never used against production traffic.
        """
        vectors, _prompt_tokens = self.embed_with_usage(agent, texts)
        return vectors

    def embed_with_usage(
        self, agent: ModelAgent, texts: list[str]
    ) -> tuple[list[list[float]], int | None]:
        """Return embeddings plus an authoritative provider input-token count when supplied."""
        if not isinstance(texts, list) or not texts:
            raise ValueError("texts must be a non-empty list of strings")
        for item in texts:
            if not isinstance(item, str) or not item:
                raise ValueError("texts entries must be non-empty strings")
        if agent.base_url.startswith("mock://"):
            vectors: list[list[float]] = []
            for item in texts:
                digest = hashlib.blake2b(item.encode("utf-8"), digest_size=16).digest()
                raw = [byte for byte in digest[: self.MOCK_EMBEDDING_DIMENSION]]
                centered = [(value / 255.0) * 2.0 - 1.0 for value in raw]
                vectors.append(centered)
            return vectors, None
        destination = self._validated_destination(agent, transport="embedding")  # pragma: no cover
        payload = {"model": agent.model, "input": texts}  # pragma: no cover
        response = self._send_raw(agent, "embeddings", payload, destination)  # pragma: no cover
        data = response.get("data") if isinstance(response, dict) else None  # pragma: no cover
        if not isinstance(data, list) or len(data) != len(texts):  # pragma: no cover
            raise RuntimeError(  # pragma: no cover
                f"provider {agent.id} returned an invalid embeddings payload"
            )
        vectors = []  # pragma: no cover
        for entry in data:  # pragma: no cover
            vector = entry.get("embedding") if isinstance(entry, dict) else None  # pragma: no cover
            if not isinstance(vector, list) or not all(  # pragma: no cover
                isinstance(value, (int, float)) and math.isfinite(float(value)) for value in vector
            ):
                raise RuntimeError(  # pragma: no cover
                    f"provider {agent.id} returned a non-numeric embedding vector"
                )
            vectors.append([float(value) for value in vector])  # pragma: no cover
        usage = response.get("usage") if isinstance(response, dict) else None  # pragma: no cover
        prompt_tokens = None  # pragma: no cover
        if isinstance(usage, dict):  # pragma: no cover
            raw_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
            if type(raw_tokens) is int and raw_tokens >= 0:
                prompt_tokens = raw_tokens
        return vectors, prompt_tokens  # pragma: no cover

    def chat(
        self,
        agent: ModelAgent,
        messages: list[ChatMessage],
        temperature: float | None = None,
        top_p: float | None = None,
        effort_profile: ReasoningEffortProfile | None = None,
    ) -> str:
        """Send messages to a mock or OpenAI-compatible chat endpoint with retries.

        When ``temperature``/``top_p`` are omitted, ``default_temperature`` and
        ``default_top_p`` are used so request-scoped Completions sampling can be
        applied without threading kwargs through every orchestrator hop.
        """
        if not is_chat_compatible_model_id(agent.model):
            raise ValueError("model is not chat-compatible and cannot serve a chat request")
        self._local.usage = None
        self._local.assistant_message = None
        self._local.shared_context_budget = None
        self._local.output_budget = None
        # Expose the effective sampling knobs for request-path tests / diagnostics.
        settings = self.request_settings_snapshot()
        effective_temperature = settings["temperature"] if temperature is None else temperature
        effective_top_p = settings["top_p"] if top_p is None else top_p
        effective_presence = settings["presence_penalty"]
        effective_frequency = settings["frequency_penalty"]
        self._local.last_temperature = effective_temperature
        self._local.last_top_p = effective_top_p
        self._local.last_presence_penalty = effective_presence
        self._local.last_frequency_penalty = effective_frequency
        if agent.base_url.startswith("mock://"):
            return self._mock(agent, messages)

        destination = self._validate_provider(agent)  # pragma: no cover
        api_key = _provider_credential(agent)  # pragma: no cover
        credential_name = _provider_credential_name(agent)  # pragma: no cover
        if credential_name and not api_key:  # pragma: no cover
            raise NotConfigured(
                f"{agent.id} requires a resolvable credential '{credential_name}' in the KV"
            )

        payload = {  # pragma: no cover
            "model": agent.model,
            "messages": messages,
            "temperature": effective_temperature,
            "stream": False,
        }
        tools = settings.get("tools")
        output_cap = self.effective_max_output_tokens(agent)
        if output_cap is not None:
            payload["max_tokens"] = output_cap
        # Shared-context output budget (issue #1157, part 2): only when the
        # agent's context window, its output ceiling, and an exact,
        # provenance-bound prompt count are all authoritative. An explicit
        # caller/client output budget wins over the catalog ceiling above
        # (as it already does via effective_max_output_tokens), so it is
        # checked against remaining shared-context capacity here rather than
        # silently clamped; no caller budget means the catalog ceiling is
        # what gets bounded down to the remaining capacity.
        scoped_output_tokens = getattr(self._local, "request_settings", {}).get(
            "max_output_tokens"
        )
        explicit_output_tokens = (
            scoped_output_tokens if scoped_output_tokens is not None else self.max_output_tokens
        )
        shared_budget = shared_context_output_budget(
            agent,
            messages,
            explicit_output_tokens,
            counter=self.token_counter,
            tools=tools,
        )
        if shared_budget is not None:
            if shared_budget.exceeds_remaining:
                requested = (
                    explicit_output_tokens
                    if explicit_output_tokens is not None
                    else shared_budget.output_ceiling
                )
                raise ProviderRequestTooLargeError(
                    "prompt does not leave room for the requested output within the "
                    f"model's shared context window: context_window={shared_budget.context_window}, "
                    f"prompt_tokens={shared_budget.prompt_tokens}, requested_output_tokens={requested}",
                    agent_id=agent.id,
                    model=agent.model,
                    transport="chat",
                )
            if explicit_output_tokens is None:
                payload["max_tokens"] = shared_budget.output_ceiling
            self._local.shared_context_budget = shared_budget.as_evidence()
        if effective_top_p is not None:  # pragma: no cover
            payload["top_p"] = effective_top_p
        if effective_presence is not None:  # pragma: no cover
            payload["presence_penalty"] = effective_presence
        if effective_frequency is not None:  # pragma: no cover
            payload["frequency_penalty"] = effective_frequency
        if tools:
            payload["tools"] = tools
        if "tool_choice" in settings:
            payload["tool_choice"] = settings["tool_choice"]
        if "parallel_tool_calls" in settings:
            payload["parallel_tool_calls"] = settings["parallel_tool_calls"]
        if _is_direct_mlx_provider_url(agent.base_url) and self.chat_template_args:
            payload["chat_template_kwargs"] = self.chat_template_args
        payload = self.apply_effort_profile(agent, payload, effort_profile)
        parsed_provider = urlparse(agent.base_url)
        resolved_timeout = self._resolved_model_timeout(agent)
        deadline = _model_deadline(resolved_timeout)
        with traced(
            f"chat {agent.model}",
            {
                "gen_ai.operation.name": "chat",
                "gen_ai.provider.name": agent.provider_name or parsed_provider.hostname or agent.id,
                "gen_ai.request.model": agent.model,
                "contextual_orchestrator.agent_id": agent.id,
                "server.address": parsed_provider.hostname or "",
                "server.port": parsed_provider.port or (443 if parsed_provider.scheme == "https" else 80),
            },
        ), _local_provider_slot(agent, self.local_concurrency, resolved_timeout):
            try:
                if deadline is None:
                    return self._send_with_retry(agent, payload, destination)
                return self._send_with_retry(
                    agent, payload, destination, timeout=_remaining_model_timeout(deadline)
                )
            except _AdministratorModelTimeout:
                raise _administrator_timeout_error(agent, "chat") from None

    def apply_effort_profile(
        self,
        agent: ModelAgent,
        payload: dict[str, Any],
        profile: ReasoningEffortProfile | None,
        *,
        api_surface: str = "chat.completions",
    ) -> dict[str, Any]:
        """Apply an opt-in profile while proving provider support before egress."""
        if api_surface not in {"chat.completions", "responses"}:
            raise ValueError("api_surface must be chat.completions or responses")
        supports = agent_proves_reasoning_effort_support(agent)
        applied = apply_request_profile(
            payload,
            profile,
            supports_reasoning_effort=supports,
            default_max_output_tokens=self.effective_max_output_tokens(agent),
        )
        if api_surface == "responses":
            if "max_tokens" in applied:
                applied["max_output_tokens"] = applied.pop("max_tokens")
            if "reasoning_effort" in applied:
                applied["reasoning"] = {"effort": applied.pop("reasoning_effort")}
        return applied

    def probe(self, agent: ModelAgent, *, timeout: float | None = None) -> dict[str, Any]:
        """Verify a local model registry, then run one unbounded completion probe.

        ``/health`` and ``/v1/models`` only prove process/model-registry liveness;
        this verifies the configured local model and deliberately exercises the
        chat path with one output token. Registry lookup and model inference are
        allowed to complete regardless of wall-clock duration and are cancelled
        only by an explicit caller action.
        """
        del timeout  # compatibility-only; readiness has no wall-clock deadline
        started = time.monotonic()
        if not is_chat_compatible_model_id(agent.model):
            return {
                "agent_id": agent.id,
                "model": agent.model,
                "status": "not_ready",
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
                "error_type": "ValueError",
                "failure_code": "non_chat_model",
            }
        self._local.usage = None
        failure_code = "provider_probe_failed"
        try:
            if agent.base_url.startswith("mock://"):
                content = self._mock(agent, [{"role": "user", "content": "Reply with exactly OK."}])
                usage = None
            else:
                destination = self._validate_provider(agent)
                if _is_local_provider_url(agent.base_url):
                    registry_request = urllib.request.Request(
                        self._provider_url(agent, "/models"),
                        method="GET",
                    )
                    with self._open_provider(registry_request, destination) as registry_response:
                        registry = json.loads(
                            self._read_bounded_response(
                                registry_response, MAX_PROVIDER_RESPONSE_BYTES
                            ).decode("utf-8")
                        )
                    model_ids = {
                        item.get("id")
                        for item in registry.get("data", [])
                        if isinstance(item, dict) and type(item.get("id")) is str
                    }
                    if agent.model not in model_ids:
                        failure_code = "provider_model_not_registered"
                        raise RuntimeError(
                            f"provider {agent.id} model registry does not contain {agent.model!r}"
                        )
                payload: dict[str, Any] = {
                    "model": agent.model,
                    "messages": [{"role": "user", "content": "Reply with exactly OK."}],
                    "temperature": 0.0,
                    "stream": False,
                    "max_tokens": 1,
                }
                if _is_direct_mlx_provider_url(agent.base_url) and self.chat_template_args:
                    payload["chat_template_kwargs"] = self.chat_template_args
                with _local_provider_slot(agent, self.local_concurrency, self.timeout):
                    content = self._send(agent, payload, destination)
                usage = self.take_usage()
            if not content.strip():
                failure_code = "provider_empty_probe_response"
                raise RuntimeError(f"provider {agent.id} returned empty probe content")
            return {
                "agent_id": agent.id,
                "model": agent.model,
                "status": "ready",
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
                "usage": usage,
            }
        except Exception as exc:  # noqa: BLE001 - readiness reports failures, it does not serve them
            return {
                "agent_id": agent.id,
                "model": agent.model,
                "status": "not_ready",
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
                "error_type": _safe_provider_probe_error_type(exc),
                "failure_code": failure_code,
            }

    def _send_with_retry(
        self,
        agent: ModelAgent,
        payload: dict[str, Any],
        destination: ProviderDestination | None = None,
        *,
        timeout: float | None = None,
    ) -> str:
        """Call the provider, retrying transient failures with exponential backoff + jitter.

        ``single_attempt_transport()`` scopes this thread to exactly one
        attempt (``retry_limit`` forced to 0) when a caller -- currently only
        ``TaskOrchestrator._invoke``'s sequential agent failover loop -- already
        owns its own retry-vs-failover decision for this exact call, so the
        two retry layers never stack. The final failure is still classified
        the same way either way; only how many real attempts get spent
        reaching it changes.
        """
        last_error: Exception | None = None
        allow_transient_retries = getattr(self._local, "allow_transient_retries", True)
        retry_limit = self._retry_limit(agent) if allow_transient_retries else 0
        deadline = _model_deadline(timeout)
        attempt = 0
        for attempt in range(retry_limit + 1):  # pragma: no branch - retry limits are validated non-negative
            _log_provider_attempt(agent, attempt, retry_limit)
            try:
                attempt_timeout = _remaining_model_timeout(deadline)
                if attempt_timeout is None:
                    return self._send(agent, payload, destination)
                return self._send(agent, payload, destination, timeout=attempt_timeout)
            except _AdministratorModelTimeout:
                raise
            except Exception as exc:  # noqa: BLE001 - classify then decide
                last_error = exc
                transient = is_transient_error(exc)
                _log_provider_attempt_failed(agent, attempt, exc, transient)
                if _is_ambiguous_passthrough_transport_failure(exc):
                    if deadline is not None and _is_timeout_transport_failure(exc):
                        raise _administrator_timeout_error(agent, "chat") from None
                    raise ProviderUpstreamError(
                        agent_id=agent.id,
                        model=agent.model,
                        error_code=PROVIDER_OUTCOME_UNKNOWN_CODE,
                        message=(
                            "the provider request outcome is unknown; "
                            "automatic replay is unsafe"
                        ),
                        client_status=502,
                        retryable=False,
                        transport="chat",
                    ) from None
                if attempt >= retry_limit or not transient:
                    break
                if isinstance(exc, urllib.error.HTTPError):
                    try:
                        exc.close()
                    except Exception:  # noqa: BLE001 - preserve the retry decision on cleanup failure
                        pass
                delay = self._backoff_delay(attempt)
                _log_provider_backoff(agent, attempt, delay)
                self._sleep(delay)
        if last_error is not None:
            _log_retry_outcome(
                agent,
                attempt,
                retry_limit,
                last_error,
                transient=transient,
                allow_transient_retries=allow_transient_retries,
            )
        try:
            if isinstance(last_error, urllib.error.HTTPError) and _is_tool_execution_stopped(last_error):
                raise _provider_tool_execution_stopped(agent) from None
            if isinstance(last_error, urllib.error.HTTPError) and (
                last_error.code == 413 or _is_oversized_tool_description_error(last_error)
            ):
                raise ProviderRequestTooLargeError(
                    "provider request body is too large",
                    agent_id=agent.id,
                    model=agent.model,
                    provider_status=last_error.code,
                    transport="chat",
                ) from None
            if isinstance(last_error, ProviderResponseError):
                raise last_error
            # Preserve actionable status before releasing the transport response.
            raise classify_provider_failure(last_error, agent_id=agent.id, model=agent.model)
        finally:
            if isinstance(last_error, urllib.error.HTTPError):
                try:
                    last_error.close()
                except Exception:  # noqa: BLE001 - cleanup must not replace the classified failure
                    pass

    def _retry_limit(self, agent: ModelAgent) -> int:
        """Return a retry budget without multiplying an expensive local queue by default."""
        return self.local_max_retries if _is_local_provider_url(agent.base_url) else self.max_retries

    def _backoff_delay(self, attempt: int) -> float:
        """Full-jitter exponential backoff, capped, so retries do not thundering-herd a provider."""
        ceiling = min(self.retry_backoff_cap, self.retry_backoff * (2 ** attempt))
        return random.uniform(0.0, ceiling)

    def _send(
        self,
        agent: ModelAgent,
        payload: dict[str, Any],
        destination: ProviderDestination | None = None,
        *,
        timeout: float | None = None,
    ) -> str:
        """Perform one provider HTTP request (isolated so retry/backoff stays testable)."""
        payload = _pin_openrouter_zdr(agent, payload)
        payload = self._clamp_agent_token_budget_with_evidence(agent, payload)
        api_key = _provider_credential(agent)
        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = format_authorization_header(agent.auth_scheme, api_key)
        inject_trace_context(headers)
        request = urllib.request.Request(
            self._provider_url(agent, "/chat/completions"),
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        started = time.monotonic()
        opened = self._open_model_provider(request, destination, agent, timeout)
        with opened as response:
            data = json.loads(
                self._read_bounded_response(response, MAX_PROVIDER_RESPONSE_BYTES).decode(
                    "utf-8"
                )
            )
        _record_provider_response_telemetry(data, started)
        usage = data.get("usage")
        if isinstance(usage, dict):
            self._local.usage = usage
        extras = _assistant_message_extras(data)
        if extras:
            self._local.assistant_message = extras
        return self._response_content(agent, data)

    @staticmethod
    def _clamp_agent_token_budget(
        agent: ModelAgent, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Clamp only explicit output-budget fields to a known provider ceiling."""
        limit = agent.max_output_tokens
        if type(limit) is not int or limit <= 0:
            return payload
        updated = payload
        for field in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
            value = updated.get(field)
            if type(value) is int and value > limit:
                if updated is payload:
                    updated = dict(payload)
                updated[field] = limit
        return updated

    def _clamp_agent_token_budget_with_evidence(
        self, agent: ModelAgent, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Clamp the payload and record honest clamp evidence for this thread.

        ADR 0130: a caller's explicit output-budget field is authoritative
        within the agent's published ceiling; when it exceeds that ceiling the
        gateway must say so in-band (trace + response) instead of silently
        rewriting it. This records what was requested and what was actually
        applied so ``take_output_budget()`` can surface both.
        """
        requested = None
        for field in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
            value = payload.get(field)
            if type(value) is int:
                requested = value
                break
        clamped_payload = self._clamp_agent_token_budget(agent, payload)
        if requested is None:
            self._local.output_budget = None
            return clamped_payload
        limit = agent.max_output_tokens
        was_clamped = type(limit) is int and limit > 0 and requested > limit
        self._local.output_budget = {
            "requested_output_tokens": requested,
            "effective_output_tokens": limit if was_clamped else requested,
            "output_budget_clamped": was_clamped,
        }
        return clamped_payload

    @staticmethod
    def _response_content(agent: ModelAgent, data: dict[str, Any]) -> str:
        """Extract text and explain provider responses that contain reasoning only."""
        choices = data.get("choices")
        message = choices[0].get("message") if isinstance(choices, list) and choices else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str) and content:
            return content
        if isinstance(message, dict) and message.get("tool_calls"):
            return ""
        if isinstance(message, dict) and message.get("reasoning"):
            raise ProviderResponseError(
                f"provider {agent.id} returned reasoning without content; "
                "for mlx-lm set chat_template_args={\"enable_thinking\": false} or increase max_output_tokens",
                failure_kind="reasoning_without_content",
            )
        raise ProviderResponseError(
            f"provider {agent.id} response did not contain assistant content",
            failure_kind="assistant_content_missing",
        )
    @staticmethod
    def _connect_validated(
        destination: ProviderDestination, timeout: float | None, source_address: tuple[str, int] | None
    ) -> socket.socket:
        """Connect to one already-resolved address without performing another DNS lookup."""
        family, sockaddr = destination
        connection = socket.socket(family, socket.SOCK_STREAM)
        cancellation = _PROVIDER_CANCELLATION.get()
        try:
            if source_address is not None:
                connection.bind(source_address)
            if cancellation is None:
                connection.settimeout(timeout)
                connection.connect(sockaddr)
                return connection
            connection.setblocking(False)
            result = connection.connect_ex(sockaddr)
            if result not in {0, errno.EISCONN}:
                if result not in {errno.EINPROGRESS, errno.EALREADY, errno.EWOULDBLOCK}:
                    raise OSError(result, os.strerror(result))
                deadline = None if timeout is None else time.monotonic() + timeout
                while True:
                    cancellation.raise_if_cancelled()
                    wait = 0.05
                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError("provider connection exceeded its explicit deadline")
                        wait = min(wait, remaining)
                    _readable, writable, exceptional = select.select(
                        (), (connection,), (connection,), wait
                    )
                    if writable or exceptional:
                        error = connection.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                        if error:
                            raise OSError(error, os.strerror(error))
                        break
            cancellation.raise_if_cancelled()
            connection.settimeout(timeout)
            return connection
        except Exception:
            connection.close()
            raise

    @staticmethod
    def _resolve_addresses(hostname: str, port: int) -> list[ProviderDestination]:
        cancellation = _PROVIDER_CANCELLATION.get()
        try:
            if cancellation is None:
                addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
            else:
                result: list[Any] = []
                finished = threading.Event()

                while not _PROVIDER_DNS_SLOTS.acquire(timeout=0.05):
                    cancellation.raise_if_cancelled()

                def resolve() -> None:
                    try:
                        result.append(socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM))
                    except BaseException as exc:  # propagated on the requesting thread
                        result.append(exc)
                    finally:
                        finished.set()
                        _PROVIDER_DNS_SLOTS.release()

                worker = threading.Thread(target=resolve, daemon=True, name="provider-dns")
                try:
                    worker.start()
                except BaseException:
                    _PROVIDER_DNS_SLOTS.release()
                    raise
                while not finished.wait(0.05):
                    cancellation.raise_if_cancelled()
                cancellation.raise_if_cancelled()
                if isinstance(result[0], BaseException):
                    raise result[0]
                addresses = result[0]
        except socket.gaierror as exc:
            raise RuntimeError(f"provider host {hostname!r} could not be resolved") from exc
        resolved = [(family, sockaddr) for family, _type, _proto, _canonname, sockaddr in addresses]
        if not resolved:
            raise RuntimeError(f"provider host {hostname!r} has no stream address")
        return resolved

    def _resolved_model_timeout(
        self, agent: ModelAgent, timeout: float | None = None
    ) -> float | None:
        """Prefer an explicit call timeout, then the model policy, then the client default."""
        if timeout is not None:
            return timeout
        if agent.model_timeout_seconds is not None:
            return agent.model_timeout_seconds
        return self.timeout

    def _open_model_provider(
        self,
        request: urllib.request.Request,
        destination: ProviderDestination | None,
        agent: ModelAgent,
        timeout: float | None = None,
    ) -> Any:
        """Open one model request using the resolved per-model wait, or none."""
        resolved = self._resolved_model_timeout(agent, timeout)
        if resolved is None:
            return self._open_provider(request, destination)
        return self._open_provider(request, destination, timeout=resolved)

    def _open_provider(
        self,
        request: urllib.request.Request,
        destination: ProviderDestination | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        """Open a validated HTTP(S) request without generic URL-handler dispatch."""
        parsed = urlparse(request.full_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise RuntimeError("provider request URL must be an HTTP(S) URL without userinfo or fragments")
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError as exc:
            raise RuntimeError("provider request URL has an invalid port") from exc
        if destination is None:
            destination = self._resolve_addresses(parsed.hostname, port)[0]
        generation_timeout = self.timeout if timeout is None else timeout
        connection_timeout = generation_timeout
        if self.connect_timeout is not None:
            connection_timeout = (
                self.connect_timeout
                if generation_timeout is None
                else min(self.connect_timeout, generation_timeout)
            )
        connection: http.client.HTTPConnection
        if parsed.scheme == "https":
            # The explicit verifying context is the security control for this reviewed API.
            connection = http.client.HTTPSConnection(  # nosemgrep: python.lang.security.audit.httpsconnection-detected.httpsconnection-detected
                parsed.hostname,
                port,
                timeout=connection_timeout,
                context=self._ssl_context,
            )
        else:
            connection = http.client.HTTPConnection(
                parsed.hostname, port, timeout=connection_timeout
            )
        connection._create_connection = (  # type: ignore[attr-defined]
            lambda _address, timeout, source_address: self._connect_validated(
                destination, timeout, source_address
            )
        )
        target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        cancellation = _PROVIDER_CANCELLATION.get()
        if cancellation is not None:
            cancellation.register(connection)
        try:
            connection.connect()
            if connection.sock is not None:
                connection.sock.settimeout(generation_timeout)
            connection.request(
                request.get_method(),
                target,
                body=request.data,
                headers=dict(request.header_items()),
            )
            response = connection.getresponse()
            if response.status >= 400:
                body = response.read(MAX_PROVIDER_ERROR_BODY_BYTES + 1)[:MAX_PROVIDER_ERROR_BODY_BYTES]
                status = response.status
                reason = response.reason
                headers = response.headers
                response.close()
                connection.close()
                raise urllib.error.HTTPError(
                    request.full_url,
                    status,
                    reason,
                    headers,
                    io.BytesIO(body),
                )
            return response
        except Exception:
            connection.close()
            raise

    def stream_chat(
        self,
        agent: ModelAgent,
        messages: list[ChatMessage],
        temperature: float | None = None,
        effort_profile: ReasoningEffortProfile | None = None,
        include_usage: bool = False,
    ):
        """Yield content deltas from a mock or OpenAI-compatible streaming endpoint.

        Real token streaming: the provider is called with stream=true and its SSE deltas
        are yielded as they arrive (not computed-then-framed). The mock path yields its
        answer in fixed chunks so behavior shape stays testable and unchanged.
        """
        if type(include_usage) is not bool:
            raise TypeError("include_usage must be a boolean")
        self._local.usage = None
        if not is_chat_compatible_model_id(agent.model):
            raise ValueError(
                f"model {agent.model!r} is not chat-compatible and cannot serve {agent.id!r}"
            )
        self._local.usage = None
        if agent.base_url.startswith("mock://"):
            answer = self._mock(agent, messages)
            for start in range(0, len(answer), 24):
                yield answer[start : start + 24]
            return

        destination = self._validated_destination(agent, transport="stream")  # pragma: no cover
        settings = self.request_settings_snapshot()
        payload = {  # pragma: no cover
            "model": agent.model,
            "messages": messages,
            "temperature": settings["temperature"] if temperature is None else temperature,
            "stream": True,
        }
        output_cap = self.effective_max_output_tokens(agent)
        if output_cap is not None:
            payload["max_tokens"] = output_cap
        if agent.stream_usage_supported:
            payload["stream_options"] = {"include_usage": True}
        if _is_direct_mlx_provider_url(agent.base_url) and self.chat_template_args:
            payload["chat_template_kwargs"] = self.chat_template_args
        if include_usage:
            payload["stream_options"] = {"include_usage": True}
        payload = self.apply_effort_profile(agent, payload, effort_profile)
        parsed_provider = urlparse(agent.base_url)
        resolved_timeout = self._resolved_model_timeout(agent)
        deadline = _model_deadline(resolved_timeout)
        with traced(
            f"chat {agent.model}",
            {
                "gen_ai.operation.name": "chat",
                "gen_ai.provider.name": agent.provider_name or parsed_provider.hostname or agent.id,
                "gen_ai.request.model": agent.model,
                "contextual_orchestrator.agent_id": agent.id,
                "server.address": parsed_provider.hostname or "",
                "server.port": parsed_provider.port or (443 if parsed_provider.scheme == "https" else 80),
            },
        ), _local_provider_slot(agent, self.local_concurrency, resolved_timeout):  # pragma: no cover
            if deadline is None:
                yield from self._stream_send(agent, payload, destination)
            else:
                yield from self._stream_send(
                    agent, payload, destination, deadline=deadline
                )

    def _stream_send(
        self,
        agent: ModelAgent,
        payload: dict[str, Any],
        destination: ProviderDestination | None = None,
        *,
        deadline: float | None = None,
    ):
        """Stream content deltas from a provider SSE response (real transport, testable)."""
        self._local.usage = None
        self._local.shared_context_budget = None
        # Shared-context output budget (issue #1157, part 2 follow-up): same
        # decision as ModelClient.chat(), applied at the same site the plain
        # catalog clamp already runs, before any provider bytes are sent for
        # this attempt. See chat() for the full contract.
        scoped_output_tokens = getattr(self._local, "request_settings", {}).get(
            "max_output_tokens"
        )
        explicit_output_tokens = (
            scoped_output_tokens if scoped_output_tokens is not None else self.max_output_tokens
        )
        shared_budget = shared_context_output_budget(
            agent,
            payload.get("messages"),
            explicit_output_tokens,
            counter=self.token_counter,
            tools=payload.get("tools"),
        )
        if shared_budget is not None:
            if shared_budget.exceeds_remaining:
                requested = (
                    explicit_output_tokens
                    if explicit_output_tokens is not None
                    else shared_budget.output_ceiling
                )
                raise ProviderRequestTooLargeError(
                    "prompt does not leave room for the requested output within the "
                    f"model's shared context window: context_window={shared_budget.context_window}, "
                    f"prompt_tokens={shared_budget.prompt_tokens}, requested_output_tokens={requested}",
                    agent_id=agent.id,
                    model=agent.model,
                    transport="stream",
                )
            if explicit_output_tokens is None:
                payload = dict(payload)
                payload["max_tokens"] = shared_budget.output_ceiling
            self._local.shared_context_budget = shared_budget.as_evidence()
        payload = _pin_openrouter_zdr(agent, payload)
        payload = self._clamp_agent_token_budget_with_evidence(agent, payload)
        api_key = _provider_credential(agent)
        headers = {"content-type": "application/json", "accept": "text/event-stream"}
        if api_key:
            headers["authorization"] = format_authorization_header(agent.auth_scheme, api_key)
        inject_trace_context(headers)
        request = urllib.request.Request(
            self._provider_url(agent, "/chat/completions"),
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        stream_error: RuntimeError | None = None
        started = time.monotonic()
        stream_usage: dict[str, Any] | None = None
        stream_model: str | None = None
        stream_choices: list[dict[str, str]] = []
        response_bytes = 0
        try:
            with self._open_model_provider(
                request,
                destination,
                agent,
                timeout=_remaining_model_timeout(deadline),
            ) as response:
                response_iterator = iter(response)
                while True:
                    remaining = _remaining_model_timeout(deadline)
                    response_socket = getattr(
                        getattr(getattr(response, "fp", None), "raw", None),
                        "_sock",
                        None,
                    )
                    if remaining is not None and response_socket is not None:
                        response_socket.settimeout(remaining)
                    try:
                        raw = next(response_iterator)
                    except StopIteration:
                        break
                    response_bytes += len(raw)
                    if response_bytes > MAX_PROVIDER_RESPONSE_BYTES:
                        raise ProviderResponseError("provider response exceeds the configured limit")
                    line = raw.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(chunk, dict):
                        continue
                    usage = chunk.get("usage")
                    if isinstance(usage, dict):
                        self._local.usage = usage
                        stream_usage = usage
                    if isinstance(chunk.get("model"), str):
                        stream_model = chunk["model"]
                    choices = chunk.get("choices")
                    if choices == []:
                        continue
                    if not isinstance(choices, list) or not choices:
                        continue
                    stream_choices.extend(
                        {"finish_reason": choice["finish_reason"]}
                        for choice in choices
                        if isinstance(choice, dict)
                        and isinstance(choice.get("finish_reason"), str)
                        and choice["finish_reason"]
                    )
                    delta = (choices[0] or {}).get("delta", {}).get("content")
                    if delta:
                        yield delta
            _record_provider_response_telemetry(
                {"usage": stream_usage, "model": stream_model, "choices": stream_choices},
                started,
            )
        except Exception as exc:  # noqa: BLE001 - provider error boundary (CWE-209)
            try:
                # The gateway's own terminal tool-stop contract must survive the
                # boundary: convert the provider HTTP shape into the package-owned
                # stop error so callers keep the 409 semantics they rely on.
                # Preserve tool-stop and response-limit contracts before classification.
                if _is_tool_execution_stopped(exc):
                    raise _provider_tool_execution_stopped(agent) from None
                if isinstance(exc, (ToolFallbackStoppedError, ProviderResponseError)):
                    raise
                # A stream may already have emitted bytes, so it can neither be retried
                # nor failed over to another provider. Keep the provider status, body,
                # and exception cause inside the gateway; callers get one stable,
                # classified, package-owned error instead of raw provider diagnostics.
                # Already-emitted bytes cannot be retried; keep diagnostics internal.
                if isinstance(exc, _AdministratorModelTimeout) or (
                    deadline is not None and _is_timeout_transport_failure(exc)
                ):
                    stream_error = _administrator_timeout_error(agent, "stream")
                else:
                    stream_error = classify_provider_failure(
                        exc, agent_id=agent.id, model=agent.model, transport="stream"
                    )
            finally:
                # HTTPError is also a response; classifiers must read it before closure.
                if isinstance(exc, urllib.error.HTTPError):
                    try:
                        exc.close()
                    except Exception:  # noqa: BLE001 - cleanup must not expose provider diagnostics
                        pass
        if stream_error is not None:
            raise stream_error

    # -- Full OpenAI passthrough (transport) ------------------------------------
    # Requests that carry provider features the multi-agent verifier cannot merge
    # (response_format / tools / the Responses API) are proxied to a single agent
    # so the full provider response shape (tool_calls, parsed structured output,
    # Responses output items) survives verbatim. Agent selection lives on the
    # orchestrator; this is the agent-level transport.
    def proxy_send(
        self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Passthrough a full request to one agent, returning the raw provider JSON."""
        return self._proxy_send(agent, endpoint, payload, allow_transient_retries=True)

    def proxy_send_once(
        self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Send one passthrough attempt so cross-provider failover cannot amplify load."""
        return self._proxy_send(agent, endpoint, payload, allow_transient_retries=False)

    def probe_structured_chat(
        self, agent: ModelAgent, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Run one bounded chat-readiness probe under separate telemetry."""
        return self._proxy_send(
            agent,
            "chat/completions",
            payload,
            allow_transient_retries=False,
            operation_kind="capability_probe",
        )

    def _proxy_send(
        self,
        agent: ModelAgent,
        endpoint: str,
        payload: dict[str, Any],
        *,
        allow_transient_retries: bool,
        operation_kind: str = "request",
    ) -> dict[str, Any]:
        """Apply the shared passthrough contract with a selectable retry policy."""
        self._local.shared_context_budget = None
        normalized_endpoint = endpoint.strip("/")
        if normalized_endpoint.startswith("v1/"):
            normalized_endpoint = normalized_endpoint[3:]
        if (
            normalized_endpoint in {"chat/completions", "completions", "responses"}
            and not is_chat_compatible_model_id(agent.model)
        ):
            raise ValueError(
                f"model {agent.model!r} is not chat-compatible and cannot serve {agent.id!r}"
            )
        if agent.base_url.startswith("mock://"):
            return self._mock_raw(agent, normalized_endpoint, payload)
        try:
            destination = self._validate_provider(agent)  # pragma: no cover
        except ProviderUpstreamError as exc:
            raise classify_provider_failure(
                exc,
                agent_id=agent.id,
                model=agent.model,
                transport="passthrough",
            ) from None
        parsed_provider = urlparse(agent.base_url)
        operation_name = {
            "chat/completions": "chat",
            "completions": "text_completion",
            "responses": "generate_content",
        }.get(normalized_endpoint, "generate_content")
        trace_name = f"{operation_name} {agent.model}"
        trace_attributes = {
            "gen_ai.operation.name": operation_name,
            "gen_ai.provider.name": agent.provider_name or parsed_provider.hostname or agent.id,
            "gen_ai.request.model": agent.model,
            "contextual_orchestrator.agent_id": agent.id,
            "contextual_orchestrator.model_group": agent.group_name or agent.model,
            "contextual_orchestrator.fallback_outcome": (
                "not_attempted" if operation_kind == "capability_probe" else "not_observed"
            ),
            "server.address": parsed_provider.hostname or "",
            "server.port": parsed_provider.port or (443 if parsed_provider.scheme == "https" else 80),
        }
        if operation_kind != "request":
            trace_name = f"{operation_kind}.{trace_name}"
            trace_attributes["contextual_orchestrator.operation_kind"] = operation_kind
        with traced(
            trace_name,
            trace_attributes,
        ):
            if normalized_endpoint == "chat/completions":
                # Shared-context output budget (issue #1157, part 2 follow-up):
                # the caller-shaped passthrough body is checked at the exact
                # point the plain catalog clamp already ran, before any local
                # provider default is injected below -- so a caller's own
                # explicit `max_tokens` (or its absence) is read honestly,
                # never confused with the gateway's own local-provider
                # default. `shared_context_output_budget` already fails
                # closed (returns None) for any messages shape
                # `describe_message_count` cannot account for -- tools, a
                # non-text content part, the Responses `input` shape, or an
                # out-of-scope model -- so no decision is forced when the
                # passthrough body is not exact chat-message accounting.
                explicit_output_tokens = payload.get("max_tokens")
                shared_budget = shared_context_output_budget(
                    agent,
                    payload.get("messages"),
                    explicit_output_tokens,
                    counter=self.token_counter,
                    tools=payload.get("tools"),
                )
                if shared_budget is not None:
                    if shared_budget.exceeds_remaining:
                        requested = (
                            explicit_output_tokens
                            if explicit_output_tokens is not None
                            else shared_budget.output_ceiling
                        )
                        raise ProviderRequestTooLargeError(
                            "prompt does not leave room for the requested output within the "
                            f"model's shared context window: context_window={shared_budget.context_window}, "
                            f"prompt_tokens={shared_budget.prompt_tokens}, requested_output_tokens={requested}",
                            agent_id=agent.id,
                            model=agent.model,
                            transport="passthrough",
                        )
                    payload = dict(payload)
                    if explicit_output_tokens is None:
                        payload["max_tokens"] = shared_budget.output_ceiling
                    self._local.shared_context_budget = shared_budget.as_evidence()
            if (
                normalized_endpoint == "chat/completions"
                and _is_local_provider_url(agent.base_url)
            ):
                # Preserve caller ownership while supplying the configured cap
                # that local OpenAI-compatible servers require when SDKs omit it.
                # setdefault is a no-op when the shared-context decision above
                # already set max_tokens to the remaining-capacity ceiling.
                payload = dict(payload)
                local_cap = self.effective_max_output_tokens(agent)
                if local_cap is not None:
                    payload.setdefault("max_tokens", local_cap)
            if normalized_endpoint == "responses" and (
                _is_local_provider_url(agent.base_url)
                or agent.provider_name == "opencode_go"
            ):
                chat_payload = _responses_to_chat_payload(payload)
                if "response_format" in chat_payload and not (
                    "response_format" in agent.tags
                    or "capability:response_format" in agent.tags
                ):
                    raise ValueError(
                        "selected model does not support the requested response format"
                    )
                local_cap = self.effective_max_output_tokens(agent)
                if local_cap is not None:
                    chat_payload.setdefault("max_tokens", local_cap)
                if _is_direct_mlx_provider_url(agent.base_url) and self.chat_template_args:
                    chat_payload["chat_template_kwargs"] = self.chat_template_args
                with _local_provider_slot(agent, self.local_concurrency, self._resolved_model_timeout(agent)):
                    chat_response = self._send_raw_with_retry(
                        agent,
                        "chat/completions",
                        chat_payload,
                        destination,
                        allow_transient_retries=allow_transient_retries,
                    )
                return _chat_to_responses_payload(chat_response, payload)
            with _local_provider_slot(agent, self.local_concurrency, self._resolved_model_timeout(agent)):  # pragma: no cover
                return self._send_raw_with_retry(
                    agent,
                    normalized_endpoint,
                    payload,
                    destination,
                    allow_transient_retries=allow_transient_retries,
                )

    def proxy_send_bytes(
        self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]
    ) -> tuple[bytes, str]:
        """Passthrough a provider response whose body is binary media."""
        payload = _pin_openrouter_zdr(agent, payload)
        if agent.base_url.startswith("mock://"):
            return b"mock audio", "audio/mpeg"
        api_key = _provider_credential(agent)  # pragma: no cover
        headers = {"content-type": "application/json"}  # pragma: no cover
        if api_key:  # pragma: no cover
            headers["authorization"] = format_authorization_header(agent.auth_scheme, api_key)
        request = urllib.request.Request(  # pragma: no cover
            self._provider_url(agent, f"/{endpoint.lstrip('/')}"),
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with self._open_model_provider(request, self._validated_destination(agent, transport="passthrough"), agent) as response:  # pragma: no cover
                return self._read_bounded_response(
                    response, MAX_PROVIDER_RESPONSE_BYTES
                ), response.headers.get_content_type()
        except Exception as exc:  # noqa: BLE001 - classify provider transport failures
            try:
                if isinstance(exc, ProviderResponseError):
                    raise
                raise classify_provider_failure(
                    exc, agent_id=agent.id, model=agent.model, transport="passthrough"
                ) from None
            finally:
                if isinstance(exc, urllib.error.HTTPError):
                    try:
                        exc.close()
                    except Exception:
                        pass  # Preserve the primary provider failure.

    def proxy_get_json(self, agent: ModelAgent, endpoint: str, *, max_response_bytes: int) -> dict[str, Any]:
        """Retrieve provider JSON from the exact agent that owns an async job."""
        if agent.base_url.startswith("mock://"):
            return {"id": endpoint.rsplit("/", 1)[-1], "status": "completed"}
        return self._batch_json(  # pragma: no cover - real provider integration
            agent,
            "GET",
            f"/{endpoint.lstrip('/')}",
            destination=self._validated_destination(agent, transport="passthrough"),
            max_response_bytes=max_response_bytes,
        )

    def proxy_delete_json(self, agent: ModelAgent, endpoint: str, *, max_response_bytes: int) -> dict[str, Any]:
        """Delete a provider resource owned by an exact provider-affine agent."""
        if agent.base_url.startswith("mock://"):
            return {"id": endpoint.rsplit("/", 1)[-1], "object": "file", "deleted": True}
        return self._batch_json(  # pragma: no cover - real provider integration
            agent,
            "DELETE",
            f"/{endpoint.lstrip('/')}",
            destination=self._validated_destination(agent, transport="passthrough"),
            max_response_bytes=max_response_bytes,
        )

    def proxy_get_bytes(self, agent: ModelAgent, endpoint: str, *, max_response_bytes: int) -> tuple[bytes, str]:
        """Retrieve provider media from the exact agent that owns an async job."""
        if agent.base_url.startswith("mock://"):
            return b"mock video", "video/mp4"
        api_key = _provider_credential(agent)  # pragma: no cover
        headers = {}  # pragma: no cover
        if api_key:  # pragma: no cover
            headers["authorization"] = format_authorization_header(agent.auth_scheme, api_key)
        request = urllib.request.Request(  # pragma: no cover
            self._provider_url(agent, f"/{endpoint.lstrip('/')}"),
            headers=headers,
            method="GET",
        )
        with self._open_model_provider(  # pragma: no cover
            request, self._validated_destination(agent, transport="passthrough"), agent
        ) as response:
            return self._read_bounded_response(response, max_response_bytes), response.headers.get_content_type()

    def proxy_upload(
        self,
        agent: ModelAgent,
        endpoint: str,
        body: Any,
        *,
        content_type: str,
        content_length: int,
        max_response_bytes: int,
    ) -> dict[str, Any]:
        """Stream a seekable multipart body to one validated provider account."""
        if agent.base_url.startswith("mock://"):
            return {
                "id": f"provider_file_{uuid.uuid4().hex}",
                "object": "file",
                "bytes": content_length,
                "purpose": "user_data",
                "filename": "upload",
            }
        api_key = _provider_credential(agent)  # pragma: no cover
        headers = {  # pragma: no cover
            "content-type": content_type,
            "content-length": str(content_length),
        }
        if api_key:  # pragma: no cover
            headers["authorization"] = format_authorization_header(agent.auth_scheme, api_key)
        request = urllib.request.Request(  # pragma: no cover
            self._provider_url(agent, f"/{endpoint.lstrip('/')}"),
            data=body,
            headers=headers,
            method="POST",
        )
        with self._open_model_provider(  # pragma: no cover
            request, self._validated_destination(agent, transport="passthrough"), agent
        ) as response:
            result = json.loads(
                self._read_bounded_response(response, max_response_bytes).decode("utf-8")
            )
        if not isinstance(result, dict):  # pragma: no cover
            raise ProviderResponseError("file provider returned a non-object response")
        return result

    def _send_raw_with_retry(
        self,
        agent: ModelAgent,
        endpoint: str,
        payload: dict[str, Any],
        destination: ProviderDestination | None = None,
        *,
        allow_transient_retries: bool = True,
    ) -> dict[str, Any]:  # pragma: no cover
        """Passthrough transport with the same transient-failure retry policy as _send."""
        last_error: Exception | None = None
        retry_limit = self._retry_limit(agent) if allow_transient_retries else 0
        attempt = 0
        for attempt in range(retry_limit + 1):
            _log_provider_attempt(agent, attempt, retry_limit)
            try:
                return self._send_raw(agent, endpoint, payload, destination)
            except Exception as exc:  # noqa: BLE001 - classify then decide
                last_error = exc
                transient = is_transient_error(exc)
                _log_provider_attempt_failed(agent, attempt, exc, transient)
                if attempt >= retry_limit or not transient:
                    break
                if isinstance(exc, urllib.error.HTTPError):
                    try:
                        exc.close()
                    except Exception:
                        pass  # Cleanup must not prevent the next provider attempt.
                delay = self._backoff_delay(attempt)
                _log_provider_backoff(agent, attempt, delay)
                self._sleep(delay)
        if last_error is not None:
            _log_retry_outcome(
                agent,
                attempt,
                retry_limit,
                last_error,
                transient=transient,
                allow_transient_retries=allow_transient_retries,
            )
        response_handed_off = False
        try:
            if isinstance(last_error, urllib.error.HTTPError) and _is_tool_execution_stopped(last_error):
                raise _provider_tool_execution_stopped(agent) from None
            if isinstance(last_error, urllib.error.HTTPError) and (
                last_error.code == 413 or _is_oversized_tool_description_error(last_error)
            ):
                raise ProviderRequestTooLargeError(
                    "provider request body is too large",
                    agent_id=agent.id,
                    model=agent.model,
                    provider_status=last_error.code,
                    transport="passthrough",
                ) from None
            if last_error is None:  # pragma: no cover - the loop always attempts once
                raise RuntimeError(f"provider {agent.id} passthrough request failed")
            if isinstance(last_error, ProviderResponseError):
                raise last_error
            if not allow_transient_retries:
                response_handed_off = True
                raise last_error
            raise classify_provider_failure(
                last_error, agent_id=agent.id, model=agent.model, transport="passthrough"
            ) from None
        finally:
            if isinstance(last_error, urllib.error.HTTPError) and not response_handed_off:
                try:
                    last_error.close()
                except Exception:
                    pass  # Preserve the primary provider failure.

    def _send_raw(
        self,
        agent: ModelAgent,
        endpoint: str,
        payload: dict[str, Any],
        destination: ProviderDestination | None = None,
    ) -> dict[str, Any]:  # pragma: no cover
        """One provider HTTP request returning the FULL provider JSON (for passthrough)."""
        payload = _pin_openrouter_zdr(agent, payload)
        payload = self._clamp_agent_token_budget_with_evidence(agent, payload)
        api_key = _provider_credential(agent)
        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = format_authorization_header(agent.auth_scheme, api_key)
        inject_trace_context(headers)
        request = urllib.request.Request(
            self._provider_url(agent, f"/{endpoint.lstrip('/')}"),
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        started = time.monotonic()
        with self._open_model_provider(request, destination, agent) as response:
            data = json.loads(
                self._read_bounded_response(
                    response, MAX_PROVIDER_RESPONSE_BYTES
                ).decode("utf-8")
            )
        _record_provider_response_telemetry(data, started)
        return data

    def _mock_raw(
        self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Mock full provider response for tests; echoes forwarded params so passthrough is assertable."""
        response_format = payload.get("response_format")
        if response_format is None and isinstance(payload.get("text"), dict):
            response_format = payload["text"].get("format")
        mock_content = (
            "{}"
            if isinstance(response_format, dict)
            and str(response_format.get("type", "")).strip().lower()
            in {"json_object", "json_schema"}
            else f"[{agent.id}] chat-mock"
        )
        echoed = {
            key: payload[key]
            for key in (
                "model",
                "response_format",
                "tools",
                "tool_choice",
                "temperature",
                "max_tokens",
                "instructions",
                "metadata",
                "messages",
                "top_logprobs",
                "text",
            )
            if key in payload
        }
        if endpoint.strip("/") == "responses":
            return {
                "id": f"resp_mock_{agent.id}",
                "object": "response",
                "model": agent.model,
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": mock_content}],
                    }
                ],
                "echo": echoed,
            }
        return {
            "id": f"chatcmpl_mock_{agent.id}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": agent.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": mock_content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "echo": echoed,
        }

    def _validated_destination(self, agent: ModelAgent, *, transport: str) -> ProviderDestination:
        """Preserve the caller's transport without changing provider overrides."""
        try:
            return self._validate_provider(agent)
        except ProviderUpstreamError as exc:
            raise classify_provider_failure(
                exc, agent_id=agent.id, model=agent.model, transport=transport
            ) from None

    def _validate_provider(self, agent: ModelAgent) -> ProviderDestination:
        """Reject unsafe model endpoints and return the exact address to connect to."""
        # Runtime secret must be resolvable from the KV — never an env var name,
        # never a silent os.getenv fallback. (Legacy api_key_env, if set, is used
        # only as the credential NAME; see ModelAgent.credential_name.)
        if _is_local_provider_url(agent.base_url):
            parsed = urlparse(agent.base_url)
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise RuntimeError(f"{agent.id} local provider URL must not contain credentials or query data")
            addresses = self._resolve_addresses(parsed.hostname or "", parsed.port or 80)
            if any(not ipaddress.ip_address(sockaddr[0]).is_loopback for _family, sockaddr in addresses):
                raise RuntimeError(f"{agent.id} local provider resolves to a non-loopback address")
            return addresses[0]
        credential_name = _provider_credential_name(agent)
        if credential_name and get_credential(credential_name) is None:
            raise NotConfigured(
                f"{agent.id} requires a resolvable credential '{credential_name}' in the KV "
                "(this replaces the legacy api_key_env environment pattern)"
            )
        parsed = urlparse(agent.base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise RuntimeError(f"{agent.id} base_url must use https")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise RuntimeError(f"{agent.id} base_url must not contain credentials, query data, or fragments")
        hostname = parsed.hostname.lower()
        if self.allowed_provider_hosts:
            return self._validate_allowlisted_provider(agent)
        addresses = self._resolve_addresses(hostname, parsed.port or 443)
        for _family, sockaddr in addresses:
            ip_address = ipaddress.ip_address(sockaddr[0])
            if (
                ip_address.is_private
                or ip_address.is_loopback
                or ip_address.is_link_local
                or ip_address.is_multicast
                or ip_address.is_reserved
            ):
                raise RuntimeError(f"{agent.id} provider resolves to non-public address")
        return addresses[0]

    def _validate_allowlisted_provider(self, agent: ModelAgent) -> ProviderDestination:
        """Validate an allowlisted https provider via EgressWeave's SSRF/DNS-rebinding guard.

        Delegates the host-allowlist match and per-address global-routability
        check to EgressWeave (CWE-918/CWE-350) instead of the hand-rolled loop
        above; that loop stays only for the no-allowlist-configured default,
        which EgressWeave's allowlist model cannot express (an empty
        allowlist there rejects every host, not none).
        """
        policy = EgressPolicy.from_hosts(self.allowed_provider_hosts, allow_local=False)
        try:
            validated = validate_egress_url_details(agent.base_url, policy=policy)
        except EgressNotAllowedError:
            validated = None
        if validated is None:
            raise ProviderUpstreamError(
                agent_id=agent.id,
                model=agent.model,
                error_code="provider_connection_error",
                message=f"provider {agent.id} host is not allowlisted",
                client_status=502,
                retryable=False,
            ) from None
        # Reuse EgressWeave's already-validated, already-resolved addresses
        # directly rather than re-resolving — re-resolving here would reopen
        # the validate-then-connect DNS-rebinding gap EgressWeave closes.
        return self._egress_address_to_destination(validated.addresses[0], validated.port)

    @staticmethod
    def _egress_address_to_destination(address: str, port: int) -> ProviderDestination:
        """Build a (family, sockaddr) pair from one already-validated EgressWeave address."""
        ip_address = ipaddress.ip_address(address)
        if isinstance(ip_address, ipaddress.IPv6Address):
            return (socket.AF_INET6, (address, port, 0, 0))
        return (socket.AF_INET, (address, port))

    def _provider_url(self, agent: ModelAgent, path: str) -> str:
        """Build a provider URL while rejecting urllib-supported local schemes."""
        parsed = urlparse(agent.base_url)
        if _is_local_provider_url(agent.base_url):
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise RuntimeError(f"{agent.id} local provider URL must not contain credentials or query data")
            base_url = urlunsplit(("http", parsed.netloc, parsed.path.rstrip("/"), "", ""))
        elif parsed.scheme in {"http", "https"} and parsed.hostname:
            base_url = agent.base_url.rstrip("/")
        else:
            raise RuntimeError(f"{agent.id} base_url must be an http(s) provider URL")
        if not path.startswith("/") or path.startswith("//") or "\r" in path or "\n" in path:
            raise RuntimeError("provider path must be a single absolute URL path")
        return f"{base_url}{path}"

    def _mock(self, agent: ModelAgent, messages: list[ChatMessage]) -> str:
        last = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        role = "worker"
        system = messages[0]["content"] if messages and messages[0].get("role") == "system" else ""
        match = re.search(r"Role: ([a-z]+)", system)
        if match:
            role = match.group(1)
        return f"[{agent.id}:{role}] {last[:220]}"

    # --- OpenAI Batch API (async, ~50% provider discount; NOT for latency-sensitive chat) ---

    def batch_chat(
        self,
        agent: ModelAgent,
        requests: dict[str, list[ChatMessage]],
        temperature: float | None = None,
        poll_interval: float = 5.0,
        poll_timeout: float = 3600.0,
        effort_profile: ReasoningEffortProfile | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Run many chat requests through the provider's Batch API and return results by id.

        ``requests`` maps a caller custom_id to its messages. Suited to eval/benchmark
        workloads (24h completion window, ~half the price); real-time chat should keep
        using ``chat``. The mock path answers synchronously so tests and local runs work.
        """
        if not is_chat_compatible_model_id(agent.model):
            raise ValueError(
                f"model {agent.model!r} is not chat-compatible and cannot serve {agent.id!r}"
            )
        if agent.base_url.startswith("mock://"):
            results = {
                custom_id: {"content": self._mock(agent, messages), "usage": None}
                for custom_id, messages in requests.items()
            }
        elif _is_local_provider_url(agent.base_url):
            results = self._local_batch_chat(agent, requests, temperature, effort_profile)
        else:
            destination = self._validated_destination(agent, transport="batch")  # pragma: no cover
            batch_error: ProviderUpstreamError | None = None
            try:
                results = self._batch_run(  # pragma: no cover
                    agent, requests, temperature, poll_interval, poll_timeout, destination, effort_profile
                )
            except Exception as exc:  # noqa: BLE001 - provider batch boundary (CWE-209)
                # Batch upload, polling, and output retrieval all cross the same
                # public gateway boundary; provider bodies and exception text stay
                # inside the authorized provider observability system. The failure
                # is still classified so callers can act on the cause.
                batch_error = classify_provider_failure(
                    exc, agent_id=agent.id, model=agent.model, transport="batch"
                )
            if batch_error is not None:
                raise batch_error
        return _validate_batch_results(requests, results)

    def _local_batch_chat(
        self,
        agent: ModelAgent,
        requests: dict[str, list[ChatMessage]],
        temperature: float | None,
        effort_profile: ReasoningEffortProfile | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Run local OpenAI-compatible requests concurrently through mlx-lm."""
        request_settings = self.request_settings_snapshot()

        def complete(custom_id: str, messages: list[ChatMessage]) -> tuple[str, dict[str, Any]]:
            with self.request_settings(**request_settings):
                if effort_profile is not None:
                    content = self.chat(
                        agent,
                        messages,
                        temperature=temperature,
                        effort_profile=effort_profile,
                    )
                else:
                    content = self.chat(agent, messages, temperature=temperature)
                return custom_id, {"content": content, "usage": self.take_usage()}

        if self.local_concurrency == 1 or len(requests) <= 1:
            return dict(complete(custom_id, messages) for custom_id, messages in requests.items())
        with ThreadPoolExecutor(max_workers=min(self.local_concurrency, len(requests))) as pool:
            futures = [
                pool.submit(copy_context().run, complete, custom_id, messages)
                for custom_id, messages in requests.items()
            ]
            return dict(future.result() for future in futures)

    def _batch_run(
        self,
        agent: ModelAgent,
        requests: dict[str, list[ChatMessage]],
        temperature: float | None,
        poll_interval: float,
        poll_timeout: float,
        destination: ProviderDestination | None = None,
        effort_profile: ReasoningEffortProfile | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Upload, create, poll, and parse one batch (isolated so the flow stays testable)."""
        settings = self.request_settings_snapshot()

        def batch_body(messages: list[ChatMessage]) -> dict[str, Any]:
            body = {
                "model": agent.model,
                "messages": messages,
                "temperature": settings["temperature"] if temperature is None else temperature,
            }
            output_cap = self.effective_max_output_tokens(agent)
            if output_cap is not None:
                body["max_tokens"] = output_cap
            return body

        lines = [
            json.dumps({
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": self._clamp_agent_token_budget_with_evidence(
                    agent,
                    _pin_openrouter_zdr(agent, self.apply_effort_profile(agent, batch_body(messages), effort_profile)),
                ),
            }, ensure_ascii=False)
            for custom_id, messages in requests.items()
        ]
        input_file_id = self._batch_upload(agent, "\n".join(lines).encode("utf-8"), destination)
        batch_id = self._batch_json(agent, "POST", "/batches", {
            "input_file_id": input_file_id,
            "endpoint": "/v1/chat/completions",
            "completion_window": "24h",
        }, destination)["id"]
        deadline = time.monotonic() + poll_timeout
        while True:
            batch = self._batch_json(agent, "GET", f"/batches/{batch_id}", destination=destination)
            status = batch.get("status")
            if status == "completed":
                break
            if status in {"failed", "expired", "cancelled"}:
                raise RuntimeError(f"batch {batch_id} ended with status {status}")
            if time.monotonic() >= deadline:
                raise TimeoutError(f"batch {batch_id} still {status} after {poll_timeout}s")
            self._sleep(poll_interval)
        raw = self._batch_raw(agent, f"/files/{batch['output_file_id']}/content", destination)
        results: dict[str, dict[str, Any]] = {}
        for line in raw.decode("utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            body = (row.get("response") or {}).get("body") or {}
            choices = body.get("choices") or [{}]
            results[row.get("custom_id", "")] = {
                "content": (choices[0].get("message") or {}).get("content"),
                "usage": body.get("usage"),
            }
        return results

    def _batch_upload(
        self, agent: ModelAgent, payload: bytes, destination: ProviderDestination | None = None
    ) -> str:
        """Upload a JSONL batch input via multipart/form-data; returns the file id."""
        boundary = f"co-batch-{uuid.uuid4().hex}"
        api_key = get_credential(agent.credential_name) or ""
        body = (
            f"--{boundary}\r\ncontent-disposition: form-data; name=\"purpose\"\r\n\r\nbatch\r\n"
            f"--{boundary}\r\ncontent-disposition: form-data; name=\"file\"; filename=\"batch.jsonl\"\r\n"
            "content-type: application/jsonl\r\n\r\n"
        ).encode("utf-8") + payload + f"\r\n--{boundary}--\r\n".encode("utf-8")
        request = urllib.request.Request(
            self._provider_url(agent, "/files"),
            data=body,
            headers={
                "authorization": format_authorization_header(agent.auth_scheme, api_key),
                "content-type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        with self._open_model_provider(request, destination, agent) as response:
            return json.loads(
                self._read_bounded_response(response, MAX_PROVIDER_RESPONSE_BYTES).decode(
                    "utf-8"
                )
            )["id"]

    def _batch_json(
        self,
        agent: ModelAgent,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        destination: ProviderDestination | None = None,
        max_response_bytes: int | None = None,
    ) -> dict[str, Any]:
        api_key = get_credential(agent.credential_name) or ""
        request = urllib.request.Request(
            self._provider_url(agent, path),
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={
                "authorization": format_authorization_header(agent.auth_scheme, api_key),
                "content-type": "application/json",
            },
            method=method,
        )
        with self._open_model_provider(request, destination, agent) as response:
            raw = self._read_bounded_response(
                response,
                MAX_PROVIDER_RESPONSE_BYTES
                if max_response_bytes is None
                else max_response_bytes,
            )
            return json.loads(raw.decode("utf-8"))

    @staticmethod
    def _read_bounded_response(response: Any, max_bytes: int) -> bytes:
        """Read at most ``max_bytes`` and fail closed on oversized provider data."""
        headers = getattr(response, "headers", None)
        declared = headers.get("content-length") if headers is not None else None
        if declared is not None:
            try:
                if int(declared) > max_bytes:
                    raise ProviderResponseError("provider response exceeds the configured limit")
            except ValueError as exc:
                raise ProviderResponseError("provider returned an invalid content length") from exc
        try:
            body = response.read(max_bytes + 1)
        except TypeError as exc:
            # Keep compatibility with small response doubles and legacy adapters
            # that expose only read(); real HTTP responses take the bounded path.
            if "positional" not in str(exc) and "argument" not in str(exc):
                raise
            body = response.read()
        if len(body) > max_bytes:
            raise ProviderResponseError("provider response exceeds the configured limit")
        return body

    def _batch_raw(self, agent: ModelAgent, path: str, destination: ProviderDestination | None = None) -> bytes:
        api_key = get_credential(agent.credential_name) or ""
        request = urllib.request.Request(
            self._provider_url(agent, path),
            headers={"authorization": format_authorization_header(agent.auth_scheme, api_key)},
            method="GET",
        )
        with self._open_model_provider(request, destination, agent) as response:
            return self._read_bounded_response(response, MAX_PROVIDER_RESPONSE_BYTES)


def _coerce_input_text(value: Any) -> str:
    """Best-effort text (for agent selection) from a Responses API ``input`` field."""
    if isinstance(value, str):
        return value
    parts: list[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                # OpenAI content-parts: {"type": "text", "text": "..."}
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
                content = item.get("content")
                if isinstance(content, str):
                    parts.append(content)
                elif isinstance(content, list):
                    for chunk in content:
                        if isinstance(chunk, dict) and isinstance(chunk.get("text"), str):
                            parts.append(chunk["text"])
    return " ".join(parts)


def _coerce_message_content_text(content: Any) -> str:
    """Best-effort plain text from chat message content (string or content-parts)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return _coerce_input_text(content)
    return ""


def load_agents(path: str) -> list[ModelAgent]:  # pragma: no cover
    """Load model agent definitions from an object- or list-shaped JSON file."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    items = data.get("agents") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("agents JSON must contain a list of agent definitions")
    return [ModelAgent.from_dict(item) for item in items]


class _AgentPoolStore:
    """Durable, normalized agent-pool storage used across process restarts.

    Agent scalar attributes live in ``agent_pool``. Ordered tags and provider
    exclusions live in child tables, so a database row never hides a second
    unqueryable JSON document. Legacy ``agent_pool(agent_id, payload)`` files
    migrate transactionally on first open; malformed or ambiguous data fails
    closed without discarding the old tab    Model-group membership lives in normalized
    ``model_group``/``model_group_member`` relations beside the pool.
    """

    _AGENT_TABLE_NAME = "agent_pool"
    _TAG_TABLE_NAME = "agent_pool_tags"
    _EXCLUSION_TABLE_NAME = "agent_pool_provider_exclusions"
    _LEGACY_TABLE_NAME = "agent_pool_legacy_payloads"
    _AGENT_COLUMNS = frozenset(
        {
            "agent_id",
            "model_name",
            "base_url",
            "api_key_env",
            "credential_key",
            "priority",
            "disabled",
            "provider_name",
            "local_credential_key",
            "auth_scheme",
            "max_output_tokens",
            "context_window",
            "reasoning_effort_supported",
            "stream_usage_supported",
            "model_timeout_seconds",
        }
    )

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
        """Return whether the exact application-owned SQLite table exists."""
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _connect(path: str) -> sqlite3.Connection:
        """Open a pool connection with relationship integrity enabled first."""
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @classmethod
    def _create_normalized_schema(cls, conn: sqlite3.Connection) -> None:
        """Create the 3NF parent and ordered child tables if absent."""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_pool (
                agent_id TEXT PRIMARY KEY,
                model_name TEXT NOT NULL,
                base_url TEXT NOT NULL,
                api_key_env TEXT NOT NULL,
                credential_key TEXT NOT NULL,
                priority INTEGER NOT NULL,
                disabled INTEGER NOT NULL,
                provider_name TEXT NOT NULL,
                local_credential_key TEXT NOT NULL,
                auth_scheme TEXT NOT NULL,
                max_output_tokens INTEGER,
                context_window INTEGER,
                reasoning_effort_supported INTEGER,
                stream_usage_supported INTEGER NOT NULL DEFAULT 0,
                model_timeout_seconds REAL CHECK (model_timeout_seconds IS NULL OR
                    (model_timeout_seconds > 0 AND model_timeout_seconds <= 2147483647)),
                CONSTRAINT agent_pool_disabled_flag_check CHECK (disabled IN (0, 1)),
                CONSTRAINT agent_pool_max_output_tokens_check
                    CHECK (
                        max_output_tokens IS NULL
                        OR (
                            max_output_tokens > 0
                            AND max_output_tokens <= 9223372036854775807
                        )
                    ),
                CONSTRAINT agent_pool_context_window_check
                    CHECK (
                        context_window IS NULL
                        OR (
                            context_window > 0
                            AND context_window <= 9223372036854775807
                        )
                    ),
                CONSTRAINT agent_pool_reasoning_effort_flag_check
                    CHECK (reasoning_effort_supported IS NULL OR reasoning_effort_supported IN (0, 1)),
                CONSTRAINT agent_pool_stream_usage_flag_check
                    CHECK (stream_usage_supported IN (0, 1))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_pool_tags (
                agent_id TEXT NOT NULL,
                tag_position INTEGER NOT NULL,
                tag_name TEXT NOT NULL,
                CONSTRAINT agent_pool_tags_primary_key PRIMARY KEY (agent_id, tag_position),
                CONSTRAINT agent_pool_tags_agent_foreign_key
                    FOREIGN KEY (agent_id) REFERENCES agent_pool(agent_id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_pool_provider_exclusions (
                agent_id TEXT NOT NULL,
                exclusion_position INTEGER NOT NULL,
                provider_name TEXT NOT NULL,
                CONSTRAINT agent_pool_provider_exclusions_primary_key
                    PRIMARY KEY (agent_id, exclusion_position),
                CONSTRAINT agent_pool_provider_exclusions_agent_foreign_key
                    FOREIGN KEY (agent_id) REFERENCES agent_pool(agent_id) ON DELETE CASCADE
            )
            """
        )

    @classmethod
    def _insert_agent(cls, conn: sqlite3.Connection, agent: "ModelAgent") -> None:
        """Insert one agent and its ordered multi-valued attributes."""
        config = agent.to_config()
        conn.execute(
            """
            INSERT INTO agent_pool (
                agent_id, model_name, base_url, api_key_env, credential_key,
                priority, disabled, provider_name, local_credential_key, auth_scheme,
                max_output_tokens, context_window, reasoning_effort_supported, stream_usage_supported,
                model_timeout_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                config["id"],
                config["model"],
                config["base_url"],
                config["api_key_env"],
                config["credential_key"],
                config["priority"],
                int(config["disabled"]),
                config["provider_name"],
                config["local_credential_key"],
                config["auth_scheme"],
                config["max_output_tokens"],
                config["context_window"],
                config["reasoning_effort_supported"],
                int(config["stream_usage_supported"]),
                config["model_timeout_seconds"],
            ),
        )
        conn.executemany(
            "INSERT INTO agent_pool_tags (agent_id, tag_position, tag_name) VALUES (?, ?, ?)",
            [(agent.id, position, tag) for position, tag in enumerate(agent.tags)],
        )
        conn.executemany(
            """
            INSERT INTO agent_pool_provider_exclusions
                (agent_id, exclusion_position, provider_name)
            VALUES (?, ?, ?)
            """,
            [
                (agent.id, position, provider)
                for position, provider in enumerate(agent.provider_exclusions)
            ],
        )

    @classmethod
    def _initialize_schema(cls, conn: sqlite3.Connection) -> None:
        """Create or transactionally migrate the agent-pool schema."""
        agent_exists = cls._table_exists(conn, cls._AGENT_TABLE_NAME)
        tag_exists = cls._table_exists(conn, cls._TAG_TABLE_NAME)
        exclusion_exists = cls._table_exists(conn, cls._EXCLUSION_TABLE_NAME)
        if not agent_exists:
            if tag_exists or exclusion_exists:
                raise RuntimeError("agent-pool child tables exist without agent_pool")
            cls._create_normalized_schema(conn)…147595 tokens truncated…  "measurement_status": "local_commercial_close_readiness",
            "source_note": (
                "Commercial close readiness separates repo-local sellable product evidence from buyer "
                "signature, legal, procurement, security acceptance, and go-live authorization inputs; "
                "it is not a valuation guarantee, purchase commitment, signed order, legal opinion, "
                "or production compliance certificate."
            ),
            "close_summary": {
                "item_count": len(close_items),
                "ready_count": state_counts.get("ready", 0),
                "warning_count": warning_count,
                "blocked_count": blocked_count,
                "buyer_signature_gap_count": buyer_signature_gap_count,
                "review_process_is_blocker": value["review_process_policy"]["is_blocker"],
            },
            "close_items": close_items,
            "concrete_blockers": concrete_blockers,
            "close_status_rules": [
                {
                    "close_status": "commercial_close_ready",
                    "rule": "sellable product packet, contract packet, onboarding/operations packet, evidence export, signatures, DPA/security acceptance, budget/PO, go-live authorization, review policy, and packaging evidence are ready",
                },
                {
                    "close_status": "commercial_close_ready_with_warnings",
                    "rule": "repo-local close packet is ready while buyer signatures, DPA/security acceptance, budget/PO, or go-live authorization remain explicit warnings",
                },
                {
                    "close_status": "commercial_close_blocked",
                    "rule": "missing local close evidence, concrete product defect, API contract failure, document mismatch, security failure, or Code Connect usage blocks close readiness",
                },
            ],
            "review_process_policy": value["review_process_policy"],
            "related_runtime_reports": {
                "commercial_value_status": value["value_status"],
                "commercial_security_attestation_status": security["security_attestation_status"],
                "commercial_contract_status": contract["contract_status"],
                "commercial_onboarding_status": onboarding["onboarding_status"],
                "commercial_operations_status": operations["operations_status"],
                "commercial_export_status": export["export_status"],
                **value["related_runtime_reports"],
            },
            "library_split_decision": value["library_split_decision"],
            "plugin_traceability": value["plugin_traceability"],
            "close_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_close_readiness/latest",
                "documentation": "docs/commercial_close_readiness.md",
            },
        }

    def commercial_go_to_market_readiness_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
        release_authority: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a buyer-facing GTM readiness index over commercial evidence."""
        close = self.commercial_close_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
            release_authority=release_authority,
        )
        value = self.commercial_value_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
            release_authority=release_authority,
        )
        security = self.commercial_security_attestation_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
            release_authority=release_authority,
        )
        export = self.commercial_evidence_export_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        handoff = self.commercial_handoff_bundle_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        saleability = self.saleability_decision_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        analytics = self.analytics_snapshot(locale_bundles=locale_bundles)
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        concrete_blockers = [
            *close["concrete_blockers"],
            *value["concrete_blockers"],
            *security["concrete_blockers"],
            *export["concrete_blockers"],
            *saleability["concrete_blockers"],
        ]
        concrete_blockers = list(dict.fromkeys(concrete_blockers))
        gtm_items = [
            {
                "item_name": "commercial_close_packet",
                "label": "Commercial close packet",
                "owner": "Deal owner",
                "sources": ["/api/v1/commercial_close_readiness/latest", "docs/commercial_close_readiness.md"],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if close["close_status"] != "commercial_close_blocked"
                and has_file("docs/commercial_close_readiness.md")
                else "blocked",
                "evidence": f"close_status={close['close_status']}",
                "action": "Use close readiness as the buyer-facing final readiness packet.",
                "exit_criteria": "Buyer sees local close packet status and remaining buyer-side signature gaps.",
            },
            {
                "item_name": "economic_value_packet",
                "label": "Economic value packet",
                "owner": "Deal owner and analytics owner",
                "sources": [
                    "/api/v1/commercial_value_readiness/latest",
                    "/api/v1/analytics_snapshots/latest",
                    "docs/commercial_value_readiness.md",
                    "docs/analytics_spec.md",
                ],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if value["value_status"] != "commercial_value_blocked"
                and has_file("docs/commercial_value_readiness.md")
                and has_file("docs/analytics_spec.md")
                else "blocked",
                "evidence": (
                    f"value_status={value['value_status']}; "
                    f"kpi_count={len(analytics['kpis'])}; guardrail_count={len(analytics['guardrails'])}"
                ),
                "action": "Show value evidence with measured-local versus buyer-specific metric separation.",
                "exit_criteria": "Buyer can inspect value claims without treating them as revenue proof or financial advice.",
            },
            {
                "item_name": "security_trust_packet",
                "label": "Security trust packet",
                "owner": "Security owner",
                "sources": [
                    "/api/v1/commercial_security_attestations/latest",
                    "docs/commercial_security_attestation.md",
                    "SECURITY.md",
                ],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if security["security_attestation_status"] != "commercial_security_attestation_blocked"
                and has_file("docs/commercial_security_attestation.md")
                and has_file("SECURITY.md")
                else "blocked",
                "evidence": f"security_attestation_status={security['security_attestation_status']}",
                "action": "Use security attestation as the buyer trust packet and keep external attestations separate.",
                "exit_criteria": "Buyer can inspect local security controls and external attestation gaps.",
            },
            {
                "item_name": "buyer_evidence_packet",
                "label": "Buyer evidence packet",
                "owner": "Evidence owner",
                "sources": [
                    "/api/v1/commercial_evidence_exports/latest",
                    "/api/v1/commercial_handoff_bundles/latest",
                    "docs/commercial_evidence_export.md",
                    "docs/commercial_buyer_handoff_bundle.md",
                ],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if export["export_status"] != "commercial_export_blocked"
                and handoff["bundle_status"] != "buyer_handoff_blocked"
                and has_file("docs/commercial_evidence_export.md")
                and has_file("docs/commercial_buyer_handoff_bundle.md")
                else "blocked",
                "evidence": f"commercial_export_status={export['export_status']}; buyer_handoff_status={handoff['bundle_status']}",
                "action": "Attach evidence export and handoff bundle as the buyer data-room index.",
                "exit_criteria": "Buyer can trace GTM claims to runtime endpoints, docs, tests, and Figma artifacts.",
            },
            {
                "item_name": "saleability_decision_packet",
                "label": "Saleability decision packet",
                "owner": "Deal owner",
                "sources": ["/api/v1/saleability_decisions/latest", "docs/commercial_saleability_decision.md"],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if saleability["saleability_status"] != "saleability_blocked"
                and has_file("docs/commercial_saleability_decision.md")
                else "blocked",
                "evidence": f"saleability_status={saleability['saleability_status']}",
                "action": "Use saleability decision as the GTM go/no-go baseline.",
                "exit_criteria": "Buyer and stakeholder review can distinguish warnings from concrete blockers.",
            },
            {
                "item_name": "admin_operator_evidence",
                "label": "Admin operator evidence",
                "owner": "Product design owner",
                "sources": ["/admin", "contextual_orchestrator/admin.py", "docs/screen_design.md"],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if has_file("contextual_orchestrator/admin.py") and has_file("docs/screen_design.md")
                else "blocked",
                "evidence": "Admin surface exposes readiness status, source notes, measurement status, and warning/blocker summaries.",
                "action": "Use the existing admin observability surface instead of creating a separate sales dashboard.",
                "exit_criteria": "Operator can inspect GTM readiness from the current admin surface.",
            },
            {
                "item_name": "analytics_truthfulness_packet",
                "label": "Analytics truthfulness packet",
                "owner": "Data analytics owner",
                "sources": ["docs/analytics_spec.md", "/api/v1/analytics_snapshots/latest"],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready" if has_file("docs/analytics_spec.md") else "blocked",
                "evidence": "Analytics spec separates measured local evidence from proposed production or buyer-specific inputs.",
                "action": "Keep GTM metrics from claiming production revenue, signed buyer proof, or unmeasured telemetry.",
                "exit_criteria": "Stakeholders can see which KPI fields are measured and which are proposed inputs.",
            },
            {
                "item_name": "stakeholder_artifacts_packet",
                "label": "Stakeholder artifacts packet",
                "owner": "Figma and Product Design owner",
                "sources": [
                    "docs/figma_artifacts.md",
                    "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                    "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                ],
                "evidence_type": "figma_artifact",
                "completion_state": "ready" if has_file("docs/figma_artifacts.md") else "blocked",
                "evidence": "Editable Figma/FigJam stakeholder artifacts are recorded and Figma Code Connect is excluded.",
                "action": "Use editable stakeholder artifacts for GTM review instead of screenshot-only evidence.",
                "exit_criteria": "Stakeholders can open the design file and FigJam board for GTM review.",
            },
            {
                "item_name": "buyer_signature_budget_follow_up",
                "label": "Buyer signature and budget follow-up",
                "owner": "Buyer sponsor, procurement owner, and deal owner",
                "sources": ["buyer order form", "MSA", "DPA", "security acceptance", "purchase order", "go-live approval"],
                "evidence_type": "buyer_input_required",
                "completion_state": "warning",
                "source_gap_status": "buyer_signature_required",
                "evidence": (
                    f"buyer_signature_gap_count={close['close_summary']['buyer_signature_gap_count']}; "
                    "signed order/MSA, DPA/security acceptance, budget/PO, and go-live authorization are buyer inputs."
                ),
                "action": "Collect buyer signatures, approvals, or waivers before representing the packet as closed-won.",
                "exit_criteria": "Buyer accepts or waives all signature, budget, security acceptance, and go-live inputs.",
            },
            {
                "item_name": "production_external_proof_follow_up",
                "label": "Production and external proof follow-up",
                "owner": "Security, operations, and deal owner",
                "sources": ["hosted scan output", "third-party attestation", "reference proof", "production telemetry"],
                "evidence_type": "external_or_production_input_required",
                "completion_state": "warning",
                "source_gap_status": "external_or_production_input_required",
                "evidence": (
                    f"security_warning_count={security['security_attestation_summary']['warning_count']}; "
                    f"value_warning_count={value['value_summary']['warning_count']}; "
                    f"export_warning_count={export['export_summary']['warning_count']}"
                ),
                "action": "Attach hosted scan, third-party attestation, reference proof, and production telemetry when available.",
                "exit_criteria": "Buyer accepts external proof, production proof, or an explicit waiver.",
            },
            {
                "item_name": "review_process_policy",
                "label": "Review process policy",
                "owner": "Deal owner",
                "sources": ["docs/commercial_go_to_market_readiness.md", "docs/commercial_saleability_decision.md"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready",
                "evidence": "Review process delay is not a GTM blocker unless a concrete failure is produced.",
                "action": "Continue GTM readiness work while queued reviews are pending.",
                "exit_criteria": "Only concrete product, security, API contract, or document failures block GTM readiness.",
            },
            {
                "item_name": "packaging_decision",
                "label": "Packaging decision",
                "owner": "Procurement and security reviewer",
                "sources": ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready"
                if close["library_split_decision"]["decision"] == "keep_single_product"
                else "warning",
                "evidence": close["library_split_decision"]["reason"],
                "action": "Keep one deployable enterprise control-plane product until extraction triggers are real.",
                "exit_criteria": "Do not create a separate library, Git submodule, or extracted package for this GTM gate.",
            },
        ]
        state_counts = Counter(item["completion_state"] for item in gtm_items)
        blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
        warning_count = state_counts.get("warning", 0)
        buyer_signature_gap_count = close["close_summary"]["buyer_signature_gap_count"]
        external_or_production_gap_count = (
            security["security_attestation_summary"]["external_attestation_gap_count"]
            + value["value_summary"]["external_value_proof_gap_count"]
            + export["export_summary"]["warning_count"]
        )
        if blocked_count:
            gtm_status = "commercial_go_to_market_blocked"
        elif warning_count:
            gtm_status = "commercial_go_to_market_ready_with_warnings"
        else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
            gtm_status = "commercial_go_to_market_ready"  # pragma: no cover

        return {
            "go_to_market_status": gtm_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_commercial_go_to_market_readiness",
            "source_note": (
                "Commercial go-to-market readiness indexes repo-local sellable product, evidence, "
                "admin, analytics, and stakeholder artifacts separately from buyer signatures, "
                "external proof, and production telemetry; it is not a valuation guarantee, purchase "
                "commitment, signed order, legal opinion, production compliance certificate, or revenue proof."
            ),
            "go_to_market_summary": {
                "item_count": len(gtm_items),
                "ready_count": state_counts.get("ready", 0),
                "warning_count": warning_count,
                "blocked_count": blocked_count,
                "buyer_signature_gap_count": buyer_signature_gap_count,
                "external_or_production_gap_count": external_or_production_gap_count,
                "review_process_is_blocker": close["review_process_policy"]["is_blocker"],
            },
            "go_to_market_items": gtm_items,
            "concrete_blockers": concrete_blockers,
            "go_to_market_status_rules": [
                {
                    "go_to_market_status": "commercial_go_to_market_ready",
                    "rule": "close, value, security, evidence, saleability, admin, analytics, stakeholder artifacts, buyer inputs, external proof, review policy, and packaging evidence are ready",
                },
                {
                    "go_to_market_status": "commercial_go_to_market_ready_with_warnings",
                    "rule": "repo-local GTM packet is ready while buyer signatures, budget/PO, DPA/security acceptance, production telemetry, reference proof, hosted scan, or third-party attestation remain explicit warnings",
                },
                {
                    "go_to_market_status": "commercial_go_to_market_blocked",
                    "rule": "missing local GTM packet evidence, concrete product defect, API contract failure, document mismatch, security failure, or Code Connect usage blocks GTM readiness",
                },
            ],
            "review_process_policy": close["review_process_policy"],
            "related_runtime_reports": {
                "commercial_close_status": close["close_status"],
                "commercial_value_status": value["value_status"],
                "commercial_security_attestation_status": security["security_attestation_status"],
                "commercial_export_status": export["export_status"],
                "buyer_handoff_status": handoff["bundle_status"],
                "saleability_status": saleability["saleability_status"],
                **close["related_runtime_reports"],
            },
            "library_split_decision": close["library_split_decision"],
            "plugin_traceability": close["plugin_traceability"],
            "go_to_market_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_go_to_market_readiness/latest",
                "documentation": "docs/commercial_go_to_market_readiness.md",
            },
        }

    def commercial_launch_readiness_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
        release_authority: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the buyer launch/trial readiness gate over commercial evidence."""
        gtm = self.commercial_go_to_market_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
            release_authority=release_authority,
        )
        operations = self.commercial_operations_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
            release_authority=release_authority,
        )
        onboarding = self.commercial_onboarding_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
            release_authority=release_authority,
        )
        acceptance = self.commercial_acceptance_check_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        analytics = self.analytics_snapshot(locale_bundles=locale_bundles)
        admin_state = self.admin_state()
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        concrete_blockers = [
            *gtm["concrete_blockers"],
            *operations["concrete_blockers"],
            *onboarding["concrete_blockers"],
            *acceptance["concrete_blockers"],
        ]
        concrete_blockers = list(dict.fromkeys(concrete_blockers))
        launch_items = [
            {
                "item_name": "go_to_market_packet",
                "label": "Go-to-market packet",
                "owner": "Deal owner",
                "sources": [
                    "/api/v1/commercial_go_to_market_readiness/latest",
                    "docs/commercial_go_to_market_readiness.md",
                ],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if gtm["go_to_market_status"] != "commercial_go_to_market_blocked"
                and has_file("docs/commercial_go_to_market_readiness.md")
                else "blocked",
                "evidence": f"go_to_market_status={gtm['go_to_market_status']}",
                "action": "Use the GTM packet as the launch/trial entry evidence.",
                "exit_criteria": "Buyer can inspect the launch packet without treating it as a signed deal or production proof.",
            },
            {
                "item_name": "runtime_launch_path",
                "label": "Runtime launch path",
                "owner": "Platform operator",
                "sources": [
                    "README.md",
                    "contextual_orchestrator/server.py",
                    "contextual_orchestrator/api_contract.py",
                    "docs/rest_api_design.md",
                    "/v1/chat/completions",
                    "/admin",
                ],
                "evidence_type": "repository_artifact",
                "completion_state": "ready"
                if all(
                    has_file(path)
                    for path in (
                        "README.md",
                        "contextual_orchestrator/server.py",
                        "contextual_orchestrator/api_contract.py",
                        "docs/rest_api_design.md",
                    )
                )
                else "blocked",
                "evidence": "Stdlib server, OpenAI-compatible endpoint, admin console, and REST contract are present.",
                "action": "Run the existing server and admin/API smoke tests for buyer trial setup.",
                "exit_criteria": "Buyer can start the runtime, authenticate admin calls, and inspect launch readiness JSON.",
            },
            {
                "item_name": "acceptance_test_packet",
                "label": "Acceptance test packet",
                "owner": "Technical reviewer",
                "sources": [
                    "/api/v1/commercial_acceptance_checks/latest",
                    "tests/test_commercial_acceptance_check.py",
                    "tests/test_commercial_go_to_market_readiness.py",
                    "tests/test_commercial_launch_readiness.py",
                    "pytest -q",
                ],
                "evidence_type": "measured_local",
                "completion_state": "ready"
                if acceptance["acceptance_status"] != "commercial_acceptance_blocked"
                and all(
                    has_file(path)
                    for path in (
                        "tests/test_commercial_acceptance_check.py",
                        "tests/test_commercial_go_to_market_readiness.py",
                        "tests/test_commercial_launch_readiness.py",
                    )
                )
                else "blocked",
                "evidence": f"acceptance_status={acceptance['acceptance_status']}",
                "action": "Use focused acceptance and launch tests as the local verification packet.",
                "exit_criteria": "Focused launch, GTM, acceptance, API, and artifact tests pass before buyer handoff.",
            },
            {
                "item_name": "operator_runbook_packet",
                "label": "Operator runbook packet",
                "owner": "Customer success and platform owner",
                "sources": [
                    "/api/v1/commercial_operations_readiness/latest",
                    "/api/v1/commercial_onboarding_readiness/latest",
                    "docs/commercial_operations_readiness.md",
                    "docs/commercial_onboarding_readiness.md",
                ],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if operations["operations_status"] != "commercial_operations_blocked"
                and onboarding["onboarding_status"] != "commercial_onboarding_blocked"
                and has_file("docs/commercial_operations_readiness.md")
                and has_file("docs/commercial_onboarding_readiness.md")
                else "blocked",
                "evidence": (
                    f"operations_status={operations['operations_status']}; "
                    f"onboarding_status={onboarding['onboarding_status']}"
                ),
                "action": "Attach onboarding and operations readiness as the launch runbook.",
                "exit_criteria": "Buyer sees implementation, support, telemetry, incident, backup, and acceptance owners.",
            },
            {
                "item_name": "admin_observability_packet",
                "label": "Admin observability packet",
                "owner": "Product design owner",
                "sources": ["/admin", "/admin/state", "contextual_orchestrator/admin.py", "docs/screen_design.md"],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if admin_state["agents"] and has_file("contextual_orchestrator/admin.py") and has_file("docs/screen_design.md")
                else "blocked",
                "evidence": (
                    f"agent_count={len(admin_state['agents'])}; "
                    "admin surface exposes launch, source, measurement, and warning summaries."
                ),
                "action": "Use the current admin observability surface rather than a separate sales dashboard.",
                "exit_criteria": "Operator can review launch readiness from the existing admin console.",
            },
            {
                "item_name": "buyer_environment_inputs",
                "label": "Buyer environment inputs",
                "owner": "Buyer implementation owner and platform operator",
                "sources": ["buyer environment URL", "deployment topology", "admin token handoff", "data retention decision"],
                "evidence_type": "buyer_environment_required",
                "completion_state": "warning",
                "source_gap_status": "buyer_environment_required",
                "evidence": "Buyer deployment URL, topology, credentials handoff, retention, and network policy are not repo-local evidence.",
                "action": "Collect buyer environment details or attach explicit trial-scope waivers.",
                "exit_criteria": "Buyer provides environment inputs or agrees the launch is limited to repo-local/demo execution.",
            },
            {
                "item_name": "production_telemetry_inputs",
                "label": "Production telemetry inputs",
                "owner": "Operations and analytics owner",
                "sources": [
                    "/api/v1/commercial_operations_readiness/latest",
                    "/api/v1/analytics_snapshots/latest",
                    "production request logs",
                    "incident drill record",
                    "backup restore proof",
                ],
                "evidence_type": "proposed_until_production",
                "completion_state": "warning",
                "source_gap_status": "production_input_required",
                "evidence": (
                    f"operations_production_evidence_action_count="
                    f"{operations['operations_summary']['production_evidence_action_count']}; "
                    f"analytics_measurement_status={analytics['measurement_status']}"
                ),
                "action": "Capture production telemetry, SLO evidence, incident drill, and restore proof in the buyer environment.",
                "exit_criteria": "First production telemetry snapshot and operations proof are attached or explicitly waived.",
            },
            {
                "item_name": "commercial_signature_inputs",
                "label": "Commercial signature inputs",
                "owner": "Buyer sponsor, procurement owner, and deal owner",
                "sources": ["signed order/MSA", "DPA/security acceptance", "purchase order", "go-live authorization"],
                "evidence_type": "buyer_signature_required",
                "completion_state": "warning",
                "source_gap_status": "buyer_signature_required",
                "evidence": (
                    f"buyer_signature_gap_count={gtm['go_to_market_summary']['buyer_signature_gap_count']}; "
                    "signed order, DPA/security acceptance, budget/PO, and go-live authorization are buyer inputs."
                ),
                "action": "Collect signatures, approvals, or waivers before representing launch readiness as closed-won.",
                "exit_criteria": "Buyer accepts all signature, DPA/security, budget, and go-live inputs.",
            },
            {
                "item_name": "review_process_policy",
                "label": "Review process policy",
                "owner": "Deal owner",
                "sources": ["docs/commercial_launch_readiness.md", "docs/commercial_go_to_market_readiness.md"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready",
                "evidence": "Review process delay is not a launch blocker unless a concrete failure is produced.",
                "action": "Continue launch readiness work while queued review processes are pending.",
                "exit_criteria": "Only concrete product, security, API contract, or document failures block launch readiness.",
            },
            {
                "item_name": "packaging_decision",
                "label": "Packaging decision",
                "owner": "Procurement and security reviewer",
                "sources": ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready"
                if gtm["library_split_decision"]["decision"] == "keep_single_product"
                else "warning",
                "evidence": gtm["library_split_decision"]["reason"],
                "action": "Keep one deployable enterprise control-plane product until extraction triggers are real.",
                "exit_criteria": "Do not create a separate library, Git submodule, or extracted package for this launch gate.",
            },
        ]
        state_counts = Counter(item["completion_state"] for item in launch_items)
        blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
        warning_count = state_counts.get("warning", 0)
        buyer_environment_gap_count = sum(
            1 for item in launch_items if item.get("source_gap_status") == "buyer_environment_required"
        )
        production_telemetry_gap_count = sum(
            1 for item in launch_items if item.get("source_gap_status") == "production_input_required"
        )
        commercial_signature_gap_count = sum(
            1 for item in launch_items if item.get("source_gap_status") == "buyer_signature_required"
        )
        external_input_group_count = (
            buyer_environment_gap_count + production_telemetry_gap_count + commercial_signature_gap_count
        )
        if blocked_count:
            launch_status = "commercial_launch_blocked"
        elif warning_count:
            launch_status = "commercial_launch_ready_with_warnings"
        else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
            launch_status = "commercial_launch_ready"  # pragma: no cover

        return {
            "launch_status": launch_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_commercial_launch_readiness",
            "source_note": (
                "Commercial launch readiness packages repo-local GTM, runtime, acceptance, operator, admin, "
                "analytics, Figma, review-process, and packaging evidence separately from buyer environment, "
                "production telemetry, and commercial signature inputs; it is not a valuation guarantee, "
                "purchase commitment, signed order, legal opinion, production compliance certificate, or revenue proof."
            ),
            "launch_summary": {
                "item_count": len(launch_items),
                "ready_count": state_counts.get("ready", 0),
                "warning_count": warning_count,
                "blocked_count": blocked_count,
                "external_input_group_count": external_input_group_count,
                "buyer_environment_gap_count": buyer_environment_gap_count,
                "production_telemetry_gap_count": production_telemetry_gap_count,
                "commercial_signature_gap_count": commercial_signature_gap_count,
                "review_process_is_blocker": gtm["review_process_policy"]["is_blocker"],
            },
            "launch_items": launch_items,
            "concrete_blockers": concrete_blockers,
            "launch_status_rules": [
                {
                    "launch_status": "commercial_launch_ready",
                    "rule": "GTM, runtime, acceptance, operator, admin, buyer environment, production telemetry, commercial signature, review policy, and packaging evidence are ready",
                },
                {
                    "launch_status": "commercial_launch_ready_with_warnings",
                    "rule": "repo-local launch packet is ready while buyer environment, production telemetry, or commercial signature inputs remain explicit warnings",
                },
                {
                    "launch_status": "commercial_launch_blocked",
                    "rule": "missing local launch packet evidence, concrete product defect, API contract failure, document mismatch, security failure, or Code Connect usage blocks launch readiness",
                },
            ],
            "review_process_policy": gtm["review_process_policy"],
            "related_runtime_reports": {
                "commercial_go_to_market_status": gtm["go_to_market_status"],
                "commercial_operations_status": operations["operations_status"],
                "commercial_onboarding_status": onboarding["onboarding_status"],
                "commercial_acceptance_status": acceptance["acceptance_status"],
                "analytics_measurement_status": analytics["measurement_status"],
                **gtm["related_runtime_reports"],
            },
            "library_split_decision": gtm["library_split_decision"],
            "plugin_traceability": gtm["plugin_traceability"],
            "launch_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_launch_readiness/latest",
                "documentation": "docs/commercial_launch_readiness.md",
            },
        }

    def commercial_completion_scorecard_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
        release_authority: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the final KRW 2B commercial completion scorecard."""
        commercial = self.commercial_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        gtm = self.commercial_go_to_market_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
            release_authority=release_authority,
        )
        launch = self.commercial_launch_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
            release_authority=release_authority,
        )
        analytics = self.analytics_snapshot(locale_bundles=locale_bundles)
        admin_state = self.admin_state()
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        concrete_blockers = list(launch["concrete_blockers"])
        if commercial["commercial_status"] == "not_commercial_ready":
            concrete_blockers.append("commercial_readiness_failed")
        if launch["launch_status"] == "commercial_launch_blocked":
            concrete_blockers.append("commercial_launch_blocked")
        concrete_blockers = list(dict.fromkeys(concrete_blockers))
        scorecard_items = [
            {
                "item_name": "product_design_evidence",
                "label": "Product Design evidence",
                "owner": "Product design owner",
                "sources": [
                    "docs/plugin_driven_design_brief.md",
                    "docs/commercial_plugin_operating_model.md",
                    "docs/screen_design.md",
                    "/admin",
                    "/api/v1/commercial_readiness/latest",
                ],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if all(
                    has_file(path)
                    for path in (
                        "docs/plugin_driven_design_brief.md",
                        "docs/commercial_plugin_operating_model.md",
                        "docs/screen_design.md",
                    )
                )
                and admin_state["agents"]
                else "blocked",
                "evidence": "Buyer, operator, security/compliance, and procurement workflows map to admin and readiness evidence.",
                "action": "Keep buyer evidence paths visible in the existing admin control plane.",
                "exit_criteria": "Every persona has a product/API/docs evidence path.",
            },
            {
                "item_name": "figma_artifacts",
                "label": "Figma artifacts",
                "owner": "Figma owner",
                "sources": [
                    "docs/figma_artifacts.md",
                    "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                    "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                ],
                "evidence_type": "figma_artifact",
                "completion_state": "ready" if has_file("docs/figma_artifacts.md") else "blocked",
                "evidence": "Editable design, FigJam diagrams, and stakeholder artifact records exist without Code Connect.",
                "action": "Use Figma/FigJam artifacts for stakeholder review without generating Code Connect metadata.",
                "exit_criteria": "Figma artifacts are recorded and Code Connect remains unused.",
            },
            {
                "item_name": "superpowers_plan_evidence",
                "label": "Superpowers plan evidence",
                "owner": "Implementation owner",
                "sources": [
                    "docs/superpowers/plans/2026-07-02-commercial-completion-scorecard-runtime.md",
                    "docs/superpowers/plans/2026-07-02-commercial-launch-readiness.md",
                    "tests/test_commercial_completion_scorecard.py",
                ],
                "evidence_type": "repository_artifact",
                "completion_state": "ready"
                if has_file("docs/superpowers/plans/2026-07-02-commercial-completion-scorecard-runtime.md")
                and has_file("tests/test_commercial_completion_scorecard.py")
                else "blocked",
                "evidence": "Dated plans and focused tests define files, expected failures, implementation, and verification commands.",
                "action": "Keep TDD plans and verification commands committed with the scorecard.",
                "exit_criteria": "Plan and focused test exist for the runtime scorecard.",
            },
            {
                "item_name": "ponytail_packaging_decision",
                "label": "Ponytail packaging decision",
                "owner": "Procurement and security reviewer",
                "sources": ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready"
                if launch["library_split_decision"]["decision"] == "keep_single_product"
                else "warning",
                "evidence": launch["library_split_decision"]["reason"],
                "action": "Keep one repository and one deployable product until extraction triggers are real.",
                "exit_criteria": "No separate library, Git submodule, or extracted package is created for this increment.",
            },
            {
                "item_name": "data_analytics_truthfulness",
                "label": "Data Analytics truthfulness",
                "owner": "Analytics owner",
                "sources": [
                    "docs/analytics_spec.md",
                    "/api/v1/analytics_snapshots/latest",
                    "/api/v1/commercial_launch_readiness/latest",
                ],
                "evidence_type": "measured_local",
                "completion_state": "ready"
                if has_file("docs/analytics_spec.md") and analytics["measurement_status"] == "local_runtime_snapshot"
                else "blocked",
                "evidence": "Measured local evidence and proposed production or buyer-specific inputs are separated.",
                "action": "Do not present proposed buyer or production inputs as measured product results.",
                "exit_criteria": "Every commercial KPI has an evidence type and source expectation.",
            },
            {
                "item_name": "runtime_endpoint_chain",
                "label": "Runtime endpoint chain",
                "owner": "Platform operator",
                "sources": [
                    "/api/v1/commercial_readiness/latest",
                    "/api/v1/commercial_go_to_market_readiness/latest",
                    "/api/v1/commercial_launch_readiness/latest",
                    "/api/v1/commercial_completion_scorecards/latest",
                ],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if commercial["commercial_status"] != "not_commercial_ready"
                and gtm["go_to_market_status"] != "commercial_go_to_market_blocked"
                and launch["launch_status"] != "commercial_launch_blocked"
                else "blocked",
                "evidence": (
                    f"commercial_status={commercial['commercial_status']}; "
                    f"go_to_market_status={gtm['go_to_market_status']}; "
                    f"launch_status={launch['launch_status']}"
                ),
                "action": "Expose completion status through the same admin-protected runtime API chain.",
                "exit_criteria": "Runtime chain has no blocked local evidence gate.",
            },
            {
                "item_name": "verification_packet",
                "label": "Verification packet",
                "owner": "Technical reviewer",
                "sources": [
                    "tests/test_commercial_completion_scorecard.py",
                    "tests/test_commercial_launch_readiness.py",
                    "tests/test_plugin_driven_artifacts.py",
                    "tests/test_api_contract.py",
                    "pytest -q",
                ],
                "evidence_type": "measured_local",
                "completion_state": "ready"
                if all(
                    has_file(path)
                    for path in (
                        "tests/test_commercial_completion_scorecard.py",
                        "tests/test_commercial_launch_readiness.py",
                        "tests/test_plugin_driven_artifacts.py",
                        "tests/test_api_contract.py",
                    )
                )
                else "blocked",
                "evidence": "Focused completion, launch, artifact, and API contract tests are present.",
                "action": "Run focused tests and full pytest before presenting completion status.",
                "exit_criteria": "Focused tests, compileall, full pytest, and diff hygiene pass.",
            },
            {
                "item_name": "review_process_policy",
                "label": "Review process policy",
                "owner": "Deal owner",
                "sources": ["docs/commercial_completion_scorecard.md", "docs/commercial_launch_readiness.md"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready",
                "evidence": "Review delay, model-review delay, and queued review automation are not product blockers.",
                "action": "Block only on concrete security, API contract, document, or functional defects.",
                "exit_criteria": "Review process delay remains non-blocking without concrete failure evidence.",
            },
            {
                "item_name": "production_buyer_followups",
                "label": "Production and buyer follow-ups",
                "owner": "Buyer sponsor, operations owner, and deal owner",
                "sources": [
                    "/api/v1/commercial_launch_readiness/latest",
                    "buyer environment",
                    "production telemetry",
                    "commercial signatures",
                ],
                "evidence_type": "external_input_required",
                "completion_state": "warning",
                "source_gap_status": "external_input_required",
                "evidence": (
                    f"external_input_group_count={launch['launch_summary']['external_input_group_count']}; "
                    f"buyer_signature_gap_count={gtm['go_to_market_summary']['buyer_signature_gap_count']}"
                ),
                "action": "Collect buyer environment, production telemetry, and signature inputs or explicit waivers.",
                "exit_criteria": "Buyer supplies or waives remaining external inputs.",
            },
        ]
        state_counts = Counter(item["completion_state"] for item in scorecard_items)
        blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
        warning_count = state_counts.get("warning", 0)
        if blocked_count:
            completion_status = "commercial_completion_blocked"
        elif warning_count:
            completion_status = "commercial_completion_ready_with_warnings"
        else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
            completion_status = "commercial_completion_ready"  # pragma: no cover

        return {
            "completion_status": completion_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_commercial_completion_scorecard",
            "source_note": (
                "Commercial completion scorecard aggregates repo-local product design, Figma, Superpowers, "
                "Ponytail, Data Analytics, runtime, verification, review-process, and packaging evidence "
                "separately from buyer and production follow-ups; it is not a valuation guarantee, purchase "
                "commitment, signed order, legal opinion, production compliance certificate, or revenue proof."
            ),
            "completion_summary": {
                "item_count": len(scorecard_items),
                "ready_count": state_counts.get("ready", 0),
                "warning_count": warning_count,
                "blocked_count": blocked_count,
                "external_input_group_count": launch["launch_summary"]["external_input_group_count"],
                "review_process_is_blocker": launch["review_process_policy"]["is_blocker"],
                "code_connect_used": False,
            },
            "completion_items": scorecard_items,
            "concrete_blockers": concrete_blockers,
            "completion_status_rules": [
                {
                    "completion_status": "commercial_completion_ready",
                    "rule": "product design, Figma, Superpowers, Ponytail, Data Analytics, runtime, verification, review policy, packaging, and external inputs are ready",
                },
                {
                    "completion_status": "commercial_completion_ready_with_warnings",
                    "rule": "repo-local program completion evidence is ready while buyer environment, production telemetry, commercial signatures, or other external inputs remain explicit warnings",
                },
                {
                    "completion_status": "commercial_completion_blocked",
                    "rule": "security failure, API contract regression, document mismatch, reproducible product defect, missing local completion evidence, or Code Connect usage blocks completion",
                },
            ],
            "review_process_policy": launch["review_process_policy"],
            "related_runtime_reports": {
                "commercial_readiness_status": commercial["commercial_status"],
                "commercial_go_to_market_status": gtm["go_to_market_status"],
                "commercial_launch_status": launch["launch_status"],
                "analytics_measurement_status": analytics["measurement_status"],
            },
            "library_split_decision": launch["library_split_decision"],
            "plugin_traceability": launch["plugin_traceability"],
            "completion_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_completion_scorecards/latest",
                "documentation": "docs/commercial_completion_scorecard.md",
            },
        }

    def commercial_buyer_acceptance_workflow_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return owner-scoped buyer acceptance workflow evidence."""
        acceptance = self.commercial_acceptance_check_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        completion = self.commercial_completion_scorecard_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        handoff = self.commercial_handoff_bundle_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        analytics = self.analytics_snapshot(locale_bundles=locale_bundles)
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        def all_files(*paths: str) -> bool:
            return all(has_file(path) for path in paths)

        def step(
            step_name: str,
            label: str,
            owner: str,
            sources: list[str],
            evidence_type: str,
            completion_state: str,
            evidence: str,
            decision_rule: str,
            next_action: str,
        ) -> dict[str, Any]:
            require_object_name(step_name, "buyer_acceptance_workflow.step_name")
            if completion_state not in {"ready", "warning", "blocked"}:  # pragma: no cover
                raise ValueError("buyer acceptance workflow state must be ready, warning, or blocked")
            return {
                "step_name": step_name,
                "label": label,
                "owner": owner,
                "sources": sources,
                "evidence_type": evidence_type,
                "completion_state": completion_state,
                "evidence": evidence,
                "decision_rule": decision_rule,
                "next_action": next_action,
            }

        concrete_blockers = list(dict.fromkeys(acceptance["concrete_blockers"] + completion["concrete_blockers"]))
        acceptance_blocked = acceptance["acceptance_status"] == "commercial_acceptance_blocked"
        completion_blocked = completion["completion_status"] == "commercial_completion_blocked"
        local_runtime_state = "blocked" if acceptance_blocked or completion_blocked or concrete_blockers else "ready"
        workflow_steps = [
            step(
                "confirm_product_scope",
                "Confirm product scope",
                "Product owner",
                ["README.md", "docs/product_planning.md", "docs/commercial_readiness.md"],
                "repository_artifact",
                "ready" if all_files("README.md", "docs/product_planning.md", "docs/commercial_readiness.md") else "blocked",
                "Product remains one enterprise orchestration control plane.",
                "Proceed when the buyer reviews one compatible API plus one admin evidence surface.",
                "Restore product scope docs before buyer acceptance.",
            ),
            step(
                "confirm_integration_surface",
                "Confirm integration surface",
                "Platform reviewer",
                ["/v1/chat/completions", "docs/rest_api_design.md", "tests/test_api_contract.py"],
                "repository_artifact",
                "ready" if all_files("docs/rest_api_design.md", "tests/test_api_contract.py") else "blocked",
                "OpenAI-compatible API and API contract tests are present.",
                "Proceed when API compatibility evidence is present and tests pass.",
                "Restore REST docs or API contract tests before buyer acceptance.",
            ),
            step(
                "confirm_operator_evidence",
                "Confirm operator evidence",
                "Platform operator",
                ["/admin", "/admin/state", "docs/screen_design.md", "contextual_orchestrator/admin.py"],
                "repository_artifact",
                "ready" if all_files("docs/screen_design.md", "contextual_orchestrator/admin.py") else "blocked",
                "Admin console exposes operator evidence for pool, policy, trace, access, replay, analytics, and readiness.",
                "Proceed when operator state and commercial readiness surfaces are visible.",
                "Restore admin evidence docs or implementation before buyer acceptance.",
            ),
            step(
                "confirm_readiness_endpoints",
                "Confirm readiness endpoints",
                "Product owner",
                [
                    "/api/v1/sales_readiness/latest",
                    "/api/v1/commercial_readiness/latest",
                    "/api/v1/commercial_acceptance_checks/latest",
                    "/api/v1/commercial_completion_scorecards/latest",
                ],
                "measured_local",
                local_runtime_state,
                (
                    f"commercial_acceptance_status={acceptance['acceptance_status']}; "
                    f"commercial_completion_status={completion['completion_status']}"
                ),
                "Proceed when local runtime gates have no concrete blockers.",
                "Resolve blocked readiness, acceptance, or completion gates before buyer acceptance.",
            ),
            step(
                "confirm_security_posture",
                "Confirm security posture",
                "Security reviewer",
                ["SECURITY.md", "tests/test_security_hardening.py", ".github/workflows/security.yml"],
                "repository_artifact",
                "ready" if all_files("SECURITY.md", "tests/test_security_hardening.py", ".github/workflows/security.yml") else "blocked",
                "Security policy, hardening tests, and hosted security workflow metadata are present.",
                "Proceed when concrete security failures are absent.",
                "Fix concrete security failures; queued security checks alone are not blockers.",
            ),
            step(
                "confirm_metric_honesty",
                "Confirm metric honesty",
                "Analytics reviewer",
                ["/api/v1/analytics_snapshots/latest", "docs/analytics_spec.md"],
                "measured_local",
                "ready" if has_file("docs/analytics_spec.md") and analytics["measurement_status"] == "local_runtime_snapshot" else "blocked",
                "Analytics spec and local snapshot separate measured local evidence from proposed production or buyer inputs.",
                "Proceed when measured and proposed claims are not mixed.",
                "Restore analytics source labels before buyer acceptance.",
            ),
            step(
                "confirm_visual_review_path",
                "Confirm visual review path",
                "Stakeholder reviewer",
                ["docs/figma_artifacts.md", "Figma design file", "FigJam board", "Figma Slides deck"],
                "figma_artifact",
                "ready" if has_file("docs/figma_artifacts.md") else "blocked",
                "Editable design, FigJam, and stakeholder artifacts are recorded without Code Connect.",
                "Proceed when visual artifacts are available for stakeholder review.",
                "Record Figma artifacts before buyer acceptance.",
            ),
            step(
                "confirm_packaging_decision",
                "Confirm packaging decision",
                "Procurement reviewer",
                ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
                "repository_artifact",
                "ready" if completion["library_split_decision"]["decision"] == "keep_single_product" else "warning",
                completion["library_split_decision"]["reason"],
                "Proceed with one repository and one deployable product.",
                "Extract only after a second product, independent release cadence, or provenance trigger exists.",
            ),
            step(
                "confirm_production_inputs",
                "Confirm production inputs",
                "Operations owner",
                ["production telemetry", "support plan", "SLO evidence", "incident drill"],
                "proposed_until_production",
                "warning",
                "Production telemetry, support, SLO, and incident evidence require a deployment or paid onboarding environment.",
                "Proceed with warning when production inputs are explicitly caveated.",
                "Collect production evidence during buyer onboarding or mark an explicit waiver.",
            ),
            step(
                "confirm_buyer_specific_inputs",
                "Confirm buyer-specific inputs",
                "Buyer and account team",
                ["ROI model", "security questionnaire", "legal review", "deployment target"],
                "proposed_until_buyer_specific",
                "warning",
                "ROI, legal, procurement, and deployment inputs require a named buyer.",
                "Proceed with warning when buyer-specific inputs are explicit follow-ups.",
                "Collect buyer-specific inputs during account diligence.",
            ),
        ]
        state_counts = Counter(item["completion_state"] for item in workflow_steps)
        blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
        warning_count = state_counts.get("warning", 0)
        if blocked_count:
            workflow_status = "buyer_acceptance_workflow_blocked"
        elif warning_count:
            workflow_status = "buyer_acceptance_workflow_ready_with_warnings"
        else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
            workflow_status = "buyer_acceptance_workflow_ready"  # pragma: no cover

        return {
            "workflow_status": workflow_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_buyer_acceptance_workflow",
            "source_note": (
                "Commercial buyer acceptance workflow maps runbook owners, runtime evidence, "
                "Figma artifacts, analytics truthfulness, review-process policy, and packaging "
                "decision into Go, Warning, and No-Go steps; it is not a valuation guarantee, "
                "purchase commitment, signed order, legal opinion, production compliance certificate, "
                "or revenue proof."
            ),
            "workflow_summary": {
                "step_count": len(workflow_steps),
                "ready_count": state_counts.get("ready", 0),
                "warning_count": warning_count,
                "blocked_count": blocked_count,
                "production_follow_up_count": sum(
                    1 for item in workflow_steps if item["evidence_type"] == "proposed_until_production"
                ),
                "buyer_specific_follow_up_count": sum(
                    1 for item in workflow_steps if item["evidence_type"] == "proposed_until_buyer_specific"
                ),
                "review_process_is_blocker": acceptance["review_process_policy"]["is_blocker"],
                "code_connect_used": False,
            },
            "acceptance_steps": workflow_steps,
            "concrete_blockers": concrete_blockers,
            "go_warning_no_go_rules": [
                {
                    "workflow_status": "buyer_acceptance_workflow_ready",
                    "rule": "all acceptance owners have ready evidence and no external production or buyer-specific inputs remain open",
                },
                {
                    "workflow_status": "buyer_acceptance_workflow_ready_with_warnings",
                    "rule": "repo-local buyer acceptance evidence is ready while production or buyer-specific inputs remain explicit warnings",
                },
                {
                    "workflow_status": "buyer_acceptance_workflow_blocked",
                    "rule": "security failure, API contract regression, document mismatch, reproducible product defect, missing acceptance path, or Code Connect usage blocks acceptance",
                },
            ],
            "review_process_policy": acceptance["review_process_policy"],
            "related_runtime_reports": {
                "commercial_acceptance_status": acceptance["acceptance_status"],
                "commercial_completion_status": completion["completion_status"],
                "buyer_handoff_status": handoff["bundle_status"],
                "analytics_measurement_status": analytics["measurement_status"],
            },
            "library_split_decision": completion["library_split_decision"],
            "plugin_traceability": completion["plugin_traceability"],
            "workflow_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_buyer_acceptance_workflows/latest",
                "documentation": "docs/commercial_buyer_acceptance_runbook.md",
            },
        }

    def commercial_demo_scenario_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return buyer-demo scenarios for the KRW 2B completion standard."""
        completion = self.commercial_completion_scorecard_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        buyer_workflow = self.commercial_buyer_acceptance_workflow_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        analytics = self.analytics_snapshot(locale_bundles=locale_bundles)
        admin_state = self.admin_state()
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        def all_files(*paths: str) -> bool:
            return all(has_file(path) for path in paths)

        def step(
            step_name: str,
            label: str,
            persona: str,
            sources: list[str],
            runtime_endpoints: list[str],
            evidence_type: str,
            completion_state: str,
            evidence: str,
            demo_action: str,
            expected_evidence: str,
        ) -> dict[str, Any]:
            require_object_name(step_name, "commercial_demo.step_name")
            if completion_state not in {"ready", "warning", "blocked"}:  # pragma: no cover
                raise ValueError("commercial demo step state must be ready, warning, or blocked")
            return {
                "step_name": step_name,
                "label": label,
                "persona": persona,
                "sources": sources,
                "runtime_endpoints": runtime_endpoints,
                "evidence_type": evidence_type,
                "completion_state": completion_state,
                "evidence": evidence,
                "demo_action": demo_action,
                "expected_evidence": expected_evidence,
            }

        concrete_blockers = list(
            dict.fromkeys(completion["concrete_blockers"] + buyer_workflow["concrete_blockers"])
        )
        local_runtime_state = (
            "blocked"
            if completion["completion_status"] == "commercial_completion_blocked"
            or buyer_workflow["workflow_status"] == "buyer_acceptance_workflow_blocked"
            or concrete_blockers
            else "ready"
        )
        event_counts = analytics.get("event_counts", {})
        recent_runs = admin_state.get("recent_workflow_runs", [])
        demo_steps = [
            step(
                "compatible_api_smoke",
                "Compatible API smoke",
                "Economic buyer",
                ["README.md", "docs/rest_api_design.md", "/v1/chat/completions"],
                ["/v1/chat/completions"],
                "measured_local",
                "ready"
                if all_files("README.md", "docs/rest_api_design.md")
                and event_counts.get("chat_completion_requested", 0) > 0
                else "blocked",
                f"successful_chat_completion_events={event_counts.get('chat_completion_requested', 0)}",
                "Run the OpenAI-compatible chat completion call used by the buyer application.",
                "The buyer sees a compatible response and the runtime records a local analytics event.",
            ),
            step(
                "conducted_workflow_trace",
                "Conducted workflow trace",
                "Platform operator",
                ["/admin", "/api/v1/workflow_runs", "docs/screen_design.md"],
                ["/admin", "/api/v1/workflow_runs"],
                "measured_local",
                "ready" if recent_runs and has_file("docs/screen_design.md") else "blocked",
                f"recent_workflow_run_count={len(recent_runs)}",
                "Open the admin trace view for a conducted workflow run.",
                "The operator can inspect mode, policy mode, selected agents, and run trace evidence.",
            ),
            step(
                "access_list_inspection",
                "Access-list inspection",
                "Compliance reviewer",
                ["docs/product_planning.md", "/api/v1/access_reports/{workflow_run_id}", "/admin"],
                ["/api/v1/access_reports/{workflow_run_id}", "/admin"],
                "repository_and_runtime_artifact",
                "ready" if has_file("docs/product_planning.md") else "blocked",
                "access reports are scoped to workflow_run_id and exposed through the admin surface",
                "Open the access report for the conducted workflow run.",
                "The reviewer sees why each agent had access to context, tools, and trace evidence.",
            ),
            step(
                "evaluation_replay",
                "Evaluation replay",
                "Quality reviewer",
                ["docs/screen_design.md", "/api/v1/evaluation_runs", "/admin"],
                ["/api/v1/evaluation_runs", "/admin"],
                "measured_local",
                "ready" if event_counts.get("evaluation_run_created", 0) > 0 else "blocked",
                f"evaluation_run_created_events={event_counts.get('evaluation_run_created', 0)}",
                "Replay the buyer prompt through the evaluation endpoint.",
                "The reviewer sees replay status and trace-backed verification evidence.",
            ),
            step(
                "admin_readiness_console",
                "Admin readiness console",
                "Economic buyer",
                [
                    "/admin",
                    "/api/v1/commercial_completion_scorecards/latest",
                    "/api/v1/commercial_buyer_acceptance_workflows/latest",
                    "/api/v1/commercial_demo_scenarios/latest",
                ],
                [
                    "/admin",
                    "/api/v1/commercial_completion_scorecards/latest",
                    "/api/v1/commercial_buyer_acceptance_workflows/latest",
                    "/api/v1/commercial_demo_scenarios/latest",
                ],
                "repository_and_runtime_artifact",
                local_runtime_state,
                (
                    f"commercial_completion_status={completion['completion_status']}; "
                    f"buyer_acceptance_workflow_status={buyer_workflow['workflow_status']}"
                ),
                "Show the readiness card chain in the admin console.",
                "The buyer sees completion, buyer acceptance, and demo status without leaving one control plane.",
            ),
            step(
                "metric_truthfulness",
                "Metric truthfulness",
                "Compliance reviewer",
                ["docs/analytics_spec.md", "/api/v1/analytics_snapshots/latest"],
                ["/api/v1/analytics_snapshots/latest"],
                "measured_local",
                "ready"
                if has_file("docs/analytics_spec.md") and analytics["measurement_status"] == "local_runtime_snapshot"
                else "blocked",
                "measured local metrics remain separate from proposed production and buyer-specific metrics",
                "Review the analytics spec and local analytics endpoint.",
                "The reviewer can distinguish measured runtime data from proposed KPI definitions.",
            ),
            step(
                "figma_stakeholder_review",
                "Figma stakeholder review",
                "Stakeholder reviewer",
                [
                    "docs/figma_artifacts.md",
                    "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                    "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                ],
                [],
                "figma_artifact",
                "ready" if has_file("docs/figma_artifacts.md") else "blocked",
                "editable Figma and FigJam stakeholder artifacts are recorded without Code Connect",
                "Walk through the design file and FigJam diagram packet.",
                "Stakeholders review the product narrative, admin surface, and runtime flow as editable artifacts.",
            ),
            step(
                "buyer_acceptance_decision",
                "Buyer acceptance decision",
                "Economic buyer",
                [
                    "docs/commercial_buyer_acceptance_runbook.md",
                    "/api/v1/commercial_buyer_acceptance_workflows/latest",
                ],
                ["/api/v1/commercial_buyer_acceptance_workflows/latest"],
                "repository_and_runtime_artifact",
                local_runtime_state,
                f"buyer_acceptance_workflow_status={buyer_workflow['workflow_status']}",
                "Use the buyer acceptance workflow as the Go/Warning/No-Go decision record.",
                "The buyer can sign off on repo-local evidence while external follow-ups stay explicit.",
            ),
            step(
                "production_buyer_followups",
                "Production and buyer follow-ups",
                "Economic buyer",
                ["production telemetry", "ROI model", "security questionnaire", "support plan"],
                [],
                "proposed_until_buyer_specific",
                "warning",
                "Production telemetry, named-buyer ROI, security questionnaire, and support plan require buyer input.",
                "Capture buyer-specific production, ROI, legal, and support inputs after the local demo.",
                "External inputs are tracked as warnings, not hidden as measured product evidence.",
            ),
        ]
        state_counts = Counter(item["completion_state"] for item in demo_steps)
        blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
        warning_count = state_counts.get("warning", 0)
        if blocked_count:
            demo_status = "commercial_demo_blocked"
        elif warning_count:
            demo_status = "commercial_demo_ready_with_warnings"
        else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
            demo_status = "commercial_demo_ready"  # pragma: no cover
        required_runtime_endpoints = list(
            dict.fromkeys(
                endpoint
                for item in demo_steps
                for endpoint in item["runtime_endpoints"]
                if endpoint.startswith("/")
            )
        )

        return {
            "demo_status": demo_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_commercial_demo_scenarios",
            "source_note": (
                "Commercial demo scenarios package repo-local runtime, admin, analytics, Figma, "
                "buyer acceptance, review-policy, and packaging evidence for KRW 2,000,000,000 "
                "saleability review; it is not a valuation guarantee, purchase commitment, "
                "signed order, legal opinion, production compliance certificate, or revenue proof."
            ),
            "demo_narrative": {
                "title": "KRW 2B commercial control-plane buyer demo",
                "promise": (
                    "Show one enterprise orchestration control plane with a compatible inference API, "
                    "operator/admin evidence, trace and access visibility, evaluation replay, and truthful metrics."
                ),
                "audience": [
                    "Economic buyer",
                    "Platform operator",
                    "Compliance reviewer",
                    "Quality reviewer",
                    "Stakeholder reviewer",
                ],
            },
            "demo_summary": {
                "step_count": len(demo_steps),
                "ready_count": state_counts.get("ready", 0),
                "warning_count": warning_count,
                "blocked_count": blocked_count,
                "persona_count": len({item["persona"] for item in demo_steps}),
                "endpoint_count": len(required_runtime_endpoints),
                "review_process_is_blocker": completion["review_process_policy"]["is_blocker"],
                "code_connect_used": False,
            },
            "demo_steps": demo_steps,
            "required_runtime_endpoints": required_runtime_endpoints,
            "concrete_blockers": concrete_blockers,
            "demo_status_rules": [
                {
                    "demo_status": "commercial_demo_ready",
                    "rule": "all demo steps are ready and no production or buyer-specific follow-ups remain open",
                },
                {
                    "demo_status": "commercial_demo_ready_with_warnings",
                    "rule": "repo-local demo evidence is ready while production, ROI, legal, support, or buyer-specific inputs remain explicit warnings",
                },
                {
                    "demo_status": "commercial_demo_blocked",
                    "rule": "security failure, API contract regression, document mismatch, runtime defect, missing local demo evidence, or Code Connect usage blocks the demo",
                },
            ],
            "review_process_policy": completion["review_process_policy"],
            "related_runtime_reports": {
                "commercial_completion_status": completion["completion_status"],
                "buyer_acceptance_workflow_status": buyer_workflow["workflow_status"],
                "analytics_measurement_status": analytics["measurement_status"],
            },
            "library_split_decision": completion["library_split_decision"],
            "plugin_traceability": completion["plugin_traceability"],
            "demo_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_demo_scenarios/latest",
                "documentation": "docs/commercial_demo_scenarios.md",
            },
        }

    def commercial_proposal_packet_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return buyer proposal sections for the KRW 2B saleability standard."""
        completion = self.commercial_completion_scorecard_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        demo = self.commercial_demo_scenario_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        buyer_workflow = self.commercial_buyer_acceptance_workflow_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        value = self.commercial_value_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        security = self.commercial_security_attestation_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        contract = self.commercial_contract_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        onboarding = self.commercial_onboarding_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        operations = self.commercial_operations_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        analytics = self.analytics_snapshot(locale_bundles=locale_bundles)
        admin_state = self.admin_state()
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        def all_files(*paths: str) -> bool:
            return all(has_file(path) for path in paths)

        def section(
            section_name: str,
            label: str,
            owner: str,
            sources: list[str],
            runtime_endpoints: list[str],
            evidence_type: str,
            completion_state: str,
            evidence: str,
            buyer_message: str,
            next_action: str,
        ) -> dict[str, Any]:
            require_object_name(section_name, "commercial_proposal.section_name")
            if completion_state not in {"ready", "warning", "blocked"}:  # pragma: no cover
                raise ValueError("commercial proposal section state must be ready, warning, or blocked")
            return {
                "section_name": section_name,
                "label": label,
                "owner": owner,
                "sources": sources,
                "runtime_endpoints": runtime_endpoints,
                "evidence_type": evidence_type,
                "completion_state": completion_state,
                "evidence": evidence,
                "buyer_message": buyer_message,
                "next_action": next_action,
            }

        concrete_blockers = list(
            dict.fromkeys(
                completion["concrete_blockers"]
                + demo["concrete_blockers"]
                + buyer_workflow["concrete_blockers"]
            )
        )
        local_runtime_state = (
            "blocked"
            if completion["completion_status"] == "commercial_completion_blocked"
            or demo["demo_status"] == "commercial_demo_blocked"
            or buyer_workflow["workflow_status"] == "buyer_acceptance_workflow_blocked"
            or concrete_blockers
            else "ready"
        )
        proposal_sections = [
            section(
                "executive_summary",
                "Executive summary",
                "Deal owner",
                ["README.md", "docs/commercial_completion_scorecard.md", "/api/v1/commercial_completion_scorecards/latest"],
                ["/api/v1/commercial_completion_scorecards/latest"],
                "repository_and_runtime_artifact",
                local_runtime_state if all_files("README.md", "docs/commercial_completion_scorecard.md") else "blocked",
                f"commercial_completion_status={completion['completion_status']}",
                "One enterprise orchestration control plane is ready for a KRW 2B buyer review with explicit caveats.",
                "Use the completion scorecard as the proposal cover evidence.",
            ),
            section(
                "product_scope",
                "Product scope",
                "Product owner",
                ["docs/product_planning.md", "docs/commercial_plugin_operating_model.md", "docs/library_research.md"],
                [],
                "repository_artifact",
                "ready"
                if all_files("docs/product_planning.md", "docs/commercial_plugin_operating_model.md", "docs/library_research.md")
                and completion["library_split_decision"]["decision"] == "keep_single_product"
                else "blocked",
                completion["library_split_decision"]["reason"],
                "The offer is one compatible API plus one admin evidence surface, not a split product suite.",
                "Keep proposal language centered on a single deployable control plane.",
            ),
            section(
                "buyer_value_case",
                "Buyer value case",
                "Economic buyer",
                ["docs/commercial_value_readiness.md", "docs/analytics_spec.md", "/api/v1/commercial_value_readiness/latest"],
                ["/api/v1/commercial_value_readiness/latest", "/api/v1/analytics_snapshots/latest"],
                "repository_and_runtime_artifact",
                "ready"
                if value["value_status"] != "commercial_value_blocked"
                and has_file("docs/commercial_value_readiness.md")
                and analytics["measurement_status"] == "local_runtime_snapshot"
                else "blocked",
                f"value_status={value['value_status']}; analytics_measurement_status={analytics['measurement_status']}",
                "Measured local value evidence is separated from buyer-specific ROI inputs.",
                "Attach buyer ROI assumptions only after buyer discovery validates them.",
            ),
            section(
                "demo_and_acceptance_path",
                "Demo and acceptance path",
                "Product design owner",
                [
                    "docs/commercial_demo_scenarios.md",
                    "docs/commercial_buyer_acceptance_runbook.md",
                    "/api/v1/commercial_demo_scenarios/latest",
                    "/api/v1/commercial_buyer_acceptance_workflows/latest",
                ],
                ["/api/v1/commercial_demo_scenarios/latest", "/api/v1/commercial_buyer_acceptance_workflows/latest"],
                "repository_and_runtime_artifact",
                local_runtime_state
                if all_files("docs/commercial_demo_scenarios.md", "docs/commercial_buyer_acceptance_runbook.md")
                else "blocked",
                f"commercial_demo_status={demo['demo_status']}; buyer_acceptance_workflow_status={buyer_workflow['workflow_status']}",
                "Buyer review can move from demo script to Go/Warning/No-Go acceptance without leaving the control plane.",
                "Run the demo packet and record the acceptance decision.",
            ),
            section(
                "technical_evidence",
                "Technical evidence",
                "Platform reviewer",
                ["docs/rest_api_design.md", "docs/screen_design.md", "contextual_orchestrator/api_contract.py", "/admin"],
                ["/v1/chat/completions", "/admin", "/api/v1/workflow_runs", "/api/v1/access_reports/{workflow_run_id}"],
                "repository_and_runtime_artifact",
                "ready"
                if all_files("docs/rest_api_design.md", "docs/screen_design.md", "contextual_orchestrator/api_contract.py")
                and admin_state["agents"]
                else "blocked",
                f"agent_count={len(admin_state['agents'])}; recent_workflow_run_count={len(admin_state['recent_workflow_runs'])}",
                "The buyer can verify API compatibility, trace evidence, and access-list evidence.",
                "Include endpoint list and admin review screenshots or live walkthrough in the proposal.",
            ),
            section(
                "security_and_compliance",
                "Security and compliance",
                "Security reviewer",
                ["SECURITY.md", "docs/commercial_security_attestation.md", "/api/v1/commercial_security_attestations/latest"],
                ["/api/v1/commercial_security_attestations/latest"],
                "repository_and_runtime_artifact",
                "ready"
                if security["security_attestation_status"] != "commercial_security_attestation_blocked"
                and all_files("SECURITY.md", "docs/commercial_security_attestation.md")
                else "blocked",
                f"security_attestation_status={security['security_attestation_status']}",
                "Repo-local security evidence is present while external attestation and buyer DPA inputs stay explicit.",
                "Do not claim third-party attestation until supplied.",
            ),
            section(
                "implementation_and_operations",
                "Implementation and operations",
                "Operations owner",
                [
                    "docs/commercial_onboarding_readiness.md",
                    "docs/commercial_operations_readiness.md",
                    "/api/v1/commercial_onboarding_readiness/latest",
                    "/api/v1/commercial_operations_readiness/latest",
                ],
                ["/api/v1/commercial_onboarding_readiness/latest", "/api/v1/commercial_operations_readiness/latest"],
                "repository_and_runtime_artifact",
                "ready"
                if onboarding["onboarding_status"] != "commercial_onboarding_blocked"
                and operations["operations_status"] != "commercial_operations_blocked"
                and all_files("docs/commercial_onboarding_readiness.md", "docs/commercial_operations_readiness.md")
                else "blocked",
                f"onboarding_status={onboarding['onboarding_status']}; operations_status={operations['operations_status']}",
                "Implementation and operations evidence is proposal-ready with production environment follow-ups separated.",
                "Convert buyer environment details into an onboarding checklist after selection.",
            ),
            section(
                "proposal_review_packet",
                "Proposal review packet",
                "Stakeholder reviewer",
                [
                    "docs/commercial_proposal_packet.md",
                    "docs/figma_artifacts.md",
                    "docs/superpowers/plans/2026-07-02-commercial-proposal-packet-runtime.md",
                ],
                ["/api/v1/commercial_proposal_packets/latest"],
                "repository_and_runtime_artifact",
                "ready"
                if all_files(
                    "docs/commercial_proposal_packet.md",
                    "docs/figma_artifacts.md",
                    "docs/superpowers/plans/2026-07-02-commercial-proposal-packet-runtime.md",
                )
                else "blocked",
                "Proposal docs, FigJam artifact record, and implementation plan are committed as repo artifacts.",
                "Stakeholders can review the proposal packet as docs, runtime JSON, and FigJam flow.",
                "Keep Figma Code Connect out of the proposal workflow.",
            ),
            section(
                "commercial_terms_followups",
                "Commercial terms follow-ups",
                "Deal owner",
                ["docs/commercial_contract_readiness.md", "buyer order form", "legal review", "pricing approval"],
                ["/api/v1/commercial_contract_readiness/latest"],
                "proposed_until_buyer_specific",
                "warning",
                f"contract_status={contract['contract_status']}",
                "Order-form, legal, pricing approval, and signature inputs need named-buyer review.",
                "Collect buyer-specific legal and commercial terms or record explicit waiver.",
            ),
            section(
                "production_buyer_inputs",
                "Production and buyer inputs",
                "Buyer sponsor",
                ["production telemetry", "buyer ROI model", "support plan", "security questionnaire"],
                [],
                "proposed_until_buyer_specific",
                "warning",
                "Production telemetry, buyer ROI model, support plan, and security questionnaire are external inputs.",
                "The proposal is locally ready while buyer-specific inputs remain caveated.",
                "Collect external evidence during proposal negotiation or paid onboarding.",
            ),
        ]
        state_counts = Counter(item["completion_state"] for item in proposal_sections)
        blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
        warning_count = state_counts.get("warning", 0)
        if blocked_count:
            proposal_status = "commercial_proposal_blocked"
        elif warning_count:
            proposal_status = "commercial_proposal_ready_with_warnings"
        else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
            proposal_status = "commercial_proposal_ready"  # pragma: no cover
        required_runtime_endpoints = list(
            dict.fromkeys(
                endpoint
                for item in proposal_sections
                for endpoint in item["runtime_endpoints"]
                if endpoint.startswith("/")
            )
        )

        return {
            "proposal_status": proposal_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_commercial_proposal_packet",
            "source_note": (
                "Commercial proposal packet packages repo-local completion, demo, acceptance, value, "
                "security, contract, onboarding, operations, analytics, Figma, review-policy, and packaging "
                "evidence for KRW 2,000,000,000 buyer proposal review; it is not a valuation guarantee, "
                "purchase commitment, signed order, legal opinion, production compliance certificate, or revenue proof."
            ),
            "proposal_narrative": {
                "title": "KRW 2B commercial buyer proposal packet",
                "promise": (
                    "Present one enterprise orchestration control plane with compatible API integration, "
                    "operator evidence, buyer demo path, acceptance workflow, and truthful commercial caveats."
                ),
                "audience": [
                    "Economic buyer",
                    "Platform reviewer",
                    "Security reviewer",
                    "Operations owner",
                    "Stakeholder reviewer",
                    "Deal owner",
                ],
            },
            "proposal_summary": {
                "section_count": len(proposal_sections),
                "ready_count": state_counts.get("ready", 0),
                "warning_count": warning_count,
                "blocked_count": blocked_count,
                "endpoint_count": len(required_runtime_endpoints),
                "review_process_is_blocker": completion["review_process_policy"]["is_blocker"],
                "code_connect_used": False,
            },
            "proposal_sections": proposal_sections,
            "required_runtime_endpoints": required_runtime_endpoints,
            "concrete_blockers": concrete_blockers,
            "proposal_status_rules": [
                {
                    "proposal_status": "commercial_proposal_ready",
                    "rule": "all proposal sections are ready and no buyer-specific commercial or production inputs remain open",
                },
                {
                    "proposal_status": "commercial_proposal_ready_with_warnings",
                    "rule": "repo-local proposal evidence is ready while pricing, legal, ROI, production, support, or signature inputs remain explicit warnings",
                },
                {
                    "proposal_status": "commercial_proposal_blocked",
                    "rule": "security failure, API contract regression, document mismatch, runtime defect, missing local proposal evidence, or Code Connect usage blocks the proposal",
                },
            ],
            "review_process_policy": completion["review_process_policy"],
            "related_runtime_reports": {
                "commercial_completion_status": completion["completion_status"],
                "commercial_demo_status": demo["demo_status"],
                "buyer_acceptance_workflow_status": buyer_workflow["workflow_status"],
                "commercial_value_status": value["value_status"],
                "commercial_security_attestation_status": security["security_attestation_status"],
                "commercial_contract_status": contract["contract_status"],
                "commercial_onboarding_status": onboarding["onboarding_status"],
                "commercial_operations_status": operations["operations_status"],
                "analytics_measurement_status": analytics["measurement_status"],
            },
            "library_split_decision": completion["library_split_decision"],
            "plugin_traceability": completion["plugin_traceability"],
            "proposal_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_proposal_packets/latest",
                "documentation": "docs/commercial_proposal_packet.md",
            },
        }

    def commercial_purchase_approval_packet_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return buyer-side purchase approval gates for the KRW 2B standard."""
        proposal = self.commercial_proposal_packet_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        close = self.commercial_close_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        procurement = self.commercial_procurement_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        contract = self.commercial_contract_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        value = self.commercial_value_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        security = self.commercial_security_attestation_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        onboarding = self.commercial_onboarding_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        operations = self.commercial_operations_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        analytics = self.analytics_snapshot(locale_bundles=locale_bundles)
        admin_state = self.admin_state()
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        def all_files(*paths: str) -> bool:
            return all(has_file(path) for path in paths)

        def gate(
            gate_name: str,
            label: str,
            owner: str,
            sources: list[str],
            runtime_endpoints: list[str],
            evidence_type: str,
            completion_state: str,
            evidence: str,
            approval_question: str,
            next_action: str,
        ) -> dict[str, Any]:
            require_object_name(gate_name, "commercial_purchase_approval.gate_name")
            if completion_state not in {"ready", "warning", "blocked"}:  # pragma: no cover
                raise ValueError("commercial purchase approval gate state must be ready, warning, or blocked")
            return {
                "gate_name": gate_name,
                "label": label,
                "owner": owner,
                "sources": sources,
                "runtime_endpoints": runtime_endpoints,
                "evidence_type": evidence_type,
                "completion_state": completion_state,
                "evidence": evidence,
                "approval_question": approval_question,
                "next_action": next_action,
            }

        concrete_blockers = list(dict.fromkeys(proposal["concrete_blockers"] + close["concrete_blockers"]))
        local_runtime_state = (
            "blocked"
            if proposal["proposal_status"] == "commercial_proposal_blocked"
            or close["close_status"] == "commercial_close_blocked"
            or concrete_blockers
            else "ready"
        )
        approval_gates = [
            gate(
                "proposal_packet_ready",
                "Proposal packet ready",
                "Deal owner",
                ["docs/commercial_proposal_packet.md", "/api/v1/commercial_proposal_packets/latest"],
                ["/api/v1/commercial_proposal_packets/latest"],
                "repository_and_runtime_artifact",
                local_runtime_state if has_file("docs/commercial_proposal_packet.md") else "blocked",
                f"commercial_proposal_status={proposal['proposal_status']}",
                "Can the buyer review one coherent proposal packet?",
                "Use the proposal packet as the approval cover artifact.",
            ),
            gate(
                "procurement_path_ready",
                "Procurement path ready",
                "Procurement owner",
                ["docs/commercial_procurement_readiness.md", "/api/v1/commercial_procurement_readiness/latest"],
                ["/api/v1/commercial_procurement_readiness/latest"],
                "repository_and_runtime_artifact",
                "ready"
                if procurement["procurement_status"] != "commercial_procurement_blocked"
                and has_file("docs/commercial_procurement_readiness.md")
                else "blocked",
                f"commercial_procurement_status={procurement['procurement_status']}",
                "Can procurement validate license, rights, distribution, admin, and caveat evidence?",
                "Route the packet to procurement with buyer-specific inputs still marked as warnings.",
            ),
            gate(
                "contract_legal_packet_ready",
                "Contract and legal packet ready",
                "Legal owner",
                ["docs/commercial_contract_readiness.md", "/api/v1/commercial_contract_readiness/latest"],
                ["/api/v1/commercial_contract_readiness/latest"],
                "repository_and_runtime_artifact",
                "ready"
                if contract["contract_status"] != "commercial_contract_blocked"
                and has_file("docs/commercial_contract_readiness.md")
                else "blocked",
                f"commercial_contract_status={contract['contract_status']}",
                "Can legal review support, privacy, audit, license, and order-form obligations?",
                "Collect final legal edits and buyer order-form fields outside the local runtime claim.",
            ),
            gate(
                "financial_value_case_ready",
                "Financial value case ready",
                "Economic buyer",
                ["docs/commercial_value_readiness.md", "docs/analytics_spec.md", "/api/v1/commercial_value_readiness/latest"],
                ["/api/v1/commercial_value_readiness/latest", "/api/v1/analytics_snapshots/latest"],
                "repository_and_runtime_artifact",
                "ready"
                if value["value_status"] != "commercial_value_blocked"
                and all_files("docs/commercial_value_readiness.md", "docs/analytics_spec.md")
                and analytics["measurement_status"] == "local_runtime_snapshot"
                else "blocked",
                f"commercial_value_status={value['value_status']}; analytics_measurement_status={analytics['measurement_status']}",
                "Can finance separate measured local evidence from buyer ROI assumptions?",
                "Attach buyer ROI and payback assumptions only after buyer discovery.",
            ),
            gate(
                "security_acceptance_ready",
                "Security acceptance ready",
                "Security owner",
                ["SECURITY.md", "docs/commercial_security_attestation.md", "/api/v1/commercial_security_attestations/latest"],
                ["/api/v1/commercial_security_attestations/latest"],
                "repository_and_runtime_artifact",
                "ready"
                if security["security_attestation_status"] != "commercial_security_attestation_blocked"
                and all_files("SECURITY.md", "docs/commercial_security_attestation.md")
                else "blocked",
                f"commercial_security_attestation_status={security['security_attestation_status']}",
                "Can security approve repo-local controls while external attestations remain caveated?",
                "Collect buyer DPA, privacy, and third-party attestation evidence separately.",
            ),
            gate(
                "implementation_readiness_ready",
                "Implementation readiness ready",
                "Implementation owner",
                [
                    "docs/commercial_onboarding_readiness.md",
                    "docs/commercial_operations_readiness.md",
                    "/api/v1/commercial_onboarding_readiness/latest",
                    "/api/v1/commercial_operations_readiness/latest",
                ],
                ["/api/v1/commercial_onboarding_readiness/latest", "/api/v1/commercial_operations_readiness/latest"],
                "repository_and_runtime_artifact",
                "ready"
                if onboarding["onboarding_status"] != "commercial_onboarding_blocked"
                and operations["operations_status"] != "commercial_operations_blocked"
                and all_files("docs/commercial_onboarding_readiness.md", "docs/commercial_operations_readiness.md")
                else "blocked",
                f"commercial_onboarding_status={onboarding['onboarding_status']}; commercial_operations_status={operations['operations_status']}",
                "Can implementation owners see onboarding and operations evidence before purchase approval?",
                "Turn buyer environment details into the paid onboarding plan.",
            ),
            gate(
                "close_readiness_ready",
                "Close readiness ready",
                "Deal owner",
                ["docs/commercial_close_readiness.md", "/api/v1/commercial_close_readiness/latest"],
                ["/api/v1/commercial_close_readiness/latest"],
                "repository_and_runtime_artifact",
                "ready"
                if close["close_status"] != "commercial_close_blocked"
                and has_file("docs/commercial_close_readiness.md")
                else "blocked",
                f"commercial_close_status={close['close_status']}",
                "Can the buyer see final signature, budget, security, and go-live caveats before approval?",
                "Use close readiness as the bridge between local product evidence and buyer approvals.",
            ),
            gate(
                "approval_runtime_packet_ready",
                "Approval runtime packet ready",
                "Stakeholder reviewer",
                [
                    "docs/commercial_purchase_approval_packet.md",
                    "docs/figma_artifacts.md",
                    "docs/superpowers/plans/2026-07-02-commercial-purchase-approval-packet-runtime.md",
                ],
                ["/api/v1/commercial_purchase_approval_packets/latest"],
                "repository_and_runtime_artifact",
                "ready"
                if all_files(
                    "docs/commercial_purchase_approval_packet.md",
                    "docs/figma_artifacts.md",
                    "docs/superpowers/plans/2026-07-02-commercial-purchase-approval-packet-runtime.md",
                )
                and admin_state["agents"]
                else "blocked",
                "Purchase approval docs, FigJam artifact record, plan, and admin runtime are present.",
                "Can stakeholders review the approval packet as docs, runtime JSON, and FigJam flow?",
                "Keep Figma Code Connect out of the approval workflow.",
            ),
            gate(
                "buyer_signature_authority",
                "Buyer signature authority",
                "Buyer sponsor and legal owner",
                ["signed order form", "MSA", "DPA", "security acceptance"],
                [],
                "proposed_until_buyer_specific",
                "warning",
                "Signed order form, MSA, DPA, and final security acceptance require buyer authority.",
                "Does the buyer have an identified signer and legal approval path?",
                "Collect named signer and final legal/security approvals.",
            ),
            gate(
                "buyer_budget_po_authority",
                "Buyer budget and PO authority",
                "Finance and procurement owner",
                ["budget approval", "purchase order", "finance authority", "go-live authorization"],
                [],
                "proposed_until_buyer_specific",
                "warning",
                "Budget approval, purchase order, finance authority, and go-live authorization require buyer input.",
                "Can finance issue the KRW 2B purchase order and approve go-live?",
                "Collect budget owner, PO path, and go-live authorization or explicit waiver.",
            ),
        ]
        state_counts = Counter(item["completion_state"] for item in approval_gates)
        blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
        warning_count = state_counts.get("warning", 0)
        if blocked_count:
            purchase_approval_status = "commercial_purchase_approval_blocked"
        elif warning_count:
            purchase_approval_status = "commercial_purchase_approval_ready_with_warnings"
        else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
            purchase_approval_status = "commercial_purchase_approval_ready"  # pragma: no cover
        required_runtime_endpoints = list(
            dict.fromkeys(
                endpoint
                for item in approval_gates
                for endpoint in item["runtime_endpoints"]
                if endpoint.startswith("/")
            )
        )

        return {
            "purchase_approval_status": purchase_approval_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_commercial_purchase_approval_packet",
            "source_note": (
                "Commercial purchase approval packet packages repo-local proposal, close, procurement, "
                "contract, value, security, onboarding, operations, analytics, Figma, review-policy, and "
                "packaging evidence for KRW 2,000,000,000 buyer purchase approval; it is not a valuation "
                "guarantee, purchase commitment, signed order, legal opinion, production compliance "
                "certificate, or revenue proof."
            ),
            "approval_narrative": {
                "title": "KRW 2B buyer purchase approval packet",
                "promise": (
                    "Give finance, procurement, legal, security, and implementation owners one runtime "
                    "approval packet that separates local product evidence from buyer-specific authority inputs."
                ),
                "audience": [
                    "Economic buyer",
                    "Finance owner",
                    "Procurement owner",
                    "Legal owner",
                    "Security owner",
                    "Implementation owner",
                ],
            },
            "approval_summary": {
                "gate_count": len(approval_gates),
                "ready_count": state_counts.get("ready", 0),
                "warning_count": warning_count,
                "blocked_count": blocked_count,
                "endpoint_count": len(required_runtime_endpoints),
                "review_process_is_blocker": proposal["review_process_policy"]["is_blocker"],
                "code_connect_used": False,
            },
            "approval_gates": approval_gates,
            "required_runtime_endpoints": required_runtime_endpoints,
            "concrete_blockers": concrete_blockers,
            "purchase_approval_status_rules": [
                {
                    "purchase_approval_status": "commercial_purchase_approval_ready",
                    "rule": "all approval gates are ready and no buyer signature, budget, PO, or go-live inputs remain open",
                },
                {
                    "purchase_approval_status": "commercial_purchase_approval_ready_with_warnings",
                    "rule": "repo-local purchase approval evidence is ready while buyer signature authority, budget, PO, or go-live authorization remain explicit warnings",
                },
                {
                    "purchase_approval_status": "commercial_purchase_approval_blocked",
                    "rule": "security failure, API contract regression, document mismatch, runtime defect, missing local approval evidence, or Code Connect usage blocks purchase approval",
                },
            ],
            "review_process_policy": proposal["review_process_policy"],
            "related_runtime_reports": {
                "commercial_proposal_status": proposal["proposal_status"],
                "commercial_close_status": close["close_status"],
                "commercial_procurement_status": procurement["procurement_status"],
                "commercial_contract_status": contract["contract_status"],
                "commercial_value_status": value["value_status"],
                "commercial_security_attestation_status": security["security_attestation_status"],
                "commercial_onboarding_status": onboarding["onboarding_status"],
                "commercial_operations_status": operations["operations_status"],
                "analytics_measurement_status": analytics["measurement_status"],
            },
            "library_split_decision": proposal["library_split_decision"],
            "plugin_traceability": proposal["plugin_traceability"],
            "approval_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_purchase_approval_packets/latest",
                "documentation": "docs/commercial_purchase_approval_packet.md",
            },
        }

    def commercial_due_diligence_room_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return buyer due diligence room sections for the KRW 2B standard."""
        purchase = self.commercial_purchase_approval_packet_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        proposal = self.commercial_proposal_packet_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        completion = self.commercial_completion_scorecard_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        demo = self.commercial_demo_scenario_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        buyer_workflow = self.commercial_buyer_acceptance_workflow_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        close = self.commercial_close_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        procurement = self.commercial_procurement_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        contract = self.commercial_contract_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        value = self.commercial_value_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        security = self.commercial_security_attestation_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        onboarding = self.commercial_onboarding_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        operations = self.commercial_operations_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        analytics = self.analytics_snapshot(locale_bundles=locale_bundles)
        admin_state = self.admin_state()
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        def all_files(*paths: str) -> bool:
            return all(has_file(path) for path in paths)

        def section(
            section_name: str,
            label: str,
            reviewer: str,
            sources: list[str],
            runtime_endpoints: list[str],
            evidence_type: str,
            completion_state: str,
            evidence: str,
            diligence_question: str,
            next_action: str,
        ) -> dict[str, Any]:
            require_object_name(section_name, "commercial_due_diligence.section_name")
            if completion_state not in {"ready", "warning", "blocked"}:  # pragma: no cover
                raise ValueError("commercial due diligence section state must be ready, warning, or blocked")
            return {
                "section_name": section_name,
                "label": label,
                "reviewer": reviewer,
                "sources": sources,
                "runtime_endpoints": runtime_endpoints,
                "evidence_type": evidence_type,
                "completion_state": completion_state,
                "evidence": evidence,
                "diligence_question": diligence_question,
                "next_action": next_action,
            }

        concrete_blockers = list(
            dict.fromkeys(
                purchase["concrete_blockers"]
                + proposal["concrete_blockers"]
                + completion["concrete_blockers"]
                + demo["concrete_blockers"]
                + buyer_workflow["concrete_blockers"]
            )
        )
        local_runtime_state = (
            "blocked"
            if purchase["purchase_approval_status"] == "commercial_purchase_approval_blocked"
            or proposal["proposal_status"] == "commercial_proposal_blocked"
            or completion["completion_status"] == "commercial_completion_blocked"
            or demo["demo_status"] == "commercial_demo_blocked"
            or buyer_workflow["workflow_status"] == "buyer_acceptance_workflow_blocked"
            or concrete_blockers
            else "ready"
        )
        diligence_sections = [
            section(
                "purchase_approval_packet",
                "Purchase approval packet",
                "Purchase committee",
                ["docs/commercial_purchase_approval_packet.md", "/api/v1/commercial_purchase_approval_packets/latest"],
                ["/api/v1/commercial_purchase_approval_packets/latest", "/api/v1/commercial_proposal_packets/latest"],
                "repository_and_runtime_artifact",
                local_runtime_state if has_file("docs/commercial_purchase_approval_packet.md") else "blocked",
                f"commercial_purchase_approval_status={purchase['purchase_approval_status']}",
                "Can the buyer review one approval packet before diligence sign-off?",
                "Use the approval packet as the diligence room cover index.",
            ),
            section(
                "runtime_api_evidence",
                "Runtime API evidence",
                "Platform reviewer",
                [
                    "docs/rest_api_design.md",
                    "contextual_orchestrator/api_contract.py",
                    "README.md",
                    "/v1/chat/completions",
                ],
                [
                    "/v1/chat/completions",
                    "/api/v1/workflow_runs",
                    "/api/v1/access_reports/{workflow_run_id}",
                    "/api/v1/commercial_due_diligence_rooms/latest",
                ],
                "repository_and_runtime_artifact",
                "ready"
                if local_runtime_state == "ready"
                and all_files("docs/rest_api_design.md", "contextual_orchestrator/api_contract.py", "README.md")
                and admin_state["agents"]
                else "blocked",
                f"agent_count={len(admin_state['agents'])}; api_contract_present={has_file('contextual_orchestrator/api_contract.py')}",
                "Can platform reviewers verify compatible API and evidence endpoints?",
                "Keep API compatibility and evidence endpoints in the diligence index.",
            ),
            section(
                "admin_trace_evidence",
                "Admin trace evidence",
                "Operator reviewer",
                ["docs/screen_design.md", "/admin", "/admin/state", "workflow trace", "access report"],
                ["/admin", "/admin/state", "/api/v1/workflow_runs", "/api/v1/access_reports/{workflow_run_id}"],
                "repository_and_runtime_artifact",
                "ready"
                if all_files("docs/screen_design.md", "contextual_orchestrator/admin.py")
                and admin_state["agents"]
                and admin_state["recent_workflow_runs"]
                else "blocked",
                f"recent_workflow_run_count={len(admin_state['recent_workflow_runs'])}",
                "Can the operator show trace and access-list evidence in the admin console?",
                "Run one conduct workflow before a live diligence walkthrough.",
            ),
            section(
                "security_and_compliance",
                "Security and compliance",
                "Security reviewer",
                ["SECURITY.md", "docs/commercial_security_attestation.md", "/api/v1/commercial_security_attestations/latest"],
                ["/api/v1/commercial_security_attestations/latest"],
                "repository_and_runtime_artifact",
                "ready"
                if security["security_attestation_status"] != "commercial_security_attestation_blocked"
                and all_files("SECURITY.md", "docs/commercial_security_attestation.md")
                else "blocked",
                f"commercial_security_attestation_status={security['security_attestation_status']}",
                "Can security separate repo-local controls from external attestation gaps?",
                "Do not claim third-party certification until supplied.",
            ),
            section(
                "commercial_terms",
                "Commercial terms",
                "Legal and procurement reviewers",
                [
                    "docs/commercial_contract_readiness.md",
                    "docs/commercial_procurement_readiness.md",
                    "docs/commercial_close_readiness.md",
                ],
                [
                    "/api/v1/commercial_contract_readiness/latest",
                    "/api/v1/commercial_procurement_readiness/latest",
                    "/api/v1/commercial_close_readiness/latest",
                ],
                "repository_and_runtime_artifact",
                "ready"
                if contract["contract_status"] != "commercial_contract_blocked"
                and procurement["procurement_status"] != "commercial_procurement_blocked"
                and close["close_status"] != "commercial_close_blocked"
                and all_files(
                    "docs/commercial_contract_readiness.md",
                    "docs/commercial_procurement_readiness.md",
                    "docs/commercial_close_readiness.md",
                )
                else "blocked",
                (
                    f"commercial_contract_status={contract['contract_status']}; "
                    f"commercial_procurement_status={procurement['procurement_status']}; "
                    f"commercial_close_status={close['close_status']}"
                ),
                "Can legal and procurement review terms, rights, and close caveats together?",
                "Attach buyer-specific order-form language outside the local runtime claim.",
            ),
            section(
                "value_and_analytics",
                "Value and analytics",
                "Economic reviewer",
                ["docs/commercial_value_readiness.md", "docs/analytics_spec.md", "/api/v1/analytics_snapshots/latest"],
                ["/api/v1/commercial_value_readiness/latest", "/api/v1/analytics_snapshots/latest"],
                "repository_and_runtime_artifact",
                "ready"
                if value["value_status"] != "commercial_value_blocked"
                and analytics["measurement_status"] == "local_runtime_snapshot"
                and all_files("docs/commercial_value_readiness.md", "docs/analytics_spec.md")
                else "blocked",
                f"commercial_value_status={value['value_status']}; analytics_measurement_status={analytics['measurement_status']}",
                "Can finance tell measured local evidence apart from buyer ROI assumptions?",
                "Keep proposed KPI targets separate from measured local runtime data.",
            ),
            section(
                "implementation_readiness",
                "Implementation readiness",
                "Implementation and operations reviewers",
                ["docs/commercial_onboarding_readiness.md", "docs/commercial_operations_readiness.md"],
                ["/api/v1/commercial_onboarding_readiness/latest", "/api/v1/commercial_operations_readiness/latest"],
                "repository_and_runtime_artifact",
                "ready"
                if onboarding["onboarding_status"] != "commercial_onboarding_blocked"
                and operations["operations_status"] != "commercial_operations_blocked"
                and all_files("docs/commercial_onboarding_readiness.md", "docs/commercial_operations_readiness.md")
                else "blocked",
                f"commercial_onboarding_status={onboarding['onboarding_status']}; commercial_operations_status={operations['operations_status']}",
                "Can implementation owners see onboarding, operations, incident, and handoff evidence?",
                "Convert buyer environment specifics into the paid onboarding plan.",
            ),
            section(
                "figma_and_design_review",
                "Figma and design review",
                "Product design reviewer",
                [
                    "docs/commercial_due_diligence_room.md",
                    "docs/figma_artifacts.md",
                    "docs/superpowers/plans/2026-07-02-commercial-due-diligence-room-runtime.md",
                ],
                ["/api/v1/commercial_due_diligence_rooms/latest"],
                "repository_and_runtime_artifact",
                "ready"
                if all_files(
                    "docs/commercial_due_diligence_room.md",
                    "docs/figma_artifacts.md",
                    "docs/superpowers/plans/2026-07-02-commercial-due-diligence-room-runtime.md",
                )
                else "blocked",
                "Due diligence doc, FigJam artifact record, and implementation plan are committed.",
                "Can stakeholders inspect the diligence room as docs, runtime JSON, and FigJam?",
                "Use FigJam only; do not use Figma Code Connect.",
            ),
            section(
                "buyer_authority_documents",
                "Buyer authority documents",
                "Buyer sponsor",
                ["named buyer signer", "budget owner and purchase order", "buyer DPA or privacy acceptance"],
                [],
                "proposed_until_buyer_specific",
                "warning",
                "Named signer, budget owner, PO, and buyer privacy acceptance require buyer authority.",
                "Does the buyer have authority artifacts ready for final diligence?",
                "Collect signer, PO, DPA/privacy acceptance, or explicit waiver.",
            ),
            section(
                "production_external_attestations",
                "Production and external attestations",
                "Production and security owners",
                ["production telemetry", "third-party security attestation", "hosted scan evidence"],
                [],
                "proposed_until_buyer_specific",
                "warning",
                "Production telemetry and third-party attestations are external evidence, not local repo measurements.",
                "Can the buyer distinguish local readiness from production and third-party evidence?",
                "Collect hosted telemetry and external attestation after environment selection.",
            ),
        ]
        state_counts = Counter(item["completion_state"] for item in diligence_sections)
        blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
        warning_count = state_counts.get("warning", 0)
        if blocked_count:
            due_diligence_status = "commercial_due_diligence_blocked"
        elif warning_count:
            due_diligence_status = "commercial_due_diligence_ready_with_warnings"
        else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
            due_diligence_status = "commercial_due_diligence_ready"  # pragma: no cover
        required_runtime_endpoints = list(
            dict.fromkeys(
                endpoint
                for item in diligence_sections
                for endpoint in item["runtime_endpoints"]
                if endpoint.startswith("/")
            )
        )

        return {
            "due_diligence_status": due_diligence_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_commercial_due_diligence_room",
            "source_note": (
                "Commercial due diligence room packages repo-local purchase approval, proposal, runtime, "
                "admin trace, security, contract, value, onboarding, operations, analytics, Figma, "
                "review-policy, and packaging evidence for KRW 2,000,000,000 buyer diligence; it is "
                "not a valuation guarantee, purchase commitment, signed order, legal opinion, production "
                "compliance certificate, third-party attestation, or revenue proof."
            ),
            "diligence_narrative": {
                "title": "KRW 2B commercial due diligence room",
                "promise": (
                    "Give finance, procurement, legal, security, product, and implementation reviewers "
                    "one evidence room that separates measured local product evidence from buyer-specific "
                    "and external production artifacts."
                ),
                "audience": [
                    "Economic buyer",
                    "Finance owner",
                    "Procurement owner",
                    "Legal owner",
                    "Security owner",
                    "Platform reviewer",
                    "Implementation owner",
                ],
            },
            "diligence_summary": {
                "section_count": len(diligence_sections),
                "ready_count": state_counts.get("ready", 0),
                "warning_count": warning_count,
                "blocked_count": blocked_count,
                "endpoint_count": len(required_runtime_endpoints),
                "review_process_is_blocker": purchase["review_process_policy"]["is_blocker"],
                "code_connect_used": False,
            },
            "diligence_sections": diligence_sections,
            "required_runtime_endpoints": required_runtime_endpoints,
            "buyer_missing_artifacts": [
                "named buyer signer",
                "budget owner and purchase order",
                "buyer DPA or privacy acceptance",
                "production telemetry",
                "third-party security attestation",
            ],
            "concrete_blockers": concrete_blockers,
            "due_diligence_status_rules": [
                {
                    "due_diligence_status": "commercial_due_diligence_ready",
                    "rule": "all diligence sections are ready and no buyer authority, production, or third-party evidence remains open",
                },
                {
                    "due_diligence_status": "commercial_due_diligence_ready_with_warnings",
                    "rule": "repo-local diligence room evidence is ready while buyer authority, production telemetry, or external attestations remain explicit warnings",
                },
                {
                    "due_diligence_status": "commercial_due_diligence_blocked",
                    "rule": "security failure, API contract regression, document mismatch, runtime defect, missing local diligence evidence, or Code Connect usage blocks buyer diligence",
                },
            ],
            "review_process_policy": purchase["review_process_policy"],
            "related_runtime_reports": {
                "commercial_purchase_approval_status": purchase["purchase_approval_status"],
                "commercial_proposal_status": proposal["proposal_status"],
                "commercial_completion_status": completion["completion_status"],
                "commercial_demo_status": demo["demo_status"],
                "buyer_acceptance_workflow_status": buyer_workflow["workflow_status"],
                "commercial_close_status": close["close_status"],
                "commercial_procurement_status": procurement["procurement_status"],
                "commercial_contract_status": contract["contract_status"],
                "commercial_value_status": value["value_status"],
                "commercial_security_attestation_status": security["security_attestation_status"],
                "commercial_onboarding_status": onboarding["onboarding_status"],
                "commercial_operations_status": operations["operations_status"],
                "analytics_measurement_status": analytics["measurement_status"],
            },
            "library_split_decision": purchase["library_split_decision"],
            "plugin_traceability": purchase["plugin_traceability"],
            "due_diligence_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_due_diligence_rooms/latest",
                "documentation": "docs/commercial_due_diligence_room.md",
            },
        }

    def commercial_investment_committee_memo_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return executive investment committee memo sections for the KRW 2B standard."""
        due_diligence = self.commercial_due_diligence_room_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        purchase = self.commercial_purchase_approval_packet_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        proposal = self.commercial_proposal_packet_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        completion = self.commercial_completion_scorecard_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        demo = self.commercial_demo_scenario_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        buyer_workflow = self.commercial_buyer_acceptance_workflow_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        close = self.commercial_close_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        procurement = self.commercial_procurement_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        contract = self.commercial_contract_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        value = self.commercial_value_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        security = self.commercial_security_attestation_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        onboarding = self.commercial_onboarding_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        operations = self.commercial_operations_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        analytics = self.analytics_snapshot(locale_bundles=locale_bundles)
        admin_state = self.admin_state()
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        def all_files(*paths: str) -> bool:
            return all(has_file(path) for path in paths)

        def section(
            section_name: str,
            label: str,
            reviewer: str,
            sources: list[str],
            runtime_endpoints: list[str],
            evidence_type: str,
            completion_state: str,
            evidence: str,
            committee_question: str,
            next_action: str,
        ) -> dict[str, Any]:
            require_object_name(section_name, "commercial_investment_committee.section_name")
            if completion_state not in {"ready", "warning", "blocked"}:  # pragma: no cover
                raise ValueError("commercial investment committee section state must be ready, warning, or blocked")
            return {
                "section_name": section_name,
                "label": label,
                "reviewer": reviewer,
                "sources": sources,
                "runtime_endpoints": runtime_endpoints,
                "evidence_type": evidence_type,
                "completion_state": completion_state,
                "evidence": evidence,
                "committee_question": committee_question,
                "next_action": next_action,
            }

        concrete_blockers = list(
            dict.fromkeys(
                due_diligence["concrete_blockers"]
                + purchase["concrete_blockers"]
                + proposal["concrete_blockers"]
                + completion["concrete_blockers"]
                + demo["concrete_blockers"]
                + buyer_workflow["concrete_blockers"]
            )
        )
        local_runtime_state = (
            "blocked"
            if due_diligence["due_diligence_status"] == "commercial_due_diligence_blocked"
            or purchase["purchase_approval_status"] == "commercial_purchase_approval_blocked"
            or proposal["proposal_status"] == "commercial_proposal_blocked"
            or completion["completion_status"] == "commercial_completion_blocked"
            or demo["demo_status"] == "commercial_demo_blocked"
            or buyer_workflow["workflow_status"] == "buyer_acceptance_workflow_blocked"
            or concrete_blockers
            else "ready"
        )
        memo_sections = [
            section(
                "executive_recommendation",
                "Executive recommendation",
                "Investment committee chair",
                [
                    "docs/commercial_investment_committee_memo.md",
                    "docs/figma_artifacts.md",
                    "docs/superpowers/plans/2026-07-02-commercial-investment-committee-memo-runtime.md",
                ],
                ["/api/v1/commercial_investment_committee_memos/latest"],
                "repository_and_runtime_artifact",
                local_runtime_state
                if all_files(
                    "docs/commercial_investment_committee_memo.md",
                    "docs/figma_artifacts.md",
                    "docs/superpowers/plans/2026-07-02-commercial-investment-committee-memo-runtime.md",
                )
                else "blocked",
                "Investment committee memo, FigJam artifact record, and implementation plan are committed.",
                "Can the committee recommend the KRW 2B purchase path with explicit conditions?",
                "Use this memo as the executive decision cover artifact.",
            ),
            section(
                "diligence_room_ready",
                "Due diligence room ready",
                "Diligence owner",
                ["docs/commercial_due_diligence_room.md", "/api/v1/commercial_due_diligence_rooms/latest"],
                ["/api/v1/commercial_due_diligence_rooms/latest"],
                "repository_and_runtime_artifact",
                local_runtime_state if has_file("docs/commercial_due_diligence_room.md") else "blocked",
                f"commercial_due_diligence_status={due_diligence['due_diligence_status']}",
                "Can the memo point to a complete diligence room?",
                "Reference due diligence room sections instead of duplicating evidence.",
            ),
            section(
                "purchase_approval_ready",
                "Purchase approval ready",
                "Purchase sponsor",
                ["docs/commercial_purchase_approval_packet.md", "/api/v1/commercial_purchase_approval_packets/latest"],
                ["/api/v1/commercial_purchase_approval_packets/latest"],
                "repository_and_runtime_artifact",
                local_runtime_state if has_file("docs/commercial_purchase_approval_packet.md") else "blocked",
                f"commercial_purchase_approval_status={purchase['purchase_approval_status']}",
                "Can the committee see finance, procurement, legal, security, and implementation gates?",
                "Use the purchase approval packet as committee appendix A.",
            ),
            section(
                "financial_case",
                "Financial case",
                "Economic buyer",
                ["docs/commercial_value_readiness.md", "docs/analytics_spec.md", "/api/v1/analytics_snapshots/latest"],
                ["/api/v1/commercial_value_readiness/latest", "/api/v1/analytics_snapshots/latest"],
                "repository_and_runtime_artifact",
                "ready"
                if value["value_status"] != "commercial_value_blocked"
                and analytics["measurement_status"] == "local_runtime_snapshot"
                and all_files("docs/commercial_value_readiness.md", "docs/analytics_spec.md")
                else "blocked",
                f"commercial_value_status={value['value_status']}; analytics_measurement_status={analytics['measurement_status']}",
                "Does the memo separate measured local evidence from buyer ROI assumptions?",
                "Attach buyer ROI model only after buyer discovery supplies it.",
            ),
            section(
                "risk_and_security_summary",
                "Risk and security summary",
                "Security reviewer",
                ["SECURITY.md", "docs/commercial_security_attestation.md", "/api/v1/commercial_security_attestations/latest"],
                ["/api/v1/commercial_security_attestations/latest"],
                "repository_and_runtime_artifact",
                "ready"
                if security["security_attestation_status"] != "commercial_security_attestation_blocked"
                and all_files("SECURITY.md", "docs/commercial_security_attestation.md")
                else "blocked",
                f"commercial_security_attestation_status={security['security_attestation_status']}",
                "Are security risks explicit without claiming external certification?",
                "Keep third-party attestation outside measured local evidence.",
            ),
            section(
                "commercial_terms_summary",
                "Commercial terms summary",
                "Legal and procurement reviewers",
                [
                    "docs/commercial_contract_readiness.md",
                    "docs/commercial_procurement_readiness.md",
                    "docs/commercial_close_readiness.md",
                ],
                [
                    "/api/v1/commercial_contract_readiness/latest",
                    "/api/v1/commercial_procurement_readiness/latest",
                    "/api/v1/commercial_close_readiness/latest",
                ],
                "repository_and_runtime_artifact",
                "ready"
                if contract["contract_status"] != "commercial_contract_blocked"
                and procurement["procurement_status"] != "commercial_procurement_blocked"
                and close["close_status"] != "commercial_close_blocked"
                and all_files(
                    "docs/commercial_contract_readiness.md",
                    "docs/commercial_procurement_readiness.md",
                    "docs/commercial_close_readiness.md",
                )
                else "blocked",
                (
                    f"commercial_contract_status={contract['contract_status']}; "
                    f"commercial_procurement_status={procurement['procurement_status']}; "
                    f"commercial_close_status={close['close_status']}"
                ),
                "Can legal and procurement conditions be approved or tracked?",
                "Attach order-form details only after buyer legal review.",
            ),
            section(
                "implementation_readiness_summary",
                "Implementation readiness summary",
                "Implementation owner",
                ["docs/commercial_onboarding_readiness.md", "docs/commercial_operations_readiness.md"],
                ["/api/v1/commercial_onboarding_readiness/latest", "/api/v1/commercial_operations_readiness/latest"],
                "repository_and_runtime_artifact",
                "ready"
                if onboarding["onboarding_status"] != "commercial_onboarding_blocked"
                and operations["operations_status"] != "commercial_operations_blocked"
                and all_files("docs/commercial_onboarding_readiness.md", "docs/commercial_operations_readiness.md")
                else "blocked",
                f"commercial_onboarding_status={onboarding['onboarding_status']}; commercial_operations_status={operations['operations_status']}",
                "Can implementation start after buyer environment details are supplied?",
                "Convert buyer environment details into the paid onboarding plan.",
            ),
            section(
                "design_and_figma_review",
                "Design and Figma review",
                "Product design reviewer",
                ["docs/figma_artifacts.md", "docs/commercial_investment_committee_memo.md"],
                ["/api/v1/commercial_investment_committee_memos/latest"],
                "repository_and_runtime_artifact",
                "ready" if all_files("docs/figma_artifacts.md", "docs/commercial_investment_committee_memo.md") else "blocked",
                "FigJam memo flow and Product Design scope are recorded without Code Connect.",
                "Can stakeholders inspect the memo flow in FigJam and runtime JSON?",
                "Keep Figma Code Connect out of the committee workflow.",
            ),
            section(
                "buyer_final_authority",
                "Buyer final authority",
                "Buyer sponsor",
                ["executive sponsor approval", "named signer", "budget owner", "purchase order"],
                [],
                "proposed_until_buyer_specific",
                "warning",
                "Executive sponsor approval, named signer, budget owner, and purchase order require buyer authority.",
                "Can the buyer approve the final KRW 2B purchase authority?",
                "Collect final buyer authority artifacts or explicit waiver.",
            ),
            section(
                "production_external_evidence",
                "Production and external evidence",
                "Production and security owners",
                ["production telemetry", "third-party security attestation", "hosted scan evidence"],
                [],
                "proposed_until_buyer_specific",
                "warning",
                "Production telemetry, third-party security attestation, and hosted scan evidence are external inputs.",
                "Can the committee approve with production and external evidence still tracked as conditions?",
                "Collect hosted evidence after environment selection.",
            ),
        ]
        state_counts = Counter(item["completion_state"] for item in memo_sections)
        blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
        warning_count = state_counts.get("warning", 0)
        if blocked_count:
            investment_committee_status = "commercial_investment_committee_blocked"
            recommendation_status = "do_not_recommend_until_blockers_cleared"
        elif warning_count:
            investment_committee_status = "commercial_investment_committee_ready_with_warnings"
            recommendation_status = "recommend_with_buyer_conditions"
        else:  # pragma: no cover - unreachable while external-evidence warning sections remain literal
            investment_committee_status = "commercial_investment_committee_ready"  # pragma: no cover
            recommendation_status = "recommend"  # pragma: no cover
        required_runtime_endpoints = list(
            dict.fromkeys(
                endpoint
                for item in memo_sections
                for endpoint in item["runtime_endpoints"]
                if endpoint.startswith("/")
            )
        )

        return {
            "investment_committee_status": investment_committee_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_commercial_investment_committee_memo",
            "source_note": (
                "Commercial investment committee memo packages repo-local due diligence, purchase approval, "
                "proposal, runtime, admin trace, security, contract, value, onboarding, operations, analytics, "
                "Figma, review-policy, and packaging evidence for KRW 2,000,000,000 executive review; it is "
                "not a valuation guarantee, purchase commitment, signed order, legal opinion, production "
                "compliance certificate, third-party attestation, or revenue proof."
            ),
            "executive_recommendation": {
                "title": "KRW 2B commercial investment committee memo",
                "recommendation_status": recommendation_status,
                "recommendation": (
                    "Recommend committee review with buyer authority, production telemetry, and external "
                    "attestation conditions tracked separately from measured local product evidence."
                    if recommendation_status == "recommend_with_buyer_conditions"
                    else "Do not recommend until concrete blockers are cleared."
                    if recommendation_status == "do_not_recommend_until_blockers_cleared"
                    else "Recommend committee approval with no open local or buyer-specific conditions."
                ),
                "audience": [
                    "Investment committee chair",
                    "Economic buyer",
                    "Finance owner",
                    "Procurement owner",
                    "Legal owner",
                    "Security owner",
                    "Implementation owner",
                ],
            },
            "memo_summary": {
                "section_count": len(memo_sections),
                "ready_count": state_counts.get("ready", 0),
                "warning_count": warning_count,
                "blocked_count": blocked_count,
                "endpoint_count": len(required_runtime_endpoints),
                "review_process_is_blocker": due_diligence["review_process_policy"]["is_blocker"],
                "code_connect_used": False,
            },
            "memo_sections": memo_sections,
            "required_runtime_endpoints": required_runtime_endpoints,
            "committee_decision_questions": [
                "Is the product evidence sufficient for KRW 2B buyer review?",
                "Are buyer authority documents named and tracked?",
                "Are production and third-party evidence gaps explicit warnings?",
                "Is any concrete blocker present?",
            ],
            "buyer_missing_artifacts": due_diligence["buyer_missing_artifacts"]
            + ["executive sponsor approval", "investment committee sign-off"],
            "concrete_blockers": concrete_blockers,
            "investment_committee_status_rules": [
                {
                    "investment_committee_status": "commercial_investment_committee_ready",
                    "rule": "all memo sections are ready and no buyer authority, production, or third-party evidence remains open",
                },
                {
                    "investment_committee_status": "commercial_investment_committee_ready_with_warnings",
                    "rule": "repo-local committee memo evidence is ready while buyer authority, production telemetry, or external attestations remain explicit warnings",
                },
                {
                    "investment_committee_status": "commercial_investment_committee_blocked",
                    "rule": "security failure, API contract regression, document mismatch, runtime defect, missing local memo evidence, or Code Connect usage blocks committee recommendation",
                },
            ],
            "review_process_policy": due_diligence["review_process_policy"],
            "related_runtime_reports": {
                "commercial_due_diligence_status": due_diligence["due_diligence_status"],
                "commercial_purchase_approval_status": purchase["purchase_approval_status"],
                "commercial_proposal_status": proposal["proposal_status"],
                "commercial_completion_status": completion["completion_status"],
                "commercial_demo_status": demo["demo_status"],
                "buyer_acceptance_workflow_status": buyer_workflow["workflow_status"],
                "commercial_close_status": close["close_status"],
                "commercial_procurement_status": procurement["procurement_status"],
                "commercial_contract_status": contract["contract_status"],
                "commercial_value_status": value["value_status"],
                "commercial_security_attestation_status": security["security_attestation_status"],
                "commercial_onboarding_status": onboarding["onboarding_status"],
                "commercial_operations_status": operations["operations_status"],
                "analytics_measurement_status": analytics["measurement_status"],
                "admin_agent_count": len(admin_state["agents"]),
            },
            "library_split_decision": due_diligence["library_split_decision"],
            "plugin_traceability": due_diligence["plugin_traceability"],
            "committee_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_investment_committee_memos/latest",
                "documentation": "docs/commercial_investment_committee_memo.md",
            },
        }

    def admin_state(
        self,
        owner_id: str | None = None,
        *,
        role: str | None = None,
        purpose: str | None = None,
    ) -> dict[str, Any]:
        """Build the admin console state payload from agents, policy, and audit data."""
        agent_page_size = max(1, len(self.candidates))
        return {
            "agents": self.list_agents(page_size=agent_page_size),
            "policy": {
                **self.policy.as_dict(),
                "roles": list(self.ROLE_TAGS),
            },
            "routing_evidence": {
                "transport": self._group_router.snapshot(),
                "quality": self._quality_router.snapshot(),
            },
            "recent_workflow_runs": [
                self._shorten_run(run)
                for run in self.list_recent_runs(
                    page_size=max(1, len(self._run_order)), owner_id=owner_id
                )
            ],
            "recent_audit_events": self.list_recent_audit_events(role=role, purpose=purpose),
            "recent_authorization_decisions": self.list_recent_authorization_decisions(),
            "spend": self.spend_analytics(),
        }

    def _shorten_run(self, run: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover
        return {
            "workflow_run_id": run["workflow_run_id"],
            "mode": run["mode"],
            "policy_mode": run["policy_mode"],
            "created_at": run["created_at"],
        }

    def _is_trace_complete(self, run: dict[str, Any]) -> bool:
        trace = run.get("trace", [])
        if not trace:
            return False
        for step in trace:
            if not all(key in step for key in ("id", "role", "agent_id", "subtask", "access", "output")):
                return False
            if not isinstance(step["access"], list) or step["output"] is None:
                return False
        verification = run.get("verification") or {}
        return bool(run.get("answer") and "accepted" in verification and "reason" in verification)

    def _is_policy_safe_run(self, run: dict[str, Any]) -> bool:
        if run["mode"] == "conduct" and run["policy_snapshot"].get("verifier_required") and not run.get("verification"):
            return False
        return self._provider_exclusion_miss_count(run) == 0

    def _provider_exclusion_miss_count(self, run: dict[str, Any]) -> int:
        misses = 0
        for step in run.get("trace", []):
            try:
                agent = self._agent(step["agent_id"])
            except KeyError:
                misses += 1
                continue
            if step["role"] in agent.provider_exclusions:
                misses += 1
        return misses

    def _locale_key_parity(self, locale_bundles: dict[str, dict[str, str]]) -> dict[str, Any]:
        english = locale_bundles.get("en", {})
        other_locale_codes = sorted(code for code in locale_bundles if code != "en")
        denominator = len(english) * len(other_locale_codes)
        missing = [
            f"{locale_code}.{key}"
            for locale_code in other_locale_codes
            for key in sorted(english)
            if not locale_bundles[locale_code].get(key)
        ]
        numerator = denominator - len(missing)
        return {
            "numerator": numerator,
            "denominator": denominator,
            "value_percent": self._percent(numerator, denominator),
            "missing_keys": missing,
        }

    def _percent(self, numerator: int, denominator: int) -> float | None:
        if denominator == 0:
            return None
        return round((numerator / denominator) * 100, 2)

    def _criterion(
        self,
        criterion_name: str,
        label: str,
        status: str,
        evidence: str,
        remediation: str,
    ) -> dict[str, str]:
        require_object_name(criterion_name, "sales_readiness.criterion_name")
        if status not in {"pass", "warn", "fail"}:  # pragma: no cover
            raise ValueError("sales readiness status must be pass, warn, or fail")
        return {
            "criterion_name": criterion_name,
            "status": status,
            "label": label,
            "evidence": evidence,
            "remediation": remediation,
        }

    def _buyer_evidence_item(
        self,
        item_name: str,
        label: str,
        reviewer: str,
        sources: list[str],
        evidence_type: str,
        completion_state: str,
        evidence: str,
        next_action: str,
    ) -> dict[str, Any]:
        require_object_name(item_name, "buyer_evidence_manifest.item_name")
        if evidence_type not in {
            "measured_local",
            "repository_artifact",
            "figma_artifact",
            "proposed_until_production",
            "proposed_until_buyer_specific",
        }:  # pragma: no cover
            raise ValueError("buyer evidence type is invalid")
        if completion_state not in {"ready", "warning", "blocked"}:  # pragma: no cover
            raise ValueError("buyer evidence completion state must be ready, warning, or blocked")
        return {
            "item_name": item_name,
            "label": label,
            "reviewer": reviewer,
            "sources": sources,
            "evidence_type": evidence_type,
            "completion_state": completion_state,
            "evidence": evidence,
            "next_action": next_action,
        }

    def _buyer_manifest_summary(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        completion_counts = Counter(item["completion_state"] for item in items)
        evidence_counts = Counter(item["evidence_type"] for item in items)
        return {
            "total_items": len(items),
            "by_completion_state": {
                "ready": completion_counts.get("ready", 0),
                "warning": completion_counts.get("warning", 0),
                "blocked": completion_counts.get("blocked", 0),
            },
            "by_evidence_type": {
                "measured_local": evidence_counts.get("measured_local", 0),
                "repository_artifact": evidence_counts.get("repository_artifact", 0),
                "figma_artifact": evidence_counts.get("figma_artifact", 0),
                "proposed_until_production": evidence_counts.get("proposed_until_production", 0),
                "proposed_until_buyer_specific": evidence_counts.get("proposed_until_buyer_specific", 0),
            },
        }

    def _security_posture_criterion(self, security_profile: dict[str, Any]) -> dict[str, str]:
        auth_mode = security_profile.get("auth_mode", "loopback_no_auth")
        issues: list[str] = []
        warnings: list[str] = []
        if auth_mode == "single_token":
            warnings.append("single bearer token shared by admin and inference scopes")
        elif auth_mode not in {"split_token", "external_bearer_verifier"}:
            issues.append("no bearer token configured outside loopback-only development")
        if security_profile.get("allow_public_bind"):
            issues.append("public bind is enabled")
        if security_profile.get("expose_trace_by_default"):
            issues.append("trace exposure is enabled by default")
        if int(security_profile.get("rate_limit_requests") or 0) <= 0:
            issues.append("request rate limiting is disabled")
        if int(security_profile.get("max_concurrent_runs") or 0) <= 0:
            issues.append("run concurrency limiting is disabled")

        if issues:
            status = "fail"
            evidence = "; ".join(issues)
            remediation = "Require bearer auth, private bind defaults, hidden traces, rate limits, and run limits."
        elif warnings:
            status = "warn"
            evidence = "; ".join(warnings)
            remediation = "For enterprise pilots, split admin and inference tokens before customer evaluation."
        else:
            status = "pass"
            auth_evidence = (
                "external bearer verifier"
                if auth_mode == "external_bearer_verifier"
                else "split tokens"
            )
            evidence = f"{auth_evidence}, private bind default, hidden traces, rate limits, and run limits are configured"
            remediation = "Keep these controls enabled for customer-facing pilots."

        return self._criterion("security_posture", "Security posture", status, evidence, remediation)

    def _locale_readiness_criterion(self, analytics: dict[str, Any]) -> dict[str, str]:
        locale_metric = next(
            metric for metric in analytics["guardrails"] if metric["metric_name"] == "locale_key_parity"
        )
        missing = locale_metric.get("missing_keys", [])
        parity = locale_metric.get("value_percent")
        if parity == 100.0:
            status = "pass"
            evidence = "English and Korean admin locale keys are aligned"
            remediation = "Keep locale parity tests updated when adding operator copy."
        else:
            status = "warn" if missing else "fail"
            evidence = f"{parity}% locale key parity; missing keys: {', '.join(missing) or 'locale bundles absent'}"
            remediation = "Fill missing Korean and English operator labels before customer review."
        return self._criterion("locale_readiness", "Locale readiness", status, evidence, remediation)

    def _provider_egress_criterion(self) -> dict[str, str]:
        unsafe = []
        remote = []
        for agent in self.agents:
            if agent.base_url.startswith("mock://"):
                continue
            if _is_local_provider_url(agent.base_url):
                continue
            remote.append(agent.id)
            parsed = urlparse(agent.base_url)
            if parsed.scheme != "https" or not agent.credential_name:
                unsafe.append(agent.id)
        if unsafe:
            status = "fail"
            evidence = f"unsafe provider egress config for agents: {', '.join(sorted(unsafe))}"
            remediation = "Use https provider endpoints with a named KV credential before enabling remote egress."
        else:
            status = "pass"
            evidence = (
                "mock providers only"
                if not remote
                else f"{len(remote)} remote providers use https and a named KV credential"
            )
            remediation = "Keep provider allow-list enforcement enabled for non-mock providers."
        return self._criterion("provider_egress_safety", "Provider egress safety", status, evidence, remediation)

    def _criteria_by_name(self, criteria: list[dict[str, str]]) -> dict[str, dict[str, str]]:
        return {row["criterion_name"]: row for row in criteria}

    def _metrics_by_name(self, metrics: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {row["metric_name"]: row for row in metrics}

    def _commercial_documentation_profile(self) -> dict[str, Any]:
        root = Path(__file__).resolve().parents[1]
        required_documents = [
            "README.md",
            "SECURITY.md",
            "docs/product_planning.md",
            "docs/rest_api_design.md",
            "docs/analytics_spec.md",
            "docs/commercial_readiness.md",
        ]
        missing_documents = [
            document_path
            for document_path in required_documents
            if not (root / document_path).is_file()
        ]
        return {
            "required_documents": required_documents,
            "missing_documents": missing_documents,
            "present_count": len(required_documents) - len(missing_documents),
            "required_count": len(required_documents),
            "has_security_policy": (root / "SECURITY.md").is_file(),
            "source": "repository documentation files",
        }

    def _criteria_summary(self, criteria: list[dict[str, str]]) -> dict[str, int]:
        counts = Counter(row["status"] for row in criteria)
        return {
            "pass": counts.get("pass", 0),
            "warn": counts.get("warn", 0),
            "fail": counts.get("fail", 0),
        }


def redact_text(text: str) -> str:
    """Mask credential shapes (API keys, tokens, passwords, bearer headers) from traces.

    Does not mask PII (email addresses, names, etc.): per governance-risk-compliance policy,
    PII is protected by purpose-limited authorization, encryption, and audit logging, not by
    destroying it in every response -- blanket PII masking here broke every downstream
    consumer that needs the real content (e.g. an email client rendering actual addresses).
    """
    redacted = text
    for pattern in SECRET_PATTERNS:
        if pattern.pattern.lower().startswith("(?i)(api"):
            redacted = pattern.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", redacted)
        else:
            redacted = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]", redacted)
    return redacted


def redact_value(value: Any) -> Any:
    """Recursively redact string values while preserving response shape."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    return value

def _freeze_report_cache_value(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(
            sorted(
                (str(key), _freeze_report_cache_value(item))
                for key, item in value.items()
            )
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_report_cache_value(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted(_freeze_report_cache_value(item) for item in value))
    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value


def _cached_commercial_report(method: Any) -> Any:
    @wraps(method)
    def wrapper(self: TaskOrchestrator, *args: Any, **kwargs: Any) -> dict[str, Any]:
        cache = _COMMERCIAL_REPORT_CACHE.get()
        token = None
        if cache is None:
            cache = {}
            token = _COMMERCIAL_REPORT_CACHE.set(cache)
        try:
            key = (
                method.__name__,
                _freeze_report_cache_value(args),
                _freeze_report_cache_value(kwargs),
            )
            if key not in cache:
                cache[key] = method(self, *args, **kwargs)
            return cache[key]
        finally:
            if token is not None:
                _COMMERCIAL_REPORT_CACHE.reset(token)

    return wrapper


for _commercial_report_name, _commercial_report_method in list(TaskOrchestrator.__dict__.items()):
    if (
        _commercial_report_name.startswith("commercial_")
        and _commercial_report_name.endswith("_report")
        and callable(_commercial_report_method)
    ):
        setattr(
            TaskOrchestrator,
            _commercial_report_name,
            _cached_commercial_report(_commercial_report_method),
        )


def _pareto_front(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Configs not dominated on (quality up, cost down)."""
    measured = [row for row in results if row.get("cost_usd") is not None]
    front: list[dict[str, Any]] = []
    for a in measured:
        dominated = any(
            b is not a
            and b["quality"] >= a["quality"]
            and b["cost_usd"] <= a["cost_usd"]
            and (b["quality"] > a["quality"] or b["cost_usd"] < a["cost_usd"])
            for b in measured
        )
        if not dominated:
            front.append(a)
    return front


def _recommend_config(results: list[dict[str, Any]], cost_budget_usd: float | None) -> dict[str, Any] | None:
    measured = [row for row in results if row.get("cost_usd") is not None]
    if not measured:
        return None
    if cost_budget_usd is not None:
        affordable = [r for r in measured if r["cost_usd"] <= cost_budget_usd]
        if affordable:
            best = max(affordable, key=lambda r: (r["quality"], -r["cost_usd"]))
            reason = "highest quality within cost budget"
        else:
            best = min(measured, key=lambda r: r["cost_usd"])
            reason = "no config within budget; cheapest instead"
    else:
        # Maximize performance first, minimize cost as the tie-break (cheapest among the
        # best-quality configs) — the honest reading of "max quality while min cost".
        best = max(measured, key=lambda r: (r["quality"], -r["cost_usd"]))
        reason = "highest quality; cheapest among equal-quality configs"
    return {"name": best["name"], "quality": best["quality"], "cost_usd": best["cost_usd"], "reason": reason}


def _optimizer_usage_snapshot(orchestrator: Any, evaluation_index: int) -> dict[str, Any]:
    """Capture cumulative engine totals without prompts, configuration, or model identifiers."""
    totals = orchestrator.spend_analytics()["totals"]
    return {
        "evaluation_index": evaluation_index,
        "scope": "cumulative_engine_snapshot",
        "snapshot_status": "available",
        "totals": {key: totals.get(key) for key in (
            "run_count", "prompt_tokens", "output_tokens", "prompt_tokens_source", "cost_usd", "currency"
        )} | {"cost_usd": totals["cost_usd"]},
    }


def _score_config(orchestrator: Any, tasks: list[dict[str, Any]], quality_fn: Any, mode: str, use_batch: bool,
                  usage_receipts: list[dict[str, Any]]) -> tuple[float, list[float]]:
    """Return the existing mean and ordered task scores without changing selection policy."""
    try:
        if use_batch and mode == "route":
            records = orchestrator.batch_route([task["prompt"] for task in tasks])
            if len(records) != len(tasks):
                raise ValueError("batch result count must match task count")
            scores = [float(quality_fn(task, record["answer"] or "")) for task, record in zip(tasks, records)]
        else:
            scores = [
                float(quality_fn(task, orchestrator.run([{"role": "user", "content": task["prompt"]}], mode=mode)["answer"]))
                for task in tasks
            ]
        if any(not math.isfinite(score) or not 0.0 <= score <= 1.0 for score in scores):
            raise ValueError("quality scores must be finite and in [0, 1]")
        usage_receipts.append(_optimizer_usage_snapshot(orchestrator, len(usage_receipts)))
        return (sum(scores) / len(scores) if scores else 0.0), scores
    except Exception as evaluation_error:
        try:
            failed_usage = _optimizer_usage_snapshot(orchestrator, len(usage_receipts))
        except Exception:
            failed_usage = {"evaluation_index": len(usage_receipts), "scope": "cumulative_engine_snapshot",
                            "snapshot_status": "unavailable", "totals": None}
        completed_usage = tuple([*usage_receipts, failed_usage])
        vars(evaluation_error)["optimizer_usage"] = completed_usage
        raise


def _require_released_optimizer_selection_contract() -> None:
    """Fail closed until fast-mlsirm releases candidate-selection authority."""
    raise RuntimeError(
        "optimizer selection requires a released fast-mlsirm candidate-selection contract"
    )


def optimize_orchestration(
    candidates: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    quality_fn: Any,
    cost_budget_usd: float | None = None,
    use_batch: bool = False,
) -> dict[str, Any]:
    """Search orchestration configs for maximum quality at minimum cost (the Fugu tradeoff).

    - ``candidates``: ``[{"name": str, "orchestrator": TaskOrchestrator, "mode": str}]``.
      Each orchestrator should be fresh so its spend reflects only this search.
    - ``tasks``: ``[{"prompt": str, ...}]`` — the eval set; each task + the produced
      answer is passed to ``quality_fn``.
    - ``quality_fn(task, answer_text) -> float`` in [0, 1] — the caller's real quality
      signal (e.g. checkable answers or a judge). This function does not fabricate quality.
    - ``cost_budget_usd``: optional cap. Recommendation = highest-quality config within
      budget, else the cheapest; with no budget, highest quality then cheapest.

    Returns per-config measured quality + real cost, the Pareto front, and a recommendation.
    Each result also retains ``score_observations`` in input-task order, before
    mean rounding. This descriptive evidence does not establish calibration or
    applicability of the existing selection policy.
    """
    _require_released_optimizer_selection_contract()
    results: list[dict[str, Any]] = []
    usage_receipts: list[dict[str, Any]] = []
    for candidate in candidates:
        orchestrator = candidate["orchestrator"]
        mode = candidate.get("mode", "auto")
        quality, score_observations = _score_config(orchestrator, tasks, quality_fn, mode, use_batch, usage_receipts)
        cost = usage_receipts[-1]["totals"]["cost_usd"]
        results.append({
            "name": candidate["name"],
            "mode": mode,
            "quality": round(quality, 4),
            "score_observations": score_observations,
            "cost_usd": round(cost, 6) if cost is not None else None,
            "quality_per_usd": (
                round(quality / cost, 2) if cost is not None and cost > 0 else None
            ),
            "task_count": len(tasks),
        })

    return {
        "objective": "maximize quality, minimize cost",
        "cost_budget_usd": cost_budget_usd,
        "results": sorted(
            results,
            key=lambda r: (
                -r["quality"],
                r["cost_usd"] is None,
                r["cost_usd"] if r["cost_usd"] is not None else float("inf"),
            ),
        ),
        "pareto_front": [r["name"] for r in _pareto_front(results)],
        "recommended": _recommend_config(results, cost_budget_usd),
    }


def evolve_orchestration(
    build_orchestrator: Any,
    search_space: dict[str, list[Any]],
    tasks: list[dict[str, Any]],
    quality_fn: Any,
    generations: int = 4,
    population: int = 6,
    cost_budget_usd: float | None = None,
    seed: int = 7,
    use_batch: bool = False,
) -> dict[str, Any]:
    """Evolve orchestration configs toward max quality at min cost (TRINITY-style search).

    For search spaces too large to enumerate: a seeded mutation+selection loop over
    ``search_space`` (param -> candidate values). ``build_orchestrator(config)`` returns a
    fresh TaskOrchestrator for a config (the caller owns provider wiring); each config is
    evaluated ONCE and cached — critical when evaluation costs real API money.

    Fitness maximizes measured quality, then minimizes measured cost; configs whose cost
    exceeds ``cost_budget_usd`` rank below all affordable ones. Quality comes from the
    caller's ``quality_fn(task, answer) -> [0,1]`` — never fabricated.
    Per-config ``score_observations`` retain input-task order before mean rounding.
    Their availability does not qualify the existing fitness policy psychometrically.
    """
    _require_released_optimizer_selection_contract()
    rng = random.Random(seed)
    params = sorted(search_space)

    def random_config() -> dict[str, Any]:
        return {p: rng.choice(search_space[p]) for p in params}

    def mutate(config: dict[str, Any]) -> dict[str, Any]:
        child = dict(config)
        gene = rng.choice(params)
        choices = [v for v in search_space[gene] if v != config[gene]] or search_space[gene]
        child[gene] = rng.choice(choices)
        return child

    def key(config: dict[str, Any]) -> str:
        return json.dumps({p: config[p] for p in params}, sort_keys=True, ensure_ascii=False)

    evaluated: dict[str, dict[str, Any]] = {}
    usage_receipts: list[dict[str, Any]] = []

    def evaluate(config: dict[str, Any]) -> dict[str, Any]:
        config_key = key(config)
        if config_key in evaluated:
            return evaluated[config_key]
        orchestrator = build_orchestrator(config)
        mode = config.get("mode", "auto")
        quality, score_observations = _score_config(orchestrator, tasks, quality_fn, mode, use_batch, usage_receipts)
        cost = usage_receipts[-1]["totals"]["cost_usd"]
        result = {
            "name": config_key,
            "config": dict(config),
            "quality": round(quality, 4),
            "score_observations": score_observations,
            "cost_usd": round(cost, 6) if cost is not None else None,
            "quality_per_usd": (
                round(quality / cost, 2) if cost is not None and cost > 0 else None
            ),
            "task_count": len(tasks),
        }
        evaluated[config_key] = result
        return result

    def fitness(row: dict[str, Any]) -> tuple[int, float, float]:
        if row["cost_usd"] is None:
            return (0, row["quality"], float("-inf"))
        affordable = 1 if cost_budget_usd is None or row["cost_usd"] <= cost_budget_usd else 0
        return (affordable, row["quality"], -row["cost_usd"])

    # Seed population (dedup keys so a tiny space doesn't waste evaluations).
    pool: list[dict[str, Any]] = []
    seen: set[str] = set()
    while len(pool) < population and len(seen) < min(population * 4, _space_size(search_space)):
        config = random_config()
        if key(config) not in seen:
            seen.add(key(config))
            pool.append(config)

    history: list[dict[str, Any]] = []
    for generation in range(generations):
        rows = [evaluate(config) for config in pool]
        rows.sort(key=fitness, reverse=True)
        survivors = rows[: max(1, len(rows) // 2)]
        history.append({
            "generation": generation,
            "best": {"config": survivors[0]["config"], "quality": survivors[0]["quality"], "cost_usd": survivors[0]["cost_usd"]},
            "evaluated_total": len(evaluated),
        })
        pool = [dict(row["config"]) for row in survivors]
        while len(pool) < population:
            pool.append(mutate(rng.choice(survivors)["config"]))

    results = sorted(evaluated.values(), key=fitness, reverse=True)
    return {
        "objective": "maximize quality, minimize cost (evolutionary search)",
        "cost_budget_usd": cost_budget_usd,
        "generations": generations,
        "evaluations": len(evaluated),
        "space_size": _space_size(search_space),
        "results": results,
        "pareto_front": [row["name"] for row in _pareto_front(results)],
        "recommended": _recommend_config(results, cost_budget_usd),
        "history": history,
    }


def _space_size(search_space: dict[str, list[Any]]) -> int:
    size = 1
    for values in search_space.values():
        size *= max(1, len(values))
    return size


def chat_completion_response(
    result: dict[str, Any],
    model: str = "contextual-orchestrator",
    include_trace: bool = False,
    usage: dict[str, int] | None = None,
    prompt_count_source: str | None = None,
    shared_context_budget: dict[str, Any] | None = None,
) -> dict[str, Any]:  # pragma: no cover
    """Wrap orchestration output in an OpenAI-compatible chat completion response.

    ``usage`` carries measured token counts. Absence remains explicit and null.
    ``prompt_count_source`` records provenance (e.g. ``"provenance_exact"``)
    only when an authoritative prompt-message token count was obtained for
    this exact served request/route revision; it is omitted rather than
    fabricated when no such count exists. ``shared_context_budget`` records
    the ``token_counting.shared_context_output_budget`` evidence
    (``context_window``/``prompt_tokens``/``output_ceiling``/``source``) for
    the agent that actually served this request, next to
    ``prompt_count_source``; it is omitted when no such decision was made.
    """
    orchestration = {
        "workflow_run_id": result.get("workflow_run_id"),
        "mode": result["mode"],
        "verification": result.get("verification"),
        "channel": result.get("channel"),
        "routing_reason": result.get("routing_reason"),
        "usage_record_id": result.get("usage_record_id"),
        "cost": result.get("cost"),
        "tool_loop_route": result.get("tool_loop_route"),
        "tool_loop_agent_id": result.get("tool_loop_agent_id"),
        "requested_output_tokens": result.get("requested_output_tokens"),
        "effective_output_tokens": result.get("effective_output_tokens"),
        "output_budget_clamped": result.get("output_budget_clamped"),
        "prompt_token_lower_bound": result.get("prompt_token_lower_bound"),
        "prompt_token_bound_source": result.get("prompt_token_bound_source"),
        "context_window_excluded": result.get("context_window_excluded") or None,
    }
    if include_trace:
        orchestration["trace"] = redact_value(result["trace"])
    message: dict[str, Any] = {"role": "assistant", "content": result["answer"]}
    tool_calls = result.get("tool_calls")
    if tool_calls:
        message["tool_calls"] = tool_calls
        if not result.get("answer"):
            message["content"] = None
    finish_reason = result.get("finish_reason") or ("tool_calls" if tool_calls else "stop")
    response: dict[str, Any] = {
        "id": _new_chat_completion_id(),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage,
        "usage_measurement_status": "measured" if usage is not None else "unavailable",
        "orchestration": {key: value for key, value in orchestration.items() if value is not None},
    }
    if prompt_count_source is not None:
        response["prompt_count_source"] = prompt_count_source
    if shared_context_budget is not None:
        response["shared_context_budget"] = shared_context_budget
    return response


def text_completion_response(
    result: dict[str, Any],
    model: str = "contextual-orchestrator",
    usage: dict[str, int] | None = None,
) -> dict[str, Any]:  # pragma: no cover
    """Wrap orchestration output as OpenAI legacy ``text_completion`` (``/v1/completions``)."""
    return {
        "id": f"cmpl-{int(time.time() * 1000)}",
        "object": "text_completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "text": result["answer"],
                "logprobs": None,
                "finish_reason": "stop",
            }
        ],
        "usage": usage,
        "usage_measurement_status": "measured" if usage is not None else "unavailable",
    }


_STREAM_CHUNK_SIZE = 32


def chat_completion_chunks(
    result: dict[str, Any],
    model: str = "contextual-orchestrator",
    include_trace: bool = False,
    include_usage: bool = False,
) -> list[dict[str, Any]]:
    """Frame an orchestration result as OpenAI-compatible chat completion chunks.

    Only provider-reported usage may be emitted. Gateway estimates remain internal
    because presenting estimates as provider usage would violate the wire contract.
    """
    answer = result.get("answer", "")
    completion_id = _new_chat_completion_id()
    created = int(time.time())
    base = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
    }
    if include_usage:
        base["usage"] = None

    chunks: list[dict[str, Any]] = [
        {
            **base,
            "choices": [
                {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}
            ],
        }
    ]
    for offset in range(0, len(answer), _STREAM_CHUNK_SIZE):
        piece = answer[offset : offset + _STREAM_CHUNK_SIZE]
        chunks.append(
            {
                **base,
                "choices": [
                    {"index": 0, "delta": {"content": piece}, "finish_reason": None}
                ],
            }
        )
    tool_calls = result.get("tool_calls")
    if tool_calls:
        chunks.append(
            {
                **base,
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {"index": index, **call}
                                for index, call in enumerate(tool_calls)
                            ]
                        },
                        "finish_reason": None,
                    }
                ],
            }
        )

    orchestration = {
        "workflow_run_id": result.get("workflow_run_id"),
        "mode": result.get("mode"),
        "verification": result.get("verification"),
        "tool_loop_route": result.get("tool_loop_route"),
        "tool_loop_agent_id": result.get("tool_loop_agent_id"),
        "requested_output_tokens": result.get("requested_output_tokens"),
        "effective_output_tokens": result.get("effective_output_tokens"),
        "output_budget_clamped": result.get("output_budget_clamped"),
    }
    if include_trace and "trace" in result:
        orchestration["trace"] = redact_value(result["trace"])

    finish_reason = result.get("finish_reason") or (
        "tool_calls" if tool_calls else "stop"
    )
    final = {
        **base,
        "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
        "orchestration": {
            key: value for key, value in orchestration.items() if value is not None
        },
    }
    chunks.append(final)

    usage = result.get("usage")
    cost = result.get("cost")
    if include_usage:
        measured = (
            isinstance(cost, dict)
            and cost.get("measurement_status") == "measured"
            and isinstance(usage, dict)
        )
        chunks.append(
            {
                **base,
                "choices": [],
                "usage": usage if measured else None,
                "usage_measurement_status": "measured" if measured else "unavailable",
            }
        )
    return chunks


def _new_chat_completion_id() -> str:
    """Create a collision-resistant OpenAI-compatible completion identifier."""
    return f"chatcmpl-{uuid.uuid4().hex}"


def sse_stream_body(chunks: list[dict[str, Any]]) -> str:
    """Serialize chat completion chunks as a Server-Sent Events body terminated by ``[DONE]``."""
    frames = [f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n" for chunk in chunks]
    frames.append("data: [DONE]\n\n")
    return "".join(frames)
