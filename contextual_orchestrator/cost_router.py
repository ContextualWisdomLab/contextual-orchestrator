"""Cost-aware routing coordinator: the LLM cost-review + routing hub.

This composes the existing :class:`~contextual_orchestrator.orchestrator.TaskOrchestrator`
with the cost ledger and the sync-vs-batch router, so the orchestrator becomes
the single control point for:

1. **Cost review** — every completion (sync, stream, *and* batch) writes a
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

import hashlib
import re
from contextvars import ContextVar
from dataclasses import replace
from typing import Any, Dict, List, Optional

from .batch_routing import (
    BatchBackend,
    BatchDownloadError,
    BatchJob,
    BatchRequest,
    BatchResultItem,
    EmbeddingBatchBackend,
    EmbeddingBatchRequest,
    EmbeddingBatchResultItem,
    LocalBatchBackend,
    LocalEmbeddingBatchBackend,
    RoutingHints,
    RoutingPolicy,
)
from .batch_job_registry import JobRegistryFactory, build_job_registry
from .cost_ledger import CostLedger, PriceBook
from .kv_config import InMemoryConfigStore
from .token_counting import HeuristicTokenCounter, build_token_counter


_RACE_USAGE_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar(
    "race_usage_context", default=None
)

_EMBEDDING_CONFIG_CATEGORY = "routing"
_DEFAULT_EMBEDDING_MAX_TOKENS_PER_REQUEST = 280_000
_DEFAULT_EMBEDDING_MAX_CHARS_PER_PART = 240_000
_EMBEDDING_UNIT_RE = re.compile(r"\S+\s*|\s+", re.UNICODE)


class BatchModelSelectionError(RuntimeError):
    """Raised when a batch request has no eligible model-group member."""


class InvalidBatchModelError(ValueError):
    """Raised only for an unknown client-supplied batch model identity."""


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
        embedding_batch_backend: Optional[EmbeddingBatchBackend] = None,
        postgres_dsn: Optional[str] = None,
        job_registry: Optional[JobRegistryFactory] = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.config = config_store or InMemoryConfigStore()
        self.price_book = price_book or PriceBook(self.config)
        self.ledger = ledger or CostLedger(self.price_book)
        self._race_usage_context = _RACE_USAGE_CONTEXT
        if hasattr(orchestrator, "_race_usage_sink"):
            orchestrator._race_usage_sink = self._record_race_endpoint_usage
        self.token_counter = token_counter or (
            build_token_counter(postgres_dsn) if postgres_dsn else HeuristicTokenCounter()
        )
        self.policy = routing_policy or RoutingPolicy(self.config)
        # Job registries live in Valkey when the credential registry carries
        # batch_job_registry_valkey_url, so submitted jobs survive a process
        # restart; otherwise they are the historical in-process dicts. Built
        # before the backends so the default local backends share it and
        # their results survive a restart too.
        registry = job_registry if job_registry is not None else build_job_registry(self.config)
        self.job_registry = registry
        if batch_backend is None:
            client = getattr(orchestrator, "client", None)
            local_concurrency = getattr(client, "local_concurrency", 1)
            self.batch_backend = LocalBatchBackend(
                runner=self._run_local_batch,
                max_concurrency=local_concurrency,
                job_registry=registry,
                request_context=lambda request: orchestrator.request_policy(request.zdr_only),
            )
        else:
            self.batch_backend = batch_backend
        self.embedding_batch_backend: EmbeddingBatchBackend = (
            embedding_batch_backend
            or LocalEmbeddingBatchBackend(
                token_counter=self.token_counter, job_registry=registry
            )
        )
        # job_id -> submitted BatchJob (so poll/retrieve can be driven by id)
        self._batch_jobs = registry.mapping("batch_jobs", decode=lambda raw: BatchJob(**raw))
        # embeddings batch state: job handle + submitted requests + cached doc,
        # keyed by batch id so poll/retrieve is idempotent (usage recorded once).
        self._embedding_jobs = registry.mapping("embedding_jobs", decode=lambda raw: BatchJob(**raw))
        self._embedding_models = registry.mapping("embedding_models")
        self._embedding_requests = registry.mapping(
            "embedding_requests", decode=lambda raw: EmbeddingBatchRequest(**raw)
        )
        self._embedding_input_counts = registry.mapping("embedding_input_counts")
        self._embedding_part_counts = registry.mapping("embedding_part_counts")
        self._embedding_part_limits = registry.mapping("embedding_part_limits")
        self._embedding_documents = registry.mapping("embedding_documents")

    def _run_local_batch(
        self, messages: List[Dict[str, str]], mode: str, model: str
    ) -> Dict[str, Any]:
        """Run one local item while retaining completed endpoint-race usage."""
        context = {
            "route_mode": mode, "attribution": None, "model_name": model,
            "workflow_run_id": None, "workflow_ready": False, "records": [],
            "pending_usage": [],
        }
        token = self._race_usage_context.set(context)
        try:
            result = self.orchestrator.complete(messages, mode=mode, model_name=model)
        finally:
            self._race_usage_context.reset(token)
        race_usage = []
        for endpoint_id, value in context["pending_usage"]:
            if isinstance(value, tuple) and len(value) == 3:
                usage = value[2]
            elif isinstance(value, dict):
                usage = value.get("usage")
            else:
                usage = None
            counts = self._provider_usage(usage)
            if counts is not None:
                race_usage.append({
                    "agent_id": endpoint_id,
                    "usage": {"prompt_tokens": counts[0], "completion_tokens": counts[1]},
                })
        result["_batch_race_usage"] = race_usage
        return result

    # ------------------------------------------------------------------
    # Provider / model resolution
    # ------------------------------------------------------------------
    @staticmethod
    def _agent_provider_model(agent: Any, fallback_model: str) -> tuple[str, str]:
        """Derive the ledger provider/model identity for one served agent."""
        provider = agent.provider_name or _provider_from_base_url(agent.base_url)
        return provider or "unknown", agent.model or fallback_model

    def _served_provider_model(self, result: Dict[str, Any], fallback_model: str) -> tuple[str, str]:
        """Derive ``(provider, model)`` from the served agent in the trace."""
        trace = result.get("trace") or []
        agent_id = ""
        for row in trace:
            agent_id = row.get("served_agent_id") or row.get("agent_id") or agent_id
        if agent_id:
            try:
                agent = self.orchestrator._agent(agent_id)
                return self._agent_provider_model(agent, fallback_model)
            except Exception:
                pass
        return "unknown", fallback_model

    @staticmethod
    def _provider_usage(usage: Any) -> tuple[int, int] | None:
        """Return validated Chat or Responses token counts."""
        if not isinstance(usage, dict):
            return None
        prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
        completion = usage.get("completion_tokens", usage.get("output_tokens"))
        if type(prompt) is not int or prompt < 0 or type(completion) is not int or completion < 0:
            return None
        return prompt, completion

    def record_async_video_usage(self, *, agent: Any, usage: Any, gateway_job_id: str):
        """Idempotently ledger concrete async-video counts reported by a provider."""
        counts = self._provider_usage(usage)
        if counts is None:
            return None
        stable_id = hashlib.sha256(gateway_job_id.encode("utf-8")).hexdigest()
        return self.ledger.record_usage(
            provider=agent.provider_name or "unknown", model=agent.model,
            prompt_tokens=counts[0], completion_tokens=counts[1],
            request_channel="async", route_mode="video",
            workflow_run_id=gateway_job_id, measurement_status="measured",
            usage_record_id=f"usage_video_{stable_id}",
        )

    def _record_race_endpoint_usage(self, endpoint_id: str, value: Any) -> None:
        """Ledger provider-reported usage for completed non-winning race calls."""
        context = self._race_usage_context.get()
        if context is None:
            return
        if not context["workflow_ready"]:
            context["pending_usage"].append((endpoint_id, value))
            return
        usage = None
        if isinstance(value, tuple) and len(value) == 3:
            usage = value[2]
        elif isinstance(value, dict):
            usage = value.get("usage")
        counts = self._provider_usage(usage)
        if counts is None:
            return
        agent = next(
            (item for item in self.orchestrator.candidates if item.id == endpoint_id),
            None,
        )
        if agent is None:  # pragma: no cover - endpoint came from the current pool
            return
        record = self._record_completion(
            messages=[],
            answer="",
            route_mode=context["route_mode"],
            request_channel="sync",
            attribution=context["attribution"],
            model_name=context["model_name"],
            provider_model=self._agent_provider_model(agent, context["model_name"]),
            workflow_run_id=context["workflow_run_id"],
            prompt_tokens=counts[0],
            completion_tokens=counts[1],
        )
        context["records"].append(record)

    def _flush_race_endpoint_usage(self, context: dict[str, Any]) -> None:
        """Persist usage held until the workflow identity becomes available."""
        pending = list(context["pending_usage"])
        context["pending_usage"].clear()
        for endpoint_id, value in pending:
            self._record_race_endpoint_usage(endpoint_id, value)

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
        cache_bypass: bool = False,
        cache_partition: Optional[str] = None,
        owner_id: Optional[str] = None,
        provider_request: Optional[Dict[str, Any]] = None,
        provider_endpoint: str = "chat/completions",
        zdr_only: bool = False,
    ) -> Dict[str, Any]:
        """Route a request (sync or batch) and record its usage + cost.

        Sync requests run the orchestrator immediately and return the completion
        augmented with ``channel``, ``routing_reason``, ``usage``, and the
        ``usage_record_id``. Batch requests are dispatched to the batch backend
        and return a job envelope; their cost is recorded on retrieval.

        For multi-step workflows, each trace step records one ledger
        row. Rows backed by provider-reported token counts are labeled
        ``measurement_status="measured"``; rows that fall back to heuristic
        estimates are labeled ``"estimated"``. The original request prompt is
        attributed at most once across unreported rows: it lands in full on the
        first unreported step, and later unreported steps estimate only their
        own output tokens. Provider-reported prompt counts remain attached to
        their respective rows because each trace step is a separate billable
        provider call; they are neither deduplicated against nor replaced by
        the fallback estimate for a different call.
        """
        if not isinstance(cache_bypass, bool):
            raise TypeError("cache_bypass must be a boolean")
        if type(zdr_only) is not bool:
            raise TypeError("zdr_only must be a boolean")
        routing_hints = hints if isinstance(hints, RoutingHints) else RoutingHints.from_mapping(hints)
        prompt_tokens_estimate = self.token_counter.count_messages(messages, model_name)
        decision = self.policy.decide(routing_hints, prompt_tokens_estimate)

        if decision.channel == "batch" and provider_request is None:
            request = BatchRequest(
                messages=messages,
                model=model_name,
                attribution=dict(attribution or {}),
                mode=mode,
                zdr_only=zdr_only,
            )
            job = self.submit_batch(
                [request], metadata={"routing_reason": decision.reason}, owner_id=owner_id
            )
            return {
                "channel": "batch",
                "routing_reason": decision.reason,
                "job_id": job.job_id,
                "backend": job.backend,
                "status": job.status,
                "request_count": job.request_count,
            }

        if provider_request is not None:
            if provider_endpoint not in {"chat/completions", "responses"}:
                raise ValueError("provider_endpoint must be chat/completions or responses")
            race_context = {
                "route_mode": mode,
                "attribution": attribution,
                "model_name": model_name,
                "workflow_run_id": workflow_run_id,
                "workflow_ready": workflow_run_id is not None,
                "records": [],
                "pending_usage": [],
            }
            race_token = self._race_usage_context.set(race_context)
            try:
                with self.orchestrator.request_policy(zdr_only):
                    provider_response = self.orchestrator.proxy_completion(
                        provider_request,
                        endpoint=provider_endpoint,
                        single_agent=False,
                    )
                lineage = provider_response.get("orchestration")
                if isinstance(lineage, dict) and isinstance(
                    lineage.get("workflow_run_id"), str
                ):
                    race_context["workflow_run_id"] = lineage["workflow_run_id"]
                race_context["workflow_ready"] = True
                self._flush_race_endpoint_usage(race_context)
            finally:
                self._race_usage_context.reset(race_token)
            lineage = provider_response.get("orchestration")
            if not isinstance(lineage, dict) or not isinstance(
                lineage.get("workflow_run_id"), str
            ):
                raise RuntimeError("provider completion omitted orchestration lineage")
            result = dict(self.orchestrator.get_workflow_run(lineage["workflow_run_id"]))
            race_records = list(race_context["records"])
            records = list(race_records)
            # The caller's request prompt is attributed at most once per
            # completion: the full prompt lands on the first trace step that
            # reports no provider usage of its own, and every later unreported
            # step estimates only its own output tokens. One workflow run must
            # never bill the same request prompt once per unreported step.
            # Reported prompt counts describe separate provider calls and stay
            # on their own measured rows; suppressing them would undercount the
            # provider invoice rather than deduplicate one request.
            request_prompt_attributed = False
            for step in result.get("trace") or []:
                if not isinstance(step, dict):
                    continue
                counts = self._provider_usage(step.get("usage"))
                attribute_request_prompt = counts is None and not request_prompt_attributed
                if attribute_request_prompt:
                    request_prompt_attributed = True
                records.append(
                    self._record_completion(
                        messages=messages if attribute_request_prompt else [],
                        answer=step.get("output", "") if counts is None else "",
                        route_mode=result.get("mode"),
                        request_channel="sync",
                        attribution=attribution,
                        model_name=model_name,
                        provider_model=self._served_provider_model(
                            {"trace": [step]}, model_name
                        ),
                        workflow_run_id=result.get("workflow_run_id"),
                        prompt_tokens=counts[0] if counts else None,
                        completion_tokens=counts[1] if counts else None,
                    )
                )
            if len(records) == len(race_records):
                counts = self._provider_usage(provider_response.get("usage"))
                records.append(
                    self._record_completion(
                        messages=messages,
                        answer=result.get("answer", ""),
                        route_mode=result.get("mode"),
                        request_channel="sync",
                        attribution=attribution,
                        model_name=model_name,
                        provider_model=self._served_provider_model(result, model_name),
                        workflow_run_id=result.get("workflow_run_id"),
                        prompt_tokens=counts[0] if counts else None,
                        completion_tokens=counts[1] if counts else None,
                    )
                )
            currencies = {record.currency_code for record in records}
            provider_response["usage_record_ids"] = [
                record.usage_record_id for record in records
            ]
            provider_response["cost"] = {
                "cost_amount": (
                    round(sum(record.cost_amount for record in records), 6)
                    if len(currencies) == 1
                    else None
                ),
                "currency_code": next(iter(currencies)) if len(currencies) == 1 else "MIXED",
                "measurement_status": (
                    "estimated"
                    if any(record.measurement_status == "estimated" for record in records)
                    else "measured"
                ),
            }
            if len(currencies) > 1:
                provider_response["cost"]["currency_components"] = [
                    {
                        "currency_code": currency,
                        "cost_amount": round(
                            sum(
                                record.cost_amount
                                for record in records
                                if record.currency_code == currency
                            ),
                            6,
                        ),
                    }
                    for currency in sorted(currencies)
                ]
                provider_response["cost"]["customer_action"] = (
                    "Review each currency component separately. Apply an approved "
                    "exchange-rate source before calculating a combined total."
                )
            return provider_response

        run_kwargs = {"mode": mode, "workflow_run_id": workflow_run_id, "owner_id": owner_id}
        if model_name != "contextual-orchestrator":
            run_kwargs["model_name"] = model_name
        if cache_bypass:
            run_kwargs["bypass_cache"] = True
        if cache_partition is not None:
            run_kwargs["cache_partition"] = cache_partition
        race_context = {
            "route_mode": mode,
            "attribution": attribution,
            "model_name": model_name,
            "workflow_run_id": workflow_run_id,
            "workflow_ready": workflow_run_id is not None,
            "records": [],
            "pending_usage": [],
        }
        race_token = self._race_usage_context.set(race_context)
        try:
            with self.orchestrator.request_policy(zdr_only):
                result = self.orchestrator.run(messages, **run_kwargs)
            if isinstance(result.get("workflow_run_id"), str):
                race_context["workflow_run_id"] = result["workflow_run_id"]
            race_context["workflow_ready"] = True
            self._flush_race_endpoint_usage(race_context)
        finally:
            self._race_usage_context.reset(race_token)
        cache_hit = result.get("cache_status") == "hit"
        race_records = list(race_context["records"])
        records = list(race_records)
        if cache_hit:
            records.append(
                self._record_completion(
                    messages=messages,
                    answer=result.get("answer", ""),
                    route_mode=result.get("mode"),
                    request_channel="cache",
                    attribution=attribution,
                    model_name=model_name,
                    provider_model=("cache", "response"),
                    workflow_run_id=result.get("workflow_run_id"),
                    prompt_tokens=0,
                    completion_tokens=0,
                )
            )
        else:
            request_prompt_attributed = False
            for step in result.get("trace") or []:
                if not isinstance(step, dict):
                    continue
                counts = self._provider_usage(step.get("usage"))
                attribute_request_prompt = counts is None and not request_prompt_attributed
                if attribute_request_prompt:
                    request_prompt_attributed = True
                records.append(
                    self._record_completion(
                        messages=messages if attribute_request_prompt else [],
                        answer=step.get("output", "") if counts is None else "",
                        route_mode=result.get("mode"),
                        request_channel="sync",
                        attribution=attribution,
                        model_name=model_name,
                        provider_model=self._served_provider_model({"trace": [step]}, model_name),
                        workflow_run_id=result.get("workflow_run_id"),
                        prompt_tokens=counts[0] if counts else None,
                        completion_tokens=counts[1] if counts else None,
                    )
                )
            if len(records) == len(race_records):
                counts = self._provider_usage(result.get("usage"))
                records.append(
                    self._record_completion(
                        messages=messages,
                        answer=result.get("answer", "") if counts is None else "",
                        route_mode=result.get("mode"),
                        request_channel="sync",
                        attribution=attribution,
                        model_name=model_name,
                        provider_model=self._served_provider_model(result, model_name),
                        workflow_run_id=result.get("workflow_run_id"),
                        prompt_tokens=counts[0] if counts else None,
                        completion_tokens=counts[1] if counts else None,
                    )
                )
        record = records[-1]
        result["channel"] = "sync"
        result["routing_reason"] = decision.reason
        result["usage_record_id"] = record.usage_record_id
        result["usage_record_ids"] = [item.usage_record_id for item in records]
        race_record_ids = {item.usage_record_id for item in race_records}
        client_usage_records = [
            item for item in records if item.usage_record_id not in race_record_ids
        ]
        result["usage"] = {
            "prompt_tokens": sum(item.prompt_tokens for item in client_usage_records),
            "completion_tokens": sum(item.completion_tokens for item in client_usage_records),
            "total_tokens": sum(item.total_tokens for item in client_usage_records),
        }
        currencies = {item.currency_code for item in records}
        result["cost"] = {
            "cost_amount": (
                round(sum(item.cost_amount for item in records), 6)
                if len(currencies) == 1
                else None
            ),
            "currency_code": next(iter(currencies)) if len(currencies) == 1 else "MIXED",
            "measurement_status": (
                "estimated"
                if any(item.measurement_status == "estimated" for item in records)
                else "measured"
            ),
        }
        if len(currencies) > 1:
            result["cost"]["currency_components"] = [
                {
                    "currency_code": currency,
                    "cost_amount": round(
                        sum(
                            item.cost_amount
                            for item in records
                            if item.currency_code == currency
                        ),
                        6,
                    ),
                }
                for currency in sorted(currencies)
            ]
            result["cost"]["customer_action"] = (
                "Review each currency component separately. Apply an approved "
                "exchange-rate source before calculating a combined total."
            )
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
        usage_record_id: Optional[str] = None,
    ):
        """Record one completion's usage + cost and return its ledger record.

        ``prompt_tokens``/``completion_tokens`` carry provider-reported counts;
        when either is missing the ledger falls back to heuristic estimates and
        the row is labeled ``measurement_status="estimated"`` instead of
        ``"measured"``. The status is exposed on the completion's ``cost``
        payload, batch retrieval results, and analytics usage-record rows so a
        buyer can always tell provider-measured spend from estimated spend.
        For multi-step structured workflows the caller passes the original
        request ``messages`` only for the first unreported step, keeping the
        request prompt attributed at most once per completion; later unreported
        steps pass empty messages and estimate their own output alone.
        """
        provider, model = provider_model
        measurement_status = (
            "measured"
            if prompt_tokens is not None and completion_tokens is not None
            else "estimated"
        )
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
            measurement_status=measurement_status,
            usage_record_id=usage_record_id,
        )

    def record_stream_usage(
        self,
        *,
        result: Dict[str, Any],
        attribution: Optional[Dict[str, Any]],
        model_name: str,
    ) -> Dict[str, Any]:
        """Record one streamed workflow without estimating missing provider usage."""
        workflow_run_id = result.get("workflow_run_id")
        trace = [step for step in result.get("trace") or [] if isinstance(step, dict)]
        if not trace:
            trace = [{}]
        records = []
        for index, step in enumerate(trace):
            counts = self._provider_usage(step.get("usage"))
            provider, model = self._served_provider_model({"trace": [step]}, model_name)
            usage_record_id = "usage_stream_" + hashlib.sha256(
                f"{workflow_run_id}:{index}".encode("utf-8")
            ).hexdigest()
            records.append(
                self.ledger.record_usage(
                    provider=provider,
                    model=model,
                    prompt_tokens=counts[0] if counts else 0,
                    completion_tokens=counts[1] if counts else 0,
                    request_channel="stream",
                    route_mode=result.get("mode"),
                    workflow_run_id=workflow_run_id,
                    attribution=attribution,
                    measurement_status="measured" if counts else "unavailable",
                    usage_record_id=usage_record_id,
                )
            )
        statuses = {record.measurement_status for record in records}
        measurement_status = (
            "unavailable" if "unavailable" in statuses
            else "estimated" if "estimated" in statuses
            else "measured"
        )
        currencies = {record.currency_code for record in records}
        return {
            "usage_record_ids": [record.usage_record_id for record in records],
            "usage": (
                {
                    "input_tokens": sum(record.prompt_tokens for record in records),
                    "output_tokens": sum(record.completion_tokens for record in records),
                    "total_tokens": sum(record.total_tokens for record in records),
                }
                if measurement_status == "measured"
                else None
            ),
            "cost": {
                "cost_amount": (
                    round(sum(record.cost_amount for record in records), 6)
                    if measurement_status == "measured" and len(currencies) == 1
                    else None
                ),
                "currency_code": next(iter(currencies)) if len(currencies) == 1 else "MIXED",
                "measurement_status": measurement_status,
            },
        }

    # ------------------------------------------------------------------
    # Batch lifecycle
    # ------------------------------------------------------------------
    def submit_batch(
        self,
        requests: List[BatchRequest],
        metadata: Optional[Dict[str, Any]] = None,
        owner_id: Optional[str] = None,
    ) -> BatchJob:
        """Submit a batch, resolve its targets, and bind its authenticated owner."""
        try:
            prepared_requests = [self._resolve_batch_request(request) for request in requests]
        except ValueError as exc:
            raise InvalidBatchModelError(str(exc)) from exc
        except RuntimeError as exc:
            raise BatchModelSelectionError(
                "no eligible model-group member is available for this batch request"
            ) from exc
        job = self.batch_backend.submit(prepared_requests, metadata=metadata)
        job.owner_id = owner_id
        self._batch_jobs[job.job_id] = job
        return job

    def _resolve_batch_request(self, request: BatchRequest) -> BatchRequest:
        """Resolve only ZDR batch requests through the caller-provided model pool."""
        if not request.zdr_only:
            return request
        with self.orchestrator.request_policy(request.zdr_only):
            try:
                agent = self.orchestrator._requested_agent(request.model)
            except ValueError as exc:
                configured_exact = any(
                    candidate.model == request.model
                    for candidate in self.orchestrator.candidates
                )
                if configured_exact:
                    raise RuntimeError(
                        "requested model is configured but not eligible for ZDR batch routing"
                    ) from exc
                raise
            if agent is None:
                text = self.orchestrator._latest_user_text(request.messages)
                agent = self.orchestrator._select_agent(
                    text,
                    "worker",
                    free_only=request.model
                    == getattr(self.orchestrator, "FREE_MODEL", object()),
                )
        return replace(request, model=agent.model)

    def poll_batch(self, job_id: str, *, owner_id: Optional[str] = None) -> Dict[str, Any]:
        """Poll a previously submitted batch job owned by ``owner_id``."""
        job = self._require_job(job_id, owner_id=owner_id)
        return self.batch_backend.poll(job)

    def retrieve_batch(self, job_id: str, *, owner_id: Optional[str] = None) -> Dict[str, Any]:
        """Retrieve results for a batch owned by ``owner_id`` and record usage.

        Raises :class:`~contextual_orchestrator.batch_routing.BatchDownloadError`
        unchanged when the backend reports an explicit download failure
        (mirroring how ``KeyError`` from an unknown/unowned job id already
        propagates to the caller) rather than masking it as a zero-result
        success -- see ``batch_routing.BatchDownloadError`` for why.
        """
        job = self._require_job(job_id, owner_id=owner_id)
        items: List[BatchResultItem] = self.batch_backend.retrieve(job)
        recorded: List[Dict[str, Any]] = []
        for item in items:
            # Prefer the real request prompt the batch item carries (e.g. from
            # LocalBatchBackend) over a blank placeholder when the estimate
            # fallback below is triggered, so an "estimated" row is actually
            # estimated from what was asked rather than from empty content.
            fallback_messages = item.messages or [{"role": "user", "content": ""}]
            records = []
            if item.cache_status == "hit":
                records.append(self._record_completion(
                    messages=[], answer="", route_mode=item.mode,
                    request_channel="cache", attribution=item.attribution,
                    model_name=item.model, provider_model=("cache", "response"),
                    workflow_run_id=job.job_id, prompt_tokens=0, completion_tokens=0,
                    usage_record_id=self._batch_usage_record_id(job_id, item.custom_id, "cache", 0),
                ))
            request_prompt_attributed = False
            billable_steps = [] if item.cache_status == "hit" else [*item.race_usage, *item.trace]
            for index, step in enumerate(billable_steps):
                counts = self._provider_usage(step.get("usage"))
                attribute_request_prompt = counts is None and not request_prompt_attributed
                if attribute_request_prompt:
                    request_prompt_attributed = True
                records.append(
                    self._record_completion(
                        messages=fallback_messages if attribute_request_prompt else [],
                        answer=step.get("output", "") if counts is None else "",
                        route_mode=item.mode,
                        request_channel="batch",
                        attribution=item.attribution,
                        model_name=item.model,
                        provider_model=self._served_provider_model(
                            {"trace": [step]}, item.model
                        ),
                        workflow_run_id=job.job_id,
                        prompt_tokens=counts[0] if counts else None,
                        completion_tokens=counts[1] if counts else None,
                        usage_record_id=self._batch_usage_record_id(
                            job_id, item.custom_id, "step", index
                        ),
                    )
                )
            if not records:
                usage_valid = item.usage_valid is True or (
                    item.usage_valid is None
                    and item.prompt_tokens > 0
                    and item.completion_tokens > 0
                )
                records.append(
                    self._record_completion(
                        messages=fallback_messages,
                        answer=item.answer,
                        route_mode=item.mode,
                        request_channel="batch",
                        attribution=item.attribution,
                        model_name=item.model,
                        provider_model=self._resolve_batch_provider_model(item),
                        workflow_run_id=job.job_id,
                        prompt_tokens=item.prompt_tokens if usage_valid else None,
                        completion_tokens=item.completion_tokens if usage_valid else None,
                        usage_record_id=self._batch_usage_record_id(
                            job_id, item.custom_id, "result", 0
                        ),
                    )
                )
            currencies = {record.currency_code for record in records}
            recorded.append(
                {
                    "custom_id": item.custom_id,
                    "answer": item.answer,
                    "usage_record_id": records[-1].usage_record_id,
                    "usage_record_ids": [record.usage_record_id for record in records],
                    "cost_amount": (
                        round(sum(record.cost_amount for record in records), 6)
                        if len(currencies) == 1
                        else None
                    ),
                    "currency_code": (
                        next(iter(currencies)) if len(currencies) == 1 else "MIXED"
                    ),
                    "prompt_tokens": sum(record.prompt_tokens for record in records),
                    "completion_tokens": sum(
                        record.completion_tokens for record in records
                    ),
                    "measurement_status": (
                        "estimated"
                        if any(
                            record.measurement_status == "estimated"
                            for record in records
                        )
                        else "measured"
                    ),
                    **({"currency_components": [
                        {
                            "currency_code": currency,
                            "cost_amount": round(sum(
                                record.cost_amount for record in records
                                if record.currency_code == currency
                            ), 6),
                        }
                        for currency in sorted(currencies)
                    ]} if len(currencies) > 1 else {}),
                }
            )
        return {
            "job_id": job_id,
            "backend": job.backend,
            "result_count": len(recorded),
            "results": recorded,
        }

    @staticmethod
    def _batch_usage_record_id(job_id: str, custom_id: str, kind: str, index: int) -> str:
        identity = f"{job_id}\x00{custom_id}\x00{kind}\x00{index}"
        return "usage_batch_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def _resolve_batch_provider_model(self, item: BatchResultItem) -> tuple[str, str]:
        provider = str(item.attribution.get("provider") or item.attribution.get("upstream_api") or "")
        if not provider:
            provider = "unknown"
        return provider, item.model

    def _require_job(self, job_id: str, *, owner_id: Optional[str] = None) -> BatchJob:
        job = self._batch_jobs.get(job_id)
        if job is None or job.owner_id != owner_id:
            raise KeyError(f"batch job {job_id!r} not found")
        return job

    # ------------------------------------------------------------------
    # Embeddings batch lifecycle
    # ------------------------------------------------------------------
    def submit_embeddings_batch(
        self,
        inputs: List[str],
        *,
        model: str = "contextual-orchestrator",
        attribution: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        zdr_only: bool = False,
        agent_id: Optional[str] = None,
    ) -> BatchJob:
        """Submit a bulk embeddings batch to the configured embeddings backend.

        This is the surface naruon's batch embedding service submits to. Each
        input becomes one :class:`EmbeddingBatchRequest`; routing + cost stay
        owned by the orchestrator. Returns the backend job handle; the vectors
        and recorded cost are produced by :meth:`embeddings_batch_document`.
        """
        if type(zdr_only) is not bool:
            raise TypeError("zdr_only must be a boolean")
        if agent_id is not None and (not isinstance(agent_id, str) or not agent_id):
            raise TypeError("agent_id must be a non-empty string when provided")
        resolved_model, resolved_agent_id = self._resolve_embedding_target(model, zdr_only, agent_id)
        shared_attribution = dict(attribution or {})
        requests, part_counts, part_limits = self._build_embedding_requests(
            inputs,
            model=resolved_model,
            attribution=shared_attribution,
            zdr_only=zdr_only,
            agent_id=resolved_agent_id,
        )
        job = self.embedding_batch_backend.submit(requests, metadata=metadata)
        self._embedding_jobs[job.job_id] = job
        self._embedding_models[job.job_id] = resolved_model
        self._embedding_requests[job.job_id] = requests
        self._embedding_input_counts[job.job_id] = len(inputs)
        self._embedding_part_counts[job.job_id] = part_counts
        self._embedding_part_limits[job.job_id] = part_limits
        return job

    def _resolve_embedding_target(
        self, model: str, zdr_only: bool, agent_id: Optional[str]
    ) -> tuple[str, Optional[str]]:
        """Resolve one embedding member without losing a caller's member choice."""
        if agent_id is None and not zdr_only:
            return model, None
        selection_model = (
            None
            if model in {"contextual-orchestrator", getattr(self.orchestrator, "AUTO_MODEL", "")}
            else model
        )
        with self.orchestrator.request_policy(zdr_only):
            candidates = self.orchestrator._capability_agents("embedding", selection_model)
        if agent_id is None:
            return candidates[0].model, candidates[0].id
        for candidate in candidates:
            if candidate.id == agent_id:
                return candidate.model, candidate.id
        raise RuntimeError(f"embedding agent {agent_id!r} is not eligible for this request")

    def _build_embedding_requests(
        self,
        inputs: List[str],
        *,
        model: str,
        attribution: Dict[str, Any],
        zdr_only: bool,
        agent_id: Optional[str],
    ) -> tuple[List[EmbeddingBatchRequest], List[int], Dict[str, int]]:
        """Map original embedding inputs into token-budgeted provider parts."""
        max_tokens, max_chars = self._embedding_request_limits()
        requests: List[EmbeddingBatchRequest] = []
        part_counts: List[int] = []
        for source_index, text in enumerate(inputs):
            source_text = str(text)
            parts = self._split_embedding_input(
                source_text, model=model, max_tokens=max_tokens, max_chars=max_chars
            )
            part_count = len(parts)
            part_counts.append(part_count)
            for part_index, (part_text, token_count) in enumerate(parts):
                requests.append(
                    EmbeddingBatchRequest(
                        input_text=part_text,
                        model=model,
                        attribution=dict(attribution),
                        source_index=source_index,
                        part_index=part_index,
                        part_count=part_count,
                        token_count=token_count,
                        zdr_only=zdr_only,
                        agent_id=agent_id,
                    )
                )
        return requests, part_counts, {
            "max_tokens_per_part": max_tokens,
            "max_chars_per_part": max_chars,
        }

    def _embedding_request_limits(self) -> tuple[int, int]:
        """Return configured per-provider-call embedding ceilings.

        Azure's current embeddings limit is surfaced by LiteLLM as a 300,000
        token request cap. The default stays below that ceiling and also applies
        a character guard so heuristic token counters cannot accidentally send a
        very long no-whitespace string as one provider request.
        """
        max_tokens = _positive_int(
            self.config.get(
                _EMBEDDING_CONFIG_CATEGORY,
                "embedding_max_tokens_per_request",
                _DEFAULT_EMBEDDING_MAX_TOKENS_PER_REQUEST,
            ),
            _DEFAULT_EMBEDDING_MAX_TOKENS_PER_REQUEST,
        )
        max_chars = _positive_int(
            self.config.get(
                _EMBEDDING_CONFIG_CATEGORY,
                "embedding_max_chars_per_part",
                _DEFAULT_EMBEDDING_MAX_CHARS_PER_PART,
            ),
            _DEFAULT_EMBEDDING_MAX_CHARS_PER_PART,
        )
        return max_tokens, max_chars

    def _split_embedding_input(
        self,
        text: str,
        *,
        model: str,
        max_tokens: int,
        max_chars: int,
    ) -> List[tuple[str, int]]:
        """Split one original embedding input into provider-safe map parts."""
        if text == "":
            return [("", 0)]
        parts = self._force_token_safe_chunks(
            text, model=model, max_tokens=max_tokens, max_chars=max_chars
        )
        return parts or [("", 0)]

    def _force_token_safe_chunks(
        self,
        text: str,
        *,
        model: str,
        max_tokens: int,
        max_chars: int,
    ) -> List[tuple[str, int]]:
        """Recursively split text until each chunk fits token and char budgets."""
        if text == "":
            return [("", 0)]
        if len(text) > max_chars:
            chunks: List[tuple[str, int]] = []
            for start in range(0, len(text), max_chars):
                chunks.extend(
                    self._force_token_safe_chunks(
                        text[start : start + max_chars],
                        model=model,
                        max_tokens=max_tokens,
                        max_chars=max_chars,
                    )
                )
            return chunks

        token_count = self._count_embedding_tokens(text, model)
        if token_count <= max_tokens or len(text) <= 1:
            return [(text, token_count)]

        units = _EMBEDDING_UNIT_RE.findall(text)
        if len(units) > 1:
            chunks = []
            current = ""
            for unit in units:
                candidate = f"{current}{unit}"
                if current and (
                    len(candidate) > max_chars
                    or self._count_embedding_tokens(candidate, model) > max_tokens
                ):
                    chunks.extend(
                        self._force_token_safe_chunks(
                            current,
                            model=model,
                            max_tokens=max_tokens,
                            max_chars=max_chars,
                        )
                    )
                    current = unit
                else:
                    current = candidate
            # ``current`` always holds the final candidate here: the regex
            # above yields only nonempty units, so the last assignment is a
            # nonempty string.
            chunks.extend(
                self._force_token_safe_chunks(
                    current,
                    model=model,
                    max_tokens=max_tokens,
                    max_chars=max_chars,
                )
            )
            # Every recursive call above receives strictly shorter input than
            # ``text`` (midpoint and early-fit returns cannot reproduce it), so
            # ``chunks`` always differs from the original single part here.
            return chunks

        midpoint = max(1, len(text) // 2)
        return self._force_token_safe_chunks(
            text[:midpoint],
            model=model,
            max_tokens=max_tokens,
            max_chars=max_chars,
        ) + self._force_token_safe_chunks(
            text[midpoint:],
            model=model,
            max_tokens=max_tokens,
            max_chars=max_chars,
        )

    def _count_embedding_tokens(self, text: str, model: str) -> int:
        """Count tokens for embedding split decisions, tolerating adapters."""
        try:
            value = int(self.token_counter.count_text(text, model))
        except Exception:
            value = len(text.split())
        if text and value <= 0:
            return 1
        return max(0, value)

    def embeddings_batch_document(self, batch_id: str) -> Dict[str, Any]:
        """Return the naruon-shaped batch document for ``batch_id``.

        Polls the backend; once complete, retrieves the vectors, records one
        usage record per embedding in the cost ledger (full attribution), and
        returns ``{batch_id, status, embeddings, cost_micro_usd, token_counts,
        total_tokens, part_count, model}``. Idempotent: the completed document is
        cached so a poll after completion never double-records cost.
        """
        cached = self._embedding_documents.get(batch_id)
        if cached is not None:
            return cached

        job = self._require_embedding_job(batch_id)
        requests = self._embedding_requests.get(batch_id, [])
        model_name = self._embedding_models.get(batch_id, "contextual-orchestrator")
        status = self.embedding_batch_backend.poll(job)
        if not status.get("is_complete"):
            return {
                "batch_id": batch_id,
                "status": status.get("status") or job.status,
                "backend": job.backend,
                "model": model_name,
                "embeddings": None,
            }

        try:
            items: List[EmbeddingBatchResultItem] = self.embedding_batch_backend.retrieve(job)
        except BatchDownloadError as exc:
            # Deliberately NOT cached: an explicit download failure must stay
            # retryable. Caching this under "completed" (as a bare `return []`
            # from the backend used to force) would permanently poison
            # ``batch_id`` with fabricated zero-vectors that no later retry
            # could ever repair, since a cache hit above short-circuits
            # poll/retrieve entirely.
            return {
                "batch_id": batch_id,
                "status": "failed",
                "backend": job.backend,
                "model": model_name,
                "embeddings": None,
                "error": str(exc),
            }
        request_by_custom_id = {request.custom_id: request for request in requests}
        input_count = self._embedding_input_counts.get(batch_id, len(requests))
        part_counts = self._embedding_part_counts.get(batch_id, [1] * input_count)
        part_limits = self._embedding_part_limits.get(batch_id, {})
        ordered = sorted(items, key=lambda item: item.index)
        parts_by_source: Dict[int, List[Dict[str, Any]]] = {index: [] for index in range(input_count)}
        for item in ordered:
            request = request_by_custom_id.get(item.custom_id)
            source_index = request.source_index if request else item.index
            prompt_tokens = int(item.prompt_tokens)
            if prompt_tokens <= 0 and request is not None:
                prompt_tokens = request.token_count or int(
                    self.token_counter.count_text(request.input_text, item.model)
                )
            parts_by_source.setdefault(source_index, []).append(
                {
                    "part_index": request.part_index if request else 0,
                    "embedding": item.embedding,
                    "prompt_tokens": max(0, prompt_tokens),
                    "model": item.model,
                    "attribution": dict(request.attribution) if request else {},
                }
            )

        embeddings: List[Dict[str, Any]] = []
        token_counts: List[int] = []
        total_cost_amount = 0.0
        currency_code = "USD"
        for source_index in range(input_count):
            parts = sorted(parts_by_source.get(source_index, []), key=lambda item: item["part_index"])
            if not parts:
                embeddings.append({"index": source_index, "embedding": []})
                token_counts.append(0)
                continue
            attribution = dict(parts[0]["attribution"])
            prompt_tokens = sum(int(part["prompt_tokens"]) for part in parts)
            model_name = str(parts[0]["model"])
            provider = str(
                attribution.get("provider") or attribution.get("upstream_api") or "unknown"
            )
            record = self.ledger.record_usage(
                provider=provider,
                model=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=0,
                request_channel="batch",
                route_mode="embedding",
                workflow_run_id=batch_id,
                attribution=attribution,
            )
            total_cost_amount += float(record.cost_amount)
            currency_code = record.currency_code
            token_counts.append(record.prompt_tokens)
            embeddings.append(
                {
                    "index": source_index,
                    "embedding": _weighted_average_embedding(
                        [(part["embedding"], int(part["prompt_tokens"])) for part in parts]
                    ),
                }
            )

        document = {
            "batch_id": batch_id,
            "status": "completed",
            "backend": job.backend,
            "model": model_name,
            "embeddings": embeddings,
            "token_counts": token_counts,
            "total_tokens": sum(token_counts),
            "part_count": len(requests),
            "input_part_counts": part_counts,
            "map_reduce": {
                "strategy": "token_budgeted_embedding_parts_weighted_average",
                **part_limits,
            },
            "cost_amount": round(total_cost_amount, 6),
            "currency_code": currency_code,
            "cost_micro_usd": int(round(total_cost_amount * 1_000_000)),
        }
        self._embedding_documents[batch_id] = document
        return document

    def complete_embeddings_batch(
        self,
        inputs: List[str],
        *,
        model: str = "contextual-orchestrator",
        attribution: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        zdr_only: bool = False,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Submit an embeddings batch and return its document (one round-trip).

        For the local/in-process backend the batch completes synchronously, so
        this returns the finished ``completed`` document with vectors and cost.
        For an async backend (pg-llm-batch) it returns a ``{batch_id, status}``
        envelope the caller then polls via :meth:`embeddings_batch_document`.
        """
        job = self.submit_embeddings_batch(
            inputs,
            model=model,
            attribution=attribution,
            metadata=metadata,
            zdr_only=zdr_only,
            agent_id=agent_id,
        )
        return self.embeddings_batch_document(job.job_id)

    def _require_embedding_job(self, batch_id: str) -> BatchJob:
        job = self._embedding_jobs.get(batch_id)
        if job is None:
            raise KeyError(f"embeddings batch job {batch_id!r} not found")
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


def _positive_int(value: Any, default: int) -> int:
    """Return ``value`` as a positive int, or ``default`` when invalid."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _weighted_average_embedding(parts: List[tuple[List[float], int]]) -> List[float]:
    """Reduce mapped chunk vectors into one deterministic embedding vector."""
    vectors = [vector for vector, _weight in parts if vector]
    if not vectors:
        return []
    dimension = max(len(vector) for vector in vectors)
    # Every weight clamps to at least 1, so a non-empty part list always
    # yields a positive total.
    total_weight = sum(max(1, int(weight)) for _vector, weight in parts)
    reduced: List[float] = []
    for offset in range(dimension):
        weighted_sum = 0.0
        for vector, weight in parts:
            weighted_sum += (vector[offset] if offset < len(vector) else 0.0) * max(1, int(weight))
        reduced.append(round(weighted_sum / total_weight, 8))
    return reduced
