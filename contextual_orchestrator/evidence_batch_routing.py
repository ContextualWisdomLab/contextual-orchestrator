"""Evidence-bounded replacements for legacy batch-routing decision seams.

The historical :mod:`contextual_orchestrator.batch_routing` module contains the
batch protocol and backend implementations.  This module owns the decision
surfaces that may affect production outcomes.  It deliberately accepts legacy
metadata for wire compatibility while refusing to turn that metadata into a
routing heuristic.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .batch_routing import (
    BatchJob,
    EmbeddingBatchRequest,
    LocalEmbeddingBatchBackend as _LegacyLocalEmbeddingBatchBackend,
    RoutingDecision,
    RoutingHints,
)

_ROUTING_CATEGORY = "routing"


class RoutingPolicy:
    """Resolve sync versus batch only from explicit caller intent.

    ``latency_tolerant``, ``priority``, prompt size, and legacy KV thresholds
    remain accepted as compatibility metadata but are not decision authority.
    In the absence of an explicit channel the synchronous request contract is
    preserved.  ``batch_enabled`` is an operator kill switch rather than a
    routing score.
    """

    def __init__(self, config_store: Any) -> None:
        self._config = config_store

    def _batch_enabled(self) -> bool:
        return bool(self._config.get(_ROUTING_CATEGORY, "batch_enabled", True))

    def decide(
        self,
        hints: RoutingHints,
        prompt_tokens: int | None = None,
    ) -> RoutingDecision:
        """Return a fail-closed routing decision without inferred preferences."""
        del prompt_tokens
        if not self._batch_enabled():
            return RoutingDecision("sync", "batch routing disabled by operator config")
        if hints.channel == "batch":
            return RoutingDecision("batch", "caller explicitly requested batch channel")
        if hints.channel == "sync":
            return RoutingDecision("sync", "caller explicitly requested sync channel")
        return RoutingDecision("sync", "batch requires an explicit caller channel")


def cheapest_upstream(
    candidates: List[Dict[str, str]],
    price_book: Any,
    *,
    prompt_tokens: int,
    completion_tokens: int,
) -> Optional[Dict[str, str]]:
    """Return a uniquely cheapest candidate for the exact request shape.

    Both token quantities must be authoritative inputs supplied by the caller.
    Unknown prices and equal minimum costs leave selection unresolved.  Input
    order is therefore never used as a substantive tie-break.
    """
    for name, value in (
        ("prompt_tokens", prompt_tokens),
        ("completion_tokens", completion_tokens),
    ):
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")

    priced: list[tuple[Dict[str, str], float]] = []
    for candidate in candidates:
        provider = candidate.get("provider", "")
        model = candidate.get("model", "")
        cost, _currency, price_known = price_book.compute_cost(
            provider,
            model,
            prompt_tokens,
            completion_tokens,
        )
        if price_known:
            priced.append((candidate, cost))
    if not priced:
        return None

    minimum = min(cost for _candidate, cost in priced)
    winners = [candidate for candidate, cost in priced if cost == minimum]
    return winners[0] if len(winners) == 1 else None


def resolve_embedding_target_evidence_only(
    coordinator: Any,
    model: str,
    zdr_only: bool,
    agent_id: Optional[str],
) -> tuple[str, Optional[str]]:
    """Resolve an embedding route only from explicit or uniquely eligible evidence.

    A concrete non-ZDR model remains explicit caller intent and therefore does
    not require capability-pool ranking.  Virtual-model and ZDR requests must
    either identify an exact eligible ``agent_id`` or have exactly one eligible
    candidate.  Price, discovery order, and static rank never break ambiguity.

    Candidate identity and model are snapshotted exactly once before comparison
    so changing getters or Proxy-like objects cannot pass one check and return a
    different routing identity later in the same decision.
    """
    virtual_models = {
        "contextual-orchestrator",
        getattr(coordinator.orchestrator, "AUTO_MODEL", ""),
    }
    unspecified_model = model in virtual_models
    if agent_id is None and not zdr_only and not unspecified_model:
        return model, None

    selection_model = None if unspecified_model else model
    with coordinator.orchestrator.request_policy(zdr_only):
        candidates = list(
            coordinator.orchestrator._capability_agents("embedding", selection_model)
        )

    snapshots: list[tuple[str, str]] = []
    for candidate in candidates:
        candidate_id = getattr(candidate, "id", None)
        candidate_model = getattr(candidate, "model", None)
        if not isinstance(candidate_id, str) or not candidate_id:
            raise RuntimeError("eligible embedding candidate omitted a stable agent id")
        if not isinstance(candidate_model, str) or not candidate_model:
            raise RuntimeError("eligible embedding candidate omitted a stable model id")
        snapshots.append((candidate_id, candidate_model))

    if agent_id is None:
        if not snapshots:
            raise RuntimeError("no eligible embedding agent is available for this request")
        if len(snapshots) != 1:
            raise RuntimeError(
                "multiple eligible embedding agents require an explicit agent_id "
                "or an independently evaluated routing model"
            )
        candidate_id, candidate_model = snapshots[0]
        return candidate_model, candidate_id

    for candidate_id, candidate_model in snapshots:
        if candidate_id == agent_id:
            return candidate_model, candidate_id
    raise RuntimeError(f"embedding agent {agent_id!r} is not eligible for this request")


def prohibited_heuristic_embedding(
    text: str,
    dimension: int = 8,
) -> List[float]:
    """Compatibility tombstone for the retired SHA-derived pseudo-embedding.

    The parameters are retained only so stale callers receive an explicit
    fail-closed error instead of silently fabricating semantic vectors.
    """
    del text, dimension
    raise RuntimeError(
        "heuristic embeddings are prohibited; an explicit semantic embedding implementation is required"
    )


def _unavailable_embedder(_text: str) -> List[float]:
    raise RuntimeError("an explicit embedding implementation is required")


class LocalEmbeddingBatchBackend(_LegacyLocalEmbeddingBatchBackend):
    """Local embedding backend requiring explicit semantics and accounting.

    The legacy backend remains the protocol/storage implementation.  This
    wrapper prevents its SHA-derived fallback from ever becoming runtime
    semantic output.  A backend created without an embedder can still retrieve
    historical local jobs, but every new submission fails closed.
    """

    def __init__(
        self,
        embedder: Any = None,
        *,
        token_counter: Any = None,
        dimension: int | None = None,
        job_registry: Any = None,
    ) -> None:
        # ``dimension`` is accepted only for source compatibility.  Without an
        # explicit embedder it cannot create a vector or affect a decision.
        del dimension
        self._explicit_embedder = embedder
        super().__init__(
            embedder=embedder if embedder is not None else _unavailable_embedder,
            token_counter=token_counter,
            job_registry=job_registry,
        )

    def submit(
        self,
        requests: List[EmbeddingBatchRequest],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> BatchJob:
        """Reject new local embedding work unless semantics were injected."""
        if self._explicit_embedder is None:
            raise RuntimeError("an explicit embedding implementation is required")
        return super().submit(requests, metadata=metadata)
