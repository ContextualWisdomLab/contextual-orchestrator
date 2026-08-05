"""Quality-aware, role-sensitive reasoning decision policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ._reasoning_profile import CANONICAL_REASONING_LEVELS, ReasoningProfile
from ._reasoning_workload import ReasoningWorkload

_COMPLEXITY_TERMS = (
    "analyze",
    "architecture",
    "compare",
    "derive",
    "evaluate",
    "implement",
    "migration",
    "optimize",
    "prove",
    "reason",
    "research",
    "trade-off",
    "tradeoff",
    "verify",
    "분석",
    "아키텍처",
    "비교",
    "구현",
    "연구",
    "검증",
)
_HIGH_RISK_TERMS = (
    "authentication",
    "authorization",
    "financial",
    "legal",
    "medical",
    "payment",
    "privacy",
    "safety",
    "security",
    "개인정보",
    "법률",
    "보안",
    "의료",
)
_ROLE_BASELINE_OFFSET = {
    "thinker": 1,
    "worker": 0,
    "verifier": 1,
    "synthesizer": 0,
}


@dataclass(frozen=True)
class ReasoningPolicy:
    """Quality policy for role-aware effort and bounded escalation."""

    strategy: str = "adaptive"
    fixed_level: str | None = None
    max_escalations: int = 1

    def __post_init__(self) -> None:
        """Reject unknown strategies, ambiguous fixed mode, and retry loops."""
        if self.strategy not in {"disabled", "adaptive", "fixed"}:
            raise ValueError("strategy must be disabled, adaptive, or fixed")
        if self.strategy == "fixed" and self.fixed_level is None:
            raise ValueError("fixed strategy requires fixed_level")
        if self.fixed_level is not None and self.fixed_level not in CANONICAL_REASONING_LEVELS:
            raise ValueError("fixed_level must be canonical")
        if isinstance(self.max_escalations, bool) or self.max_escalations not in {0, 1}:
            raise ValueError("max_escalations must be 0 or 1")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReasoningPolicy":
        """Parse a strict JSON-compatible reasoning policy."""
        if not isinstance(value, Mapping):
            raise ValueError("reasoning policy must be an object")
        unknown = set(value) - {"strategy", "fixed_level", "max_escalations"}
        if unknown:
            raise ValueError(f"unknown reasoning policy keys: {sorted(unknown)}")
        return cls(
            strategy=value.get("strategy", "adaptive"),
            fixed_level=value.get("fixed_level"),
            max_escalations=value.get("max_escalations", 1),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the policy as stable audit data."""
        return {
            "strategy": self.strategy,
            "fixed_level": self.fixed_level,
            "max_escalations": self.max_escalations,
        }


@dataclass(frozen=True)
class ReasoningDecision:
    """One explainable request-time reasoning-level decision."""

    level: str
    source: str
    role: str
    complexity_score: int
    factors: tuple[str, ...]
    escalation_index: int = 0
    workload: ReasoningWorkload | None = None

    def __post_init__(self) -> None:
        """Validate canonical and non-negative decision evidence."""
        if self.level not in CANONICAL_REASONING_LEVELS:
            raise ValueError("decision level must be canonical")
        if not self.source or not self.role:
            raise ValueError("decision source and role must not be empty")
        if isinstance(self.complexity_score, bool) or not isinstance(self.complexity_score, int):
            raise ValueError("complexity_score must be an integer")
        if self.complexity_score < 0:
            raise ValueError("complexity_score must be non-negative")
        if not all(isinstance(item, str) and item for item in self.factors):
            raise ValueError("decision factors must be non-empty strings")
        if isinstance(self.escalation_index, bool) or not isinstance(self.escalation_index, int):
            raise ValueError("escalation_index must be an integer")
        if self.escalation_index < 0:
            raise ValueError("escalation_index must be non-negative")
        if self.workload is not None and not isinstance(self.workload, ReasoningWorkload):
            raise ValueError("decision workload must be ReasoningWorkload or None")

    def to_dict(self) -> dict[str, Any]:
        """Return API-safe evidence without private intermediate reasoning text."""
        value: dict[str, Any] = {
            "level": self.level,
            "source": self.source,
            "role": self.role,
            "complexity_score": self.complexity_score,
            "factors": list(self.factors),
            "escalation_index": self.escalation_index,
        }
        if self.workload is not None:
            value["workload"] = self.workload.to_dict()
        return value


@dataclass(frozen=True)
class ReasoningAblationCell:
    """One measured fixed-effort cell in a reasoning ablation."""

    level: str
    prompt_count: int
    accepted_count: int
    reasoning_tokens: int
    total_tokens: int

    def to_dict(self) -> dict[str, int | str]:
        """Return a stable machine-readable ablation cell."""
        return {
            "level": self.level,
            "prompt_count": self.prompt_count,
            "accepted_count": self.accepted_count,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens,
        }


def select_reasoning_decision(
    profile: ReasoningProfile | None,
    policy: ReasoningPolicy,
    task: str,
    role: str,
    *,
    workload: ReasoningWorkload | Mapping[str, Any] | None = None,
) -> ReasoningDecision | None:
    """Select bounded effort from role, task evidence, and workflow topology.

    Latency is intentionally not an input. The policy allocates test-time compute
    from role, semantic complexity, risk, decomposition, recursion, and access-list
    fan-in, subject only to the model profile's explicit maximum.
    """
    if profile is None or policy.strategy == "disabled":
        return None
    if not isinstance(task, str) or not isinstance(role, str) or not role:
        raise ValueError("task and role must be strings and role must not be empty")
    structure = _coerce_workload(workload)
    if policy.strategy == "fixed":
        requested = policy.fixed_level or profile.default_level
        level = _nearest_supported(profile.bounded_levels, requested)
        return ReasoningDecision(
            level,
            "fixed_policy",
            role,
            0,
            ("fixed_policy",),
            workload=structure,
        )

    lowered = task.lower()
    factors: list[str] = []
    score = _ROLE_BASELINE_OFFSET.get(role, 0)
    if score:
        factors.append(f"role:{role}")
    term_hits = sum(1 for term in _COMPLEXITY_TERMS if term in lowered)
    if term_hits >= 2:
        score += 1
        factors.append("multiple_complexity_signals")
    if len(task) > 800:
        score += 1
        factors.append("long_context")
    if task.count("\n") >= 8 or sum(task.count(marker) for marker in ("1.", "2.", "- ")) >= 4:
        score += 1
        factors.append("multi_step_structure")
    risk_hits = sum(1 for term in _HIGH_RISK_TERMS if term in lowered)
    if risk_hits >= 2:
        score += 1
        factors.append("multiple_high_impact_signals")
    if structure is not None:
        if structure.workflow_step_count >= 4 or structure.decomposition_count >= 3:
            score += 1
            factors.append("decomposed_workflow")
        if structure.recursion_depth >= 2:
            score += 1
            factors.append("recursive_workflow_depth")
        if structure.accessible_step_count >= 2:
            score += 1
            factors.append("access_list_fan_in")
        if (
            structure.workflow_step_index >= max(2, structure.workflow_step_count - 2)
            and structure.accessible_step_count >= 1
        ):
            score += 1
            factors.append("late_workflow_integration")

    base_index = CANONICAL_REASONING_LEVELS.index(profile.default_level)
    requested_index = min(
        base_index + score,
        CANONICAL_REASONING_LEVELS.index(profile.maximum_level),
    )
    requested = CANONICAL_REASONING_LEVELS[requested_index]
    level = _nearest_supported(profile.bounded_levels, requested)
    return ReasoningDecision(
        level=level,
        source="adaptive_policy",
        role=role,
        complexity_score=score,
        factors=tuple(factors or ("profile_default",)),
        workload=structure,
    )


def adapt_reasoning_decision(
    profile: ReasoningProfile | None,
    decision: ReasoningDecision | None,
) -> ReasoningDecision | None:
    """Project one canonical decision onto a failover model's capabilities."""
    if profile is None or decision is None:
        return None
    level = _nearest_supported(profile.bounded_levels, decision.level)
    if level == decision.level:
        return decision
    return ReasoningDecision(
        level=level,
        source=f"{decision.source}:capability_projection",
        role=decision.role,
        complexity_score=decision.complexity_score,
        factors=decision.factors + ("projected_to_provider_capability",),
        escalation_index=decision.escalation_index,
        workload=decision.workload,
    )


def escalate_reasoning_decision(
    profile: ReasoningProfile | None,
    policy: ReasoningPolicy,
    decision: ReasoningDecision | None,
) -> ReasoningDecision | None:
    """Return the immediately higher supported level after a verifier rejection."""
    if profile is None or decision is None:
        return None
    if policy.max_escalations == 0 or decision.escalation_index >= policy.max_escalations:
        return None
    levels = profile.bounded_levels
    current = _nearest_supported(levels, decision.level)
    index = levels.index(current)
    if index + 1 >= len(levels):
        return None
    return ReasoningDecision(
        level=levels[index + 1],
        source="verifier_escalation",
        role=decision.role,
        complexity_score=decision.complexity_score,
        factors=decision.factors + ("verifier_rejected_prior_attempt",),
        escalation_index=decision.escalation_index + 1,
        workload=decision.workload,
    )


def _coerce_workload(
    value: ReasoningWorkload | Mapping[str, Any] | None,
) -> ReasoningWorkload | None:
    """Normalize optional typed or JSON-compatible structural evidence."""
    if value is None or isinstance(value, ReasoningWorkload):
        return value
    if isinstance(value, Mapping):
        return ReasoningWorkload.from_mapping(value)
    raise ValueError("workload must be a mapping, ReasoningWorkload, or None")


def _nearest_supported(levels: tuple[str, ...], requested: str) -> str:
    """Project a canonical requested level to the closest supported lower level."""
    if not levels:
        raise ValueError("no bounded reasoning levels are available")
    if requested not in CANONICAL_REASONING_LEVELS:
        raise ValueError(f"unknown canonical reasoning level: {requested}")
    requested_index = CANONICAL_REASONING_LEVELS.index(requested)
    lower = [
        level
        for level in levels
        if CANONICAL_REASONING_LEVELS.index(level) <= requested_index
    ]
    return lower[-1] if lower else levels[0]


__all__ = [
    "ReasoningAblationCell",
    "ReasoningDecision",
    "ReasoningPolicy",
    "ReasoningWorkload",
    "_coerce_workload",
    "_nearest_supported",
    "adapt_reasoning_decision",
    "escalate_reasoning_decision",
    "select_reasoning_decision",
]
