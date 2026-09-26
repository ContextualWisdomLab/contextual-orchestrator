"""Candidate answers produced by several workers for one task.

These value objects are the input and output of every combination strategy
(``contextual_orchestrator.domain.combination``). They carry no provider,
transport, or persistence detail: an adapter turns provider responses into
``CandidateAnswer`` values before any strategy runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any


@dataclass(frozen=True)
class CandidateAnswer:
    """One worker's answer to the task being combined.

    Attributes:
        agent_id: Identifier of the worker that produced the answer.
        text: The answer text exactly as returned by the worker.
        rank: The worker's prior routing rank for this task; ``0`` is the
            most preferred. Strategies use it only to break ties
            deterministically, never as evidence of correctness.
        cost_usd: Measured or priced cost of producing this answer, or
            ``None`` when no honest cost is known.
    """

    agent_id: str
    text: str
    rank: int
    cost_usd: float | None = None

    def __post_init__(self) -> None:
        """Reject values that would make a combination result ambiguous."""
        if not isinstance(self.agent_id, str) or not self.agent_id.strip():
            raise ValueError("candidate agent_id must be a nonempty string")
        if not isinstance(self.text, str):
            raise ValueError("candidate text must be a string")
        if type(self.rank) is not int or self.rank < 0:
            raise ValueError("candidate rank must be a nonnegative integer")
        if self.cost_usd is not None:
            if type(self.cost_usd) not in (int, float) or not math.isfinite(
                self.cost_usd
            ):
                raise ValueError("candidate cost_usd must be a finite number")
            if self.cost_usd < 0:
                raise ValueError("candidate cost_usd must not be negative")

    @property
    def is_empty(self) -> bool:
        """Whether the answer has no non-whitespace content."""
        return not self.text.strip()

    def as_record(self) -> dict[str, Any]:
        """Return a JSON-compatible record of this candidate."""
        return {
            "agent_id": self.agent_id,
            "rank": self.rank,
            "cost_usd": self.cost_usd,
            "text": self.text,
        }


@dataclass(frozen=True)
class CandidateSet:
    """A nonempty set of answers to one task, ordered by prior rank.

    Agent ids and ranks must each be unique, so every tie-break a strategy
    performs has exactly one outcome.
    """

    candidates: tuple[CandidateAnswer, ...]

    def __post_init__(self) -> None:
        """Validate uniqueness and store candidates in rank order."""
        members = tuple(self.candidates)
        if not members:
            raise ValueError("a candidate set needs at least one candidate")
        if any(not isinstance(member, CandidateAnswer) for member in members):
            raise ValueError("candidate set members must be CandidateAnswer values")
        if len({member.agent_id for member in members}) != len(members):
            raise ValueError("candidate agent_id values must be unique")
        if len({member.rank for member in members}) != len(members):
            raise ValueError("candidate rank values must be unique")
        object.__setattr__(
            self, "candidates", tuple(sorted(members, key=lambda item: item.rank))
        )

    def __len__(self) -> int:
        """Return the number of candidates."""
        return len(self.candidates)

    def nonempty(self) -> tuple[CandidateAnswer, ...]:
        """Return candidates with non-whitespace text, in rank order."""
        return tuple(member for member in self.candidates if not member.is_empty)

    @property
    def total_cost_usd(self) -> float | None:
        """Sum of candidate costs, or ``None`` if any cost is unknown."""
        costs = [member.cost_usd for member in self.candidates]
        if any(cost is None for cost in costs):
            return None
        return float(sum(costs))


@dataclass(frozen=True)
class CombinationOutcome:
    """The result of applying one combination strategy to a candidate set.

    Attributes:
        strategy: Name of the strategy that produced this outcome.
        selected: The chosen candidate, or ``None`` when the strategy
            abstained. An abstention is a fail-closed result: the caller
            decides the fallback, the strategy never invents an answer.
        reason: Machine-readable reason for the selection or abstention.
        support: Share of all candidates that back the selection, when the
            strategy defines one (plurality vote); otherwise ``None``.
        evidence: Per-candidate evidence as ``(agent_id, value)`` pairs in
            rank order, for example the extracted vote key or the score.
    """

    strategy: str
    selected: CandidateAnswer | None
    reason: str
    support: float | None = None
    evidence: tuple[tuple[str, Any], ...] = field(default_factory=tuple)

    @property
    def abstained(self) -> bool:
        """Whether the strategy declined to select a candidate."""
        return self.selected is None

    def as_record(self) -> dict[str, Any]:
        """Return a JSON-compatible record for traces and evaluation cells."""
        return {
            "strategy": self.strategy,
            "selected_agent_id": None if self.selected is None else self.selected.agent_id,
            "reason": self.reason,
            "support": self.support,
            "evidence": [list(pair) for pair in self.evidence],
        }
