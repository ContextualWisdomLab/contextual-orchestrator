"""Cost-aware routing coordinator: the LLM cost-review + routing hub.

This composes the existing :class:`~contextual_orchestrator.orchestrator.TaskOrchestrator`
with the cost ledger and the sync-vs-batch router, so the orchestrator becomes
the single control point for:

1. **Cost review** — every completion (sync *and* batch) writes a
   :class:`~contextual_orchestrator.cost_ledger.UsageRecord` with token counts +
   computed cost and full multi-dimensional attribution.
2. **Routing** — :class:`~contextual_orchestrator.batch_routing.RoutingPolicy`
   picks sync vs batch; the batch path is dispatched to a
   :class:`~contextual_orchestrator.batch_routing.BatchBackend` (pg-llm-batch in
   production, local in-process for the mock/standalone path).

All config (prices, thresholds, endpoints) is read from the injected KV config
store, never ``os.getenv``.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .batch_routing import (
    BatchBackend,
    BatchJob,
    BatchRequest,
    BatchResultItem,
    LocalBatchBackend,
    RoutingHints,
    RoutingPolicy,
)
from .cost_ledger import AttributionDimensions, CostLedger, PriceBook
from .kv_config import InMemoryConfigStore
from .token_counting import HeuristicTokenCounter, build_token_counter


class CostRoutingCoordinator:
    """Wire routing + cost accounting around a ``TaskOrchestrator``."""

    def __init__(
        self,
        orchestrator: Any,
        config_store: Any = None,
        *,
        price_book: Optional[PriceBook] = None,
        ledger: Optional[CostLedger] = None,
        token_counter: Any = None,
        routing_policy: Optional[RoutingPolicy] = None,
        batch_backend: Optional[BatchBackend] = None,
        postgres_dsn: Optional[str] = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.config = config_store or InMemoryConfigStore()
        self.price_book = price_book or PriceBook(self.config)
        self.ledger = ledger or CostLedger(self.price_book)
        self.token_counter = token_counter or (
            build_token_counter(postgres_dsn) if postgres_dsn else HeuristicTokenCounter()
        )
        self.policy = routing_policy or RoutingPolicy(self.config)
        self.batch_backend: BatchBackend = batch_backend or LocalBatchBackend(
            runner=lambda messages, mode: orchestrator.complete(messages, mode=mode)
        )
        # job_id -> submitted BatchJob (so poll/retrieve can be driven by id)
        self._batch_jobs: Dict[str, BatchJob] = {}

    # ------------------------------------------------------------------
    # Provider / model resolution
    # ------------------------------------------------------------------
    def _served_provider_model(self, result: Dict[str, Any], fallback_model: str) -> tuple[str, str]:
        """Derive ``(provider, model)`` from the served agent in the trace."""
        trace = result.get("trace") or []
        agent_id = ""
        for row in trace:
            agent_id = row.get("served_agent_id") or row.get("agent_id") or agent_id
        if agent_id:
            try:
                agent = self.orchestrator._agent(agent_id)
                provider = agent.provider_name or _provider_from_base_url(agent.base_url)
                return provider or "unknown", agent.model or fallback_model
            except Exception:
                pass
        return "unknown", fallback_model

    # ------------------------------------------------------------------
    # Sync + batch completion
    # ------------------------------------------------------------------
    def complete(
        self,
        messages: List[Dict[str, str]],
        *,
        mode: str = "auto",
        attribution: Optional[Dict[str, Any]] = None,
        hints: Optional[Dict[str, Any]] = None,
        model_name: str = "contextual-orchestrator",
        workflow_run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Route a request (sync or batch) and record its usage + cost.

        Sync requests run the orchestrator immediately and return the completion
        augmented with ``channel``, ``routing_reason``, ``usage``, and the
        ``usage_record_id``. Batch requests are dispatched to the batch backend
        and return a job envelope; their cost is recorded on retrieval.
        """
        routing_hints = hints if isinstance(hints, RoutingHints) else RoutingHints.from_mapping(hints)
        prompt_tokens_estimate = self.token_counter.count_messages(messages, model_name)
        decision = self.policy.decide(routing_hints, prompt_tokens_estimate)

        if decision.channel == "batch":
            request = BatchRequest(
                messages=messages,
                model=model_name,
                attribution=dict(attribution or {}),
                mode=mode,
            )
            job = self.submit_batch([request], metadata={"routing_reason": decision.reason})
            return {
                "channel": "batch",
                "routing_reason": decision.reason,
                "job_id": job.job_id,
                "backend": job.backend,
                "status": job.status,
                "request_count": job.request_count,
            }

        result = self.orchestrator.run(messages, mode=mode, workflow_run_id=workflow_run_id)
        record = self._record_completion(
            messages=messages,
            answer=result.get("answer", ""),
            route_mode=result.get("mode"),
            request_channel="sync",
            attribution=attribution,
            model_name=model_name,
            provider_model=self._served_provider_model(result, model_name),
            workflow_run_id=result.get("workflow_run_id"),
        )
        result["channel"] = "sync"
        result["routing_reason"] = decision.reason
        result["usage_record_id"] = record.usage_record_id
        result["usage"] = {
            "prompt_tokens": record.prompt_tokens,
            "completion_tokens": record.completion_tokens,
            "total_tokens": record.total_tokens,
        }
        result["cost"] = {"cost_amount": record.cost_amount, "currency_code": record.currency_code}
        return result

    def _record_completion(
        self,
        *,
        messages: List[Dict[str, str]],
        answer: str,
        route_mode: Optional[str],
        request_channel: str,
        attribution: Optional[Dict[str, Any]],
        model_name: str,
        provider_model: tuple[str, str],
        workflow_run_id: Optional[str],
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
    ):
        provider, model = provider_model
        if prompt_tokens is None:
            prompt_tokens = self.token_counter.count_messages(messages, model)
        if completion_tokens is None:
            completion_tokens = self.token_counter.count_text(answer, model)
        return self.ledger.record_usage(
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            request_channel=request_channel,
            route_mode=route_mode,
            workflow_run_id=workflow_run_id,
            attribution=attribution,
        )

    # ------------------------------------------------------------------
    # Batch lifecycle
    # ------------------------------------------------------------------
    def submit_batch(
        self,
        requests: List[BatchRequest],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> BatchJob:
        """Submit a batch of requests to the configured batch backend."""
        job = self.batch_backend.submit(requests, metadata=metadata)
        self._batch_jobs[job.job_id] = job
        return job

    def poll_batch(self, job_id: str) -> Dict[str, Any]:
        """Poll a previously submitted batch job by id."""
        job = self._require_job(job_id)
        return self.batch_backend.poll(job)

    def retrieve_batch(self, job_id: str) -> Dict[str, Any]:
        """Retrieve batch results and record usage + cost for each completion."""
        job = self._require_job(job_id)
        items: List[BatchResultItem] = self.batch_backend.retrieve(job)
        recorded: List[Dict[str, Any]] = []
        for item in items:
            provider_model = self._resolve_batch_provider_model(item)
            record = self._record_completion(
                messages=[{"role": "user", "content": ""}],
                answer=item.answer,
                route_mode=item.mode,
                request_channel="batch",
                attribution=item.attribution,
                model_name=item.model,
                provider_model=provider_model,
                workflow_run_id=job.job_id,
                prompt_tokens=item.prompt_tokens or None,
                completion_tokens=item.completion_tokens or None,
            )
            recorded.append(
                {
                    "custom_id": item.custom_id,
                    "answer": item.answer,
                    "usage_record_id": record.usage_record_id,
                    "cost_amount": record.cost_amount,
                    "currency_code": record.currency_code,
                    "prompt_tokens": record.prompt_tokens,
                    "completion_tokens": record.completion_tokens,
                }
            )
        return {
            "job_id": job_id,
            "backend": job.backend,
            "result_count": len(recorded),
            "results": recorded,
        }

    def _resolve_batch_provider_model(self, item: BatchResultItem) -> tuple[str, str]:
        provider = str(item.attribution.get("provider") or item.attribution.get("upstream_api") or "")
        if not provider:
            provider = "unknown"
        return provider, item.model

    def _require_job(self, job_id: str) -> BatchJob:
        job = self._batch_jobs.get(job_id)
        if job is None:
            raise KeyError(f"batch job {job_id!r} not found")
        return job

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    def cost_report(
        self,
        dimension: str,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return a cost rollup report grouped by ``dimension`` over a window."""
        return self.ledger.report(dimension, start, end)


def _provider_from_base_url(base_url: str) -> str:
    """Best-effort provider label from a base URL scheme/host."""
    if base_url.startswith("mock://"):
        return "mock"
    try:
        from urllib.parse import urlparse

        host = urlparse(base_url).hostname or ""
    except Exception:
        return ""
    return host
