"""Regressions for structured tool metadata preserved through provider wrappers."""

from __future__ import annotations

import pytest

from contextual_orchestrator.tool_fallback import (
    ToolExecutionError,
    ToolFallbackAction,
    ToolFailureKind,
    classify_tool_failure,
)


def _wrapped(error: BaseException) -> RuntimeError:
    """Wrap one tool error as provider and agent layers commonly do."""
    try:
        raise RuntimeError("agent invocation failed") from error
    except RuntimeError as wrapper:
        return wrapper


def test_wrapped_idempotent_timeout_keeps_safe_retry_metadata() -> None:
    """A wrapper must not erase the structured idempotency decision."""
    error = _wrapped(
        ToolExecutionError(
            "read timed out",
            tool_name="inspect_repository",
            kind=ToolFailureKind.TIMEOUT,
            idempotent=True,
        )
    )

    decision = classify_tool_failure(error)

    assert decision.kind is ToolFailureKind.TIMEOUT
    assert decision.action is ToolFallbackAction.RETRY_SAME_AGENT
    assert decision.retry_safe is True


def test_wrapped_unknown_outcome_remains_fail_closed() -> None:
    """A wrapper must not turn an uncertain side effect into ordinary failover."""
    error = _wrapped(
        ToolExecutionError(
            "connection reset after dispatch",
            tool_name="send_message",
            kind=ToolFailureKind.TRANSPORT_ERROR,
            idempotent=True,
            outcome_unknown=True,
        )
    )

    decision = classify_tool_failure(error)

    assert decision.kind is ToolFailureKind.AMBIGUOUS_OUTCOME
    assert decision.observed_kind is ToolFailureKind.TRANSPORT_ERROR
    assert decision.action is ToolFallbackAction.FAIL_CLOSED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
