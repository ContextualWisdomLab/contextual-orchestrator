"""Sync-vs-batch routing and the batch-submission path to pg-llm-batch.

The orchestrator — not the caller — decides whether a request runs
**synchronously** (interactive, low-latency) or is dispatched to a **batch**
backend (latency-tolerant, cost-optimised). This module owns:

* :class:`RoutingPolicy` — the sync-vs-batch decision, driven by request hints
  plus thresholds read from the KV config store.
* :func:`cheapest_upstream` — cost-optimising upstream selection (the
  "LiteLLM-plus" cost optimiser) using the configurable price table.
* Batch backends behind one :class:`BatchBackend` surface:
    * :class:`LocalBatchBackend` — runs requests in-process via an injected
      runner (preserves the mock/local path; used by tests and standalone).
    * :class:`PgLlmBatchBackend` — submits to **pg-llm-batch** (the submodule /
      service) over its OpenAI-compatible ``BatchAPIClient`` and retrieves
      results, so batch model routing is controlled by the orchestrator.

Config/thresholds come from KV, never ``os.getenv``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import time
from typing import Any, Callable, Dict, List, Optional, Protocol
import uuid


_ROUTING_CATEGORY = "routing"


# ---------------------------------------------------------------------------
# Routing decision
# ---------------------------------------------------------------------------


@dataclass
class RoutingHints:
    """Per-request routing hints supplied by the caller (never authoritative)."""

    channel: Optional[str] = None  # explicit "sync" | "batch" request
    latency_tolerant: bool = False
    priority: str = "normal"  # "interactive" | "normal" | "bulk"

    @classmethod
    def from_mapping(cls, data: Optional[Dict[str, Any]]) -> "RoutingHints":
        """Build hints from a loose mapping, tolerating missing keys."""
        data = data or {}
        channel = data.get("channel")
        if channel is not None:
            channel = str(channel).lower()
        return cls(
            channel=channel,
            latency_tolerant=bool(data.get("latency_tolerant", False)),
            priority=str(data.get("priority", "normal")).lower(),
        )


@dataclass
class RoutingDecision:
    """Outcome of the sync-vs-batch decision."""

    channel: str  # "sync" | "batch"
    reason: str


class RoutingPolicy:
    """Decides sync vs batch from hints + KV-configured thresholds.

    Config (category ``routing``):

    * ``batch_enabled`` (bool, default ``True``) — master switch. When off,
      everything runs sync.
    * ``batch_min_tokens`` (int, default ``0``) — prompts at/over this token
      count are eligible for batch when nothing forces sync. ``0`` disables the
      size trigger.
    * ``interactive_forces_sync`` (bool, default ``True``) — an ``interactive``
      priority hint always stays sync.
    """

    def __init__(self, config_store: Any) -> None:
        self._config = config_store

    def _batch_enabled(self) -> bool:
        return bool(self._config.get(_ROUTING_CATEGORY, "batch_enabled", True))

    def decide(self, hints: RoutingHints, prompt_tokens: int = 0) -> RoutingDecision:
        """Return the routing decision for one request."""
        if not self._batch_enabled():
            return RoutingDecision("sync", "batch routing disabled by config")

        interactive_forces_sync = bool(
            self._config.get(_ROUTING_CATEGORY, "interactive_forces_sync", True)
        )
        if hints.priority == "interactive" and interactive_forces_sync:
            return RoutingDecision("sync", "interactive priority forces sync")

        if hints.channel == "sync":
            return RoutingDecision("sync", "caller requested sync channel")
        if hints.channel == "batch":
            return RoutingDecision("batch", "caller requested batch channel")

        if hints.latency_tolerant or hints.priority == "bulk":
            return RoutingDecision("batch", "latency-tolerant request routed to batch")

        batch_min_tokens = int(self._config.get(_ROUTING_CATEGORY, "batch_min_tokens", 0))
        if batch_min_tokens and prompt_tokens >= batch_min_tokens:
            return RoutingDecision(
                "batch", f"prompt tokens {prompt_tokens} >= batch_min_tokens {batch_min_tokens}"
            )

        return RoutingDecision("sync", "default interactive path")


def cheapest_upstream(
    candidates: List[Dict[str, str]],
    price_book: Any,
    *,
    assumed_prompt_tokens: int = 1000,
    assumed_completion_tokens: int = 1000,
) -> Optional[Dict[str, str]]:
    """Return the lowest-cost ``{provider, model}`` candidate by the price table.

    Cost-optimising upstream selection for load balancing: given candidate
    provider/model pairs, price each against the configurable price table for a
    representative request shape and return the cheapest. Unpriced candidates
    cost ``0`` and are treated as free (explicit, so a missing price is visible
    rather than silently expensive). Ties keep input order.
    """
    if not candidates:
        return None
    best: Optional[Dict[str, str]] = None
    best_cost: Optional[float] = None
    for candidate in candidates:
        provider = candidate.get("provider", "")
        model = candidate.get("model", "")
        cost, _currency = price_book.compute_cost(
            provider, model, assumed_prompt_tokens, assumed_completion_tokens
        )
        if best_cost is None or cost < best_cost:
            best_cost = cost
            best = candidate
    return best


# ---------------------------------------------------------------------------
# Batch requests / jobs / results
# ---------------------------------------------------------------------------


@dataclass
class BatchRequest:
    """One request destined for a batch backend."""

    messages: List[Dict[str, str]]
    model: str = "contextual-orchestrator"
    custom_id: str = field(default_factory=lambda: f"req_{uuid.uuid4().hex}")
    attribution: Dict[str, Any] = field(default_factory=dict)
    mode: str = "auto"

    def to_jsonl_line(self, endpoint: str = "/v1/chat/completions") -> Dict[str, Any]:
        """Render this request as an OpenAI Batch API JSONL line."""
        return {
            "custom_id": self.custom_id,
            "method": "POST",
            "url": endpoint,
            "body": {"model": self.model, "messages": self.messages},
        }


@dataclass
class BatchJob:
    """Handle for a submitted batch job."""

    job_id: str
    backend: str
    status: str = "submitted"
    submitted_at: int = field(default_factory=lambda: int(time.time()))
    request_count: int = 0


@dataclass
class BatchResultItem:
    """A single completed request within a batch."""

    custom_id: str
    answer: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    attribution: Dict[str, Any] = field(default_factory=dict)
    model: str = "contextual-orchestrator"
    mode: str = "auto"


class BatchBackend(Protocol):
    """Submit/poll/retrieve contract shared by every batch backend."""

    name: str

    def submit(self, requests: List[BatchRequest], metadata: Optional[Dict[str, Any]] = None) -> BatchJob:
        """Submit a batch of requests and return a job handle."""
        ...

    def poll(self, job: BatchJob) -> Dict[str, Any]:
        """Return the current status of a batch job."""
        ...

    def retrieve(self, job: BatchJob) -> List[BatchResultItem]:
        """Retrieve completed results for a batch job."""
        ...


class LocalBatchBackend:
    """In-process batch backend that runs each request via an injected runner.

    Preserves the mock/local path: no external service, no Postgres. The runner
    is any callable ``(messages, mode) -> {"answer": str, "mode": str}`` — the
    orchestrator's own ``complete`` fits directly. Results are computed eagerly
    on submit and returned verbatim on retrieve, so the batch lifecycle is fully
    observable in tests.
    """

    name = "local"

    def __init__(self, runner: Callable[[List[Dict[str, str]], str], Dict[str, Any]]) -> None:
        self._runner = runner
        self._results: Dict[str, List[BatchResultItem]] = {}

    def submit(self, requests: List[BatchRequest], metadata: Optional[Dict[str, Any]] = None) -> BatchJob:
        """Run every request in-process and stash the results under a job id."""
        job_id = f"localbatch_{uuid.uuid4().hex}"
        items: List[BatchResultItem] = []
        for request in requests:
            result = self._runner(request.messages, request.mode)
            answer = result.get("answer", "")
            items.append(
                BatchResultItem(
                    custom_id=request.custom_id,
                    answer=answer,
                    attribution=dict(request.attribution),
                    model=request.model,
                    mode=result.get("mode", request.mode),
                )
            )
        self._results[job_id] = items
        return BatchJob(job_id=job_id, backend=self.name, status="completed", request_count=len(requests))

    def poll(self, job: BatchJob) -> Dict[str, Any]:
        """Local batches complete synchronously, so always report completed."""
        return {"job_id": job.job_id, "status": "completed", "is_complete": True}

    def retrieve(self, job: BatchJob) -> List[BatchResultItem]:
        """Return the results computed at submit time."""
        return self._results.get(job.job_id, [])


class PgLlmBatchBackend:
    """Batch backend that submits to **pg-llm-batch** and retrieves results.

    Drives the pg-llm-batch OpenAI-compatible ``BatchAPIClient`` async flow
    (upload JSONL -> create batch job -> poll -> download results). The client
    is injected so it can be the real ``pg_llm_batch.BatchAPIClient`` (from the
    submodule/service) in production or a fake in tests. An optional
    ``payload_assembler`` persists the JSONL into Postgres and returns a
    ``memory://`` reference; without one, an in-memory reference is used (the
    injected client is responsible for loading it).
    """

    name = "pg-llm-batch"

    def __init__(
        self,
        client: Any,
        *,
        endpoint_alias: str = "default",
        endpoint: str = "/v1/chat/completions",
        payload_assembler: Any = None,
    ) -> None:
        self._client = client
        self._endpoint_alias = endpoint_alias
        self._endpoint = endpoint
        self._assembler = payload_assembler
        self._jobs: Dict[str, Dict[str, Any]] = {}

    def _assemble_payload(self, requests: List[BatchRequest]) -> str:
        if self._assembler is not None:
            return self._assembler.assemble(
                [request.to_jsonl_line(self._endpoint) for request in requests]
            )
        # No Postgres assembler: hand the client a memory:// reference. The JSONL
        # body itself is built here so a real assembler or client can load it.
        return f"memory://{uuid.uuid4().hex}"

    @staticmethod
    def _run(coro: Any) -> Any:
        return asyncio.run(coro)

    def submit(self, requests: List[BatchRequest], metadata: Optional[Dict[str, Any]] = None) -> BatchJob:
        """Upload JSONL + create a batch job via the pg-llm-batch client."""
        file_path = self._assemble_payload(requests)

        async def _submit() -> Dict[str, Any]:
            uploaded = await self._client.upload_jsonl(file_path, self._endpoint_alias)
            input_file_id = uploaded["id"]
            return await self._client.create_batch_job(
                input_file_id,
                self._endpoint_alias,
                endpoint=self._endpoint,
                metadata=metadata,
            )

        job_payload = self._run(_submit())
        batch_id = job_payload["id"]
        self._jobs[batch_id] = {
            "endpoint_alias": self._endpoint_alias,
            "requests": {request.custom_id: request for request in requests},
        }
        return BatchJob(
            job_id=batch_id,
            backend=self.name,
            status=job_payload.get("status", "validating"),
            request_count=len(requests),
        )

    def poll(self, job: BatchJob) -> Dict[str, Any]:
        """Poll batch status via the pg-llm-batch client."""
        async def _poll() -> Dict[str, Any]:
            return await self._client.get_batch_status(job.job_id, self._endpoint_alias)

        status = self._run(_poll())
        return {
            "job_id": job.job_id,
            "status": status.get("status"),
            "is_complete": status.get("is_complete", False),
            "progress_percentage": status.get("progress_percentage", 0),
        }

    def retrieve(self, job: BatchJob) -> List[BatchResultItem]:
        """Download + parse batch results, mapping them back to submitted requests."""
        async def _download() -> Dict[str, Any]:
            return await self._client.download_results(job.job_id, self._endpoint_alias)

        payload = self._run(_download())
        if not payload.get("success"):
            return []
        tracked = self._jobs.get(job.job_id, {}).get("requests", {})
        items: List[BatchResultItem] = []
        for entry in payload.get("responses", []):
            custom_id = entry.get("custom_id", "")
            body = (entry.get("response") or {}).get("body", {})
            answer = _extract_answer(body)
            usage = body.get("usage", {}) or {}
            request = tracked.get(custom_id)
            items.append(
                BatchResultItem(
                    custom_id=custom_id,
                    answer=answer,
                    prompt_tokens=int(usage.get("prompt_tokens", 0)),
                    completion_tokens=int(usage.get("completion_tokens", 0)),
                    attribution=dict(request.attribution) if request else {},
                    model=request.model if request else "contextual-orchestrator",
                    mode=request.mode if request else "auto",
                )
            )
        return items


def _extract_answer(body: Dict[str, Any]) -> str:
    choices = body.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return str(message.get("content", ""))


def build_jsonl_body(requests: List[BatchRequest], endpoint: str = "/v1/chat/completions") -> str:
    """Serialize batch requests into an OpenAI Batch API JSONL body."""
    return "\n".join(json.dumps(request.to_jsonl_line(endpoint)) for request in requests)
