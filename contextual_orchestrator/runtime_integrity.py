"""Runtime integrity guards for execution identity and embedding provenance.

This module centralizes fail-closed rules that must hold even while the legacy
HTTP and cost-routing surfaces are being consolidated. It deliberately keeps
caller-supplied attribution descriptive: execution identity (provider/model)
is derived from the operation that actually ran, never from untrusted request
metadata.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .batch_routing import LocalEmbeddingBatchBackend
from .cost_router import CostRoutingCoordinator as _BaseCostRoutingCoordinator


LOCAL_HEURISTIC_EMBEDDING_MODEL = "local-heuristic-embedding"
_EXECUTION_IDENTITY_KEYS = frozenset({"model_name", "provider", "upstream_api"})


def _descriptive_attribution(attribution: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return attribution with caller-controlled execution identity removed.

    ``model_name`` and provider aliases are evidence produced by execution, not
    labels a caller may choose. Account/service/team/group/company remain valid
    descriptive dimensions.
    """

    cleaned = dict(attribution or {})
    for key in _EXECUTION_IDENTITY_KEYS:
        cleaned.pop(key, None)
    return cleaned


class IntegrityCostRoutingCoordinator(_BaseCostRoutingCoordinator):
    """Cost-routing coordinator with fail-closed execution provenance.

    The local embedding backend is an offline deterministic test backend. It
    therefore accepts only the explicit ``local-heuristic-embedding`` model id;
    an arbitrary chat/provider model can never be represented by its SHA-derived
    vector. Caller attribution is also prevented from overwriting provider or
    model evidence in the usage ledger.
    """

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
        """Run completion routing without trusting caller execution identity."""

        return super().complete(
            messages,
            mode=mode,
            attribution=_descriptive_attribution(attribution),
            hints=hints,
            model_name=model_name,
            workflow_run_id=workflow_run_id,
        )

    def submit_embeddings_batch(
        self,
        inputs: List[str],
        *,
        model: str = "contextual-orchestrator",
        attribution: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Submit embeddings only when backend/model provenance is truthful."""

        cleaned = _descriptive_attribution(attribution)
        if isinstance(self.embedding_batch_backend, LocalEmbeddingBatchBackend):
            if model != LOCAL_HEURISTIC_EMBEDDING_MODEL:
                raise ValueError(
                    "local embedding backend only serves "
                    f"{LOCAL_HEURISTIC_EMBEDDING_MODEL!r}; requested model {model!r} "
                    "would falsely attribute a heuristic vector"
                )
            cleaned["upstream_api"] = "local_heuristic"
        return super().submit_embeddings_batch(
            inputs,
            model=model,
            attribution=cleaned,
            metadata=metadata,
        )


def install_runtime_integrity_guards() -> None:
    """Install the hardened coordinator as the canonical cost-router class.

    ``server`` imports ``CostRoutingCoordinator`` from the module at import time,
    so installing the alias during package initialization gives every public
    entrypoint the same provenance contract without duplicating endpoint logic.
    """

    from . import cost_router

    cost_router.CostRoutingCoordinator = IntegrityCostRoutingCoordinator
