"""Classify tool execution failures into bounded, safety-aware fallback actions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import socket
import urllib.error


class ToolFailureKind(str, Enum):
    """Stable categories for failures reported by model tool runtimes."""

    TOOL_NOT_FOUND = "tool_not_found"
    TOOL_UNAVAILABLE = "tool_unavailable"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    TRANSPORT_ERROR = "transport_error"
    INVALID_ARGUMENTS = "invalid_arguments"
    PERMISSION_DENIED = "permission_denied"
    POLICY_BLOCKED = "policy_blocked"
    EXECUTION_FAILED = "execution_failed"
    AMBIGUOUS_OUTCOME = "ambiguous_outcome"
    UNKNOWN = "unknown"


class ToolFallbackAction(str, Enum):
    """Bounded actions the orchestrator may take after a tool failure."""

    RETRY_SAME_AGENT = "retry_same_agent"
    FAILOVER_AGENT = "failover_agent"
    FAIL_CLOSED = "fail_closed"


@dataclass(frozen=True)
class ToolFailureDecision:
    """One deterministic fallback decision for a classified tool failure."""

    kind: ToolFailureKind
    action: ToolFallbackAction
    reason_code: str
    retry_safe: bool
    circuit_failure: bool


class ToolExecutionError(RuntimeError):
    """Structured tool failure raised by an agent or tool adapter.

    ``idempotent`` means replaying the same operation cannot create an additional
    externally visible side effect. ``outcome_unknown`` means the caller cannot
    prove whether the first operation completed and therefore must fail closed.
    """

    def __init__(
        self,
        message: str,
        *,
        tool_name: str,
        kind: ToolFailureKind = ToolFailureKind.EXECUTION_FAILED,
        idempotent: bool = False,
        outcome_unknown: bool = False,
    ) -> None:
        if not tool_name.strip():
            raise ValueError("tool_name must be non-empty")
        if not isinstance(kind, ToolFailureKind):
            raise TypeError("kind must be a ToolFailureKind")
        if not isinstance(idempotent, bool):
            raise TypeError("idempotent must be a boolean")
        if not isinstance(outcome_unknown, bool):
            raise TypeError("outcome_unknown must be a boolean")
        super().__init__(message)
        self.tool_name = tool_name
        self.kind = kind
        self.idempotent = idempotent
        self.outcome_unknown = outcome_unknown


class ToolFallbackStoppedError(RuntimeError):
    """Raised when retry or cross-agent failover would risk an unsafe replay."""

    def __init__(self, agent_id: str, decision: ToolFailureDecision) -> None:
        self.agent_id = agent_id
        self.decision = decision
        super().__init__(
            "tool execution stopped safely "
            f"(agent={agent_id}, reason={decision.reason_code})"
        )


def _decision(
    kind: ToolFailureKind,
    action: ToolFallbackAction,
    *,
    retry_safe: bool = False,
    circuit_failure: bool = False,
) -> ToolFailureDecision:
    """Build a decision with a stable machine-readable reason code."""
    return ToolFailureDecision(
        kind=kind,
        action=action,
        reason_code=f"tool_failure.{kind.value}.{action.value}",
        retry_safe=retry_safe,
        circuit_failure=circuit_failure,
    )


def _exception_text(error: BaseException) -> str:
    """Collect a bounded lowercase message chain without exposing it to callers."""
    messages: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen and len(messages) < 8:
        seen.add(id(current))
        messages.append(str(current).lower())
        current = current.__cause__ or current.__context__
    return " | ".join(messages)


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    """Return whether any normalized failure marker occurs in ``text``."""
    return any(marker in text for marker in markers)


def _looks_tool_related(error: BaseException, text: str) -> bool:
    """Return whether legacy exception evidence identifies a tool runtime."""
    if _contains_any(text, ("tool", "command", "mcp", "function call", "sandbox")):
        return True
    url = getattr(error, "url", "")
    return isinstance(url, str) and "tool" in url.lower()


def _classify_unstructured(error: BaseException) -> ToolFailureKind:
    """Classify legacy exceptions that identify a tool-runtime failure."""
    text = _exception_text(error)

    if _contains_any(
        text,
        (
            "outcome unknown",
            "may have completed",
            "might have completed",
            "acknowledgement lost",
            "acknowledgment lost",
        ),
    ):
        return ToolFailureKind.AMBIGUOUS_OUTCOME
    if _contains_any(
        text,
        (
            "not found in agent",
            "unknown tool",
            "no such tool",
            "unregistered tool",
            "tool does not exist",
        ),
    ):
        return ToolFailureKind.TOOL_NOT_FOUND
    if isinstance(error, PermissionError) or _contains_any(
        text,
        ("permission denied", "access denied", "unauthorized", "forbidden"),
    ):
        return ToolFailureKind.PERMISSION_DENIED
    if _contains_any(
        text,
        (
            "denied by policy",
            "policy blocked",
            "blocked by policy",
            "sandbox denied",
            "approval required",
        ),
    ):
        return ToolFailureKind.POLICY_BLOCKED
    if _contains_any(
        text,
        (
            "invalid tool arguments",
            "invalid arguments",
            "malformed arguments",
            "missing required argument",
            "schema validation",
        ),
    ):
        return ToolFailureKind.INVALID_ARGUMENTS
    if not _looks_tool_related(error, text):
        return ToolFailureKind.UNKNOWN
    if isinstance(error, urllib.error.HTTPError):
        if error.code == 429:
            return ToolFailureKind.RATE_LIMITED
        if error.code in {408, 504}:
            return ToolFailureKind.TIMEOUT
        if error.code in {502, 503}:
            return ToolFailureKind.TRANSPORT_ERROR
        return ToolFailureKind.UNKNOWN
    if _contains_any(text, ("rate limit", "too many requests", "throttl")):
        return ToolFailureKind.RATE_LIMITED
    if isinstance(error, (TimeoutError, socket.timeout)) or _contains_any(
        text,
        ("timed out", "timeout", "deadline exceeded"),
    ):
        return ToolFailureKind.TIMEOUT
    if isinstance(error, urllib.error.URLError) or _contains_any(
        text,
        (
            "connection reset",
            "connection refused",
            "dns failure",
            "network unreachable",
            "broken pipe",
        ),
    ):
        return ToolFailureKind.TRANSPORT_ERROR
    if _contains_any(
        text,
        (
            "tool server unavailable",
            "tool unavailable",
            "tool is unavailable",
            "tool disabled",
            "tool not configured",
            "mcp server unavailable",
        ),
    ):
        return ToolFailureKind.TOOL_UNAVAILABLE
    if _contains_any(
        text,
        (
            "tool execution failed",
            "command failed",
            "non-zero exit",
            "nonzero exit",
            "exit status",
        ),
    ):
        return ToolFailureKind.EXECUTION_FAILED
    return ToolFailureKind.UNKNOWN


def classify_tool_failure(
    error: BaseException,
    *,
    idempotent: bool = False,
) -> ToolFailureDecision:
    """Map a tool failure to retry, agent failover, or fail-closed behavior.

    Missing or unavailable tools fail over because no side effect was attempted.
    Timeouts and transport errors retry only when replay is explicitly idempotent.
    Ambiguous non-idempotent outcomes, invalid arguments, permission failures, and
    policy denials fail closed. Unknown exceptions retain the existing sequential
    agent-failover behavior for backward compatibility.
    """
    if not isinstance(idempotent, bool):
        raise TypeError("idempotent must be a boolean")
    if isinstance(error, ToolExecutionError):
        if error.outcome_unknown:
            kind = ToolFailureKind.AMBIGUOUS_OUTCOME
        else:
            kind = error.kind
        effective_idempotent = error.idempotent
    else:
        kind = _classify_unstructured(error)
        effective_idempotent = idempotent

    if kind is ToolFailureKind.AMBIGUOUS_OUTCOME:
        return _decision(kind, ToolFallbackAction.FAIL_CLOSED)
    if kind in {ToolFailureKind.TOOL_NOT_FOUND, ToolFailureKind.TOOL_UNAVAILABLE}:
        return _decision(
            kind,
            ToolFallbackAction.FAILOVER_AGENT,
            circuit_failure=True,
        )
    if kind in {
        ToolFailureKind.INVALID_ARGUMENTS,
        ToolFailureKind.PERMISSION_DENIED,
        ToolFailureKind.POLICY_BLOCKED,
    }:
        return _decision(kind, ToolFallbackAction.FAIL_CLOSED)
    if kind in {ToolFailureKind.TIMEOUT, ToolFailureKind.TRANSPORT_ERROR}:
        if effective_idempotent:
            return _decision(
                kind,
                ToolFallbackAction.RETRY_SAME_AGENT,
                retry_safe=True,
                circuit_failure=True,
            )
        return _decision(
            ToolFailureKind.AMBIGUOUS_OUTCOME,
            ToolFallbackAction.FAIL_CLOSED,
        )
    if kind is ToolFailureKind.RATE_LIMITED:
        if effective_idempotent:
            return _decision(
                kind,
                ToolFallbackAction.RETRY_SAME_AGENT,
                retry_safe=True,
                circuit_failure=True,
            )
        return _decision(
            kind,
            ToolFallbackAction.FAILOVER_AGENT,
            circuit_failure=True,
        )
    if kind is ToolFailureKind.EXECUTION_FAILED:
        action = (
            ToolFallbackAction.FAILOVER_AGENT
            if effective_idempotent
            else ToolFallbackAction.FAIL_CLOSED
        )
        return _decision(
            kind,
            action,
            circuit_failure=effective_idempotent,
        )
    return _decision(
        ToolFailureKind.UNKNOWN,
        ToolFallbackAction.FAILOVER_AGENT,
        circuit_failure=True,
    )
