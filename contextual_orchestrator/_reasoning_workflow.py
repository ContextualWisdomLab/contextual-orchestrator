"""Workflow annotation, batch projection, and bounded verifier escalation."""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Sequence

from .reasoning_control import (
    ReasoningDecision,
    ReasoningProfile,
    adapt_reasoning_decision,
    apply_reasoning_payload,
    escalate_reasoning_decision,
)
from ._reasoning_state import (
    _ACTIVE_POLICY,
    _EVENT_CAPTURE,
    _annotate_trace,
    _reasoning_evidence,
    agent_reasoning_profile,
    orchestrator_reasoning_policy,
    reasoning_override,
)

def _step_messages(task: str, row: Mapping[str, Any], trace: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Reconstruct the repository's access-list prompt for one retryable step."""
    accessed: list[str] = []
    for raw_index in row.get("access", []):
        if isinstance(raw_index, int) and 0 <= raw_index < len(trace):
            accessed.append(str(trace[raw_index].get("output", "")))
    prior = "\n\n".join(accessed) if accessed else "(none)"
    role = str(row.get("role", "worker"))
    return [
        {
            "role": "system",
            "content": (
                f"Role: {role}. Complete only the assigned subtask. "
                "Use only explicitly accessed prior outputs and do not invent evidence."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Original task:\n{task}\n\nAccessed prior work:\n{prior}"
                f"\n\nSubtask:\n{row.get('subtask', '')}"
            ),
        },
    ]


def _refresh_step_reasoning_from_event(
    row: dict[str, Any],
    role: str,
    served_agent_id: str,
    usage: Mapping[str, Any] | None,
) -> None:
    """Refresh a recomputed step with the exact captured provider decision."""
    events = _EVENT_CAPTURE.get() or []
    event = next(
        (
            item
            for item in reversed(events)
            if item["role"] == role and item["agent_id"] == served_agent_id
        ),
        None,
    )
    if event is None:
        return
    effective_usage = usage if isinstance(usage, Mapping) else event.get("usage")
    row["reasoning"] = _reasoning_evidence(
        event["profile"], event["decision"], effective_usage
    )


def _retry_rejected_worker_once(orchestrator: Any, result: dict[str, Any], task: str) -> None:
    """Escalate one rejected worker and recompute affected downstream roles once."""
    verification = result.get("verification")
    trace = result.get("trace")
    if not isinstance(verification, Mapping) or verification.get("accepted") is not False:
        return
    if not isinstance(trace, list):
        return
    worker = next((row for row in reversed(trace) if row.get("role") == "worker"), None)
    if not isinstance(worker, dict):
        return
    evidence = worker.get("reasoning")
    decision_data = evidence.get("decision") if isinstance(evidence, Mapping) else None
    if not isinstance(decision_data, Mapping):
        return
    try:
        prior = ReasoningDecision(
            level=str(decision_data["level"]),
            source=str(decision_data["source"]),
            role="worker",
            complexity_score=int(decision_data.get("complexity_score", 0)),
            factors=tuple(decision_data.get("factors", ())),
            escalation_index=int(decision_data.get("escalation_index", 0)),
        )
    except (KeyError, TypeError, ValueError):
        return
    agent_id = worker.get("served_agent_id", worker.get("agent_id"))
    try:
        agent = orchestrator._agent(agent_id)
    except (KeyError, TypeError):
        return
    policy = orchestrator_reasoning_policy(orchestrator)
    profile = agent_reasoning_profile(agent)
    escalated = escalate_reasoning_decision(profile, policy, prior)
    if escalated is None:
        return

    with reasoning_override(escalated):
        output, served_id, usage = orchestrator._invoke(
            agent,
            _step_messages(task, worker, trace),
            text=task,
            role="worker",
        )
    worker["output"] = output
    worker["served_agent_id"] = served_id
    if usage is not None:
        worker["usage"] = usage
    served_agent = orchestrator._agent(served_id)
    served_profile = agent_reasoning_profile(served_agent)
    served_decision = adapt_reasoning_decision(served_profile, escalated)
    if served_profile is not None and served_decision is not None:
        worker["reasoning"] = _reasoning_evidence(served_profile, served_decision, usage)

    verifier = next((row for row in trace if row.get("role") == "verifier" and row.get("id", -1) > worker.get("id", -1)), None)
    if isinstance(verifier, dict):
        verifier_agent = orchestrator._agent(verifier.get("agent_id"))
        verifier_output, verifier_served, verifier_usage = orchestrator._invoke(
            verifier_agent,
            _step_messages(task, verifier, trace),
            text=task,
            role="verifier",
        )
        verifier["output"] = verifier_output
        verifier["served_agent_id"] = verifier_served
        if verifier_usage is not None:
            verifier["usage"] = verifier_usage
        _refresh_step_reasoning_from_event(
            verifier, "verifier", verifier_served, verifier_usage
        )
        result["verification"] = orchestrator._judge_verifier_output(
            verifier_output,
            str(next((row.get("output", "") for row in trace if row.get("role") == "thinker"), "")),
            output,
        )

    accepted = bool(result.get("verification", {}).get("accepted"))
    synthesizer = next((row for row in reversed(trace) if row.get("role") == "synthesizer"), None)
    if accepted and isinstance(synthesizer, dict):
        synth_agent = orchestrator._agent(synthesizer.get("agent_id"))
        synth_output, synth_served, synth_usage = orchestrator._invoke(
            synth_agent,
            _step_messages(task, synthesizer, trace),
            text=task,
            role="synthesizer",
        )
        synthesizer["output"] = synth_output
        synthesizer["served_agent_id"] = synth_served
        if synth_usage is not None:
            synthesizer["usage"] = synth_usage
        _refresh_step_reasoning_from_event(
            synthesizer, "synthesizer", synth_served, synth_usage
        )
        result["answer"] = synth_output
    else:
        result["answer"] = output
    result["reasoning_escalation"] = {
        "attempted": True,
        "from_level": prior.level,
        "to_level": escalated.level,
        "accepted_after_retry": accepted,
    }


def _rewrite_batch_payload(payload: bytes, decisions: Mapping[str, ReasoningDecision], profile: ReasoningProfile) -> bytes:
    """Apply per-item decisions to an OpenAI Batch JSONL request body."""
    output: list[str] = []
    for raw_line in payload.decode("utf-8").splitlines():
        if not raw_line.strip():
            continue
        row = json.loads(raw_line)
        custom_id = row.get("custom_id")
        body = row.get("body")
        decision = decisions.get(custom_id) if isinstance(custom_id, str) else None
        if isinstance(body, Mapping) and decision is not None:
            row["body"] = apply_reasoning_payload(body, profile, decision, "chat/completions")
        output.append(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
    return ("\n".join(output) + "\n").encode("utf-8")



def _capture_batch(
    orchestrator: Any,
    operation: Callable[[Any, list[str]], list[dict[str, Any]]],
    prompts: list[str],
) -> list[dict[str, Any]]:
    """Capture and annotate reasoning evidence for a batch-route operation."""
    events: list[dict[str, Any]] = []
    event_token = _EVENT_CAPTURE.set(events)
    policy = orchestrator_reasoning_policy(orchestrator)
    policy_token = _ACTIVE_POLICY.set(policy)
    try:
        records = operation(orchestrator, prompts)
        for record in records:
            trace = record.get("trace")
            if isinstance(trace, list):
                _annotate_trace(trace, events)
            record["reasoning_control"] = policy.to_dict()
    finally:
        _ACTIVE_POLICY.reset(policy_token)
        _EVENT_CAPTURE.reset(event_token)
    return records



__all__ = [
    "_capture_batch",
    "_refresh_step_reasoning_from_event",
    "_retry_rejected_worker_once",
    "_rewrite_batch_payload",
    "_step_messages",
]
