"""Validated workflow-structure evidence for test-time reasoning allocation."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping, Sequence

_ACCESS_SECTION = re.compile(
    r"Accessed prior work:\n(?P<section>.*?)(?:\n\nSubtask:|\Z)",
    re.DOTALL,
)
_STEP_LINE = re.compile(r"^Step\s+(?P<step_id>\d+):", re.MULTILINE)


@dataclass(frozen=True)
class ReasoningWorkload:
    """Structural evidence for one role invocation in a workflow graph.

    The object intentionally contains no latency field. Reasoning allocation is
    based on workflow topology, role, task evidence, and operator caps rather
    than response-speed targets.
    """

    workflow_step_index: int = 0
    workflow_step_count: int = 1
    recursion_depth: int = 0
    decomposition_count: int = 1
    accessible_step_count: int = 0

    def __post_init__(self) -> None:
        """Reject boolean pseudo-integers and impossible workflow topology."""
        values = {
            "workflow_step_index": self.workflow_step_index,
            "workflow_step_count": self.workflow_step_count,
            "recursion_depth": self.recursion_depth,
            "decomposition_count": self.decomposition_count,
            "accessible_step_count": self.accessible_step_count,
        }
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values.values()):
            raise ValueError("reasoning workload values must be integers")
        if self.workflow_step_count < 1 or self.decomposition_count < 1:
            raise ValueError("workflow_step_count and decomposition_count must be positive")
        if any(
            value < 0
            for name, value in values.items()
            if name not in {"workflow_step_count", "decomposition_count"}
        ):
            raise ValueError("reasoning workload values must be non-negative")
        if self.workflow_step_index >= self.workflow_step_count:
            raise ValueError("workflow_step_index must be within workflow_step_count")
        if self.recursion_depth > self.workflow_step_index:
            raise ValueError("recursion_depth cannot exceed workflow_step_index")
        if self.accessible_step_count > self.workflow_step_index:
            raise ValueError("accessible_step_count cannot exceed prior workflow steps")
        if self.decomposition_count > self.workflow_step_count:
            raise ValueError("decomposition_count cannot exceed workflow_step_count")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ReasoningWorkload":
        """Parse one strict JSON-compatible workflow workload object."""
        if not isinstance(value, Mapping):
            raise ValueError("reasoning workload must be an object")
        allowed = {
            "workflow_step_index",
            "workflow_step_count",
            "recursion_depth",
            "decomposition_count",
            "accessible_step_count",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown reasoning workload keys: {sorted(unknown)}")
        return cls(**{key: value[key] for key in allowed if key in value})

    def to_dict(self) -> dict[str, int]:
        """Return stable audit evidence for the structural allocation input."""
        return {
            "workflow_step_index": self.workflow_step_index,
            "workflow_step_count": self.workflow_step_count,
            "recursion_depth": self.recursion_depth,
            "decomposition_count": self.decomposition_count,
            "accessible_step_count": self.accessible_step_count,
        }


@dataclass
class WorkflowReasoningCursor:
    """Track structural position while a route or conducted workflow executes."""

    workflow_step_count: int
    decomposition_count: int | None = None
    next_step_index: int = 0
    depths: dict[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize the initial decomposition count and validate positivity."""
        if (
            isinstance(self.workflow_step_count, bool)
            or not isinstance(self.workflow_step_count, int)
            or self.workflow_step_count < 1
        ):
            raise ValueError("workflow_step_count must be a positive integer")
        if self.decomposition_count is None:
            self.decomposition_count = self.workflow_step_count
        if (
            isinstance(self.decomposition_count, bool)
            or not isinstance(self.decomposition_count, int)
            or self.decomposition_count < 1
        ):
            raise ValueError("decomposition_count must be a positive integer")
        if self.decomposition_count > self.workflow_step_count:
            raise ValueError("decomposition_count cannot exceed workflow_step_count")

    def set_plan_size(self, step_count: int) -> None:
        """Replace the provisional template size with a validated generated plan size."""
        if isinstance(step_count, bool) or not isinstance(step_count, int) or step_count < 1:
            raise ValueError("generated workflow step_count must be a positive integer")
        if self.next_step_index:
            raise RuntimeError("workflow plan size cannot change after step execution begins")
        self.workflow_step_count = step_count
        self.decomposition_count = step_count

    def observe(self, messages: Sequence[Mapping[str, Any]]) -> ReasoningWorkload | None:
        """Return and advance the structural evidence for the next workflow step."""
        if self.next_step_index >= self.workflow_step_count:
            return None
        step_index = self.next_step_index
        access_ids, had_access_content = _access_ids(messages)
        if not access_ids and had_access_content and self.workflow_step_count == 4:
            access_ids = tuple(range(step_index))
        access_ids = tuple(sorted({value for value in access_ids if 0 <= value < step_index}))
        recursion_depth = 0
        if access_ids:
            recursion_depth = 1 + max(self.depths.get(value, 0) for value in access_ids)
        workload = ReasoningWorkload(
            workflow_step_index=step_index,
            workflow_step_count=self.workflow_step_count,
            recursion_depth=recursion_depth,
            decomposition_count=int(self.decomposition_count),
            accessible_step_count=len(access_ids),
        )
        self.depths[step_index] = recursion_depth
        self.next_step_index += 1
        return workload


def _access_ids(messages: Sequence[Mapping[str, Any]]) -> tuple[tuple[int, ...], bool]:
    """Extract exact accessed step identifiers from the bounded prompt section."""
    user_text = "\n".join(
        str(message.get("content", ""))
        for message in messages
        if message.get("role") == "user" and isinstance(message.get("content"), str)
    )
    match = _ACCESS_SECTION.search(user_text)
    if match is None:
        return (), False
    section = match.group("section").strip()
    had_access_content = bool(section and section != "(none)")
    return tuple(int(item.group("step_id")) for item in _STEP_LINE.finditer(section)), had_access_content


def workload_for_trace_row(
    row: Mapping[str, Any],
    trace: Sequence[Mapping[str, Any]],
) -> ReasoningWorkload:
    """Reconstruct structural evidence for one existing trace row and its access list."""
    rows = [
        item
        for item in trace
        if isinstance(item.get("id"), int)
        and not isinstance(item.get("id"), bool)
        and item["id"] >= 0
    ]
    if not rows:
        raise ValueError("trace must contain at least one non-negative integer step id")
    target_id = row.get("id")
    if isinstance(target_id, bool) or not isinstance(target_id, int) or target_id < 0:
        raise ValueError("trace row id must be a non-negative integer")
    step_count = max(item["id"] for item in rows) + 1
    if target_id >= step_count:
        raise ValueError("trace row id is outside the workflow")
    depths: dict[int, int] = {}
    target_access: tuple[int, ...] = ()
    for item in sorted(rows, key=lambda item: item["id"]):
        step_id = item["id"]
        raw_access = item.get("access", ())
        access = (
            tuple(
                sorted(
                    {
                        value
                        for value in raw_access
                        if isinstance(value, int)
                        and not isinstance(value, bool)
                        and 0 <= value < step_id
                    }
                )
            )
            if isinstance(raw_access, (list, tuple))
            else ()
        )
        depths[step_id] = 0 if not access else 1 + max(depths.get(value, 0) for value in access)
        if step_id == target_id:
            target_access = access
    return ReasoningWorkload(
        workflow_step_index=target_id,
        workflow_step_count=step_count,
        recursion_depth=depths.get(target_id, 0),
        decomposition_count=len(rows),
        accessible_step_count=len(target_access),
    )


__all__ = [
    "ReasoningWorkload",
    "WorkflowReasoningCursor",
    "_access_ids",
    "workload_for_trace_row",
]
