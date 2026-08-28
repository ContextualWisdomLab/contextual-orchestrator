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
  separately. A run that cannot execute every cell fails before capability egress.
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
import datetime as datetime_module
import hashlib
import http.client
import io
import json
import math
import os
import random
import re
import socket
import ssl
import struct
import threading
import time
import urllib.error
import urllib.parse
import wave
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .conventions import is_two_word_snake_case
from .credentials import NotConfigured, get_credential, register_credential
from .orchestrator import (
    ModelAgent,
    ModelClient,
    OrchestrationPolicy,
    ReasoningEffortProfile,
    TaskOrchestrator,
    estimate_tokens,
)
from .provider_transport import (
    _PinnedHTTPSConnection,
    _validated_public_addresses,
)

BENCHMARK_SCHEMA_VERSION = "1.0.0"
NIM_DEFAULT_ENDPOINT = "https://integrate.api.nvidia.com/v1"
NIM_CREDENTIAL_NAME = "NVIDIA_NIM_API_KEY"
DRY_RUN_PROVENANCE_PLACEHOLDER = "dry_run"
# Fixed epoch for deterministic dry-run artifacts (2026-01-01T00:00:00Z).
DRY_RUN_FIXED_UNIX_TIME = 1767225600.0
# Issue contract: Conductor/TRINITY-style deep paths are capped at five steps.
MAX_WORKFLOW_DEPTH = 5
# Bound every provider response before materializing it in memory. Eight MiB is
# ample for model catalogs, JSON probe responses, and the deliberately tiny
# benchmark media outputs while preventing a provider from returning an
# unbounded body to the evidence collector.
MAX_PROVIDER_RESPONSE_BYTES = 8 * 1024 * 1024
# Smoke manifests can exercise plumbing but cannot justify production routing.
MINIMUM_PAIRED_TASK_COUNT = 30
REQUIRED_COMPLETION_FRACTION = 0.9

ACTUAL_COST_EVIDENCE: dict[str, Any] = {
    "evidence_schema_version": "1.0.0",
    "source_title": "NVIDIA NIM General FAQ",
    "source_url": "https://docs.api.nvidia.com/nim/docs/product",
    "reviewed_at_date": "2026-08-05",
    "valid_until_date": "2026-09-04",
    "access_program": "NVIDIA Developer Program API Catalog hosted endpoints",
    "access_scope": "free API endpoint access for prototyping",
    "production_access_note": (
        "Production support and licensing require NVIDIA AI Enterprise."
    ),
    "actual_cost_usd": 0.0,
    "uncertainty": (
        "Hosted-endpoint access terms can change. Live runs fail closed after "
        "the validity date until the official source is reviewed again."
    ),
}

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


def require_public_https_endpoint(url: str) -> tuple[str, ...]:
    """Resolve and return public addresses approved for one HTTPS request.

    The returned addresses are the only addresses a caller may dial. Combining
    resolution and validation in one operation closes the DNS time-of-check to
    time-of-use gap caused by a generic URL opener resolving the hostname again.

    Args:
        url: Complete provider URL whose origin may receive credentials.

    Returns:
        Deduplicated globally routable IPv4 or IPv6 addresses.

    Raises:
        BenchmarkContractError: If the URL is not HTTPS, lacks a hostname, or
            resolves to any non-global address.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise BenchmarkContractError(f"benchmark endpoint must use https: {url!r}")
    try:
        return _validated_public_addresses(
            parsed.hostname.lower(),
            parsed.port or 443,
            "NIM benchmark",
        )
    except RuntimeError as exc:
        raise BenchmarkContractError(str(exc)) from exc


def build_default_transport(timeout_seconds: float) -> ProviderTransport:
    """Build direct HTTPS transport pinned to each request's DNS evidence.

    Every request resolves exactly once, validates every answer as globally
    routable, and connects only to those validation-time addresses. The original
    hostname remains the HTTP authority and TLS SNI/certificate name. Environment
    proxies and redirect handlers are never used.

    Args:
        timeout_seconds: Socket, TLS, and response timeout for each address.

    Returns:
        A provider transport returning HTTP status and raw response bytes.

    Raises:
        BenchmarkContractError: If a request URL or redirect violates policy.
        urllib.error.URLError: If all validation-time addresses fail.
    """
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise BenchmarkContractError("timeout_seconds must be a positive number")
    ssl_context = ssl.create_default_context()

    def transport(
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
    ) -> tuple[int, bytes]:
        """Perform one request without proxy lookup, redirect follow, or re-resolution."""
        parsed = urllib.parse.urlparse(url)
        approved_addresses = require_public_https_endpoint(url)
        port = parsed.port or 443
        target = parsed.path or "/"
        if parsed.params:
            target = f"{target};{parsed.params}"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        request_headers = dict(headers)
        request_headers["Connection"] = "close"

        last_error: BaseException | None = None
        for pinned_ip in approved_addresses:
            connection = _PinnedHTTPSConnection(
                parsed.hostname or "",
                pinned_ip,
                port,
                float(timeout_seconds),
                ssl_context,
            )
            response = None
            try:
                connection.request(
                    method,
                    target,
                    body=body,
                    headers=request_headers,
                )
                response = connection.getresponse()
                status = int(response.status)
                response_body = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
                if len(response_body) > MAX_PROVIDER_RESPONSE_BYTES:
                    raise BenchmarkContractError(
                        "benchmark provider response exceeds "
                        f"{MAX_PROVIDER_RESPONSE_BYTES} byte limit"
                    )
                if 300 <= status < 400:
                    raise BenchmarkContractError(
                        f"benchmark provider redirects are not permitted (HTTP {status})"
                    )
                return status, response_body
            except BenchmarkContractError:
                raise
            except (OSError, http.client.HTTPException) as exc:
                last_error = exc
            finally:
                if response is not None:
                    response.close()
                connection.close()
        raise urllib.error.URLError(last_error or "benchmark provider connection failed")

    return transport


# --------------------------------------------------------------------------
# Request budget (fail-closed hard cap)
# --------------------------------------------------------------------------


class RequestBudget:
    """Thread-safe hard cap on total provider requests for one benchmark run."""

    def __init__(self, max_total_requests: int) -> None:
        """Create a positive integer request allowance.

        Args:
            max_total_requests: Maximum provider calls in the complete run.

        Raises:
            BenchmarkContractError: If the cap is boolean or not positive.
        """
        if (
            isinstance(max_total_requests, bool)
            or not isinstance(max_total_requests, int)
            or max_total_requests < 1
        ):
            raise BenchmarkContractError("max_total_requests must be a positive integer")
        self.max_total_requests = max_total_requests
        self._spent = 0
        self._lock = threading.Lock()

    def try_spend(self) -> bool:
        """Consume one request from the budget; return ``False`` when exhausted."""
        with self._lock:
            if self._spent >= self.max_total_requests:
                return False
            self._spent += 1
            return True

    def spend_or_fail(self) -> None:
        """Consume one request or raise for a phase that must complete."""
        if not self.try_spend():
            raise BenchmarkBudgetError(
                f"request budget of {self.max_total_requests} exhausted; "
                "refusing further provider calls"
            )

    @property
    def requests_spent(self) -> int:
        """Return the number of provider requests consumed so far."""
        with self._lock:
            return self._spent

    @property
    def remaining_requests(self) -> int:
        """Return the non-negative provider request allowance still available."""
        with self._lock:
            return self.max_total_requests - self._spent


class _BudgetedModelClient(ModelClient):
    """ModelClient that charges every chat call against the shared request budget."""

    def __init__(
        self,
        request_budget: RequestBudget,
        transport: ProviderTransport | None = None,
        **kwargs: Any,
    ) -> None:
        # ponytail: disable hidden provider retries so the hard request budget
        # bounds actual egress rather than only logical chat calls.
        kwargs["max_retries"] = 0
        super().__init__(**kwargs)
        self._request_budget = request_budget
        self._benchmark_transport = transport

    def _send(
        self,
        agent: ModelAgent,
        payload: dict[str, Any],
        destination: Any = None,
        *,
        timeout: float | None = None,
    ) -> str:
        """Send evaluation chat calls through the benchmark's pinned transport."""
        if self._benchmark_transport is None or agent.base_url.startswith("mock://"):
            return super()._send(agent, payload, destination, timeout=timeout)
        url = self._provider_url(agent, "/chat/completions")
        status, body = self._benchmark_transport(
            "POST",
            url,
            _auth_headers(get_credential(NIM_CREDENTIAL_NAME) or ""),
            json.dumps(payload).encode("utf-8"),
        )
        if status >= 400:
            raise urllib.error.HTTPError(
                url,
                status,
                "NIM benchmark provider request failed",
                {},
                io.BytesIO(body),
            )
        data = json.loads(body.decode("utf-8"))
        usage = data.get("usage")
        if isinstance(usage, dict):
            self._local.usage = usage
        return self._response_content(agent, data)

    def chat(
        self,
        agent: ModelAgent,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        top_p: float | None = None,
        effort_profile: ReasoningEffortProfile | None = None,
    ) -> str:
        """Spend one budgeted request, then delegate to the normal chat path."""
        self._request_budget.spend_or_fail()
        return super().chat(agent, messages, temperature, top_p, effort_profile)


class PolicyTokenBudgetExceeded(RuntimeError):
    """A policy cell exhausted its shared token or call allowance."""


class EqualBudgetModelClient:
    """Delegate model calls while enforcing an equal per-cell budget.

    Direct, route-once, conduct, and cheapest-worker cells all receive the same
    total prompt-plus-completion token allowance and the same declared maximum-
    call envelope. The wrapper lowers each provider call's output cap to the
    remaining allowance and reconciles estimates with provider-reported usage.
    """

    def __init__(
        self,
        delegate: ModelClient,
        total_token_budget: int,
        maximum_calls: int,
    ) -> None:
        """Create a cell-local limiter around an existing provider client.

        Args:
            delegate: Existing request-budgeted provider client.
            total_token_budget: Cell-wide prompt-plus-completion allowance.
            maximum_calls: Maximum calls available to every compared policy.

        Raises:
            ValueError: If either allowance is boolean or not positive.
        """
        if (
            isinstance(total_token_budget, bool)
            or not isinstance(total_token_budget, int)
            or total_token_budget < 1
        ):
            raise ValueError("total_token_budget must be a positive integer")
        if (
            isinstance(maximum_calls, bool)
            or not isinstance(maximum_calls, int)
            or maximum_calls < 1
        ):
            raise ValueError("maximum_calls must be a positive integer")
        self._delegate = delegate
        self.total_token_budget = total_token_budget
        self.maximum_calls = maximum_calls
        self.observed_calls = 0
        self.observed_tokens = 0
        self._pending_estimated_tokens: int | None = None
        self._exceeded = False

    def __getattr__(self, name: str) -> Any:
        """Forward provider-client capabilities not owned by the cell limiter."""
        return getattr(self._delegate, name)

    @property
    def max_output_tokens(self) -> int:
        """Expose the delegate cap for compatibility with orchestration clients."""
        return int(self._delegate.max_output_tokens)

    @max_output_tokens.setter
    def max_output_tokens(self, value: int) -> None:
        """Forward explicit cap changes to the delegated model client."""
        self._delegate.max_output_tokens = value

    @property
    def remaining_tokens(self) -> int:
        """Return the non-negative token allowance remaining in this cell."""
        return max(0, self.total_token_budget - self.observed_tokens)

    @property
    def exceeded(self) -> bool:
        """Return whether observed usage crossed the configured allowance."""
        return self._exceeded

    @staticmethod
    def _coerce_usage_count(value: Any) -> int | None:
        """Return one valid non-negative provider token count, otherwise ``None``."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(value) or value < 0:
            return None
        return int(value)

    def chat(
        self,
        agent: ModelAgent,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
        top_p: float | None = None,
        effort_profile: ReasoningEffortProfile | None = None,
    ) -> str:
        """Perform one delegated call within the remaining cell allowance.

        Raises:
            PolicyTokenBudgetExceeded: If the call or token allowance is already
                exhausted or the prompt cannot fit.
        """
        if self._exceeded or self.observed_calls >= self.maximum_calls:
            raise PolicyTokenBudgetExceeded(
                "policy cell maximum-call allowance exhausted"
            )
        prompt_text = json.dumps(messages, ensure_ascii=False, sort_keys=True)
        prompt_tokens = estimate_tokens(prompt_text)
        output_allowance = self.remaining_tokens - prompt_tokens
        if output_allowance < 1:
            raise PolicyTokenBudgetExceeded(
                "policy cell total-token allowance exhausted"
            )

        output_cap = min(int(self._delegate.max_output_tokens), output_allowance)
        self.observed_calls += 1
        with self._delegate.request_settings(max_output_tokens=output_cap):
            answer = self._delegate.chat(
                agent,
                messages,
                temperature,
                top_p,
                effort_profile,
            )

        estimated_total = prompt_tokens + estimate_tokens(answer)
        self.observed_tokens += estimated_total
        self._pending_estimated_tokens = estimated_total
        self._exceeded = self.observed_tokens > self.total_token_budget
        return answer

    def take_usage(self) -> dict[str, Any] | None:
        """Return delegated usage and replace the latest estimate when valid."""
        usage = self._delegate.take_usage()
        pending_estimate = self._pending_estimated_tokens
        self._pending_estimated_tokens = None
        if pending_estimate is None or not isinstance(usage, dict):
            return usage
        prompt_tokens = self._coerce_usage_count(usage.get("prompt_tokens"))
        completion_tokens = self._coerce_usage_count(
            usage.get("completion_tokens")
        )
        if prompt_tokens is None or completion_tokens is None:
            return usage
        self.observed_tokens += prompt_tokens + completion_tokens - pending_estimate
        self._exceeded = self.observed_tokens > self.total_token_budget
        return usage


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
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
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
# Deterministic one-frame 16x16 H.264 MP4 generated once with bit-exact flags.
_TINY_MP4_BASE64 = """AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAALzbW9vdgAAAGxtdmhkAAAAAAAAAAAA
AAAAAAAD6AAAACgAAQAAAQAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAA
AABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAkJ0cmFrAAAAXHRraGQAAAADAAAA
AAAAAAAAAAABAAAAAAAAACgAAAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAA
AAAAAAAAAABAAAAAABAAAAAQAAAAAAAkZWR0cwAAABxlbHN0AAAAAAAAAAEAAAAoAAAAAAABAAAA
AAG6bWRpYQAAACBtZGhkAAAAAAAAAAAAAAAAAAAyAAAAAgBVxAAAAAAALWhkbHIAAAAAAAAAAHZp
ZGUAAAAAAAAAAAAAAABWaWRlb0hhbmRsZXIAAAABZW1pbmYAAAAUdm1oZAAAAAEAAAAAAAAAAAAA
ACRkaW5mAAAAHGRyZWYAAAAAAAAAAQAAAAx1cmwgAAAAAQAAASVzdGJsAAAAwXN0c2QAAAAAAAAA
AQAAALFhdmMxAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAABAAEABIAAAASAAAAAAAAAABDExhdmMg
bGlieDI2NAAAAAAAAAAAAAAAAAAAAAAAAAAAGP//AAAAN2F2Y0MBZAAK/+EAGWdkAAqscgRewEQA
AAMABAAAAwDIPEiWEYABAAdo6EOPEyEw/fj4AAAAABBwYXNwAAAAAQAAAAEAAAAUYnRydAAAAAAA
Ai3QAAAAAAAAABhzdHRzAAAAAAAAAAEAAAABAAACAAAAABxzdHNjAAAAAAAAAAEAAAABAAAAAQAA
AAEAAAAUc3RzegAAAAAAAALKAAAAAQAAABRzdGNvAAAAAAAAAAEAAAMjAAAAPXVkdGEAAAA1bWV0
YQAAAAAAAAAhaGRscgAAAAAAAAAAbWRpcmFwcGwAAAAAAAAAAAAAAAAIaWxzdAAAAAhmcmVlAAAC
0m1kYXQAAAKyBgX//67cRem95tlIt5Ys2CDZI+7veDI2NCAtIGNvcmUgMTY0IHIzMTA4IDMxZTE5
ZjkgLSBILjI2NC9NUEVHLTQgQVZDIGNvZGVjIC0gQ29weWxlZnQgMjAwMy0yMDIzIC0gaHR0cDov
L3d3dy52aWRlb2xhbi5vcmcveDI2NC5odG1sIC0gb3B0aW9uczogY2FiYWM9MSByZWY9MTYgZGVi
bG9jaz0xOi0zOi0zIGFuYWx5c2U9MHgzOjB4MTMzIG1lPXVtaCBzdWJtZT0xMCBwc3k9MSBwc3lf
cmQ9Mi4wMDowLjcwIG1peGVkX3JlZj0xIG1lX3JhbmdlPTI0IGNocm9tYV9tZT0xIHRyZWxsaXM9
MiA4eDhkY3Q9MSBjcW09MCBkZWFkem9uZT0yMSwxMSBmYXN0X3Bza2lwPTEgY2hyb21hX3FwX29m
ZnNldD0tNCB0aHJlYWRzPTEgbG9va2FoZWFkX3RocmVhZHM9MSBzbGljZWRfdGhyZWFkcz0wIG5y
PTAgZGVjaW1hdGU9MSBpbnRlcmxhY2VkPTAgYmx1cmF5X2NvbXBhdD0wIGNvbnN0cmFpbmVkX2lu
dHJhPTAgYmZyYW1lcz04IGJfcHlyYW1pZD0yIGJfYWRhcHQ9MiBiX2JpYXM9MCBkaXJlY3Q9MyB3
ZWlnaHRiPTEgb3Blbl9nb3A9MCB3ZWlnaHRwPTIga2V5aW50PTI1MCBrZXlpbnRfbWluPTI1IHNj
ZW5lY3V0PTQwIGludHJhX3JlZnJlc2g9MCByY19sb29rYWhlYWQ9NjAgcmM9Y3JmIG1idHJlZT0x
IGNyZj0yMy4wIHFjb21wPTAuNjAgcXBtaW49MCBxcG1heD02OSBxcHN0ZXA9NCBpcF9yYXRpbz0x
LjQwIGFxPTE6MS4yMACAAAAAEGWIgQAG5z/+9vD+BTZWBME="""
VIDEO_PROBE_FIXTURE_SHA256 = "777dda43b5a15162b68a39aa486d5c70c9994d7fe761742fd00d4e13508983c0"
_MULTIPART_BOUNDARY = "nim-benchmark-boundary-7f3a1c"
_MP4_CONTAINER_BOX_TYPES = frozenset(
    {b"moov", b"trak", b"mdia", b"minf", b"dinf", b"stbl", b"edts", b"udta"}
)


def _iter_mp4_boxes(
    data: bytes,
    start_offset: int = 0,
    end_offset: int | None = None,
):
    """Yield validated ISO-BMFF boxes as type and payload/end offsets.

    Args:
        data: Complete MP4 bytes.
        start_offset: First byte of the bounded box sequence.
        end_offset: Exclusive sequence end, defaulting to ``len(data)``.

    Yields:
        Tuples of ``(box_type, payload_start, box_end)``.

    Raises:
        BenchmarkContractError: If box headers, sizes, or bounds are malformed.
    """
    sequence_end = len(data) if end_offset is None else end_offset
    offset = start_offset
    while offset < sequence_end:
        if sequence_end - offset < 8:
            raise BenchmarkContractError("video probe MP4 has a truncated box header")
        box_size = struct.unpack(">I", data[offset : offset + 4])[0]
        box_type = data[offset + 4 : offset + 8]
        header_size = 8
        if box_size == 1:
            if sequence_end - offset < 16:
                raise BenchmarkContractError("video probe MP4 has a truncated extended box")
            box_size = struct.unpack(">Q", data[offset + 8 : offset + 16])[0]
            header_size = 16
        elif box_size == 0:
            box_size = sequence_end - offset
        if box_size < header_size or offset + box_size > sequence_end:
            raise BenchmarkContractError("video probe MP4 box exceeds its parent bounds")
        payload_start = offset + header_size
        box_end = offset + box_size
        yield box_type, payload_start, box_end
        offset = box_end


def _walk_mp4_boxes(data: bytes):
    """Yield every validated box in the deterministic video fixture."""

    def walk(start_offset: int, end_offset: int):
        """Recursively traverse known ISO-BMFF container boxes."""
        for box_type, payload_start, box_end in _iter_mp4_boxes(
            data,
            start_offset,
            end_offset,
        ):
            yield box_type, payload_start, box_end
            if box_type in _MP4_CONTAINER_BOX_TYPES:
                yield from walk(payload_start, box_end)
            elif box_type == b"meta":
                if box_end - payload_start < 4:
                    raise BenchmarkContractError(
                        "video probe MP4 meta box lacks full-box flags"
                    )
                yield from walk(payload_start + 4, box_end)

    yield from walk(0, len(data))


def validate_video_probe_fixture(data: bytes) -> dict[str, Any]:
    """Validate one H.264 video stream, dimensions, and frame count.

    Args:
        data: Candidate ISO-BMFF/MP4 bytes.

    Returns:
        Codec, width, height, and frame count for the single video stream.

    Raises:
        BenchmarkContractError: If required boxes or one-frame video evidence is
            missing, inconsistent, or malformed.
    """
    top_level_types = {box_type for box_type, _, _ in _iter_mp4_boxes(data)}
    if not {b"ftyp", b"moov", b"mdat"} <= top_level_types:
        raise BenchmarkContractError("video probe MP4 lacks ftyp, moov, or mdat")

    width: int | None = None
    height: int | None = None
    frame_count: int | None = None
    video_handler_count = 0
    codec_name: str | None = None
    for box_type, payload_start, box_end in _walk_mp4_boxes(data):
        payload = data[payload_start:box_end]
        if box_type == b"tkhd":
            if len(payload) < 8:
                raise BenchmarkContractError("video probe MP4 tkhd box is truncated")
            width_fixed, height_fixed = struct.unpack(">II", payload[-8:])
            width = width_fixed >> 16
            height = height_fixed >> 16
        elif box_type == b"hdlr" and len(payload) >= 12:
            if payload[8:12] == b"vide":
                video_handler_count += 1
        elif box_type == b"stsz":
            if len(payload) < 12:
                raise BenchmarkContractError("video probe MP4 stsz box is truncated")
            frame_count = struct.unpack(">I", payload[8:12])[0]
        elif box_type == b"stsd" and b"avc1" in payload:
            codec_name = "h264"

    metadata = {
        "codec_name": codec_name,
        "width": width,
        "height": height,
        "frame_count": frame_count,
    }
    expected = {
        "codec_name": "h264",
        "width": 16,
        "height": 16,
        "frame_count": 1,
    }
    if video_handler_count != 1 or metadata != expected:
        raise BenchmarkContractError(
            f"video probe MP4 must contain one 16x16 one-frame H.264 stream: {metadata}"
        )
    return metadata


def _tiny_mp4_bytes() -> bytes:
    """Return the validated deterministic one-frame MP4 probe fixture."""
    fixture = base64.b64decode("".join(_TINY_MP4_BASE64.split()), validate=True)
    if hashlib.sha256(fixture).hexdigest() != VIDEO_PROBE_FIXTURE_SHA256:
        raise BenchmarkContractError("video probe MP4 checksum does not match")
    validate_video_probe_fixture(fixture)
    return fixture


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
    """Return a data URI containing the validated one-frame MP4 fixture."""
    return f"data:video/mp4;base64,{base64.b64encode(_tiny_mp4_bytes()).decode('ascii')}"


def _audio_probe_base64() -> str:
    """Base64 WAV payload used by the omni-style audio-understanding probe."""
    return base64.b64encode(_tiny_wav_bytes()).decode("ascii")


def _build_capability_probes() -> dict[str, dict[str, Any]]:
    """Registry of every probe contract, in the fixed order they are attempted.

    Each spec: ``path``, ``content_type``, ``body`` (model_id -> bytes),
    ``validate`` (decoded JSON -> bool), and ``binary_response`` for endpoints
    that answer with raw media instead of JSON. A deterministic validated media fixture is used for each modality; only an
    HTTP 200 with the expected response shape counts as contract support.
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
    if status in (401, 403):
        return "auth_rejected"
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
    """Probe every model with deterministic allocation and bounded concurrency.

    The permitted ``(model_id, capability)`` cells are fixed in sorted catalog
    and capability order before worker threads start. Thread scheduling can
    change completion order but cannot choose which cells run.

    Args:
        models: Discovered model rows containing ``model_id`` and ``owned_by``.
        transport: Provider request seam.
        endpoint: OpenAI-compatible provider base endpoint.
        api_key: In-memory credential value, never serialized.
        request_budget: Shared hard provider-call cap.
        probe_concurrency: Maximum simultaneous model workers.
        clock: Provenance timestamp source.
        timer: Per-probe monotonic latency source.

    Returns:
        Sorted model rows with complete capability evidence for every model.

    Raises:
        BenchmarkContractError: If concurrency is boolean or not positive.
    """
    if (
        isinstance(probe_concurrency, bool)
        or not isinstance(probe_concurrency, int)
        or probe_concurrency < 1
    ):
        raise BenchmarkContractError("probe_concurrency must be a positive integer")

    sorted_models = sorted(models, key=lambda row: row["model_id"])
    required_probe_requests = len(sorted_models) * len(CAPABILITY_PROBE_ORDER)
    if required_probe_requests > request_budget.remaining_requests:
        raise BenchmarkBudgetError(
            f"complete capability probe plan needs {required_probe_requests} "
            f"requests but only {request_budget.remaining_requests} remain"
        )

    def probe_one(model: dict[str, Any]) -> dict[str, Any]:
        """Execute every preflighted capability cell for one model."""
        rows: list[dict[str, Any]] = []
        for capability_name in CAPABILITY_PROBE_ORDER:
            request_budget.spend_or_fail()
            rows.append(
                execute_capability_probe(
                    transport,
                    endpoint,
                    api_key,
                    model["model_id"],
                    capability_name,
                    timer,
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
        results = list(executor.map(probe_one, sorted_models))
    return results


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


def _normalize_expected_text(value: str, *, case_sensitive: bool) -> str:
    """Canonicalize one expected text value for exact or containment checks."""
    normalized = value.strip()
    return normalized if case_sensitive else normalized.casefold()


def _text_match_candidates(expected: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Return case sensitivity plus the declared expected text candidates."""
    case_sensitive = bool(expected.get("strict_case_sensitive"))
    strict_texts = expected.get("strict_texts")
    if isinstance(strict_texts, list) and strict_texts:
        values = tuple(str(value) for value in strict_texts)
    else:
        values = (str(expected["substring"]),)
    return case_sensitive, values


def expected_text_leaks(expected: dict[str, Any], prompt_text: str) -> bool:
    """Return ``True`` when any declared expected text appears inside the prompt."""
    case_sensitive, candidates = _text_match_candidates(expected)
    haystack = _normalize_expected_text(prompt_text, case_sensitive=case_sensitive)
    for candidate in candidates:
        if _normalize_expected_text(candidate, case_sensitive=case_sensitive) in haystack:
            return True
    return False


def score_substring_match(expected: dict[str, Any], answer_text: str) -> float:
    """Score declared text answers with optional case-sensitive exact matching."""
    case_sensitive, candidates = _text_match_candidates(expected)
    normalized_answer = _normalize_expected_text(answer_text, case_sensitive=case_sensitive)
    strict_texts = expected.get("strict_texts")
    if isinstance(strict_texts, list) and strict_texts:
        normalized_candidates = {
            _normalize_expected_text(candidate, case_sensitive=case_sensitive)
            for candidate in candidates
        }
        return 1.0 if normalized_answer in normalized_candidates else 0.0
    needle = _normalize_expected_text(str(expected["substring"]), case_sensitive=case_sensitive)
    return 1.0 if needle in normalized_answer else 0.0


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
        if scorer_key == ("substring_match", "1"):
            leaked = expected_text_leaks(expected, prompt)
        else:
            leaked = SCORER_REGISTRY[scorer_key](expected, prompt) != 0.0
        if leaked:
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


_REVIEWED_PRICING_FIELDS = (
    "source_url",
    "reviewed_by",
    "reviewed_at_date",
    "valid_until_date",
    "rate_basis",
    "uncertainty",
)


def _parse_evidence_date(value: Any, field_name: str) -> datetime_module.date:
    """Parse one ISO evidence date or raise a field-specific contract error."""
    if not isinstance(value, str):
        raise BenchmarkContractError(
            f"pricing scenario {field_name} must be an ISO date string"
        )
    try:
        return datetime_module.date.fromisoformat(value)
    except ValueError as exc:
        raise BenchmarkContractError(
            f"pricing scenario {field_name} must be a valid ISO date"
        ) from exc


def _validate_reviewed_pricing_metadata(scenario: dict[str, Any]) -> None:
    """Require complete provenance for a scenario labeled ``reviewed``."""
    missing = [field for field in _REVIEWED_PRICING_FIELDS if field not in scenario]
    if missing:
        raise BenchmarkContractError(
            f"reviewed pricing scenario is missing fields: {missing}"
        )
    parsed_source = urllib.parse.urlparse(str(scenario["source_url"]))
    if parsed_source.scheme != "https" or not parsed_source.hostname:
        raise BenchmarkContractError(
            "reviewed pricing scenario source_url must use https"
        )
    for field_name in ("reviewed_by", "rate_basis", "uncertainty"):
        value = scenario[field_name]
        if not isinstance(value, str) or not value.strip():
            raise BenchmarkContractError(
                f"reviewed pricing scenario {field_name} must be non-empty"
            )
    reviewed_at = _parse_evidence_date(scenario["reviewed_at_date"], "reviewed_at_date")
    valid_until = _parse_evidence_date(scenario["valid_until_date"], "valid_until_date")
    if valid_until < reviewed_at:
        raise BenchmarkContractError(
            "reviewed pricing scenario valid_until_date precedes reviewed_at_date"
        )


def validate_live_pricing_scenario(
    scenario: dict[str, Any] | None,
    today: datetime_module.date | None = None,
) -> None:
    """Fail before egress when supplied live price evidence is not current.

    Omitting a scenario is valid and leaves every hypothetical cost ``unknown``.
    Supplying one requires an explicit reviewed status, complete provenance, and
    a validity horizon that includes the run date.
    """
    if scenario is None:
        return
    if scenario.get("scenario_status") != "reviewed":
        raise BenchmarkContractError(
            "live benchmark pricing scenario must be independently reviewed"
        )
    _validate_reviewed_pricing_metadata(scenario)
    observed_date = today or datetime_module.date.today()
    reviewed_at = _parse_evidence_date(scenario["reviewed_at_date"], "reviewed_at_date")
    valid_until = _parse_evidence_date(scenario["valid_until_date"], "valid_until_date")
    if reviewed_at > observed_date:
        raise BenchmarkContractError("reviewed pricing evidence is dated in the future")
    if observed_date > valid_until:
        raise BenchmarkContractError("reviewed pricing evidence expired")


def load_pricing_scenario(path: str | None) -> dict[str, Any] | None:
    """Load and validate one explicit hypothetical price-assumption file.

    ``None`` is legal and keeps hypothetical costs ``unknown``. Rates are never
    inferred: only finite non-negative input/output USD-per-million-token values
    explicitly present in the supplied file are accepted. A scenario labeled
    ``reviewed`` must also carry complete source and validity metadata.

    Args:
        path: JSON scenario path, or ``None`` to omit paid-cost assumptions.

    Returns:
        Validated scenario dictionary or ``None``.

    Raises:
        BenchmarkContractError: If JSON, status, provenance, or rates are invalid.
    """
    if path is None:
        return None
    with open(path, "r", encoding="utf-8") as handle:
        try:
            scenario = json.load(handle)
        except ValueError as exc:
            raise BenchmarkContractError(
                f"pricing scenario is not valid JSON: {exc}"
            ) from exc
    if not isinstance(scenario, dict) or not isinstance(
        scenario.get("scenario_version"), str
    ):
        raise BenchmarkContractError(
            "pricing scenario must be an object with a string 'scenario_version'"
        )
    if scenario.get("scenario_status") not in ("example_unreviewed", "reviewed"):
        raise BenchmarkContractError(
            "pricing scenario_status must be 'example_unreviewed' or 'reviewed'"
        )
    rates = scenario.get("usd_per_million_tokens")
    if not isinstance(rates, dict):
        raise BenchmarkContractError(
            "pricing scenario must carry a 'usd_per_million_tokens' object"
        )
    for model_id, rate in rates.items():
        if not isinstance(model_id, str) or not model_id.strip():
            raise BenchmarkContractError("pricing model id must be a non-empty string")
        if not isinstance(rate, dict):
            raise BenchmarkContractError(
                f"pricing entry for {model_id!r} must be an object"
            )
        _require_finite_rate(rate.get("input"), f"{model_id}.input")
        _require_finite_rate(rate.get("output"), f"{model_id}.output")
    if scenario["scenario_status"] == "reviewed":
        _validate_reviewed_pricing_metadata(scenario)
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

    Direct baselines, ``route_once``, and cheapest-eligible cells each reserve
    one worker call plus one real-time judge call. ``route_once`` reserves the
    full equal-call envelope because endpoint races and future failover may use
    more than one worker attempt. ``conduct`` reserves its five-step workflow
    envelope, including the model judge.
    """
    return locked_task_count * (
        worker_count * 2 + MAX_WORKFLOW_DEPTH + MAX_WORKFLOW_DEPTH + 2
    )


def plan_complete_request_budget(
    discovered_model_count: int,
    max_eval_models: int,
    locked_task_count: int,
) -> dict[str, int]:
    """Return the complete conservative request plan for one catalog snapshot.

    The plan reserves one catalog request, every model-capability probe, and
    the worst-case equal-budget evaluation envelope for every worker that may
    enter the capped evaluation pool. It is intentionally conservative: fewer
    chat-eligible or scenario-priced workers may leave requests unused, but a
    live run never starts a biased partial probe phase.

    Args:
        discovered_model_count: Usable model ids returned by ``/v1/models``.
        max_eval_models: Maximum workers allowed into policy evaluation.
        locked_task_count: Number of locked benchmark tasks.

    Returns:
        Named request counts including the complete run total.

    Raises:
        BenchmarkContractError: If any count is boolean or not positive.
    """
    counts = {
        "discovered_model_count": discovered_model_count,
        "max_eval_models": max_eval_models,
        "locked_task_count": locked_task_count,
    }
    for label, value in counts.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise BenchmarkContractError(
                f"{label} must be a positive integer"
            )
    planned_worker_count = min(discovered_model_count, max_eval_models)
    capability_probe_request_count = (
        discovered_model_count * len(CAPABILITY_PROBE_ORDER)
    )
    evaluation_reserve_request_count = planned_evaluation_requests(
        planned_worker_count,
        locked_task_count,
    )
    return {
        "catalog_request_count": 1,
        "capability_probe_request_count": capability_probe_request_count,
        "evaluation_reserve_request_count": evaluation_reserve_request_count,
        "planned_worker_count": planned_worker_count,
        "total_required_request_count": (
            1
            + capability_probe_request_count
            + evaluation_reserve_request_count
        ),
    }


def planned_complete_run_requests(
    model_count: int,
    locked_task_count: int,
    max_eval_models: int,
) -> dict[str, int]:
    """Return buyer-facing request counts for a complete benchmark run.

    This stable planning view translates the internal conservative preflight
    into terminology used by release acceptance, operator documentation, and
    acquisition evidence. Validation remains centralized in
    :func:`plan_complete_request_budget`, so both views fail closed identically.

    Args:
        model_count: Usable model identifiers discovered from ``/v1/models``.
        locked_task_count: Number of locked evaluation tasks.
        max_eval_models: Maximum workers admitted to policy comparison.

    Returns:
        Catalog, capability, evaluation, post-catalog, and total request counts.
    """
    plan = plan_complete_request_budget(
        discovered_model_count=model_count,
        max_eval_models=max_eval_models,
        locked_task_count=locked_task_count,
    )
    requests_after_catalog = (
        plan["capability_probe_request_count"]
        + plan["evaluation_reserve_request_count"]
    )
    return {
        "catalog_discovery_requests": plan["catalog_request_count"],
        "capability_probe_requests": plan["capability_probe_request_count"],
        "evaluation_worker_ceiling": plan["planned_worker_count"],
        "evaluation_requests": plan["evaluation_reserve_request_count"],
        "requests_after_catalog": requests_after_catalog,
        "total_requests": plan["total_required_request_count"],
    }


def evaluate_policies(
    agents: list[ModelAgent],
    manifest: dict[str, Any],
    pricing_scenario: dict[str, Any] | None,
    client: ModelClient,
    request_budget: RequestBudget,
    timer: Callable[[], float] = time.perf_counter,
    total_token_budget: int = 256,
    maximum_calls: int = MAX_WORKFLOW_DEPTH,
) -> dict[str, Any]:
    """Run every compared policy with equal cell-level token and call budgets.

    Every policy/task cell receives a fresh orchestrator and limiter so traces,
    usage, call counts, and allowances never bleed across tasks or policy arms.

    Args:
        agents: Chat-eligible workers selected from capability probes.
        manifest: Validated task manifest.
        pricing_scenario: Optional explicit hypothetical price assumptions.
        client: Shared request-budgeted model client.
        request_budget: Complete-run provider request cap.
        timer: Monotonic latency source.
        total_token_budget: Equal prompt-plus-completion allowance per cell.
        maximum_calls: Equal declared provider-call envelope per cell.

    Returns:
        Evaluation cells and pool/task metadata.

    Raises:
        BenchmarkContractError: If no workers or locked tasks are available.
        BenchmarkBudgetError: If the complete evaluation cannot fit the run cap.
    """
    if not agents:
        raise BenchmarkContractError(
            "policy evaluation requires at least one chat-eligible worker"
        )
    tasks = locked_evaluation_tasks(manifest)
    if not tasks:
        raise BenchmarkContractError("task manifest has no locked evaluation tasks")
    planned = planned_evaluation_requests(len(agents), len(tasks))
    if planned > request_budget.remaining_requests:
        raise BenchmarkBudgetError(
            f"planned evaluation needs up to {planned} requests but only "
            f"{request_budget.remaining_requests} remain in the budget"
        )

    agents_by_id = {agent.id: agent.model for agent in agents}
    depth_policy = dataclasses.replace(
        OrchestrationPolicy(),
        max_workflow_steps=MAX_WORKFLOW_DEPTH,
    )

    def run_cell(
        policy_name: str,
        task: dict[str, Any],
        pool: list[ModelAgent],
        mode: str,
    ) -> dict[str, Any]:
        """Run one independent policy/task cell and append budget evidence."""
        cell_client = EqualBudgetModelClient(
            client,
            total_token_budget,
            maximum_calls,
        )
        orchestrator = TaskOrchestrator(
            pool,
            client=cell_client,
            tool_retry_attempts=0,
        )
        orchestrator.policy = depth_policy
        cell = run_policy_cell(
            policy_name,
            task,
            lambda: orchestrator.complete(
                [{"role": "user", "content": task["prompt"]}],
                mode=mode,
            ),
            agents_by_id,
            pricing_scenario,
            timer,
        )
        cell.update(
            {
                "configured_total_token_budget": total_token_budget,
                "configured_maximum_calls": maximum_calls,
                "observed_budget_tokens": cell_client.observed_tokens,
                "observed_budget_calls": cell_client.observed_calls,
                "remaining_budget_tokens": cell_client.remaining_tokens,
            }
        )
        if cell_client.exceeded:
            cell["run_outcome"] = "failure"
            cell["outcome_reason"] = "observed_usage_exceeded_equal_token_budget"
            cell["task_score"] = None
        return cell

    cells: list[dict[str, Any]] = []
    for agent in agents:
        for task in tasks:
            cells.append(
                run_cell(
                    f"direct_single_worker:{agent.model}",
                    task,
                    [agent],
                    "route",
                )
            )
    for task in tasks:
        cells.append(run_cell("route_once", task, agents, "route"))
        cells.append(run_cell("conduct_bounded", task, agents, "conduct"))

    cheapest_skip_reason = None
    cheapest = cheapest_priced_agent(agents, pricing_scenario)
    if cheapest is None:
        cheapest_skip_reason = (
            "no_pricing_scenario_supplied"
            if pricing_scenario is None
            else "no_worker_priced_by_scenario"
        )
    else:
        for task in tasks:
            cells.append(
                run_cell(
                    "cheapest_eligible_worker",
                    task,
                    [cheapest],
                    "route",
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
    successful = [row for row in summaries if row["success_count"] > 0]
    return {
        "quality_vs_latency": pareto_frontier(
            successful,
            "mean_task_score",
            "mean_latency_ms",
        ),
        "quality_vs_hypothetical_cost": pareto_frontier(
            _numeric_cost_rows(successful),
            "mean_task_score",
            "mean_hypothetical_cost_usd",
        ),
        "excluded_unknown_cost_policies": sorted(
            row["policy_name"]
            for row in successful
            if not isinstance(row["mean_hypothetical_cost_usd"], float)
        ),
        "excluded_zero_success_policies": sorted(
            row["policy_name"] for row in summaries if row["success_count"] == 0
        ),
    }


def _validate_actual_cost_evidence(report: dict[str, Any]) -> None:
    """Require complete official provenance for the zero access-cost claim."""
    evidence = report.get("actual_cost_evidence")
    if not isinstance(evidence, dict):
        raise BenchmarkContractError(
            "benchmark report is missing actual_cost_evidence"
        )
    required_fields = (
        "evidence_schema_version",
        "source_title",
        "source_url",
        "reviewed_at_date",
        "valid_until_date",
        "access_program",
        "access_scope",
        "production_access_note",
        "actual_cost_usd",
        "uncertainty",
    )
    missing = [field for field in required_fields if field not in evidence]
    if missing:
        raise BenchmarkContractError(
            f"actual cost evidence is missing fields: {missing}"
        )
    if evidence["actual_cost_usd"] != 0.0:
        raise BenchmarkContractError(
            "actual cost evidence must preserve the reviewed zero-cost value"
        )
    if evidence["source_url"] != "https://docs.api.nvidia.com/nim/docs/product":
        raise BenchmarkContractError(
            "actual cost evidence must cite the reviewed NVIDIA NIM General FAQ"
        )
    reviewed_at = _parse_evidence_date(evidence["reviewed_at_date"], "reviewed_at_date")
    valid_until = _parse_evidence_date(evidence["valid_until_date"], "valid_until_date")
    if valid_until < reviewed_at:
        raise BenchmarkContractError(
            "actual cost evidence validity precedes its review date"
        )


def _require_current_actual_cost_evidence(
    today: datetime_module.date | None = None,
) -> None:
    """Fail closed after the reviewed hosted-access validity horizon."""
    observed_date = today or datetime_module.date.today()
    reviewed_at = _parse_evidence_date(
        ACTUAL_COST_EVIDENCE["reviewed_at_date"],
        "reviewed_at_date",
    )
    valid_until = _parse_evidence_date(
        ACTUAL_COST_EVIDENCE["valid_until_date"],
        "valid_until_date",
    )
    if observed_date < reviewed_at:
        raise BenchmarkContractError(
            "reviewed NVIDIA hosted-endpoint cost evidence is dated in the future"
        )
    if observed_date > valid_until:
        raise BenchmarkContractError(
            "reviewed NVIDIA hosted-endpoint cost evidence expired; "
            "re-review official terms"
        )


def _evaluation_evidence_summary(
    cells: list[dict[str, Any]],
    locked_task_count: int,
) -> dict[str, Any]:
    """Classify whether benchmark evidence can inform production review."""
    successful_cells = [cell for cell in cells if cell["run_outcome"] == "success"]
    completion_fraction = (
        round(len(successful_cells) / len(cells), 6) if cells else 0.0
    )
    successful_tasks_by_policy: dict[str, set[str]] = {}
    for cell in successful_cells:
        successful_tasks_by_policy.setdefault(cell["policy_name"], set()).add(
            cell["task_id"]
        )
    paired_task_ids = successful_tasks_by_policy.get("route_once", set()) & (
        successful_tasks_by_policy.get("conduct_bounded", set())
    )
    sufficient = (
        locked_task_count >= MINIMUM_PAIRED_TASK_COUNT
        and len(paired_task_ids) >= MINIMUM_PAIRED_TASK_COUNT
        and completion_fraction >= REQUIRED_COMPLETION_FRACTION
    )
    return {
        "evidence_status": (
            "evidence_review_required" if sufficient else "insufficient_evidence"
        ),
        "decision_use": (
            "production_candidate_review" if sufficient else "benchmark_smoke_only"
        ),
        "minimum_paired_task_count": MINIMUM_PAIRED_TASK_COUNT,
        "required_completion_fraction": REQUIRED_COMPLETION_FRACTION,
        "observed_locked_task_count": locked_task_count,
        "observed_paired_task_count": len(paired_task_ids),
        "observed_completion_fraction": completion_fraction,
        "routing_recommendation": None,
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
    "evaluation.evidence_status",
    "evaluation.decision_use",
    "evaluation.minimum_paired_task_count",
    "evaluation.required_completion_fraction",
    "evaluation.observed_paired_task_count",
    "evaluation.observed_completion_fraction",
    "evaluation.routing_recommendation",
    "request_budget.max_total_requests",
    "request_budget.requests_spent",
    "request_budget.planned_total_requests",
    "request_budget.catalog_requests",
    "request_budget.capability_probe_requests",
    "request_budget.evaluation_reserve_requests",
    "request_budget.planned_worker_count",
    "actual_cost_evidence",
    "honesty_labels.actual_cost_basis",
    "honesty_labels.provider_latency_source",
    "honesty_labels.hypothetical_cost_source",
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
    "configured_total_token_budget",
    "configured_maximum_calls",
    "observed_budget_tokens",
    "observed_budget_calls",
    "remaining_budget_tokens",
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
    """Render a buyer-readable summary with evidence and cost caveats."""
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
        f"- complete request plan: {report['request_budget']['planned_total_requests']} "
        "(catalog + all capability probes + evaluation reserve)",
        f"- evidence status: `{report['evaluation']['evidence_status']}`",
        f"- decision use: `{report['evaluation']['decision_use']}`",
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
            f"| {row['policy_name']} | {row['mean_task_score']} | "
            f"{row['mean_latency_ms']} | {row['mean_hypothetical_cost_usd']} "
            f"| {row['actual_cost_usd']} |"
        )
    lines += ["", "## Paired comparisons (95% bootstrap CI)", ""]
    for comparison in report["evaluation"]["paired_comparisons"]:
        lines.append(
            f"- `{comparison['policy_a']}` vs `{comparison['policy_b']}`: "
            f"mean diff {comparison['mean_difference']} "
            f"[{comparison['ci_low']}, {comparison['ci_high']}]"
        )
    evidence = report["actual_cost_evidence"]
    lines += [
        "",
        "## Evidence sufficiency",
        "",
        f"- paired tasks: {report['evaluation']['observed_paired_task_count']} "
        f"/ {report['evaluation']['minimum_paired_task_count']} required",
        f"- completion fraction: {report['evaluation']['observed_completion_fraction']} "
        f"/ {report['evaluation']['required_completion_fraction']} required",
        "- production routing recommendation: none"
        if report["evaluation"]["routing_recommendation"] is None
        else f"- production routing recommendation: {report['evaluation']['routing_recommendation']}",
        "",
        "## Actual API access-cost evidence",
        "",
        f"- source: {evidence['source_title']}",
        f"- reviewed: {evidence['reviewed_at_date']}",
        f"- valid until: {evidence['valid_until_date']}",
        f"- access context: {evidence['access_program']} — {evidence['access_scope']}",
        f"- production distinction: {evidence['production_access_note']}",
        f"- uncertainty: {evidence['uncertainty']}",
        "",
        "## Honesty labels",
        "",
        f"- actual cost basis: {report['honesty_labels']['actual_cost_basis']}",
        f"- provider latency: {report['honesty_labels']['provider_latency_source']}",
        f"- hypothetical cost source: {report['honesty_labels']['hypothetical_cost_source']}",
        "",
    ]
    return "\n".join(lines)


def write_benchmark_artifacts(
    report: dict[str, Any],
    output_dir: str,
) -> dict[str, str]:
    """Validate cost evidence and schema, then write JSON, CSV, and Markdown."""
    _validate_actual_cost_evidence(report)
    validate_report_schema(report)
    os.makedirs(output_dir, exist_ok=True)
    json_text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    _ensure_secret_absent(json_text)
    json_path = os.path.join(output_dir, "benchmark_report.json")
    with open(json_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json_text + "\n")

    csv_path = os.path.join(output_dir, "benchmark_cells.csv")
    csv_buffer = io.StringIO()
    writer = csv.DictWriter(
        csv_buffer,
        fieldnames=_CSV_CELL_COLUMNS,
        extrasaction="ignore",
    )
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
    return {
        "json_path": json_path,
        "csv_path": csv_path,
        "markdown_path": markdown_path,
    }


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
    """Assemble and validate the complete evidence-grade benchmark report."""
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
    evidence_summary = _evaluation_evidence_summary(
        cells,
        evaluation["locked_task_count"],
    )
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
            "cheapest_worker_skip_reason": evaluation[
                "cheapest_worker_skip_reason"
            ],
            "locked_task_count": evaluation["locked_task_count"],
            "worker_count": evaluation["worker_count"],
            **evidence_summary,
        },
        "request_budget": {
            "max_total_requests": request_budget.max_total_requests,
            "requests_spent": request_budget.requests_spent,
            "planned_total_requests": provenance_inputs["request_plan"][
                "total_required_request_count"
            ],
            "catalog_requests": provenance_inputs["request_plan"][
                "catalog_request_count"
            ],
            "capability_probe_requests": provenance_inputs["request_plan"][
                "capability_probe_request_count"
            ],
            "evaluation_reserve_requests": provenance_inputs["request_plan"][
                "evaluation_reserve_request_count"
            ],
            "planned_worker_count": provenance_inputs["request_plan"][
                "planned_worker_count"
            ],
        },
        "actual_cost_evidence": dict(ACTUAL_COST_EVIDENCE),
        "honesty_labels": {
            "actual_cost_basis": (
                "deterministic_dry_run_no_provider_egress"
                if run_mode == "dry_run"
                else "reviewed_nvidia_developer_program_hosted_endpoint_access"
            ),
            "provider_latency_source": (
                "not_observable_via_openai_compatible_body"
            ),
            "hypothetical_cost_source": (
                "explicit_versioned_pricing_scenario_or_unknown"
            ),
            "dry_run_scores_note": (
                "dry-run scores reflect deterministic mock echoes, not model quality"
            ),
        },
    }
    _validate_actual_cost_evidence(report)
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
    max_total_requests: int = 2000,
    probe_concurrency: int = 4,
    timeout_seconds: float = 60.0,
    max_output_tokens: int = 256,
    max_eval_models: int = 7,
    seed: int = 7,
    git_sha: str = "",
    workflow_run_id: str = "",
    transport: ProviderTransport | None = None,
) -> dict[str, Any]:
    """Run the complete benchmark in deterministic dry or evidence-gated live mode.

    Live evidence, optional paid-price provenance, and run identity are validated
    before any provider transport can execute. Dry runs use an in-process provider
    and never need or read the NVIDIA credential.

    Args:
        run_mode: ``dry_run`` or ``live``.
        task_manifest_path: Versioned locked/exploratory task manifest.
        pricing_scenario_path: Optional explicit hypothetical pricing scenario.
        output_dir: Destination for JSON, CSV, and Markdown artifacts.
        endpoint: OpenAI-compatible provider endpoint.
        max_total_requests: Complete-run provider request cap.
        probe_concurrency: Maximum concurrent model probe workers.
        timeout_seconds: Per-address network timeout.
        max_output_tokens: Equal per-cell prompt-plus-completion token budget.
        max_eval_models: Maximum chat-eligible workers in policy evaluation.
        seed: Deterministic bootstrap seed.
        git_sha: Exact source revision, required live.
        workflow_run_id: Workflow provenance identifier, required live.
        transport: Optional injected provider transport for deterministic tests.

    Returns:
        Complete report including written artifact paths.

    Raises:
        BenchmarkContractError: If mode, evidence, or parameters are invalid.
        NotConfigured: If a live run cannot resolve its KV credential.
    """
    if run_mode not in ("dry_run", "live"):
        raise BenchmarkContractError(
            f"run_mode must be 'dry_run' or 'live', not {run_mode!r}"
        )
    manifest = load_task_manifest(task_manifest_path)
    pricing_scenario = load_pricing_scenario(pricing_scenario_path)
    if run_mode == "live":
        if not git_sha or not workflow_run_id:
            raise BenchmarkContractError(
                "live runs require --git-sha and --workflow-run-id provenance"
            )
        _require_current_actual_cost_evidence()
        validate_live_pricing_scenario(pricing_scenario)
    request_budget = RequestBudget(max_total_requests)

    if run_mode == "dry_run":
        api_key = "dry-run-placeholder-not-a-secret"
        active_transport = transport or build_dry_run_transport()

        def dry_run_clock() -> float:
            """Return the fixed timestamp used by deterministic dry runs."""
            return DRY_RUN_FIXED_UNIX_TIME

        def dry_run_probe_timer() -> float:
            """Return a zero-duration probe clock for deterministic evidence."""
            return 0.0

        clock: Callable[[], float] = dry_run_clock
        probe_timer: Callable[[], float] = dry_run_probe_timer
        timer = _deterministic_timer()
        eval_base_url = "mock://nim-dry-run"
        eval_client: ModelClient = _BudgetedModelClient(
            request_budget,
            transport=active_transport,
            max_output_tokens=max_output_tokens,
        )
    else:
        api_key = get_credential(NIM_CREDENTIAL_NAME) or ""
        if not api_key:
            raise NotConfigured(
                f"live benchmark requires the '{NIM_CREDENTIAL_NAME}' credential "
                "in the KV; seed it via register-credential bootstrap (never argv)"
            )
        active_transport = transport or build_default_transport(timeout_seconds)
        clock = time.time
        probe_timer = time.perf_counter
        timer = time.perf_counter
        eval_base_url = endpoint
        eval_client = _BudgetedModelClient(
            request_budget,
            transport=active_transport,
            timeout=float(timeout_seconds),
            max_output_tokens=max_output_tokens,
        )

    benchmark_parameters = {
        "endpoint": endpoint,
        "max_total_requests": max_total_requests,
        "probe_concurrency": probe_concurrency,
        "timeout_seconds": timeout_seconds,
        "max_output_tokens": max_output_tokens,
        "max_eval_models": max_eval_models,
        "max_workflow_depth": MAX_WORKFLOW_DEPTH,
        "policy_total_token_budget": max_output_tokens,
        "policy_maximum_calls": MAX_WORKFLOW_DEPTH,
        "minimum_paired_task_count": MINIMUM_PAIRED_TASK_COUNT,
        "required_completion_fraction": REQUIRED_COMPLETION_FRACTION,
        "seed": seed,
        "task_manifest_version": manifest["manifest_version"],
        "pricing_scenario_version": (
            pricing_scenario["scenario_version"] if pricing_scenario else None
        ),
        "pricing_scenario_status": (
            pricing_scenario["scenario_status"] if pricing_scenario else None
        ),
    }

    catalog = discover_model_catalog(
        active_transport,
        endpoint,
        api_key,
        request_budget,
    )
    request_plan = plan_complete_request_budget(
        discovered_model_count=len(catalog["models"]),
        max_eval_models=max_eval_models,
        locked_task_count=len(locked_evaluation_tasks(manifest)),
    )
    if (
        request_plan["total_required_request_count"]
        > request_budget.max_total_requests
    ):
        raise BenchmarkBudgetError(
            "complete benchmark needs "
            f"{request_plan['total_required_request_count']} requests but "
            f"configured cap is {request_budget.max_total_requests}; "
            "no capability probes were started"
        )
    benchmark_parameters.update(
        {
            "catalog_request_count": request_plan["catalog_request_count"],
            "capability_probe_request_count": request_plan[
                "capability_probe_request_count"
            ],
            "evaluation_reserve_request_count": request_plan[
                "evaluation_reserve_request_count"
            ],
            "planned_worker_count": request_plan["planned_worker_count"],
            "total_required_request_count": request_plan[
                "total_required_request_count"
            ],
        }
    )
    probed_models = probe_discovered_models(
        catalog["models"],
        active_transport,
        endpoint,
        api_key,
        request_budget,
        probe_concurrency,
        clock,
        probe_timer,
    )
    agents = build_worker_agents(probed_models, eval_base_url, max_eval_models)
    evaluation = evaluate_policies(
        agents,
        manifest,
        pricing_scenario,
        eval_client,
        request_budget,
        timer,
        total_token_budget=max_output_tokens,
        maximum_calls=MAX_WORKFLOW_DEPTH,
    )
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
            "request_plan": request_plan,
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
    parser.add_argument("--max-total-requests", type=int, default=2000)
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
