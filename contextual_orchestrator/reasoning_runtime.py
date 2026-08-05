"""Runtime integration for provider-neutral adaptive reasoning control.

The extension installs only stable configuration, provider transport, role,
workflow trace, bounded retry, and ablation seams. It remains idempotent and
keeps the orchestration core usable without importing this optional module.
"""

from __future__ import annotations

from typing import Any

from ._reasoning_client_hooks import install_client_hooks
from ._reasoning_config_hooks import install_config_hooks
from ._reasoning_orchestrator_hooks import install_orchestrator_hooks
from ._reasoning_state import (
    _ACTIVE_DECISION,
    _ACTIVE_POLICY,
    _AGENT_PROFILES,
    _BATCH_DECISIONS,
    _EVENT_CAPTURE,
    _OVERRIDE_DECISION,
    _POLICY_OBJECTS,
    _WeakIdentityMap,
    _annotate_trace,
    _append_event,
    _decision_scope,
    _infer_role,
    _input_text,
    _message_text,
    _reasoning_evidence,
    _resolve_decision,
    agent_reasoning_profile,
    configure_agent_reasoning,
    configure_orchestrator_reasoning,
    current_reasoning_decision,
    orchestrator_reasoning_policy,
    reasoning_override,
)
from ._reasoning_workflow import (
    _capture_batch,
    _retry_rejected_worker_once,
    _rewrite_batch_payload,
    _step_messages,
)


def install_reasoning_control(
    model_agent_type: type[Any],
    model_client_type: type[Any],
    orchestrator_type: type[Any],
    policy_type: type[Any],
) -> None:
    """Install reasoning control on repository runtime classes exactly once."""
    if getattr(model_client_type, "_reasoning_control_installed", False):
        return
    install_config_hooks(model_agent_type, orchestrator_type, policy_type)
    install_client_hooks(model_client_type)
    install_orchestrator_hooks(orchestrator_type)
    model_client_type._reasoning_control_installed = True


__all__ = [
    "agent_reasoning_profile",
    "configure_agent_reasoning",
    "configure_orchestrator_reasoning",
    "current_reasoning_decision",
    "install_reasoning_control",
    "orchestrator_reasoning_policy",
    "reasoning_override",
]
