"""Contracts for the parallel fan-out and Mixture-of-Agents service."""

from __future__ import annotations

import threading
import time

import pytest

from contextual_orchestrator.application.fan_out import (
    CompletionReply,
    FanOutResult,
    ProposerFailure,
    collect_candidates,
    mixture_of_agents,
    select_answer,
)
from contextual_orchestrator.domain.combination import PluralityVote, normalized_text_key
from contextual_orchestrator.domain.moa import AGGREGATE_AND_SYNTHESIZE_INSTRUCTION

MESSAGES = [{"role": "user", "content": "capital of France?"}]


def _port(replies: dict[str, object], calls: list | None = None):
    def complete(agent_id, messages):
        if calls is not None:
            calls.append((agent_id, messages))
        reply = replies[agent_id]
        if isinstance(reply, BaseException):
            raise reply
        return reply

    return complete


def test_collect_candidates_keeps_rank_and_records_failures_without_messages() -> None:
    result = collect_candidates(
        ["b_worker", "a_worker", "c_worker", "d_worker"],
        MESSAGES,
        _port(
            {
                "b_worker": CompletionReply("Paris", 0.001),
                "a_worker": RuntimeError("secret-bearing provider message"),
                "c_worker": CompletionReply("paris.", None),
                "d_worker": "not a reply",
            }
        ),
        max_concurrency=4,
        deadline_seconds=5,
    )
    assert result.candidates is not None
    assert [(m.agent_id, m.rank) for m in result.candidates.candidates] == [
        ("b_worker", 0),
        ("c_worker", 2),
    ]
    assert result.failures == (
        ProposerFailure("a_worker", "RuntimeError"),
        ProposerFailure("d_worker", "invalid_reply"),
    )
    record = result.as_record()
    assert "secret" not in repr(record)
    assert record["failures"][0] == {"agent_id": "a_worker", "error_type": "RuntimeError"}


def test_each_worker_gets_an_isolated_copy_of_the_messages() -> None:
    calls: list = []

    def complete(agent_id, messages):
        calls.append(messages)
        messages[0]["content"] = f"mutated by {agent_id}"
        return CompletionReply("x")

    collect_candidates(["a_one", "b_two"], MESSAGES, complete, max_concurrency=1, deadline_seconds=5)
    assert MESSAGES[0]["content"] == "capital of France?"
    assert calls[0] is not calls[1]


def test_collect_candidates_runs_workers_concurrently() -> None:
    barrier = threading.Barrier(3, timeout=5)

    def complete(agent_id, messages):
        barrier.wait()
        return CompletionReply(agent_id)

    result = collect_candidates(
        ["a_one", "b_two", "c_three"], MESSAGES, complete, max_concurrency=3, deadline_seconds=5
    )
    assert result.failures == ()
    assert len(result.candidates) == 3


def test_collect_candidates_marks_slow_workers_past_the_deadline() -> None:
    release = threading.Event()

    def complete(agent_id, messages):
        if agent_id == "slow_worker":
            release.wait(5)
        return CompletionReply(agent_id)

    started = time.perf_counter()
    result = collect_candidates(
        ["fast_worker", "slow_worker"], MESSAGES, complete, max_concurrency=2, deadline_seconds=0.2
    )
    elapsed = time.perf_counter() - started
    release.set()
    assert elapsed < 2
    assert [m.agent_id for m in result.candidates.candidates] == ["fast_worker"]
    assert result.failures == (ProposerFailure("slow_worker", "deadline_exceeded"),)


def test_collect_candidates_returns_none_when_all_fail() -> None:
    result = collect_candidates(
        ["a_one"], MESSAGES, _port({"a_one": ValueError()}), max_concurrency=1, deadline_seconds=1
    )
    assert result.candidates is None
    assert result.as_record()["candidates"] == []
    assert select_answer(result, PluralityVote(normalized_text_key, min_support=0.5)) is None


@pytest.mark.parametrize(
    ("ids", "messages", "concurrency", "deadline", "match"),
    [
        ([], MESSAGES, 1, 1, "at least one agent"),
        (["a", "a"], MESSAGES, 1, 1, "unique"),
        (["a"], [], 1, 1, "at least one message"),
        (["a"], MESSAGES, 0, 1, "max_concurrency"),
        (["a"], MESSAGES, True, 1, "max_concurrency"),
        (["a"], MESSAGES, 1, 0, "deadline_seconds"),
        (["a"], MESSAGES, 1, float("inf"), "deadline_seconds"),
    ],
)
def test_collect_candidates_requires_declared_bounds(ids, messages, concurrency, deadline, match) -> None:
    with pytest.raises(ValueError, match=match):
        collect_candidates(
            ids, messages, _port({}), max_concurrency=concurrency, deadline_seconds=deadline
        )


def test_select_answer_votes_over_the_fan_out() -> None:
    result = collect_candidates(
        ["a_one", "b_two", "c_three"],
        MESSAGES,
        _port(
            {
                "a_one": CompletionReply("Lyon"),
                "b_two": CompletionReply("Paris"),
                "c_three": CompletionReply("paris"),
            }
        ),
        max_concurrency=3,
        deadline_seconds=5,
    )
    outcome = select_answer(result, PluralityVote(normalized_text_key, min_support=0.5))
    assert outcome is not None and outcome.selected.agent_id == "b_two"


def test_mixture_of_agents_aggregates_only_arrived_proposals() -> None:
    calls: list = []
    result = mixture_of_agents(
        MESSAGES,
        ["p_one", "p_two", "p_three"],
        "agg_worker",
        _port(
            {
                "p_one": CompletionReply("Paris", 0.001),
                "p_two": TimeoutError(),
                "p_three": CompletionReply("It is Paris", 0.002),
                "agg_worker": CompletionReply("Paris.", 0.003),
            },
            calls,
        ),
        max_concurrency=3,
        deadline_seconds=5,
    )
    assert result.answer == "Paris."
    assert result.aggregator_error is None
    # A failed proposer may still have been billed: the total is unknown.
    assert result.cost_usd is None
    aggregator_messages = [messages for agent, messages in calls if agent == "agg_worker"][0]
    assert aggregator_messages[0]["content"].startswith(AGGREGATE_AND_SYNTHESIZE_INSTRUCTION)
    assert "1. Paris\n2. It is Paris" in aggregator_messages[0]["content"]
    assert aggregator_messages[1:] == MESSAGES
    record = result.as_record()
    assert record["strategy"] == "mixture_of_agents"
    assert record["proposers"]["failures"] == [{"agent_id": "p_two", "error_type": "TimeoutError"}]


def test_mixture_of_agents_totals_cost_when_every_part_is_known() -> None:
    result = mixture_of_agents(
        MESSAGES,
        ["p_one", "p_two"],
        "agg_worker",
        _port(
            {
                "p_one": CompletionReply("a", 0.001),
                "p_two": CompletionReply("b", 0.002),
                "agg_worker": CompletionReply("c", 0.004),
            }
        ),
        max_concurrency=2,
        deadline_seconds=5,
    )
    assert result.cost_usd == pytest.approx(0.007)


def test_mixture_of_agents_fails_closed_without_proposals() -> None:
    calls: list = []
    result = mixture_of_agents(
        MESSAGES,
        ["p_one", "p_two"],
        "agg_worker",
        _port({"p_one": OSError(), "p_two": CompletionReply("   ")}, calls),
        max_concurrency=2,
        deadline_seconds=5,
    )
    assert result.answer is None and result.aggregator_error == "no_proposals"
    assert "agg_worker" not in [agent for agent, _ in calls]


@pytest.mark.parametrize(
    ("aggregator_reply", "error"),
    [(RuntimeError("leak"), "RuntimeError"), ("bad", "invalid_reply")],
)
def test_mixture_of_agents_records_aggregator_failure(aggregator_reply, error) -> None:
    result = mixture_of_agents(
        MESSAGES,
        ["p_one"],
        "agg_worker",
        _port({"p_one": CompletionReply("a", 0.1), "agg_worker": aggregator_reply}),
        max_concurrency=1,
        deadline_seconds=5,
    )
    assert result.answer is None
    assert result.aggregator_error == error
    assert result.cost_usd is None


def test_mixture_of_agents_requires_an_aggregator() -> None:
    with pytest.raises(ValueError, match="aggregator_id"):
        mixture_of_agents(
            MESSAGES, ["p_one"], " ", _port({}), max_concurrency=1, deadline_seconds=1
        )


def test_fan_out_result_record_lists_candidates() -> None:
    result = collect_candidates(
        ["a_one"], MESSAGES, _port({"a_one": CompletionReply("x", 0.5)}), max_concurrency=1, deadline_seconds=1
    )
    assert isinstance(result, FanOutResult)
    assert result.as_record()["candidates"] == [
        {"agent_id": "a_one", "rank": 0, "cost_usd": 0.5, "text": "x"}
    ]
