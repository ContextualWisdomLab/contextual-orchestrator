"""Runtime integration for provider-neutral adaptive reasoning control.

Importing this module is side-effect free. Library consumers explicitly call
:func:`enable_reasoning_control` before constructing or loading runtime objects;
the product CLI performs that activation during command execution. The lower-
level installer remains available for isolated fakes and alternate runtimes.
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
    _WORKLOAD_OVERRIDE,
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
    current_reasoning_workload,
    orchestrator_reasoning_policy,
    reasoning_override,
    reasoning_workload_override,
)
from ._reasoning_workflow import (
    _capture_batch,
    _refresh_step_reasoning_from_event,
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
    """Install reasoning control on supplied runtime classes exactly once."""
    if getattr(model_client_type, "_reasoning_control_installed", False):
        return
    install_config_hooks(model_agent_type, orchestrator_type, policy_type)
    install_client_hooks(model_client_type)
    install_orchestrator_hooks(orchestrator_type)
    model_client_type._reasoning_control_installed = True


def enable_reasoning_control() -> None:
    """Explicitly activate reasoning control for the built-in runtime classes.

    Call this before loading agent configuration or constructing a
    :class:`~contextual_orchestrator.orchestrator.TaskOrchestrator`. Repeated
    calls are safe and do not wrap methods more than once.
    """
    from .orchestrator import (  # Local import preserves package import purity.
        ModelAgent,
        ModelClient,
        OrchestrationPolicy,
        TaskOrchestrator,
    )

    install_reasoning_control(
        ModelAgent,
        ModelClient,
        TaskOrchestrator,
        OrchestrationPolicy,
    )


__all__ = [
    "agent_reasoning_profile",
    "configure_agent_reasoning",
    "configure_orchestrator_reasoning",
    "current_reasoning_decision",
    "current_reasoning_workload",
    "enable_reasoning_control",
    "install_reasoning_control",
    "orchestrator_reasoning_policy",
    "reasoning_override",
    "reasoning_workload_override",
]
