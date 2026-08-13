"""Runtime integrity guards for execution identity and embedding provenance.

This module centralizes fail-closed rules that must hold even while the legacy
HTTP and cost-routing surfaces are being consolidated. It deliberately keeps
caller-supplied attribution descriptive: execution identity (provider/model)
is derived from the operation that actually ran, never from untrusted request
metadata.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Dict, List, Optional

from .batch_routing import LocalEmbeddingBatchBackend
from .cost_ledger import CostLedger
from .cost_router import CostRoutingCoordinator as _BaseCostRoutingCoordinator


LOCAL_HEURISTIC_EMBEDDING_MODEL = "local-heuristic-embedding"
_EXECUTION_IDENTITY_KEYS = frozenset({"model_name", "provider", "upstream_api"})
_LEDGER_GUARD_MARKER = "__contextual_orchestrator_execution_identity_guard__"


def _descriptive_attribution(attribution: Any) -> Dict[str, Any]:
    """Return attribution with caller-controlled execution identity removed.

    ``model_name`` and provider aliases are evidence produced by execution, not
    labels a caller may choose. Account/service/team/group/company remain valid
    descriptive dimensions. Both mappings and AttributionDimensions-like
    objects are accepted because :meth:`CostLedger.record_usage` exposes both.
    """

    if attribution is None:
        cleaned: Dict[str, Any] = {}
    elif isinstance(attribution, dict):
        cleaned = dict(attribution)
    else:
        as_dict = getattr(attribution, "as_dict", None)
        if not callable(as_dict):
            raise TypeError("attribution must be a mapping or attribution dimensions object")
        cleaned = dict(as_dict())
    for key in _EXECUTION_IDENTITY_KEYS:
        cleaned.pop(key, None)
    return cleaned


def _install_cost_ledger_identity_guard() -> None:
    """Make execution identity authoritative for every public ledger write.

    The cost ledger is exported as a public API, so protecting only the HTTP
    coordinator leaves a bypass: a direct caller could otherwise provide
    ``attribution.model_name`` or a provider alias and cause persisted rollups to
    disagree with the provider/model used to price the request. The wrapper is
    idempotent and preserves the original method's behavior for descriptive
    attribution.
    """

    current = CostLedger.record_usage
    if getattr(current, _LEDGER_GUARD_MARKER, False):
        return

    @wraps(current)
    def guarded_record_usage(self: CostLedger, *args: Any, **kwargs: Any):
        kwargs["attribution"] = _descriptive_attribution(kwargs.get("attribution"))
        return current(self, *args, **kwargs)

    setattr(guarded_record_usage, _LEDGER_GUARD_MARKER, True)
    CostLedger.record_usage = guarded_record_usage  # type: ignore[method-assign]


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
    """Install hardened provenance guards for all public runtime entrypoints.

    ``server`` imports ``CostRoutingCoordinator`` from the module at import time,
    so installing the alias during package initialization gives every HTTP
    entrypoint the same provenance contract. The ledger guard closes the direct
    public-API bypass as well.
    """

    from . import cost_router

    _install_cost_ledger_identity_guard()
    cost_router.CostRoutingCoordinator = IntegrityCostRoutingCoordinator
