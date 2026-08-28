"""Evidence-grade NVIDIA NIM model discovery and cost-quality benchmark harness.

This is the optional benchmark adapter demanded by the "[Product Gap]
Evidence-grade NVIDIA NIM model discovery and cost-quality benchmark" issue.
It is NOT part of the runtime request path: the gateway keeps its
provider-neutral, standard-library-only contract, and this module simply
reuses the same stdlib HTTP/KV seams to measure the repo's own policies
(``route_once`` vs ``conduct`` vs single-worker baselines) against a
dynamically discovered NIM catalog.

Design contract (mirrors the issue):

* **Dynamic catalog** — models come from the OpenAI-compatible
  ``GET /v1/models`` endpoint; nothing here hard-codes a model inventory.
* **All-modality capability probes** — every discovered model is probed,
  under bounded concurrency and a hard request budget, for every contract
  NIM can host: chat completions, legacy text completions, the Responses
  API, embeddings, image understanding (vision), video understanding,
  audio understanding (omni-style ``input_audio``), audio transcription,
  and audio speech synthesis. ``omni_capable`` is derived, never probed
  separately. Skipped probes always carry a machine-readable reason.
* **Fair comparison** — the same task manifest, scorers, call caps,
  workflow-depth cap (five), timeout, and output-token budget apply to all
  compared systems.
* **Honest cost accounting** — actual cost is recorded as ``0`` while the
  hosted catalog is free to the caller; hypothetical paid cost is computed
  only from an explicit versioned pricing scenario and is ``"unknown"``
  for any model the scenario does not price. The two never mix.
* **Fail closed** — a live run refuses to start without the KV-resolvable
  ``NVIDIA_NIM_API_KEY`` credential, complete provenance, and a request
  budget large enough for the planned evaluation. The secret is never
  accepted via argv and never serialized into artifacts.
* **Deterministic dry run** — ``--dry-run`` drives the entire pipeline
  against an in-process synthetic provider covering every modality class,
  so manifests, pricing assumptions, scorer registration, budgets, and
  output schemas are validated without any network egress.
"""

from __future__ import annotations

import argparse
import base64
import csv
import dataclasses
import hashlib
import io
import ipaddress
import json
import math
import os
import random
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .conventions import is_two_word_snake_case
from .credentials import NotConfigured, get_credential, register_credential
from .orchestrator import (
    ModelAgent,
    ModelClient,
    OrchestrationPolicy,
    TaskOrchestrator,
    estimate_tokens,
)

BENCHMARK_SCHEMA_VERSION = "1.0.0"
NIM_DEFAULT_ENDPOINT = "https://integrate.api.nvidia.com/v1"
NIM_CREDENTIAL_NAME = "NVIDIA_NIM_API_KEY"
DRY_RUN_PROVENANCE_PLACEHOLDER = "dry_run"
# Fixed epoch for deterministic dry-run artifacts (2026-01-01T00:00:00Z).
DRY_RUN_FIXED_UNIX_TIME = 1767225600.0
# Issue contract: Conductor/TRINITY-style deep paths are capped at five steps.
MAX_WORKFLOW_DEPTH = 5

# Transport seam: (method, url, headers, body_bytes_or_None) -> (status, body).
# Network-level failures raise URLError/TimeoutError/ConnectionError/socket.timeout.
ProviderTransport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]


class BenchmarkContractError(ValueError):
    """A manifest, pricing scenario, schema, or parameter violates the benchmark contract."""


class CatalogDiscoveryError(RuntimeError):
    """The provider model catalog could not be discovered or parsed completely."""


class BenchmarkAuthError(RuntimeError):
    """The provider rejected the benchmark credential; the run must fail closed."""


class BenchmarkBudgetError(RuntimeError):
    """The benchmark would exceed (or has exceeded) its hard request budget."""


class SecretLeakError(RuntimeError):
    """A serialized artifact contained the provider secret; writing is refused."""


# --------------------------------------------------------------------------
# Egress guard + default transport
# --------------------------------------------------------------------------


def require_public_https_endpoint(url: str) -> None:
    """Reject non-HTTPS endpoints and hosts resolving to non-public addresses.

    Mirrors the runtime ``ModelClient`` egress guard so the benchmark cannot be
    pointed at loopback/private/reserved infrastructure.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise BenchmarkContractError(f"benchmark endpoint must use https: {url!r}")
    for address in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM):
        ip_address = ipaddress.ip_address(address[4][0])
        if (
            ip_address.is_private
            or ip_address.is_loopback
            or ip_address.is_link_local
            or ip_address.is_multicast
            or ip_address.is_reserved
        ):
            raise BenchmarkContractError(f"benchmark endpoint resolves to a non-public address: {url!r}")


def build_default_transport(timeout_seconds: float) -> ProviderTransport:
    """Return the real HTTPS transport with per-host egress validation.

    HTTP error statuses are returned as ``(status, body)`` rather than raised so
    probe classification can inspect them; genuine network failures propagate.
    """
    ssl_context = ssl.create_default_context()
    validated_hosts: set[str] = set()

    def transport(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, bytes]:
        """Perform one provider HTTP round trip against a validated public host."""
        host_key = urllib.parse.urlparse(url).netloc
        if host_key not in validated_hosts:
            require_public_https_endpoint(url)
            validated_hosts.add(host_key)
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(  # nosec B310 - https-only, egress-validated above
                request, timeout=timeout_seconds, context=ssl_context
            ) as response:
                return int(response.status), response.read()
        except urllib.error.HTTPError as exc:
            error_body = exc.read() if exc.fp is not None else b""
            return int(exc.code), error_body

    return transport


# --------------------------------------------------------------------------
# Request budget (fail-closed hard cap)
# --------------------------------------------------------------------------


class RequestBudget:
    """Thread-safe hard cap on total provider requests for one benchmark run."""

    def __init__(self, max_total_requests: int) -> None:
        if max_total_requests < 1:
            raise BenchmarkContractError("max_total_requests must be a positive integer")
        self.max_total_requests = max_total_requests
        self._spent = 0
        self._lock = threading.Lock()

    def try_spend(self) -> bool:
        """Consume one request from the budget; ``False`` means exhausted (skip)."""
        with self._lock:
            if self._spent >= self.max_total_requests:
                return False
            self._spent += 1
            return True

    def spend_or_fail(self) -> None:
        """Consume one request or raise, for phases that must fail closed."""
        if not self.try_spend():
            raise BenchmarkBudgetError(
                f"request budget of {self.max_total_requests} exhausted; refusing further provider calls"
            )

    @property
    def requests_spent(self) -> int:
        """Number of provider requests consumed so far."""
        with self._lock:
            return self._spent


class _BudgetedModelClient(ModelClient):
    """ModelClient that charges every chat call against the shared request budget."""

    def __init__(self, request_budget: RequestBudget, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._request_budget = request_budget

    def chat(self, agent: ModelAgent, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        """Spend one budgeted request, then delegate to the normal chat path."""
        self._request_budget.spend_or_fail()
        return super().chat(agent, messages, temperature)


# --------------------------------------------------------------------------
# Catalog discovery
# --------------------------------------------------------------------------


def parse_model_catalog_body(body: bytes) -> dict[str, Any]:
    """Parse an OpenAI-compatible ``GET /v1/models`` body into a hygienic inventory.

    Adversarial inputs (non-JSON, wrong shapes, entries without an id,
    duplicate ids) never crash: structural failures raise
    :class:`CatalogDiscoveryError`; salvageable per-entry problems are recorded
    with machine-readable reasons in ``invalid_entries``/``duplicate_model_ids``.
    """
    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CatalogDiscoveryError(f"model catalog body is not valid JSON: {exc}") from exc
    if not isinstance(decoded, dict) or not isinstance(decoded.get("data"), list):
        raise CatalogDiscoveryError("model catalog must be a JSON object with a 'data' list")

    models: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    duplicate_model_ids: list[str] = []
    invalid_entries: list[dict[str, Any]] = []
    for index, entry in enumerate(decoded["data"]):
        if not isinstance(entry, dict):
            invalid_entries.append({"entry_index": index, "invalid_reason": "entry_not_an_object"})
            continue
        model_id = entry.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            invalid_entries.append({"entry_index": index, "invalid_reason": "missing_model_id"})
            continue
        model_id = model_id.strip()
        if model_id in seen_ids:
            duplicate_model_ids.append(model_id)
            continue
        seen_ids.add(model_id)
        owned_by = entry.get("owned_by")
        models.append(
            {
                "model_id": model_id,
                "owned_by": owned_by if isinstance(owned_by, str) else "",
            }
        )
    models.sort(key=lambda row: row["model_id"])
    return {
        "models": models,
        "duplicate_model_ids": sorted(duplicate_model_ids),
        "invalid_entries": invalid_entries,
    }


def discover_model_catalog(
    transport: ProviderTransport,
    endpoint: str,
    api_key: str,
    request_budget: RequestBudget,
) -> dict[str, Any]:
    """Fetch and parse the live model catalog, failing closed on any discovery gap."""
    request_budget.spend_or_fail()
    url = f"{endpoint.rstrip('/')}/models"
    try:
        status, body = transport("GET", url, _auth_headers(api_key), None)
    except (urllib.error.URLError, TimeoutError, ConnectionError, socket.timeout) as exc:
        raise CatalogDiscoveryError(f"model catalog request failed: {type(exc).__name__}") from exc
    if status in (401, 403):
        raise BenchmarkAuthError(f"provider rejected the benchmark credential (HTTP {status})")
    if status != 200:
        raise CatalogDiscoveryError(f"model catalog request returned HTTP {status}")
    catalog = parse_model_catalog_body(body)
    if not catalog["models"]:
        raise CatalogDiscoveryError("model catalog discovery returned zero usable models")
    return catalog


def _auth_headers(api_key: str, content_type: str = "application/json") -> dict[str, str]:
    """Standard provider headers; the bearer value never appears in artifacts."""
    return {"authorization": f"Bearer {api_key}", "content-type": content_type, "accept": "application/json"}


# --------------------------------------------------------------------------
# Capability probes — every contract NIM can host
# --------------------------------------------------------------------------

# 1x1 transparent PNG for vision probes.
_TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
# Minimal ISO-BMFF 'ftyp' box: a syntactically recognizable video container stub.
_TINY_MP4_BYTES = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2"
_MULTIPART_BOUNDARY = "nim-benchmark-boundary-7f3a1c"


def _tiny_wav_bytes() -> bytes:
    """Return a deterministic 10ms silent mono WAV used by the audio probes."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 80)
    return buffer.getvalue()


def _chat_probe_body(model_id: str, content: Any) -> bytes:
    """Serialize a minimal single-message chat probe for ``model_id``."""
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 1,
        "temperature": 0.0,
    }
    return json.dumps(payload).encode("utf-8")


def _multipart_transcription_body(model_id: str) -> bytes:
    """Build a deterministic multipart body for the audio transcription probe."""
    boundary = _MULTIPART_BOUNDARY.encode("ascii")
    parts = [
        b"--" + boundary,
        b'Content-Disposition: form-data; name="model"',
        b"",
        model_id.encode("utf-8"),
        b"--" + boundary,
        b'Content-Disposition: form-data; name="file"; filename="probe.wav"',
        b"Content-Type: audio/wav",
        b"",
        _tiny_wav_bytes(),
        b"--" + boundary + b"--",
        b"",
    ]
    return b"\r\n".join(parts)


def _has_choice(payload: dict[str, Any]) -> bool:
    """True when an OpenAI chat/completions payload carries at least one choice."""
    choices = payload.get("choices")
    return isinstance(choices, list) and len(choices) > 0


def _has_embedding(payload: dict[str, Any]) -> bool:
    """True when an embeddings payload carries at least one embedding vector."""
    data = payload.get("data")
    return (
        isinstance(data, list)
        and len(data) > 0
        and isinstance(data[0], dict)
        and isinstance(data[0].get("embedding"), list)
    )


def _has_response_output(payload: dict[str, Any]) -> bool:
    """True when a Responses API payload carries an output field."""
    return any(key in payload for key in ("output", "output_text", "response"))


def _has_transcription_text(payload: dict[str, Any]) -> bool:
    """True when a transcription payload carries the transcribed text field."""
    return isinstance(payload.get("text"), str)


def _image_data_uri() -> str:
    """Data URI of the tiny PNG used by the image-understanding probe."""
    return f"data:image/png;base64,{_TINY_PNG_BASE64}"


def _video_data_uri() -> str:
    """Data URI of the tiny MP4 stub used by the video-understanding probe."""
    return f"data:video/mp4;base64,{base64.b64encode(_TINY_MP4_BYTES).decode('ascii')}"


def _audio_probe_base64() -> str:
    """Base64 WAV payload used by the omni-style audio-understanding probe."""
    return base64.b64encode(_tiny_wav_bytes()).decode("ascii")


def _build_capability_probes() -> dict[str, dict[str, Any]]:
    """Registry of every probe contract, in the fixed order they are attempted.

    Each spec: ``path``, ``content_type``, ``body`` (model_id -> bytes),
    ``validate`` (decoded JSON -> bool), and ``binary_response`` for endpoints
    that answer with raw media instead of JSON. A tiny synthetic asset is used
    for media probes; only an HTTP 200 counts as support, so a model that
    rejects the stub asset is honestly classified unsupported for the contract.
    """
    return {
        "chat_completion": {
            "path": "/chat/completions",
            "content_type": "application/json",
            "body": lambda model_id: _chat_probe_body(model_id, "Reply with OK."),
            "validate": _has_choice,
            "binary_response": False,
        },
        "text_completion": {
            "path": "/completions",
            "content_type": "application/json",
            "body": lambda model_id: json.dumps(
                {"model": model_id, "prompt": "OK", "max_tokens": 1, "temperature": 0.0}
            ).encode("utf-8"),
            "validate": _has_choice,
            "binary_response": False,
        },
        "response_generation": {
            "path": "/responses",
            "content_type": "application/json",
            "body": lambda model_id: json.dumps(
                {"model": model_id, "input": "Reply with OK.", "max_output_tokens": 16}
            ).encode("utf-8"),
            "validate": _has_response_output,
            "binary_response": False,
        },
        "text_embedding": {
            "path": "/embeddings",
            "content_type": "application/json",
            "body": lambda model_id: json.dumps({"model": model_id, "input": "probe"}).encode("utf-8"),
            "validate": _has_embedding,
            "binary_response": False,
        },
        "image_understanding": {
            "path": "/chat/completions",
            "content_type": "application/json",
            "body": lambda model_id: _chat_probe_body(
                model_id,
                [
                    {"type": "text", "text": "Describe the image in one word."},
                    {"type": "image_url", "image_url": {"url": _image_data_uri()}},
                ],
            ),
            "validate": _has_choice,
            "binary_response": False,
        },
        "video_understanding": {
            "path": "/chat/completions",
            "content_type": "application/json",
            "body": lambda model_id: _chat_probe_body(
                model_id,
                [
                    {"type": "text", "text": "Describe the video in one word."},
                    {"type": "video_url", "video_url": {"url": _video_data_uri()}},
                ],
            ),
            "validate": _has_choice,
            "binary_response": False,
        },
        "audio_understanding": {
            "path": "/chat/completions",
            "content_type": "application/json",
            "body": lambda model_id: _chat_probe_body(
                model_id,
                [
                    {"type": "text", "text": "Transcribe the audio."},
                    {"type": "input_audio", "input_audio": {"data": _audio_probe_base64(), "format": "wav"}},
                ],
            ),
            "validate": _has_choice,
            "binary_response": False,
        },
        "audio_transcription": {
            "path": "/audio/transcriptions",
            "content_type": f"multipart/form-data; boundary={_MULTIPART_BOUNDARY}",
            "body": _multipart_transcription_body,
            "validate": _has_transcription_text,
            "binary_response": False,
        },
        "audio_speech": {
            "path": "/audio/speech",
            "content_type": "application/json",
            "body": lambda model_id: json.dumps(
                {"model": model_id, "input": "OK", "voice": "default"}
            ).encode("utf-8"),
            "validate": lambda payload: True,
            "binary_response": True,
        },
    }


CAPABILITY_PROBES = _build_capability_probes()
CAPABILITY_PROBE_ORDER = tuple(CAPABILITY_PROBES)

# HTTP statuses meaning "this model does not serve this contract" (not an outage).
_UNSUPPORTED_HTTP_STATUS = frozenset({400, 404, 405, 415, 422, 501})


def classify_probe_status(status: int) -> str:
    """Map one probe HTTP status to its machine-readable outcome class."""
    if status == 200:
        return "supported"
    if status in _UNSUPPORTED_HTTP_STATUS:
        return "unsupported"
    if status == 401:
        return "auth_rejected"
    if status == 403:
        return "unavailable"
    if status == 408:
        return "timeout"
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "unavailable"
    return "failed"


def execute_capability_probe(
    transport: ProviderTransport,
    endpoint: str,
    api_key: str,
    model_id: str,
    capability_name: str,
    timer: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    """Run one capability probe against one model and classify the outcome."""
    spec = CAPABILITY_PROBES[capability_name]
    url = f"{endpoint.rstrip('/')}{spec['path']}"
    headers = _auth_headers(api_key, spec["content_type"])
    started = timer()
    try:
        status, body = transport("POST", url, headers, spec["body"](model_id))
    except (TimeoutError, socket.timeout) as exc:
        return _probe_row(capability_name, "timeout", f"network_timeout:{type(exc).__name__}", None, started, timer)
    except (urllib.error.URLError, ConnectionError) as exc:
        return _probe_row(capability_name, "failed", f"network_error:{type(exc).__name__}", None, started, timer)

    outcome = classify_probe_status(status)
    if outcome == "auth_rejected":
        raise BenchmarkAuthError(f"provider rejected the benchmark credential during probes (HTTP {status})")
    reason = f"http_status:{status}"
    if outcome == "supported" and not spec["binary_response"]:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            payload = None
        if not isinstance(payload, dict) or not spec["validate"](payload):
            outcome, reason = "malformed_response", "http_200_with_unexpected_body_shape"
    if outcome == "supported" and spec["binary_response"] and not body:
        outcome, reason = "malformed_response", "http_200_with_empty_media_body"
    return _probe_row(capability_name, outcome, reason, status, started, timer)


def _probe_row(
    capability_name: str,
    probe_outcome: str,
    outcome_reason: str,
    http_status: int | None,
    started: float,
    timer: Callable[[], float],
) -> dict[str, Any]:
    """Assemble one probe result row with its end-to-end latency."""
    return {
        "capability_name": capability_name,
        "probe_outcome": probe_outcome,
        "outcome_reason": outcome_reason,
        "http_status": http_status,
        "probe_latency_ms": round((timer() - started) * 1000, 2),
    }


def _skipped_probe_row(capability_name: str, skip_reason: str) -> dict[str, Any]:
    """Row for a probe that never ran; the reason stays machine-readable."""
    return {
        "capability_name": capability_name,
        "probe_outcome": "skipped",
        "outcome_reason": skip_reason,
        "http_status": None,
        "probe_latency_ms": 0.0,
    }


_CHAT_CLASSIFICATIONS = frozenset({"chat_capable", "vision_chat_capable", "omni_capable"})


def classify_model_capabilities(probe_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive one model-level classification from its per-capability probe rows.

    Chat-family support wins (with vision/omni refinements derived from the
    modality probes); otherwise the strongest single-contract class applies;
    otherwise the dominant failure mode is reported, so a skipped or throttled
    model is never silently confused with an unsupported one.
    """
    outcomes = {row["capability_name"]: row["probe_outcome"] for row in probe_rows}
    supported = sorted(name for name, outcome in outcomes.items() if outcome == "supported")
    supported_set = set(supported)
    if "chat_completion" in supported_set:
        if {"image_understanding", "audio_understanding"} <= supported_set:
            classification = "omni_capable"
        elif supported_set & {"image_understanding", "video_understanding"}:
            classification = "vision_chat_capable"
        else:
            classification = "chat_capable"
    elif "text_embedding" in supported_set:
        classification = "embedding_only"
    elif "text_completion" in supported_set:
        classification = "completion_only"
    elif "response_generation" in supported_set:
        classification = "responses_only"
    elif supported_set & {"audio_transcription", "audio_speech"}:
        classification = "audio_only"
    else:
        observed = set(outcomes.values())
        if observed == {"skipped"}:
            classification = "skipped"
        elif "rate_limited" in observed:
            classification = "rate_limited"
        elif "unavailable" in observed:
            classification = "unavailable"
        elif observed & {"timeout", "failed", "malformed_response"}:
            classification = "failed"
        else:
            classification = "unsupported_for_contract"
    return {
        "model_classification": classification,
        "supported_capabilities": supported,
        "chat_eligible": classification in _CHAT_CLASSIFICATIONS,
    }


def probe_discovered_models(
    models: list[dict[str, Any]],
    transport: ProviderTransport,
    endpoint: str,
    api_key: str,
    request_budget: RequestBudget,
    probe_concurrency: int,
    clock: Callable[[], float],
    timer: Callable[[], float] = time.perf_counter,
) -> list[dict[str, Any]]:
    """Probe every discovered model across every capability, bounded and ordered.

    Concurrency is bounded by ``probe_concurrency``; the shared request budget
    is enforced per probe, and results are returned sorted by ``model_id`` so
    provider response-order drift can never reorder the snapshot.
    """
    if probe_concurrency < 1:
        raise BenchmarkContractError("probe_concurrency must be a positive integer")

    def probe_one(model: dict[str, Any]) -> dict[str, Any]:
        """Probe all capabilities for one model, honoring the shared budget."""
        rows: list[dict[str, Any]] = []
        for capability_name in CAPABILITY_PROBE_ORDER:
            if not request_budget.try_spend():
                rows.append(_skipped_probe_row(capability_name, "request_budget_exhausted"))
                continue
            rows.append(
                execute_capability_probe(
                    transport, endpoint, api_key, model["model_id"], capability_name, timer
                )
            )
        classified = classify_model_capabilities(rows)
        return {
            "model_id": model["model_id"],
            "owned_by": model["owned_by"],
            "endpoint": endpoint,
            "discovered_at_unix": round(clock(), 3),
            "capability_probe_rows": rows,
            **classified,
        }

    with ThreadPoolExecutor(max_workers=probe_concurrency) as executor:
        results = list(executor.map(probe_one, models))
    return sorted(results, key=lambda row: row["model_id"])


# --------------------------------------------------------------------------
# Task manifest, scorers, pricing scenario
# --------------------------------------------------------------------------


def score_exact_number_match(expected: dict[str, Any], answer_text: str) -> float:
    """1.0 when the exact expected number appears as a standalone number in the answer.

    A trailing sentence period ("the answer is 21.") still matches; being part
    of a longer number ("210", "21.5", "121") never does.
    """
    pattern = rf"(?<![\d.]){re.escape(str(expected['number']))}(?!\d)(?!\.\d)"
    return 1.0 if re.search(pattern, answer_text) else 0.0


def score_substring_match(expected: dict[str, Any], answer_text: str) -> float:
    """1.0 when the expected substring appears (case-insensitive) in the answer."""
    return 1.0 if str(expected["substring"]).lower() in answer_text.lower() else 0.0


SCORER_REGISTRY: dict[tuple[str, str], Callable[[dict[str, Any], str], float]] = {
    ("exact_number_match", "1"): score_exact_number_match,
    ("substring_match", "1"): score_substring_match,
}

_VALID_TASK_SPLITS = frozenset({"locked", "exploratory"})


def load_task_manifest(path: str) -> dict[str, Any]:
    """Load and validate the versioned task manifest, rejecting leakage and drift.

    Enforces: a manifest version, unique immutable snake_case task ids, known
    splits, registered scorer name+version pairs, and the no-leakage rule that
    an expected answer value never appears inside its own task prompt.
    """
    with open(path, "r", encoding="utf-8") as handle:
        try:
            manifest = json.load(handle)
        except ValueError as exc:
            raise BenchmarkContractError(f"task manifest is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("manifest_version"), str):
        raise BenchmarkContractError("task manifest must be an object with a string 'manifest_version'")
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise BenchmarkContractError("task manifest must carry a non-empty 'tasks' list")
    seen_task_ids: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise BenchmarkContractError("every task manifest entry must be an object")
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not is_two_word_snake_case(task_id):
            raise BenchmarkContractError(f"task_id must be two-plus-word snake_case: {task_id!r}")
        if task_id in seen_task_ids:
            raise BenchmarkContractError(f"duplicate task_id in manifest: {task_id!r}")
        seen_task_ids.add(task_id)
        if task.get("split") not in _VALID_TASK_SPLITS:
            raise BenchmarkContractError(f"task {task_id!r} split must be 'locked' or 'exploratory'")
        prompt = task.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise BenchmarkContractError(f"task {task_id!r} must carry a non-empty prompt")
        scorer = task.get("scorer")
        if not isinstance(scorer, dict):
            raise BenchmarkContractError(f"task {task_id!r} must carry a scorer object")
        scorer_key = (str(scorer.get("name")), str(scorer.get("version")))
        if scorer_key not in SCORER_REGISTRY:
            raise BenchmarkContractError(f"task {task_id!r} names an unregistered scorer: {scorer_key}")
        expected = task.get("expected")
        if not isinstance(expected, dict) or not expected:
            raise BenchmarkContractError(f"task {task_id!r} must carry a non-empty expected object")
        # No-leakage rule, defined by the scorer itself: if the registered
        # scorer would award the prompt text a point, the expected answer has
        # leaked into the prompt and a prompt-echoing model would score.
        if SCORER_REGISTRY[scorer_key](expected, prompt) != 0.0:
            raise BenchmarkContractError(
                f"task {task_id!r} leaks its expected answer into the prompt (test-set leakage)"
            )
    return manifest


def locked_evaluation_tasks(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only the locked evaluation split, in manifest order."""
    return [task for task in manifest["tasks"] if task["split"] == "locked"]


def _require_finite_rate(value: Any, label: str) -> float:
    """Validate one USD-per-million-token rate: a finite, non-negative number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise BenchmarkContractError(f"pricing scenario rate {label} must be a finite non-negative number")
    return float(value)


def load_pricing_scenario(path: str | None) -> dict[str, Any] | None:
    """Load and validate the versioned hypothetical price-assumption file.

    ``None`` (no scenario supplied) is legal: every hypothetical cost then
    stays ``"unknown"``. Rates are never invented here — only explicit,
    finite input/output USD-per-million-token pairs are accepted.
    """
    if path is None:
        return None
    with open(path, "r", encoding="utf-8") as handle:
        try:
            scenario = json.load(handle)
        except ValueError as exc:
            raise BenchmarkContractError(f"pricing scenario is not valid JSON: {exc}") from exc
    if not isinstance(scenario, dict) or not isinstance(scenario.get("scenario_version"), str):
        raise BenchmarkContractError("pricing scenario must be an object with a string 'scenario_version'")
    if scenario.get("scenario_status") not in ("example_unreviewed", "reviewed"):
        raise BenchmarkContractError("pricing scenario_status must be 'example_unreviewed' or 'reviewed'")
    rates = scenario.get("usd_per_million_tokens")
    if not isinstance(rates, dict):
        raise BenchmarkContractError("pricing scenario must carry a 'usd_per_million_tokens' object")
    for model_id, rate in rates.items():
        if not isinstance(rate, dict):
            raise BenchmarkContractError(f"pricing entry for {model_id!r} must be an object")
        _require_finite_rate(rate.get("input"), f"{model_id}.input")
        _require_finite_rate(rate.get("output"), f"{model_id}.output")
    return scenario


def hypothetical_cost_usd(
    pricing_scenario: dict[str, Any] | None,
    usage_by_model: dict[str, dict[str, int]],
) -> float | str:
    """Cost under the pricing scenario, or ``"unknown"`` when any model is unpriced.

    ``usage_by_model`` maps model id to its prompt/completion token counts for
    one cell. No authoritative rate for a used model means the whole cell is
    honestly ``"unknown"`` — a partial sum would understate cost.
    """
    if pricing_scenario is None:
        return "unknown"
    rates = pricing_scenario["usd_per_million_tokens"]
    total = 0.0
    for model_id, usage in usage_by_model.items():
        rate = rates.get(model_id)
        if rate is None:
            return "unknown"
        total += usage["prompt_tokens"] * float(rate["input"]) / 1_000_000
        total += usage["completion_tokens"] * float(rate["output"]) / 1_000_000
    return round(total, 10)


# --------------------------------------------------------------------------
# Policy evaluation
# --------------------------------------------------------------------------


def sanitize_worker_agent_id(model_id: str, taken_ids: set[str]) -> str:
    """Deterministically derive a convention-compliant agent id from a model id."""
    base = re.sub(r"[^a-z0-9]+", "_", model_id.lower()).strip("_") or "unnamed_model"
    if not is_two_word_snake_case(base):
        base = f"nim_{base}"
    candidate = base
    suffix = 2
    while candidate in taken_ids:
        candidate = f"{base}_{suffix}"
        suffix += 1
    taken_ids.add(candidate)
    return candidate


def build_worker_agents(
    probed_models: list[dict[str, Any]],
    base_url: str,
    max_eval_models: int,
) -> list[ModelAgent]:
    """Build the evaluation worker pool from chat-eligible probed models.

    Deterministic: models are already sorted by id; the pool is capped at
    ``max_eval_models`` so a huge catalog cannot silently explode the budget.
    """
    if max_eval_models < 1:
        raise BenchmarkContractError("max_eval_models must be a positive integer")
    taken_ids: set[str] = set()
    agents: list[ModelAgent] = []
    for row in probed_models:
        if not row["chat_eligible"]:
            continue
        if len(agents) >= max_eval_models:
            break
        agents.append(
            ModelAgent(
                id=sanitize_worker_agent_id(row["model_id"], taken_ids),
                model=row["model_id"],
                base_url=base_url,
                credential_key=NIM_CREDENTIAL_NAME,
                tags=("reasoning", "writing"),
            )
        )
    return agents


def _coerce_token_count(value: Any) -> int | None:
    """Defensively coerce a provider-reported token count; ``None`` when unusable.

    Guards the adversarial cases: booleans, non-numbers, NaN/inf, negatives.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return int(value)


def _cell_usage(
    trace: list[dict[str, Any]],
    agents_by_id: dict[str, str],
    task_prompt: str,
) -> tuple[dict[str, dict[str, int]], dict[str, Any]]:
    """Aggregate per-model token usage for one cell, labeling its source honestly.

    Provider-reported usage wins; steps without usable reported numbers fall
    back to the repo's character-length estimate and mark the whole cell
    ``estimated`` (never silently mixed into ``reported``).
    """
    usage_by_model: dict[str, dict[str, int]] = {}
    any_estimated = False
    models_used: list[dict[str, Any]] = []
    for row in trace:
        agent_id = row.get("served_agent_id") or row["agent_id"]
        model_id = agents_by_id[agent_id]
        models_used.append(
            {"step_id": row["id"], "role": row["role"], "agent_id": agent_id, "model_id": model_id}
        )
        usage = row.get("usage") if isinstance(row.get("usage"), dict) else {}
        prompt_tokens = _coerce_token_count(usage.get("prompt_tokens"))
        completion_tokens = _coerce_token_count(usage.get("completion_tokens"))
        if prompt_tokens is None:
            prompt_tokens = estimate_tokens(task_prompt)
            any_estimated = True
        if completion_tokens is None:
            completion_tokens = estimate_tokens(row.get("output") or "")
            any_estimated = True
        bucket = usage_by_model.setdefault(model_id, {"prompt_tokens": 0, "completion_tokens": 0})
        bucket["prompt_tokens"] += prompt_tokens
        bucket["completion_tokens"] += completion_tokens
    prompt_total = sum(bucket["prompt_tokens"] for bucket in usage_by_model.values())
    completion_total = sum(bucket["completion_tokens"] for bucket in usage_by_model.values())
    summary = {
        "prompt_tokens": prompt_total,
        "completion_tokens": completion_total,
        "total_tokens": prompt_total + completion_total,
        "token_usage_source": "estimated" if any_estimated else "reported",
        "models_used": models_used,
    }
    return usage_by_model, summary


def _classify_run_error(exc: Exception) -> str:
    """Split a failed policy run into the issue's timeout vs failure classes."""
    causes = {type(exc), type(exc.__cause__)}
    if causes & {TimeoutError, socket.timeout}:
        return "timeout"
    return "failure"


def run_policy_cell(
    policy_name: str,
    task: dict[str, Any],
    run_callable: Callable[[], dict[str, Any]],
    agents_by_id: dict[str, str],
    pricing_scenario: dict[str, Any] | None,
    timer: Callable[[], float],
) -> dict[str, Any]:
    """Execute one policy on one task and record the full evidence cell."""
    scorer = task["scorer"]
    started = timer()
    try:
        result = run_callable()
    except (BenchmarkBudgetError, BenchmarkAuthError):
        # Budget exhaustion and credential rejection must abort the whole run
        # (fail closed), never degrade into one quietly failed cell.
        raise
    except Exception as exc:  # noqa: BLE001 - classified into the contract outcomes
        return {
            "policy_name": policy_name,
            "task_id": task["task_id"],
            "task_split": task["split"],
            "scorer_name": scorer["name"],
            "scorer_version": scorer["version"],
            "task_score": None,
            "run_outcome": _classify_run_error(exc),
            "outcome_reason": f"{type(exc).__name__}",
            "end_to_end_latency_ms": round((timer() - started) * 1000, 3),
            "provider_latency_ms": None,
            "call_count": 0,
            "workflow_depth": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "token_usage_source": "unavailable",
            "actual_cost_usd": 0.0,
            "hypothetical_cost_usd": "unknown",
            "models_used": [],
            "response_sha256": None,
        }
    elapsed_ms = round((timer() - started) * 1000, 3)
    answer = result.get("answer") or ""
    scorer_fn = SCORER_REGISTRY[(scorer["name"], scorer["version"])]
    trace = result.get("trace") or []
    usage_by_model, usage_summary = _cell_usage(trace, agents_by_id, task["prompt"])
    return {
        "policy_name": policy_name,
        "task_id": task["task_id"],
        "task_split": task["split"],
        "scorer_name": scorer["name"],
        "scorer_version": scorer["version"],
        "task_score": scorer_fn(task["expected"], answer),
        "run_outcome": "success",
        "outcome_reason": "completed",
        "end_to_end_latency_ms": elapsed_ms,
        # Provider-side latency is not observable through the OpenAI-compatible
        # response body; recorded as None rather than a fabricated number.
        "provider_latency_ms": None,
        "call_count": len(trace),
        "workflow_depth": len(trace),
        "prompt_tokens": usage_summary["prompt_tokens"],
        "completion_tokens": usage_summary["completion_tokens"],
        "total_tokens": usage_summary["total_tokens"],
        "token_usage_source": usage_summary["token_usage_source"],
        # Actual cost of the hosted NIM catalog to the caller is zero today;
        # hypothetical paid cost comes only from the explicit scenario.
        "actual_cost_usd": 0.0,
        "hypothetical_cost_usd": hypothetical_cost_usd(pricing_scenario, usage_by_model),
        "models_used": usage_summary["models_used"],
        "response_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
    }


def _combined_rate(pricing_scenario: dict[str, Any], model_id: str) -> float | None:
    """Combined input+output USD/1M rate for cheapest-worker selection, or ``None``."""
    rate = pricing_scenario["usd_per_million_tokens"].get(model_id)
    if rate is None:
        return None
    return float(rate["input"]) + float(rate["output"])


def cheapest_priced_agent(
    agents: list[ModelAgent], pricing_scenario: dict[str, Any] | None
) -> ModelAgent | None:
    """The cheapest scenario-priced worker (deterministic tiebreak by model id)."""
    if pricing_scenario is None:
        return None
    priced = [
        (rate, agent.model, agent)
        for agent in agents
        for rate in [_combined_rate(pricing_scenario, agent.model)]
        if rate is not None
    ]
    if not priced:
        return None
    return min(priced, key=lambda row: (row[0], row[1]))[2]


def planned_evaluation_requests(worker_count: int, locked_task_count: int) -> int:
    """Upper bound on evaluation calls, checked pre-flight so the run fails closed.

    Direct baselines: one call per worker per task; ``route_once``: one call
    per task; ``conduct``: at most :data:`MAX_WORKFLOW_DEPTH` calls per task;
    cheapest-eligible: one call per task.
    """
    return locked_task_count * (worker_count + 1 + MAX_WORKFLOW_DEPTH + 1)


def evaluate_policies(
    agents: list[ModelAgent],
    manifest: dict[str, Any],
    pricing_scenario: dict[str, Any] | None,
    client: ModelClient,
    request_budget: RequestBudget,
    timer: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    """Run every compared policy over the locked split and assemble the cells.

    Compared systems (identical task set, scorers, caps, and client budgets):
    per-worker direct baselines (also the source of the best-single-worker-in-
    hindsight reference), the deterministic ``route_once`` policy, the bounded
    deep ``conduct`` policy, and the cheapest-scenario-priced-worker baseline.
    """
    if not agents:
        raise BenchmarkContractError("policy evaluation requires at least one chat-eligible worker")
    tasks = locked_evaluation_tasks(manifest)
    if not tasks:
        raise BenchmarkContractError("task manifest has no locked evaluation tasks")
    planned = planned_evaluation_requests(len(agents), len(tasks))
    remaining = request_budget.max_total_requests - request_budget.requests_spent
    if planned > remaining:
        raise BenchmarkBudgetError(
            f"planned evaluation needs up to {planned} requests but only {remaining} remain in the budget"
        )

    agents_by_id = {agent.id: agent.model for agent in agents}
    depth_policy = dataclasses.replace(OrchestrationPolicy(), max_workflow_steps=MAX_WORKFLOW_DEPTH)

    def fresh_orchestrator(pool: list[ModelAgent]) -> TaskOrchestrator:
        """One orchestrator per policy arm so spend/trace never bleed across arms."""
        orchestrator = TaskOrchestrator(pool, client=client)
        orchestrator.policy = depth_policy
        return orchestrator

    cells: list[dict[str, Any]] = []
    for agent in agents:
        single = fresh_orchestrator([agent])
        for task in tasks:
            cells.append(
                run_policy_cell(
                    f"direct_single_worker:{agent.model}",
                    task,
                    lambda single=single, task=task: single.complete(
                        [{"role": "user", "content": task["prompt"]}], mode="route"
                    ),
                    agents_by_id,
                    pricing_scenario,
                    timer,
                )
            )
    pool_router = fresh_orchestrator(agents)
    pool_conductor = fresh_orchestrator(agents)
    for task in tasks:
        cells.append(
            run_policy_cell(
                "route_once",
                task,
                lambda task=task: pool_router.complete([{"role": "user", "content": task["prompt"]}], mode="route"),
                agents_by_id,
                pricing_scenario,
                timer,
            )
        )
        cells.append(
            run_policy_cell(
                "conduct_bounded",
                task,
                lambda task=task: pool_conductor.complete(
                    [{"role": "user", "content": task["prompt"]}], mode="conduct"
                ),
                agents_by_id,
                pricing_scenario,
                timer,
            )
        )
    cheapest_skip_reason = None
    cheapest = cheapest_priced_agent(agents, pricing_scenario)
    if cheapest is None:
        cheapest_skip_reason = (
            "no_pricing_scenario_supplied" if pricing_scenario is None else "no_worker_priced_by_scenario"
        )
    else:
        cheapest_orchestrator = fresh_orchestrator([cheapest])
        for task in tasks:
            cells.append(
                run_policy_cell(
                    "cheapest_eligible_worker",
                    task,
                    lambda task=task: cheapest_orchestrator.complete(
                        [{"role": "user", "content": task["prompt"]}], mode="route"
                    ),
                    agents_by_id,
                    pricing_scenario,
                    timer,
                )
            )
    cells.sort(key=lambda cell: (cell["policy_name"], cell["task_id"]))
    return {
        "evaluation_cells": cells,
        "cheapest_worker_skip_reason": cheapest_skip_reason,
        "locked_task_count": len(tasks),
        "worker_count": len(agents),
    }


# --------------------------------------------------------------------------
# Statistics: paired bootstrap + Pareto frontiers
# --------------------------------------------------------------------------


def paired_bootstrap_mean_difference(
    paired_scores: list[tuple[float, float]],
    iterations: int = 2000,
    seed: int = 7,
) -> dict[str, Any]:
    """Paired bootstrap CI for mean(score_a - score_b) over shared tasks."""
    if not paired_scores:
        raise BenchmarkContractError("paired bootstrap requires at least one score pair")
    differences = [a - b for a, b in paired_scores]
    rng = random.Random(seed)
    resampled_means = sorted(
        sum(rng.choice(differences) for _ in differences) / len(differences) for _ in range(iterations)
    )
    lower_index = int(0.025 * (iterations - 1))
    upper_index = int(0.975 * (iterations - 1))
    return {
        "mean_difference": round(sum(differences) / len(differences), 6),
        "ci_low": round(resampled_means[lower_index], 6),
        "ci_high": round(resampled_means[upper_index], 6),
        "iterations": iterations,
        "seed": seed,
        "pair_count": len(differences),
        "method": "paired_bootstrap_percentile_95",
    }


def pareto_frontier(
    rows: list[dict[str, Any]], quality_key: str, cost_key: str
) -> list[dict[str, Any]]:
    """Rows not dominated on (``quality_key`` up, ``cost_key`` down)."""
    frontier = [
        a
        for a in rows
        if not any(
            b is not a
            and b[quality_key] >= a[quality_key]
            and b[cost_key] <= a[cost_key]
            and (b[quality_key] > a[quality_key] or b[cost_key] < a[cost_key])
            for b in rows
        )
    ]
    return sorted(frontier, key=lambda row: (-row[quality_key], row[cost_key]))


def summarize_policies(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate evaluation cells per policy with honest unknown-cost labeling."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for cell in cells:
        grouped.setdefault(cell["policy_name"], []).append(cell)
    summaries = []
    for policy_name in sorted(grouped):
        policy_cells = grouped[policy_name]
        scored = [cell for cell in policy_cells if cell["run_outcome"] == "success"]
        priced = [cell for cell in scored if isinstance(cell["hypothetical_cost_usd"], float)]
        mean_score = round(sum(cell["task_score"] for cell in scored) / len(scored), 6) if scored else 0.0
        summaries.append(
            {
                "policy_name": policy_name,
                "cell_count": len(policy_cells),
                "success_count": len(scored),
                "mean_task_score": mean_score,
                "mean_latency_ms": round(
                    sum(cell["end_to_end_latency_ms"] for cell in policy_cells) / len(policy_cells), 3
                ),
                "total_call_count": sum(cell["call_count"] for cell in policy_cells),
                "max_workflow_depth": max(cell["workflow_depth"] for cell in policy_cells),
                "total_tokens": sum(cell["total_tokens"] for cell in policy_cells),
                "actual_cost_usd": 0.0,
                "mean_hypothetical_cost_usd": (
                    round(sum(cell["hypothetical_cost_usd"] for cell in priced) / len(priced), 10)
                    if priced
                    else "unknown"
                ),
                "unknown_hypothetical_cost_cells": len(scored) - len(priced),
            }
        )
    return summaries


def best_single_worker_hindsight(summaries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The best direct single worker selected in hindsight on the locked split."""
    direct = [row for row in summaries if row["policy_name"].startswith("direct_single_worker:")]
    if not direct:
        return None
    best = max(direct, key=lambda row: (row["mean_task_score"], row["policy_name"]))
    return {
        "policy_name": best["policy_name"],
        "model_id": best["policy_name"].split(":", 1)[1],
        "mean_task_score": best["mean_task_score"],
        "selection_basis": "hindsight_argmax_mean_locked_score",
    }


def paired_policy_comparisons(cells: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    """Paired task-level bootstrap comparisons between the headline policies."""
    scores: dict[str, dict[str, float]] = {}
    for cell in cells:
        if cell["run_outcome"] == "success":
            scores.setdefault(cell["policy_name"], {})[cell["task_id"]] = cell["task_score"]
    summaries = summarize_policies(cells)
    hindsight = best_single_worker_hindsight(summaries)
    comparison_pairs = [("conduct_bounded", "route_once"), ("cheapest_eligible_worker", "route_once")]
    if hindsight is not None:
        comparison_pairs.append(("route_once", hindsight["policy_name"]))
        comparison_pairs.append(("conduct_bounded", hindsight["policy_name"]))
    comparisons = []
    for policy_a, policy_b in comparison_pairs:
        tasks_a, tasks_b = scores.get(policy_a), scores.get(policy_b)
        if not tasks_a or not tasks_b:
            continue
        shared_tasks = sorted(set(tasks_a) & set(tasks_b))
        if not shared_tasks:
            continue
        pairs = [(tasks_a[task_id], tasks_b[task_id]) for task_id in shared_tasks]
        comparisons.append(
            {
                "policy_a": policy_a,
                "policy_b": policy_b,
                **paired_bootstrap_mean_difference(pairs, seed=seed),
            }
        )
    return comparisons


def _numeric_cost_rows(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summaries whose mean hypothetical cost is numeric (unknowns excluded, labeled)."""
    return [row for row in summaries if isinstance(row["mean_hypothetical_cost_usd"], float)]


def build_pareto_frontiers(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Quality-latency and quality-hypothetical-cost Pareto frontiers."""
    return {
        "quality_vs_latency": pareto_frontier(summaries, "mean_task_score", "mean_latency_ms"),
        "quality_vs_hypothetical_cost": pareto_frontier(
            _numeric_cost_rows(summaries), "mean_task_score", "mean_hypothetical_cost_usd"
        ),
        "excluded_unknown_cost_policies": sorted(
            row["policy_name"] for row in summaries if not isinstance(row["mean_hypothetical_cost_usd"], float)
        ),
    }


# --------------------------------------------------------------------------
# Provenance, report schema, artifacts
# --------------------------------------------------------------------------


def sha256_of_file(path: str) -> str:
    """Hex SHA-256 of a file's bytes (manifest/pricing provenance hashes)."""
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def sha256_of_json(value: Any) -> str:
    """Hex SHA-256 of a canonical JSON serialization (catalog snapshot hash)."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def build_provenance(
    run_mode: str,
    git_sha: str,
    workflow_run_id: str,
    catalog_snapshot: dict[str, Any],
    task_manifest_path: str,
    pricing_scenario_path: str | None,
    benchmark_parameters: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the provenance block; live runs fail closed on missing identity."""
    if run_mode == "live" and (not git_sha or not workflow_run_id):
        raise BenchmarkContractError("live runs require --git-sha and --workflow-run-id provenance")
    return {
        "run_mode": run_mode,
        "git_sha": git_sha or DRY_RUN_PROVENANCE_PLACEHOLDER,
        "workflow_run_id": workflow_run_id or DRY_RUN_PROVENANCE_PLACEHOLDER,
        "catalog_snapshot_sha256": sha256_of_json(catalog_snapshot),
        "task_manifest_sha256": sha256_of_file(task_manifest_path),
        "pricing_scenario_sha256": (
            sha256_of_file(pricing_scenario_path) if pricing_scenario_path else None
        ),
        "benchmark_parameters": benchmark_parameters,
    }


_REPORT_REQUIRED_PATHS = (
    "benchmark_schema_version",
    "provenance.run_mode",
    "provenance.git_sha",
    "provenance.workflow_run_id",
    "provenance.catalog_snapshot_sha256",
    "provenance.task_manifest_sha256",
    "provenance.benchmark_parameters",
    "catalog_snapshot.endpoint",
    "catalog_snapshot.discovered_model_count",
    "catalog_snapshot.duplicate_model_ids",
    "catalog_snapshot.invalid_entries",
    "catalog_snapshot.probed_models",
    "capability_summary",
    "evaluation.evaluation_cells",
    "evaluation.policy_summaries",
    "evaluation.paired_comparisons",
    "evaluation.pareto_frontiers",
    "request_budget.max_total_requests",
    "request_budget.requests_spent",
    "honesty_labels.actual_cost_basis",
    "honesty_labels.provider_latency_source",
)


def validate_report_schema(report: dict[str, Any]) -> None:
    """Fail closed when any required report path is absent."""
    missing = []
    for path in _REPORT_REQUIRED_PATHS:
        node: Any = report
        for key in path.split("."):
            if not isinstance(node, dict) or key not in node:
                missing.append(path)
                break
            node = node[key]
    if missing:
        raise BenchmarkContractError(f"benchmark report is missing required paths: {missing}")


_CSV_CELL_COLUMNS = (
    "policy_name",
    "task_id",
    "task_split",
    "scorer_name",
    "scorer_version",
    "task_score",
    "run_outcome",
    "outcome_reason",
    "end_to_end_latency_ms",
    "provider_latency_ms",
    "call_count",
    "workflow_depth",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "token_usage_source",
    "actual_cost_usd",
    "hypothetical_cost_usd",
    "response_sha256",
)


def _ensure_secret_absent(serialized: str) -> None:
    """Refuse to write any artifact that contains the resolved provider secret."""
    secret = get_credential(NIM_CREDENTIAL_NAME)
    if secret and secret in serialized:
        raise SecretLeakError("benchmark artifact would contain the provider credential; refusing to write")


def render_markdown_summary(report: dict[str, Any]) -> str:
    """Human-readable Markdown summary of one benchmark run."""
    lines = [
        "# NIM cost-quality benchmark summary",
        "",
        f"- run mode: `{report['provenance']['run_mode']}`",
        f"- git sha: `{report['provenance']['git_sha']}`",
        f"- workflow run id: `{report['provenance']['workflow_run_id']}`",
        f"- catalog snapshot sha256: `{report['provenance']['catalog_snapshot_sha256']}`",
        f"- discovered models: {report['catalog_snapshot']['discovered_model_count']}",
        f"- requests spent: {report['request_budget']['requests_spent']}"
        f" / {report['request_budget']['max_total_requests']}",
        "",
        "## Capability classifications",
        "",
        "| classification | models |",
        "| --- | --- |",
    ]
    for classification, count in sorted(report["capability_summary"].items()):
        lines.append(f"| {classification} | {count} |")
    lines += [
        "",
        "## Policy summaries (locked split)",
        "",
        "| policy | mean score | mean latency ms | mean hypothetical cost USD | actual cost USD |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in report["evaluation"]["policy_summaries"]:
        lines.append(
            f"| {row['policy_name']} | {row['mean_task_score']} | {row['mean_latency_ms']} "
            f"| {row['mean_hypothetical_cost_usd']} | {row['actual_cost_usd']} |"
        )
    lines += ["", "## Paired comparisons (95% bootstrap CI)", ""]
    for comparison in report["evaluation"]["paired_comparisons"]:
        lines.append(
            f"- `{comparison['policy_a']}` vs `{comparison['policy_b']}`: "
            f"mean diff {comparison['mean_difference']} "
            f"[{comparison['ci_low']}, {comparison['ci_high']}]"
        )
    lines += [
        "",
        "## Honesty labels",
        "",
        f"- actual cost basis: {report['honesty_labels']['actual_cost_basis']}",
        f"- provider latency: {report['honesty_labels']['provider_latency_source']}",
        f"- hypothetical cost source: {report['honesty_labels']['hypothetical_cost_source']}",
        "",
    ]
    return "\n".join(lines)


def write_benchmark_artifacts(report: dict[str, Any], output_dir: str) -> dict[str, str]:
    """Validate the report schema, then write the JSON/CSV/Markdown artifacts."""
    validate_report_schema(report)
    os.makedirs(output_dir, exist_ok=True)
    json_text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    _ensure_secret_absent(json_text)
    json_path = os.path.join(output_dir, "benchmark_report.json")
    with open(json_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json_text + "\n")

    csv_path = os.path.join(output_dir, "benchmark_cells.csv")
    csv_buffer = io.StringIO()
    writer = csv.DictWriter(csv_buffer, fieldnames=_CSV_CELL_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for cell in report["evaluation"]["evaluation_cells"]:
        writer.writerow(cell)
    csv_text = csv_buffer.getvalue()
    _ensure_secret_absent(csv_text)
    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(csv_text)

    markdown_text = render_markdown_summary(report)
    _ensure_secret_absent(markdown_text)
    markdown_path = os.path.join(output_dir, "benchmark_summary.md")
    with open(markdown_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(markdown_text)
    return {"json_path": json_path, "csv_path": csv_path, "markdown_path": markdown_path}


# --------------------------------------------------------------------------
# Benchmark assembly (shared by dry and live runs)
# --------------------------------------------------------------------------


def assemble_benchmark_report(
    run_mode: str,
    endpoint: str,
    catalog: dict[str, Any],
    probed_models: list[dict[str, Any]],
    evaluation: dict[str, Any],
    request_budget: RequestBudget,
    provenance_inputs: dict[str, Any],
    seed: int,
) -> dict[str, Any]:
    """Assemble the full schema-validated report from the pipeline outputs."""
    cells = evaluation["evaluation_cells"]
    summaries = summarize_policies(cells)
    capability_summary: dict[str, int] = {}
    for row in probed_models:
        capability_summary[row["model_classification"]] = (
            capability_summary.get(row["model_classification"], 0) + 1
        )
    catalog_snapshot = {
        "endpoint": endpoint,
        "discovered_model_count": len(catalog["models"]),
        "duplicate_model_ids": catalog["duplicate_model_ids"],
        "invalid_entries": catalog["invalid_entries"],
        "probed_models": probed_models,
    }
    report = {
        "benchmark_schema_version": BENCHMARK_SCHEMA_VERSION,
        "provenance": build_provenance(
            run_mode,
            provenance_inputs["git_sha"],
            provenance_inputs["workflow_run_id"],
            catalog_snapshot,
            provenance_inputs["task_manifest_path"],
            provenance_inputs["pricing_scenario_path"],
            provenance_inputs["benchmark_parameters"],
        ),
        "catalog_snapshot": catalog_snapshot,
        "capability_summary": capability_summary,
        "evaluation": {
            "evaluation_cells": cells,
            "policy_summaries": summaries,
            "best_single_worker_hindsight": best_single_worker_hindsight(summaries),
            "paired_comparisons": paired_policy_comparisons(cells, seed=seed),
            "pareto_frontiers": build_pareto_frontiers(summaries),
            "cheapest_worker_skip_reason": evaluation["cheapest_worker_skip_reason"],
            "locked_task_count": evaluation["locked_task_count"],
            "worker_count": evaluation["worker_count"],
        },
        "request_budget": {
            "max_total_requests": request_budget.max_total_requests,
            "requests_spent": request_budget.requests_spent,
        },
        "honesty_labels": {
            "actual_cost_basis": "hosted_nim_catalog_free_to_caller_actual_cost_zero",
            "provider_latency_source": "not_observable_via_openai_compatible_body",
            "hypothetical_cost_source": "explicit_versioned_pricing_scenario_or_unknown",
            "dry_run_scores_note": "dry-run scores reflect deterministic mock echoes, not model quality",
        },
    }
    validate_report_schema(report)
    return report


# --------------------------------------------------------------------------
# Deterministic dry-run provider (all modality classes, no network)
# --------------------------------------------------------------------------

# Synthetic catalog covering every capability class the harness can emit,
# plus one duplicate id and one invalid entry to exercise catalog hygiene.
_DRY_RUN_MODEL_BEHAVIOR = {
    "dryrun/chat-basic": {"chat_completion"},
    "dryrun/chat-vision": {"chat_completion", "image_understanding"},
    "dryrun/chat-omni": {
        "chat_completion",
        "image_understanding",
        "video_understanding",
        "audio_understanding",
    },
    "dryrun/chat-video": {"chat_completion", "video_understanding"},
    "dryrun/embed-basic": {"text_embedding"},
    "dryrun/completion-legacy": {"text_completion"},
    "dryrun/responses-native": {"response_generation"},
    "dryrun/audio-transcribe": {"audio_transcription"},
    "dryrun/audio-speech": {"audio_speech"},
    "dryrun/throttled-model": "rate_limited",
    "dryrun/outage-model": "unavailable",
    "dryrun/legacy-unsupported": "unsupported",
}


def _dry_run_catalog_body() -> bytes:
    """Serialized synthetic /v1/models body, including hygiene edge cases."""
    data = [{"id": model_id, "owned_by": "dryrun"} for model_id in _DRY_RUN_MODEL_BEHAVIOR]
    data.append({"id": "dryrun/chat-basic", "owned_by": "dryrun"})  # duplicate id
    data.append({"owned_by": "dryrun"})  # missing model id
    return json.dumps({"object": "list", "data": data}).encode("utf-8")


def _dry_run_success_body(path: str) -> bytes:
    """Minimal valid success body for each probed endpoint contract."""
    if path.endswith("/embeddings"):
        return json.dumps({"data": [{"embedding": [0.0, 0.1]}]}).encode("utf-8")
    if path.endswith("/responses"):
        return json.dumps({"output_text": "OK"}).encode("utf-8")
    if path.endswith("/audio/transcriptions"):
        return json.dumps({"text": "ok"}).encode("utf-8")
    if path.endswith("/audio/speech"):
        return b"RIFFdryrunaudio"
    return json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode("utf-8")


def _dry_run_probe_capability(path: str, body: bytes | None) -> str:
    """Infer which capability a dry-run probe request represents."""
    if path.endswith("/chat/completions"):
        text = (body or b"").decode("utf-8")
        if "image_url" in text:
            return "image_understanding"
        if "video_url" in text:
            return "video_understanding"
        if "input_audio" in text:
            return "audio_understanding"
        return "chat_completion"
    for capability_name, spec in CAPABILITY_PROBES.items():
        if path.endswith(spec["path"]) and capability_name != "chat_completion":
            return capability_name
    raise CatalogDiscoveryError(f"dry-run transport received an unexpected path: {path}")


def build_dry_run_transport() -> ProviderTransport:
    """In-process provider fake serving the synthetic all-modality catalog."""

    def transport(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, bytes]:
        """Serve catalog and probe requests deterministically without network."""
        path = urllib.parse.urlparse(url).path
        if method == "GET" and path.endswith("/models"):
            return 200, _dry_run_catalog_body()
        model_match = re.search(rb'"model"\s*:\s*"([^"]+)"', body or b"")
        if model_match is None:
            model_match = re.search(rb'name="model"\r\n\r\n([^\r]+)', body or b"")
        model_id = model_match.group(1).decode("utf-8") if model_match else ""
        behavior = _DRY_RUN_MODEL_BEHAVIOR.get(model_id)
        if behavior is None:
            return 404, json.dumps({"error": "unknown dry-run model"}).encode("utf-8")
        if behavior == "rate_limited":
            return 429, b"{}"
        if behavior == "unavailable":
            return 503, b"{}"
        if behavior == "unsupported":
            return 404, b"{}"
        capability_name = _dry_run_probe_capability(path, body)
        if capability_name in behavior:
            return 200, _dry_run_success_body(path)
        return 400, json.dumps({"error": "capability not supported"}).encode("utf-8")

    return transport


def _deterministic_timer() -> Callable[[], float]:
    """Monotonic fake timer for reproducible dry-run latency fields."""
    state = {"now": 0.0}

    def timer() -> float:
        """Advance one millisecond per observation."""
        state["now"] += 0.001
        return state["now"]

    return timer


# --------------------------------------------------------------------------
# Run orchestration + CLI
# --------------------------------------------------------------------------


def run_benchmark(
    run_mode: str,
    task_manifest_path: str,
    pricing_scenario_path: str | None,
    output_dir: str,
    endpoint: str = NIM_DEFAULT_ENDPOINT,
    max_total_requests: int = 500,
    probe_concurrency: int = 4,
    timeout_seconds: float = 60.0,
    max_output_tokens: int = 256,
    max_eval_models: int = 7,
    seed: int = 7,
    git_sha: str = "",
    workflow_run_id: str = "",
    transport: ProviderTransport | None = None,
) -> dict[str, Any]:
    """Run the full benchmark pipeline in ``dry_run`` or ``live`` mode.

    Dry runs use the in-process synthetic provider, mock evaluation workers,
    a fixed clock, and a deterministic timer; live runs require the KV-backed
    ``NVIDIA_NIM_API_KEY`` credential and complete provenance, and go through
    the egress-validated HTTPS transport. Both share every validation, probe,
    evaluation, statistics, and artifact code path.
    """
    if run_mode not in ("dry_run", "live"):
        raise BenchmarkContractError(f"run_mode must be 'dry_run' or 'live', not {run_mode!r}")
    manifest = load_task_manifest(task_manifest_path)
    pricing_scenario = load_pricing_scenario(pricing_scenario_path)
    request_budget = RequestBudget(max_total_requests)

    if run_mode == "dry_run":
        api_key = "dry-run-placeholder-not-a-secret"
        active_transport = transport or build_dry_run_transport()
        clock: Callable[[], float] = lambda: DRY_RUN_FIXED_UNIX_TIME
        # Zero probe timer: probes run concurrently, so a counting timer would
        # make latencies depend on thread interleaving and break determinism.
        probe_timer: Callable[[], float] = lambda: 0.0
        timer = _deterministic_timer()
        eval_base_url = "mock://nim-dry-run"
        eval_client: ModelClient = _BudgetedModelClient(request_budget)
    else:
        api_key = get_credential(NIM_CREDENTIAL_NAME) or ""
        if not api_key:
            raise NotConfigured(
                f"live benchmark requires the '{NIM_CREDENTIAL_NAME}' credential in the KV; "
                "seed it via `register-credential` bootstrap (never argv)"
            )
        active_transport = transport or build_default_transport(timeout_seconds)
        clock = time.time
        probe_timer = time.perf_counter
        timer = time.perf_counter
        eval_base_url = endpoint
        eval_client = _BudgetedModelClient(
            request_budget, timeout=int(timeout_seconds), max_output_tokens=max_output_tokens
        )

    benchmark_parameters = {
        "endpoint": endpoint,
        "max_total_requests": max_total_requests,
        "probe_concurrency": probe_concurrency,
        "timeout_seconds": timeout_seconds,
        "max_output_tokens": max_output_tokens,
        "max_eval_models": max_eval_models,
        "max_workflow_depth": MAX_WORKFLOW_DEPTH,
        "seed": seed,
        "task_manifest_version": manifest["manifest_version"],
        "pricing_scenario_version": pricing_scenario["scenario_version"] if pricing_scenario else None,
    }

    catalog = discover_model_catalog(active_transport, endpoint, api_key, request_budget)
    probed_models = probe_discovered_models(
        catalog["models"], active_transport, endpoint, api_key, request_budget, probe_concurrency, clock, probe_timer
    )
    agents = build_worker_agents(probed_models, eval_base_url, max_eval_models)
    evaluation = evaluate_policies(agents, manifest, pricing_scenario, eval_client, request_budget, timer)
    report = assemble_benchmark_report(
        run_mode,
        endpoint,
        catalog,
        probed_models,
        evaluation,
        request_budget,
        {
            "git_sha": git_sha,
            "workflow_run_id": workflow_run_id,
            "task_manifest_path": task_manifest_path,
            "pricing_scenario_path": pricing_scenario_path,
            "benchmark_parameters": benchmark_parameters,
        },
        seed,
    )
    report["artifact_paths"] = write_benchmark_artifacts(report, output_dir)
    return report


def _bootstrap_live_credential() -> None:
    """One-shot bootstrap: move the job-environment secret into the KV.

    Environment is used strictly as bootstrap transport (the same contract as
    ``register-credential --from-env``); runtime reads then resolve the key
    through :func:`get_credential` only.
    """
    if get_credential(NIM_CREDENTIAL_NAME) is None and os.environ.get(NIM_CREDENTIAL_NAME):
        register_credential(NIM_CREDENTIAL_NAME, os.environ[NIM_CREDENTIAL_NAME])


def run_benchmark_cli(argv: list[str]) -> int:
    """CLI entry for ``python -m contextual_orchestrator nim-benchmark``.

    The provider secret is never accepted via argv: live runs resolve it from
    the KV, seeded from the job environment by the one-shot bootstrap step.
    """
    parser = argparse.ArgumentParser(
        prog="python -m contextual_orchestrator nim-benchmark",
        description="Evidence-grade NVIDIA NIM model discovery and cost-quality benchmark.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate everything without contacting NVIDIA.")
    parser.add_argument("--task-manifest", default="examples/nim_task_manifest.json")
    parser.add_argument("--pricing-scenario", default=None,
                        help="Versioned hypothetical price-assumption JSON (omit => costs stay 'unknown').")
    parser.add_argument("--output-dir", default="benchmark_artifacts")
    parser.add_argument("--endpoint", default=NIM_DEFAULT_ENDPOINT)
    parser.add_argument("--max-total-requests", type=int, default=500)
    parser.add_argument("--probe-concurrency", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--max-output-tokens", type=int, default=256)
    parser.add_argument("--max-eval-models", type=int, default=7)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--git-sha", default="", help="Provenance: the exact commit under benchmark (required live).")
    parser.add_argument("--workflow-run-id", default="", help="Provenance: the CI run id (required live).")
    args = parser.parse_args(argv)

    run_mode = "dry_run" if args.dry_run else "live"
    if run_mode == "live":
        _bootstrap_live_credential()
    try:
        report = run_benchmark(
            run_mode,
            args.task_manifest,
            args.pricing_scenario,
            args.output_dir,
            endpoint=args.endpoint,
            max_total_requests=args.max_total_requests,
            probe_concurrency=args.probe_concurrency,
            timeout_seconds=args.timeout_seconds,
            max_output_tokens=args.max_output_tokens,
            max_eval_models=args.max_eval_models,
            seed=args.seed,
            git_sha=args.git_sha,
            workflow_run_id=args.workflow_run_id,
        )
    except (BenchmarkContractError, CatalogDiscoveryError, BenchmarkAuthError,
            BenchmarkBudgetError, SecretLeakError, NotConfigured, OSError) as exc:
        print(json.dumps({"benchmark_failed_closed": True, "error_class": type(exc).__name__,
                          "error_message": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(
        {
            "run_mode": report["provenance"]["run_mode"],
            "discovered_model_count": report["catalog_snapshot"]["discovered_model_count"],
            "capability_summary": report["capability_summary"],
            "requests_spent": report["request_budget"]["requests_spent"],
            "artifact_paths": report["artifact_paths"],
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0
