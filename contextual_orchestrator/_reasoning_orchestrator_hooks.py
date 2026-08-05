"""Orchestrator hooks for role control, traces, retries, and ablation."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Callable, Iterator, Mapping, Sequence

from .reasoning_control import (
    ReasoningAblationCell,
    ReasoningPolicy,
    ReasoningProfile,
    ReasoningWorkload,
    WorkflowReasoningCursor,
    select_reasoning_decision,
    sum_usage_tokens,
)
from ._reasoning_state import (
    _ACTIVE_POLICY,
    _EVENT_CAPTURE,
    _OVERRIDE_DECISION,
    _annotate_trace,
    _decision_scope,
    _input_text,
    _message_text,
    agent_reasoning_profile,
    configure_agent_reasoning,
    configure_orchestrator_reasoning,
    current_reasoning_workload,
    orchestrator_reasoning_policy,
)
from ._reasoning_workflow import _capture_batch, _retry_rejected_worker_once

_WORKFLOW_CURSOR: ContextVar[WorkflowReasoningCursor | None] = ContextVar(
    "contextual_orchestrator_reasoning_workflow_cursor",
    default=None,
)


def _update_generated_plan_cursor(steps: Any) -> None:
    """Apply a validated generated list size to the active workflow cursor."""
    cursor = _WORKFLOW_CURSOR.get()
    if cursor is not None and isinstance(steps, list):
        cursor.set_plan_size(len(steps))


def install_orchestrator_hooks(orchestrator_type: type[Any]) -> None:
    """Install role-aware invocation, workflow evidence, retry, and ablation hooks."""
    original_invoke = orchestrator_type._invoke
    original_route_once = orchestrator_type.route_once
    original_conduct = orchestrator_type.conduct
    original_stream_route = orchestrator_type.stream_route
    original_batch_route = orchestrator_type.batch_route
    original_proxy_completion = orchestrator_type.proxy_completion
    original_plan_generated = orchestrator_type._plan_generated
    original_model_judge = orchestrator_type._model_judge_verification
    original_patch_agent = getattr(orchestrator_type, "patch_agent", None)
    original_agent_to_admin_payload = getattr(orchestrator_type, "_agent_to_admin_payload", None)

    def agent_to_admin_payload(self: Any, agent: Any) -> dict[str, Any]:
        """Expose explicit reasoning capability in the admin-safe agent view."""
        value = original_agent_to_admin_payload(self, agent)
        profile = agent_reasoning_profile(agent)
        if profile is not None:
            value["reasoning_profile"] = profile.to_dict()
        return value

    def patch_agent(
        self: Any,
        agent_pool_id: str,
        worker_agent_id: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        """Preserve or explicitly update capability when the core replaces an agent."""
        current = self._agent(worker_agent_id)
        previous = agent_reasoning_profile(current)
        explicit = "reasoning_profile" in patch
        requested: ReasoningProfile | None = previous
        if explicit:
            raw_profile = patch["reasoning_profile"]
            if raw_profile is None:
                requested = None
            elif isinstance(raw_profile, ReasoningProfile):
                requested = raw_profile
            elif isinstance(raw_profile, Mapping):
                requested = ReasoningProfile.from_dict(raw_profile)
            else:
                raise TypeError(
                    "reasoning_profile patch must be a mapping, ReasoningProfile, or None"
                )
        core_patch = dict(patch)
        core_patch.pop("reasoning_profile", None)
        original_patch_agent(self, agent_pool_id, worker_agent_id, core_patch)
        replacement = self._agent(worker_agent_id)
        configure_agent_reasoning(replacement, requested)
        pool_store = getattr(self, "_pool_store", None)
        if pool_store is not None:
            pool_store.save(replacement)
        return self._agent_to_admin_payload(replacement)

    def orchestrator_invoke(
        self: Any,
        primary: Any,
        messages: list[dict[str, str]],
        *,
        text: str,
        role: str,
    ) -> tuple[str, str, dict[str, Any] | None]:
        """Select once from role, task, and graph evidence, then project on failover."""
        policy = orchestrator_reasoning_policy(self)
        profile = agent_reasoning_profile(primary)
        workload = current_reasoning_workload()
        cursor = _WORKFLOW_CURSOR.get()
        if workload is None and cursor is not None:
            workload = cursor.observe(messages)
        decision = _OVERRIDE_DECISION.get() or select_reasoning_decision(
            profile,
            policy,
            text,
            role,
            workload=workload,
        )
        policy_token = _ACTIVE_POLICY.set(policy)
        try:
            with _decision_scope(decision):
                output, served_id, usage = original_invoke(
                    self,
                    primary,
                    messages,
                    text=text,
                    role=role,
                )
        finally:
            _ACTIVE_POLICY.reset(policy_token)
        events = _EVENT_CAPTURE.get()
        if events:
            for event in reversed(events):
                if (
                    event["role"] == role
                    and event["agent_id"] == served_id
                    and event.get("usage") is None
                ):
                    event["usage"] = usage
                    break
        return output, served_id, usage

    def _capture_workflow(
        self: Any,
        operation: Callable[[Any, list[dict[str, str]]], dict[str, Any]],
        messages: list[dict[str, str]],
        *,
        allow_escalation: bool,
        workflow_step_count: int,
    ) -> dict[str, Any]:
        """Capture, structurally annotate, and optionally repair one visible workflow."""
        events: list[dict[str, Any]] = []
        event_token = _EVENT_CAPTURE.set(events)
        policy = orchestrator_reasoning_policy(self)
        policy_token = _ACTIVE_POLICY.set(policy)
        cursor_token = _WORKFLOW_CURSOR.set(WorkflowReasoningCursor(workflow_step_count))
        try:
            result = operation(self, messages)
            trace = result.get("trace")
            if isinstance(trace, list):
                _annotate_trace(trace, events)
            result["reasoning_control"] = policy.to_dict()
            if allow_escalation:
                _retry_rejected_worker_once(self, result, _message_text(messages))
        finally:
            _WORKFLOW_CURSOR.reset(cursor_token)
            _ACTIVE_POLICY.reset(policy_token)
            _EVENT_CAPTURE.reset(event_token)
        return result

    def route_once(self: Any, messages: list[dict[str, str]]) -> dict[str, Any]:
        """Capture reasoning evidence for the single-step route path."""
        return _capture_workflow(
            self,
            original_route_once,
            messages,
            allow_escalation=False,
            workflow_step_count=1,
        )

    def conduct(self: Any, messages: list[dict[str, str]]) -> dict[str, Any]:
        """Capture graph-aware deep-workflow evidence and one verifier-driven retry."""
        return _capture_workflow(
            self,
            original_conduct,
            messages,
            allow_escalation=True,
            workflow_step_count=4,
        )

    def stream_route(
        self: Any,
        messages: list[dict[str, str]],
        workflow_run_id: str | None = None,
    ) -> Iterator[str]:
        """Keep direct-route worker effort active across one streamed response."""
        task = _message_text(messages)
        agent = self._select_agent(task, "worker")
        policy = orchestrator_reasoning_policy(self)
        decision = select_reasoning_decision(
            agent_reasoning_profile(agent),
            policy,
            task,
            "worker",
            workload=ReasoningWorkload(),
        )
        policy_token = _ACTIVE_POLICY.set(policy)
        try:
            with _decision_scope(decision):
                yield from original_stream_route(self, messages, workflow_run_id=workflow_run_id)
        finally:
            _ACTIVE_POLICY.reset(policy_token)

    def batch_route(self: Any, prompts: list[str]) -> list[dict[str, Any]]:
        """Capture per-item reasoning evidence for the provider Batch route."""
        return _capture_batch(self, original_batch_route, prompts)

    def proxy_completion(
        self: Any,
        body: dict[str, Any],
        *,
        endpoint: str = "chat/completions",
    ) -> dict[str, Any]:
        """Apply direct-route defaults to full-shape chat and Responses requests."""
        task = _input_text(body)
        agent = self._select_agent(task, "worker")
        policy = orchestrator_reasoning_policy(self)
        decision = select_reasoning_decision(
            agent_reasoning_profile(agent),
            policy,
            task,
            "worker",
            workload=ReasoningWorkload(),
        )
        policy_token = _ACTIVE_POLICY.set(policy)
        try:
            with _decision_scope(decision):
                return original_proxy_completion(self, body, endpoint=endpoint)
        finally:
            _ACTIVE_POLICY.reset(policy_token)

    def plan_generated(self: Any, task: str) -> Any:
        """Allocate thinker effort for explicit workflow decomposition."""
        planner = self._select_agent(task, "thinker")
        policy = orchestrator_reasoning_policy(self)
        maximum_steps = int(getattr(self.policy, "max_workflow_steps", 4))
        planning_workload = ReasoningWorkload(
            workflow_step_index=0,
            workflow_step_count=maximum_steps,
            recursion_depth=0,
            decomposition_count=maximum_steps,
            accessible_step_count=0,
        )
        decision = select_reasoning_decision(
            agent_reasoning_profile(planner),
            policy,
            task,
            "thinker",
            workload=planning_workload,
        )
        policy_token = _ACTIVE_POLICY.set(policy)
        try:
            with _decision_scope(decision):
                steps = original_plan_generated(self, task)
        finally:
            _ACTIVE_POLICY.reset(policy_token)
        _update_generated_plan_cursor(steps)
        return steps

    def model_judge(self: Any, task: str, fallback: dict[str, Any]) -> dict[str, Any]:
        """Apply verifier-role effort to the optional model verdict."""
        judge = self._select_agent(task, "verifier")
        policy = orchestrator_reasoning_policy(self)
        decision = select_reasoning_decision(
            agent_reasoning_profile(judge),
            policy,
            task,
            "verifier",
            workload=ReasoningWorkload(),
        )
        policy_token = _ACTIVE_POLICY.set(policy)
        try:
            with _decision_scope(decision):
                return original_model_judge(self, task, fallback)
        finally:
            _ACTIVE_POLICY.reset(policy_token)

    def run_reasoning_ablation(
        self: Any,
        prompts: Sequence[str],
        *,
        mode: str = "auto",
        levels: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Measure fixed effort cells under one prompt set without persisting outputs."""
        if not prompts:
            raise ValueError("reasoning ablation requires at least one prompt")
        candidate_levels = tuple(levels or ("minimal", "low", "medium", "high"))
        previous = orchestrator_reasoning_policy(self)
        cells: list[ReasoningAblationCell] = []
        try:
            for level in candidate_levels:
                fixed = ReasoningPolicy(
                    strategy="fixed",
                    fixed_level=level,
                    max_escalations=0,
                )
                configure_orchestrator_reasoning(self, fixed)
                accepted = 0
                reasoning_tokens = 0
                total_tokens = 0
                for prompt in prompts:
                    result = self._dispatch([{"role": "user", "content": prompt}], mode)
                    accepted += int(bool(result.get("verification", {}).get("accepted")))
                    trace = result.get("trace")
                    if isinstance(trace, list):
                        cell_reasoning, cell_total = sum_usage_tokens(trace)
                        reasoning_tokens += cell_reasoning
                        total_tokens += cell_total
                cells.append(
                    ReasoningAblationCell(
                        level=level,
                        prompt_count=len(prompts),
                        accepted_count=accepted,
                        reasoning_tokens=reasoning_tokens,
                        total_tokens=total_tokens,
                    )
                )
        finally:
            configure_orchestrator_reasoning(self, previous)
        return {
            "mode": mode,
            "prompt_count": len(prompts),
            "cells": [cell.to_dict() for cell in cells],
            "quality_measure": (
                "workflow verifier acceptance; task-specific benchmark scorers remain authoritative"
            ),
        }

    orchestrator_type._invoke = orchestrator_invoke
    orchestrator_type.route_once = route_once
    orchestrator_type.conduct = conduct
    orchestrator_type.stream_route = stream_route
    orchestrator_type.batch_route = batch_route
    orchestrator_type.proxy_completion = proxy_completion
    orchestrator_type._plan_generated = plan_generated
    orchestrator_type._model_judge_verification = model_judge
    orchestrator_type.run_reasoning_ablation = run_reasoning_ablation
    if original_agent_to_admin_payload is not None:
        orchestrator_type._agent_to_admin_payload = agent_to_admin_payload
    if original_patch_agent is not None and original_agent_to_admin_payload is not None:
        orchestrator_type.patch_agent = patch_agent


__all__ = [
    "_WORKFLOW_CURSOR",
    "_update_generated_plan_cursor",
    "install_orchestrator_hooks",
]
