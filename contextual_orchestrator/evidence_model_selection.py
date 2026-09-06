"""Fail-closed model selection that requires identified routing evidence.

This module is a compatibility bridge while the historical static ranking code
is removed from ``orchestrator.py``. It deliberately exposes no priority,
metadata-similarity, provider-name, discovery-order, or transport-composite
fallback. Multiple eligible candidates require complete exact-context
fast-mlsirm evidence; otherwise selection is unresolved.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .model_group import (
    BETA_PRIOR_FAILURE_COUNT,
    BETA_PRIOR_SUCCESS_COUNT,
    RATE_OBSERVATION_WINDOW_SECONDS,
    UNOBSERVED_MEMBER_SCORE,
    ModelGroupRouter,
    canonical_group_name,
)


def ranked_agents_evidence_only(
    self: Any,
    text: str,
    role: str,
    *,
    required_tags: tuple[str, ...] = (),
    free_only: bool = False,
    chat_only: bool = True,
    candidate_pool: Iterable[Any] | None = None,
    prompt_context: str | None = None,
    effort_profile: Any = None,
) -> list[Any]:
    """Return an identified order or fail closed when routing is ambiguous."""
    from .orchestrator import (
        _REQUEST_ZDR_ONLY,
        _agent_matches_request_endpoint,
        _eligible_role_effort_candidates,
        _is_general_chat_agent,
    )

    del text
    source = self.agents if candidate_pool is None else list(candidate_pool)
    candidates = [
        agent
        for agent in source
        if not agent.disabled
        and _agent_matches_request_endpoint(agent)
        and self._zdr_agent_allowed(agent)
        and role not in agent.provider_exclusions
        and (
            not free_only
            or (
                self._is_general_free_agent(agent)
                if chat_only
                else self._is_free_agent(agent)
            )
        )
        and (
            not free_only
            or getattr(agent, "credential_name", "") != "OPENAI_API_KEY"
        )
        and (not chat_only or _is_general_chat_agent(agent))
        and all(tag in agent.tags for tag in required_tags)
    ]
    if chat_only:
        candidates = _eligible_role_effort_candidates(
            candidates, effort_profile or self._role_effort_profile(role)
        )
    if not candidates:
        if _REQUEST_ZDR_ONLY.get():
            raise RuntimeError(
                "no ZDR-eligible agent is available for the active privacy policy"
            )
        if free_only:
            raise RuntimeError("no enabled zero-cost model is available")
        if chat_only:
            raise RuntimeError("no chat-compatible agent available")
        raise RuntimeError("no eligible capability agent is available")
    if len(candidates) == 1:
        return candidates

    if prompt_context:
        evidence = self._psychometric_router.ranked_evidence(
            [candidate.id for candidate in candidates],
            prompt_context,
            None,
        )
        evidenced_ids = [agent_id for agent_id, _score in evidence]
        candidate_ids = {candidate.id for candidate in candidates}
        if (
            len(evidenced_ids) == len(candidates)
            and len(set(evidenced_ids)) == len(candidates)
            and set(evidenced_ids) == candidate_ids
        ):
            by_id = {candidate.id: candidate for candidate in candidates}
            return [by_id[agent_id] for agent_id in evidenced_ids]

    raise RuntimeError(
        "multiple eligible agents require complete exact-context psychometric "
        "routing evidence or explicit model/agent selection"
    )


def requested_agent_evidence_only(self: Any, requested_model: Any) -> Any | None:
    """Resolve an explicit model only when it identifies one eligible agent."""
    from .orchestrator import (
        _REQUEST_ZDR_ONLY,
        _agent_matches_request_endpoint,
    )

    if requested_model is None or requested_model in {
        self.GATEWAY_DEFAULT_MODEL,
        self.AUTO_MODEL,
        self.FREE_MODEL,
    }:
        return None
    if type(requested_model) is not str or not requested_model:
        raise ValueError("requested model must be a configured non-empty string")

    exact = [
        candidate
        for candidate in self.candidates
        if candidate.model == requested_model
        and _agent_matches_request_endpoint(candidate)
        and self._zdr_agent_allowed(candidate)
        and (not _REQUEST_ZDR_ONLY.get() or not candidate.disabled)
    ]
    if exact:
        enabled = [candidate for candidate in exact if not candidate.disabled]
        if len(enabled) == 1:
            return enabled[0]
        if len(enabled) > 1:
            raise RuntimeError(
                "requested model maps to multiple eligible agents; explicit endpoint "
                "or other identified routing evidence is required"
            )
        if len(exact) == 1:
            return exact[0]
        raise RuntimeError("requested model has no uniquely identifiable enabled agent")

    configured_exact = any(
        candidate.model == requested_model for candidate in self.candidates
    )
    if configured_exact:
        raise ValueError(f"requested model {requested_model!r} is not configured")

    try:
        requested_group = canonical_group_name(requested_model)
    except ValueError:
        requested_group = ""
    group_candidates = [
        candidate
        for candidate in self.candidates
        if candidate.group_name
        and canonical_group_name(candidate.group_name) == requested_group
        and not candidate.disabled
        and _agent_matches_request_endpoint(candidate)
        and self._zdr_agent_allowed(candidate)
    ]
    if len(group_candidates) == 1:
        return group_candidates[0]
    if len(group_candidates) > 1:
        raise RuntimeError(
            "requested model group contains multiple eligible agents; explicit endpoint "
            "or other identified routing evidence is required"
        )
    raise ValueError(f"requested model {requested_model!r} is not configured")


def prohibited_static_rank_key(*_args: Any, **_kwargs: Any) -> tuple[()]:
    """Tombstone the historical priority/cosine/identifier routing key."""
    raise RuntimeError(
        "static priority/cosine/identifier routing is prohibited; use identified evidence"
    )


def measured_member_order_fail_closed(self: Any, member_ids: list[str]) -> list[str]:
    """Do not convert transport/quality diagnostics into an ad-hoc route order."""
    if len(member_ids) <= 1:
        return list(member_ids)
    raise RuntimeError(
        "multiple model-group members require explicit or validated routing evidence"
    )


def get_model_group_diagnostic(self: Any, group_name: str) -> dict[str, Any]:
    """Return group observations without presenting a diagnostic score as a route order.

    Agent identifiers are sorted only to provide canonical serialization for the
    admin/read surface. That order is not used by any inference selector.
    """
    from .orchestrator import MODEL_CAPABILITIES

    name = canonical_group_name(group_name)
    members = [
        agent
        for agent in self.candidates
        if agent.group_name and canonical_group_name(agent.group_name) == name
    ]
    if not members:
        raise KeyError(name)
    members_by_id = {agent.id: agent for agent in members}
    display_ids = sorted(members_by_id)
    return {
        "group_name": name,
        "member_agent_ids": display_ids,
        "member_order_authority": "none",
        "enabled_member_count": sum(1 for agent in members if not agent.disabled),
        "capability_coverage": {
            capability: sum(capability in agent.tags for agent in members)
            for capability in sorted(MODEL_CAPABILITIES)
            if any(capability in agent.tags for agent in members)
        },
        "members": [
            self._agent_to_admin_payload(members_by_id[agent_id])
            for agent_id in display_ids
        ],
    }


def model_group_member_score_prohibited(self: Any, member_id: str) -> float:
    """Reject the retired posterior/latency quotient as routing authority."""
    del self, member_id
    raise RuntimeError(
        "composite routing score is prohibited without a validated routing estimand"
    )


def model_group_ranked_member_ids_fail_closed(
    self: Any,
    member_ids: list[str] | tuple[str, ...],
) -> list[str]:
    """Return a singleton identity or require a validated routing model."""
    del self
    identities = list(member_ids)
    if len(identities) <= 1:
        return identities
    raise RuntimeError(
        "multiple model-group members require an explicit or validated routing model"
    )


def model_group_score_locked_prohibited(self: Any, member_id: str) -> float:
    """Prevent private callers from reviving the retired composite score."""
    del self, member_id
    raise RuntimeError(
        "composite routing score is prohibited without a validated routing estimand"
    )


def model_group_report_locked_diagnostic(
    self: Any,
    member_id: str,
) -> dict[str, float | int | None]:
    """Return separate observed quantities without synthesizing a route score."""
    state = self._members.get(member_id)
    if state is None:
        return {
            "success_posterior_mean": UNOBSERVED_MEMBER_SCORE,
            "ewma_latency_seconds": None,
            "ewma_tokens_per_second": None,
            "max_observed_rpm": 0,
            "max_observed_tpm": 0,
            "rate_observation_window_seconds": int(RATE_OBSERVATION_WINDOW_SECONDS),
            "success_count": 0,
            "failure_count": 0,
            "score": None,
        }
    alpha = float(state["alpha"])
    beta = float(state["beta"])
    ewma = state["ewma"]
    ewma_tps = state["ewma_tps"]
    return {
        "success_posterior_mean": round(alpha / (alpha + beta), 6),
        "ewma_latency_seconds": None if ewma is None else round(float(ewma), 6),
        "ewma_tokens_per_second": (
            None if ewma_tps is None else round(float(ewma_tps), 6)
        ),
        "max_observed_rpm": self._max_observed_rpm.get(member_id, 0),
        "max_observed_tpm": self._max_observed_tpm.get(member_id, 0),
        "rate_observation_window_seconds": int(RATE_OBSERVATION_WINDOW_SECONDS),
        "success_count": int(
            alpha - float(state.get("prior_alpha", BETA_PRIOR_SUCCESS_COUNT))
        ),
        "failure_count": int(
            beta - float(state.get("prior_beta", BETA_PRIOR_FAILURE_COUNT))
        ),
        "score": None,
    }


# Model-group transport observations remain useful diagnostics, but the legacy
# P(success)/EWMA-latency quotient and input-order tie resolution are not a
# validated model-selection estimand. Patch every public/private scoring seam
# when this evidence boundary is imported so direct submodule consumers cannot
# bypass the TaskOrchestrator-level fail-closed selection contract.
ModelGroupRouter.member_score = model_group_member_score_prohibited
ModelGroupRouter.ranked_member_ids = model_group_ranked_member_ids_fail_closed
ModelGroupRouter._score_locked = model_group_score_locked_prohibited
ModelGroupRouter._report_locked = model_group_report_locked_diagnostic
