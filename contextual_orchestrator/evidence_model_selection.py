"""Fail-closed model selection that requires identified routing evidence.

This module is a compatibility bridge while the historical static ranking code
is removed from ``orchestrator.py``.  It deliberately exposes no priority,
metadata-similarity, provider-name, discovery-order, or transport-composite
fallback.  Multiple eligible candidates require complete exact-context
fast-mlsirm evidence; otherwise selection is unresolved.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .model_group import canonical_group_name


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
