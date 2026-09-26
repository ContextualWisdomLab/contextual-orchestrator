"""Run several workers on one task in parallel and combine their answers.

This is the multi-model execution step that ``TaskOrchestrator.conduct``
lacks on ``main``: conduct runs one worker per plan, so no request ever has
more than one candidate answer to combine. The functions here take the
provider call as a port (``CompletionPort``) and so can be wired into the
orchestrator, the NIM benchmark, or tests without importing any of them.

Two entry points:

- ``collect_candidates``: bounded parallel fan-out that returns a
  ``CandidateSet`` plus per-worker failures.
- ``mixture_of_agents``: one proposer layer plus one aggregator call
  (Wang et al., 2024, arXiv:2406.04692; the paper's two-layer shape).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, wait
import copy
from dataclasses import dataclass
import math
from typing import Any

from ..domain.candidates import CandidateAnswer, CandidateSet, CombinationOutcome
from ..domain.combination import CombinationStrategy
from ..domain.moa import aggregate_and_synthesize_messages


@dataclass(frozen=True)
class CompletionReply:
    """What a completion port returns for one call.

    Attributes:
        text: The model's answer text.
        cost_usd: Measured or priced cost, or ``None`` when unknown.
    """

    text: str
    cost_usd: float | None = None


CompletionPort = Callable[[str, list[dict[str, Any]]], CompletionReply]
"""Port signature: ``(agent_id, messages) -> CompletionReply``."""


@dataclass(frozen=True)
class ProposerFailure:
    """A worker that produced no candidate.

    Attributes:
        agent_id: The worker that failed.
        error_type: Exception class name, or ``"deadline_exceeded"``. The
            message is omitted on purpose: provider errors can carry request
            content or credentials.
    """

    agent_id: str
    error_type: str


@dataclass(frozen=True)
class FanOutResult:
    """Candidates collected from a fan-out, plus the workers that failed.

    ``candidates`` is ``None`` only when every worker failed.
    """

    candidates: CandidateSet | None
    failures: tuple[ProposerFailure, ...]

    def as_record(self) -> dict[str, Any]:
        """Return a JSON-compatible record for traces."""
        return {
            "candidates": (
                []
                if self.candidates is None
                else [member.as_record() for member in self.candidates.candidates]
            ),
            "failures": [
                {"agent_id": failure.agent_id, "error_type": failure.error_type}
                for failure in self.failures
            ],
        }


def _require_positive_int(value: object, field_name: str) -> int:
    """Return ``value`` if it is a positive non-boolean integer."""
    if type(value) is not int or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _require_positive_seconds(value: object, field_name: str) -> float:
    """Return ``value`` as seconds if it is a positive finite number."""
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{field_name} must be a positive finite number")
    return float(value)


def collect_candidates(
    agent_ids: Sequence[str],
    messages: Sequence[Mapping[str, Any]],
    complete: CompletionPort,
    *,
    max_concurrency: int,
    deadline_seconds: float,
) -> FanOutResult:
    """Ask every worker the same question in parallel.

    Args:
        agent_ids: Workers in prior rank order; position becomes
            ``CandidateAnswer.rank``. Must be unique and nonempty.
        messages: The chat messages every worker receives. Each worker gets
            its own deep copy, so one port cannot alter another's input.
        complete: The completion port.
        max_concurrency: Upper bound on simultaneous calls. Declared by the
            caller; there is no default.
        deadline_seconds: Wall-clock budget for the whole fan-out. Workers
            still running at the deadline are recorded as
            ``deadline_exceeded``; their threads are not awaited.

    Returns:
        The collected candidates and failures.
    """
    ids = list(agent_ids)
    if not ids:
        raise ValueError("fan-out needs at least one agent id")
    if len(set(ids)) != len(ids):
        raise ValueError("fan-out agent ids must be unique")
    if not messages:
        raise ValueError("fan-out needs at least one message")
    concurrency = _require_positive_int(max_concurrency, "max_concurrency")
    deadline = _require_positive_seconds(deadline_seconds, "deadline_seconds")

    executor = ThreadPoolExecutor(
        max_workers=min(concurrency, len(ids)), thread_name_prefix="fan_out"
    )
    try:
        futures = {
            executor.submit(complete, agent_id, copy.deepcopy(list(messages))): (
                rank,
                agent_id,
            )
            for rank, agent_id in enumerate(ids)
        }
        # ALL_COMPLETED: one worker's failure must not stop the others.
        done, _pending = wait(futures, timeout=deadline, return_when="ALL_COMPLETED")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    answers: list[CandidateAnswer] = []
    failures: list[ProposerFailure] = []
    for future, (rank, agent_id) in sorted(futures.items(), key=lambda item: item[1][0]):
        if future not in done:
            failures.append(ProposerFailure(agent_id, "deadline_exceeded"))
            continue
        error = future.exception()
        if error is not None:
            if not isinstance(error, Exception):  # pragma: no cover - BaseException
                raise error
            failures.append(ProposerFailure(agent_id, type(error).__name__))
            continue
        reply = future.result()
        if not isinstance(reply, CompletionReply):
            failures.append(ProposerFailure(agent_id, "invalid_reply"))
            continue
        answers.append(
            CandidateAnswer(
                agent_id=agent_id, text=reply.text, rank=rank, cost_usd=reply.cost_usd
            )
        )
    return FanOutResult(
        candidates=CandidateSet(tuple(answers)) if answers else None,
        failures=tuple(failures),
    )


def select_answer(
    fan_out: FanOutResult, strategy: CombinationStrategy
) -> CombinationOutcome | None:
    """Apply a selection strategy, or return ``None`` if nothing was collected."""
    if fan_out.candidates is None:
        return None
    return strategy.combine(fan_out.candidates)


@dataclass(frozen=True)
class MixtureOfAgentsResult:
    """Outcome of one proposer layer plus one aggregator call.

    Attributes:
        answer: The aggregator's answer, or ``None`` if it could not run.
        aggregator_id: The aggregator worker.
        fan_out: The proposer layer's candidates and failures.
        aggregator_error: Exception class name if the aggregator call
            failed, ``"no_proposals"`` if no proposer answered, else ``None``.
        cost_usd: Total cost of proposers and aggregator, or ``None`` if any
            part is unknown. A failed or timed-out call may still have been
            billed, so any failure makes the total unknown rather than
            silently lower.
    """

    answer: str | None
    aggregator_id: str
    fan_out: FanOutResult
    aggregator_error: str | None
    cost_usd: float | None

    def as_record(self) -> dict[str, Any]:
        """Return a JSON-compatible record for traces and evaluation cells."""
        return {
            "strategy": "mixture_of_agents",
            "aggregator_id": self.aggregator_id,
            "aggregator_error": self.aggregator_error,
            "cost_usd": self.cost_usd,
            "proposers": self.fan_out.as_record(),
        }


def mixture_of_agents(
    messages: Sequence[Mapping[str, Any]],
    proposer_ids: Sequence[str],
    aggregator_id: str,
    complete: CompletionPort,
    *,
    max_concurrency: int,
    deadline_seconds: float,
) -> MixtureOfAgentsResult:
    """Run proposers in parallel, then have the aggregator synthesize.

    Failed proposers are dropped; the aggregator sees only answers that
    arrived. If no proposer answered, the aggregator is not called and
    ``answer`` is ``None`` (fail-closed: no single-model fallback is
    substituted silently; the caller decides). The aggregator call is not
    bounded by ``deadline_seconds``; bound it inside the port.
    """
    if not isinstance(aggregator_id, str) or not aggregator_id.strip():
        raise ValueError("aggregator_id must be a nonempty string")
    fan_out = collect_candidates(
        proposer_ids,
        messages,
        complete,
        max_concurrency=max_concurrency,
        deadline_seconds=deadline_seconds,
    )
    proposer_cost = (
        None
        if fan_out.candidates is None or fan_out.failures
        else fan_out.candidates.total_cost_usd
    )
    if fan_out.candidates is None or not fan_out.candidates.nonempty():
        return MixtureOfAgentsResult(
            answer=None,
            aggregator_id=aggregator_id,
            fan_out=fan_out,
            aggregator_error="no_proposals",
            cost_usd=proposer_cost,
        )
    aggregator_messages = aggregate_and_synthesize_messages(messages, fan_out.candidates)
    try:
        reply = complete(aggregator_id, aggregator_messages)
    except Exception as error:  # noqa: BLE001 - recorded by class name only
        return MixtureOfAgentsResult(
            answer=None,
            aggregator_id=aggregator_id,
            fan_out=fan_out,
            aggregator_error=type(error).__name__,
            cost_usd=None,
        )
    if not isinstance(reply, CompletionReply):
        return MixtureOfAgentsResult(
            answer=None,
            aggregator_id=aggregator_id,
            fan_out=fan_out,
            aggregator_error="invalid_reply",
            cost_usd=None,
        )
    total_cost = (
        None
        if proposer_cost is None or reply.cost_usd is None
        else proposer_cost + reply.cost_usd
    )
    return MixtureOfAgentsResult(
        answer=reply.text,
        aggregator_id=aggregator_id,
        fan_out=fan_out,
        aggregator_error=None,
        cost_usd=total_cost,
    )
