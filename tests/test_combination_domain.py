"""Contracts for the pure multi-model combination domain (ADR 0124 step 4)."""

from __future__ import annotations

import math
import random

import pytest

from contextual_orchestrator.domain.candidates import (
    CandidateAnswer,
    CandidateSet,
    CombinationOutcome,
)
from contextual_orchestrator.domain.combination import (
    CombinationStrategy,
    PluralityVote,
    RankedFirst,
    ScoredBestOfN,
    normalized_text_key,
)
from contextual_orchestrator.domain.moa import (
    AGGREGATE_AND_SYNTHESIZE_INSTRUCTION,
    aggregate_and_synthesize_messages,
)


def _set(*texts: str, costs: tuple[float | None, ...] | None = None) -> CandidateSet:
    return CandidateSet(
        tuple(
            CandidateAnswer(
                agent_id=f"agent_{index}",
                text=text,
                rank=index,
                cost_usd=None if costs is None else costs[index],
            )
            for index, text in enumerate(texts)
        )
    )


# --- value objects -------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"agent_id": "", "text": "x", "rank": 0},
        {"agent_id": "  ", "text": "x", "rank": 0},
        {"agent_id": 3, "text": "x", "rank": 0},
        {"agent_id": "a", "text": None, "rank": 0},
        {"agent_id": "a", "text": "x", "rank": -1},
        {"agent_id": "a", "text": "x", "rank": True},
        {"agent_id": "a", "text": "x", "rank": 1.0},
        {"agent_id": "a", "text": "x", "rank": 0, "cost_usd": -0.01},
        {"agent_id": "a", "text": "x", "rank": 0, "cost_usd": math.nan},
        {"agent_id": "a", "text": "x", "rank": 0, "cost_usd": math.inf},
        {"agent_id": "a", "text": "x", "rank": 0, "cost_usd": True},
        {"agent_id": "a", "text": "x", "rank": 0, "cost_usd": "0.1"},
    ],
)
def test_candidate_answer_rejects_ambiguous_values(kwargs) -> None:
    with pytest.raises(ValueError):
        CandidateAnswer(**kwargs)


def test_candidate_set_orders_by_rank_and_requires_uniqueness() -> None:
    late = CandidateAnswer("late", "b", 2)
    early = CandidateAnswer("early", "a", 0)
    assert CandidateSet((late, early)).candidates == (early, late)
    assert len(CandidateSet((late, early))) == 2
    with pytest.raises(ValueError, match="at least one"):
        CandidateSet(())
    with pytest.raises(ValueError, match="agent_id"):
        CandidateSet((early, CandidateAnswer("early", "c", 1)))
    with pytest.raises(ValueError, match="rank"):
        CandidateSet((early, CandidateAnswer("other", "c", 0)))
    with pytest.raises(ValueError, match="CandidateAnswer"):
        CandidateSet((early, "not a candidate"))  # type: ignore[arg-type]


def test_total_cost_is_unknown_when_any_member_cost_is_unknown() -> None:
    assert _set("a", "b", costs=(0.25, 0.5)).total_cost_usd == pytest.approx(0.75)
    assert _set("a", "b", costs=(0.25, None)).total_cost_usd is None


def test_records_are_json_compatible() -> None:
    candidate = CandidateAnswer("a", "text", 0, 0.1)
    assert candidate.as_record() == {
        "agent_id": "a",
        "rank": 0,
        "cost_usd": 0.1,
        "text": "text",
    }
    outcome = CombinationOutcome("s", candidate, "r", 0.5, (("a", "k"),))
    assert outcome.as_record() == {
        "strategy": "s",
        "selected_agent_id": "a",
        "reason": "r",
        "support": 0.5,
        "evidence": [["a", "k"]],
    }
    assert not outcome.abstained
    assert CombinationOutcome("s", None, "r").as_record()["selected_agent_id"] is None


# --- strategies ----------------------------------------------------------


def test_strategies_satisfy_the_protocol() -> None:
    for strategy in (
        RankedFirst(),
        PluralityVote(normalized_text_key),
        ScoredBestOfN(lambda candidate: 1.0),
    ):
        assert isinstance(strategy, CombinationStrategy)


def test_ranked_first_matches_route_semantics() -> None:
    outcome = RankedFirst().combine(_set("  ", "second", "third"))
    assert outcome.selected is not None and outcome.selected.agent_id == "agent_1"
    assert outcome.reason == "best_ranked_nonempty"
    assert outcome.evidence == (("agent_0", False), ("agent_1", True), ("agent_2", True))
    abstained = RankedFirst().combine(_set("", " "))
    assert abstained.abstained and abstained.reason == "no_nonempty_candidate"


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("Paris.", "paris"),
        ("  paris ", "paris"),
        ("New   York!", "new york"),
        ("42", "42"),
        ("...", None),
        ("", None),
    ],
)
def test_normalized_text_key(text: str, key: str | None) -> None:
    assert normalized_text_key(text) == key


def test_normalized_text_key_rejects_non_text() -> None:
    with pytest.raises(TypeError):
        normalized_text_key(None)  # type: ignore[arg-type]


def test_plurality_vote_overrules_the_top_ranked_minority() -> None:
    outcome = PluralityVote(normalized_text_key).combine(
        _set("Lyon", "Paris.", "paris", "Marseille")
    )
    assert outcome.selected is not None
    assert outcome.selected.agent_id == "agent_1"  # best-ranked supporter
    assert outcome.support == pytest.approx(0.5)
    assert outcome.reason == "plurality"
    assert outcome.evidence == (
        ("agent_0", "lyon"),
        ("agent_1", "paris"),
        ("agent_2", "paris"),
        ("agent_3", "marseille"),
    )


def test_plurality_vote_abstains_when_maximum_counts_tie() -> None:
    outcome = PluralityVote(normalized_text_key).combine(_set("b", "a", "a", "b"))
    assert outcome.abstained
    assert outcome.reason == "plurality_tie"
    assert outcome.support == pytest.approx(0.5)


def test_plurality_vote_uses_the_unique_mode_without_a_policy_threshold() -> None:
    outcome = PluralityVote(normalized_text_key).combine(_set("a", "a", "b", "c", "d"))
    assert outcome.selected is not None and outcome.selected.agent_id == "agent_0"
    assert outcome.reason == "plurality"
    assert outcome.support == pytest.approx(0.4)


def test_plurality_support_counts_unextractable_candidates() -> None:
    outcome = PluralityVote(normalized_text_key).combine(_set("a", "", "...", "b"))
    assert outcome.abstained and outcome.reason == "plurality_tie"
    assert outcome.support == pytest.approx(0.25)
    none = PluralityVote(normalized_text_key).combine(_set("", "..."))
    assert none.abstained and none.reason == "no_extractable_answer"
    assert none.support == 0.0


def test_plurality_vote_rejects_bad_extractors() -> None:
    with pytest.raises(TypeError):
        PluralityVote("not callable")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="string or None"):
        PluralityVote(lambda text: 3).combine(_set("a"))  # type: ignore[arg-type,return-value]


def test_plurality_vote_treats_empty_key_as_unextractable() -> None:
    outcome = PluralityVote(lambda text: "").combine(_set("a"))
    assert outcome.reason == "no_extractable_answer"


def test_scored_best_of_n_selects_max_and_skips_unscored() -> None:
    scores = {"agent_0": None, "agent_1": 0.4, "agent_2": 0.9, "agent_3": 0.8}
    outcome = ScoredBestOfN(lambda candidate: scores[candidate.agent_id]).combine(
        _set("a", "b", "c", "d")
    )
    assert outcome.selected is not None and outcome.selected.agent_id == "agent_2"
    assert outcome.reason == "highest_score"
    assert outcome.evidence == (
        ("agent_0", None),
        ("agent_1", 0.4),
        ("agent_2", 0.9),
        ("agent_3", 0.8),
    )


def test_scored_best_of_n_abstains_when_maximum_scores_tie() -> None:
    outcome = ScoredBestOfN(lambda candidate: 0.9).combine(_set("a", "b"))
    assert outcome.abstained
    assert outcome.reason == "score_tie"


def test_scored_best_of_n_never_scores_empty_answers() -> None:
    calls: list[str] = []

    def scorer(candidate: CandidateAnswer) -> float:
        calls.append(candidate.agent_id)
        return 1.0

    outcome = ScoredBestOfN(scorer).combine(_set("", "b"))
    assert calls == ["agent_1"]
    assert outcome.selected is not None and outcome.selected.agent_id == "agent_1"


def test_scored_best_of_n_abstains_without_scores_and_rejects_bad_scores() -> None:
    outcome = ScoredBestOfN(lambda candidate: None).combine(_set("a", "b"))
    assert outcome.abstained and outcome.reason == "no_scored_candidate"
    for bad in (math.nan, math.inf, "1", True):
        with pytest.raises(ValueError, match="finite"):
            ScoredBestOfN(lambda candidate, bad=bad: bad).combine(_set("a"))
    with pytest.raises(TypeError):
        ScoredBestOfN(None)  # type: ignore[arg-type]


def test_plurality_vote_mechanism_beats_best_single_on_independent_errors() -> None:
    """Mechanism check only, on synthetic data; it is not a product claim.

    Five simulated workers answer each item correctly with probability 0.7,
    independently, and spread wrong answers over four distractors. Under
    those assumptions (Condorcet's jury theorem), a plurality vote should
    beat every single worker. Real providers have correlated errors; the
    product claim needs live paired evaluation (``nim_benchmark``).
    """
    rng = random.Random(20260926)
    item_count, worker_count = 400, 5
    single_correct = [0] * worker_count
    vote_correct = 0
    vote = PluralityVote(normalized_text_key)
    for _item in range(item_count):
        texts = []
        for worker in range(worker_count):
            correct = rng.random() < 0.7
            single_correct[worker] += correct
            texts.append("right" if correct else f"wrong{rng.randrange(4)}")
        outcome = vote.combine(_set(*texts))
        vote_correct += outcome.selected is not None and outcome.selected.text == "right"
    assert vote_correct > max(single_correct)


# --- Mixture-of-Agents aggregator messages -------------------------------


def test_moa_messages_follow_the_paper_shape() -> None:
    original = [{"role": "user", "content": "What is 2+2?"}]
    messages = aggregate_and_synthesize_messages(original, _set("4", "  ", "four"))
    assert messages[0]["role"] == "system"
    system = messages[0]["content"]
    assert system.startswith(AGGREGATE_AND_SYNTHESIZE_INSTRUCTION)
    assert system.endswith("Responses from models:\n1. 4\n2. four")
    assert "agent_" not in system  # proposers are anonymous
    assert messages[1:] == original
    messages[1]["content"] = "mutated"
    assert original[0]["content"] == "What is 2+2?"


def test_moa_messages_require_conversation_and_a_proposal() -> None:
    with pytest.raises(ValueError, match="original"):
        aggregate_and_synthesize_messages([], _set("a"))
    with pytest.raises(ValueError, match="nonempty proposer"):
        aggregate_and_synthesize_messages([{"role": "user", "content": "q"}], _set(" "))
