"""Coverage regressions for explicit activation and generated-plan sizing."""

from __future__ import annotations

from typing import Any

import contextual_orchestrator._reasoning_orchestrator_hooks as orchestrator_hooks
import contextual_orchestrator.reasoning_runtime as reasoning_runtime
from contextual_orchestrator.reasoning_control import WorkflowReasoningCursor


def test_enable_reasoning_control_delegates_to_builtin_runtime_types(
    monkeypatch: Any,
) -> None:
    """Explicit activation must bind exactly the repository's four core classes."""
    captured: list[tuple[type[Any], ...]] = []

    def capture(*runtime_types: type[Any]) -> None:
        """Record the activation target without mutating process-global classes."""
        captured.append(runtime_types)

    monkeypatch.setattr(reasoning_runtime, "install_reasoning_control", capture)
    reasoning_runtime.enable_reasoning_control()

    from contextual_orchestrator.orchestrator import (
        ModelAgent,
        ModelClient,
        OrchestrationPolicy,
        TaskOrchestrator,
    )

    assert captured == [
        (ModelAgent, ModelClient, TaskOrchestrator, OrchestrationPolicy)
    ]


def test_generated_plan_cursor_updates_only_for_validated_step_lists() -> None:
    """Generated list plans replace the provisional size; other shapes do not."""
    cursor = WorkflowReasoningCursor(4)
    token = orchestrator_hooks._WORKFLOW_CURSOR.set(cursor)
    try:
        orchestrator_hooks._update_generated_plan_cursor(("not", "a", "list"))
        assert cursor.workflow_step_count == 4
        orchestrator_hooks._update_generated_plan_cursor([{"id": 0}, {"id": 1}])
        assert cursor.workflow_step_count == 2
        assert cursor.decomposition_count == 2
    finally:
        orchestrator_hooks._WORKFLOW_CURSOR.reset(token)

    # With no active workflow, a generated list is intentionally a no-op.
    orchestrator_hooks._update_generated_plan_cursor([{"id": 0}])
