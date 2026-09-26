"""Strategies that combine several workers' answers into one.

The product's core claim is that combining models beats any single model
(Sakana Fugu; Mixture-of-Agents, Wang et al., 2024, arXiv:2406.04692). On
``main`` before this module, the only combination paths were rank-ordered
failover and an LLM synthesizer over one worker's output. This module makes
the selection rule an explicit, testable domain object.

Strategies are pure: they receive a ``CandidateSet`` and return a
``CombinationOutcome``. They never call a provider. When the evidence does
not support a selection they abstain (``selected is None``) and the caller
chooses the fallback, matching the repository's fail-closed judgment policy
(planning ADR 0001).

Implemented strategies and their sources:

- ``RankedFirst``: today's route semantics. The best-ranked nonempty answer
  wins. No paper claim.
- ``PluralityVote``: the aggregation rule of self-consistency (Wang et al.,
  2023, arXiv:2203.11171, Section 2): extract a final answer from each
  output and take the most frequent one. The paper samples one model many
  times; here the voters are different workers, which the paper treats as a
  model ensemble. The agreement share is reported as ``support``, because the
  paper finds that consistency correlates with accuracy (Section 3.5). The
  Tied maximum counts abstain because the cited rule supplies no secondary
  authority for choosing one tied answer.
- ``ScoredBestOfN``: best-of-n selection by an external scorer, such as the
  fast-mlsirm judge. The scorer is a port; this module does not choose one.
"""

from __future__ import annotations

from collections.abc import Callable
import math
import re
from typing import Protocol, runtime_checkable

from .candidates import CandidateAnswer, CandidateSet, CombinationOutcome

_WHITESPACE = re.compile(r"\s+")
_TRAILING_PUNCTUATION = ".,;:!?\"'`)]}"


@runtime_checkable
class CombinationStrategy(Protocol):
    """Select at most one answer from a candidate set."""

    name: str

    def combine(self, candidates: CandidateSet) -> CombinationOutcome:
        """Return the selected candidate, or an abstention with a reason."""
        ...


def normalized_text_key(text: str) -> str | None:
    """Return a comparison key for short final answers, or ``None`` if empty.

    The key case-folds, collapses internal whitespace, and strips trailing
    punctuation, so ``"Paris."`` and ``" paris "`` vote together. It is meant
    for short, closed-form answers. Long free-form answers rarely match
    exactly and should use a task-specific extractor instead.
    """
    if not isinstance(text, str):
        raise TypeError("answer text must be a string")
    key = _WHITESPACE.sub(" ", text.casefold()).strip().rstrip(_TRAILING_PUNCTUATION).strip()
    return key or None


class RankedFirst:
    """Select the best-ranked candidate with a nonempty answer."""

    name = "ranked_first"

    def combine(self, candidates: CandidateSet) -> CombinationOutcome:
        """Return the first nonempty candidate in rank order."""
        evidence = tuple(
            (member.agent_id, not member.is_empty) for member in candidates.candidates
        )
        nonempty = candidates.nonempty()
        if not nonempty:
            return CombinationOutcome(
                strategy=self.name,
                selected=None,
                reason="no_nonempty_candidate",
                evidence=evidence,
            )
        return CombinationOutcome(
            strategy=self.name,
            selected=nonempty[0],
            reason="best_ranked_nonempty",
            evidence=evidence,
        )


class PluralityVote:
    """Select the answer that most candidates agree on.

    Args:
        answer_key: Extracts the final answer to vote on from a candidate's
            text, or returns ``None`` when no answer can be extracted.
            Unextractable candidates still count in the ``support``
            denominator, so a vote among few parseable answers is not
            reported as unanimous.
    """

    name = "plurality_vote"

    def __init__(
        self,
        answer_key: Callable[[str], str | None],
    ) -> None:
        """Validate and store the answer extractor."""
        if not callable(answer_key):
            raise TypeError("answer_key must be callable")
        self._answer_key = answer_key

    def combine(self, candidates: CandidateSet) -> CombinationOutcome:
        """Vote over extracted keys; break count ties by best supporter rank."""
        keys: list[tuple[CandidateAnswer, str | None]] = []
        for member in candidates.candidates:
            key = None if member.is_empty else self._answer_key(member.text)
            if key is not None and not isinstance(key, str):
                raise TypeError("answer_key must return a string or None")
            keys.append((member, key or None))
        evidence = tuple((member.agent_id, key) for member, key in keys)
        supporters: dict[str, list[CandidateAnswer]] = {}
        for member, key in keys:
            if key is not None:
                supporters.setdefault(key, []).append(member)
        if not supporters:
            return CombinationOutcome(
                strategy=self.name,
                selected=None,
                reason="no_extractable_answer",
                support=0.0,
                evidence=evidence,
            )
        maximum_count = max(len(group) for group in supporters.values())
        winning_keys = [
            key for key, group in supporters.items() if len(group) == maximum_count
        ]
        support = maximum_count / len(candidates)
        if len(winning_keys) != 1:
            return CombinationOutcome(
                strategy=self.name,
                selected=None,
                reason="plurality_tie",
                support=support,
                evidence=evidence,
            )
        winning_key = winning_keys[0]
        winners = supporters[winning_key]
        return CombinationOutcome(
            strategy=self.name,
            selected=winners[0],
            reason="plurality",
            support=support,
            evidence=evidence,
        )


class ScoredBestOfN:
    """Select the highest-scoring candidate according to an external scorer.

    Args:
        scorer: Returns a finite score (higher is better) for a candidate, or
            ``None`` when the candidate cannot be scored. ``None`` excludes
            the candidate; it is never treated as a low score. A non-finite
            score is a scorer defect and raises ``ValueError``.
    """

    name = "scored_best_of_n"

    def __init__(self, scorer: Callable[[CandidateAnswer], float | None]) -> None:
        """Store the scorer port."""
        if not callable(scorer):
            raise TypeError("scorer must be callable")
        self._scorer = scorer

    def combine(self, candidates: CandidateSet) -> CombinationOutcome:
        """Score candidates and select a unique maximum, abstaining on ties."""
        scored: list[tuple[CandidateAnswer, float]] = []
        evidence: list[tuple[str, float | None]] = []
        for member in candidates.candidates:
            score = None if member.is_empty else self._scorer(member)
            if score is not None:
                if type(score) not in (int, float) or not math.isfinite(score):
                    raise ValueError("scorer must return a finite number or None")
                scored.append((member, float(score)))
            evidence.append((member.agent_id, None if score is None else float(score)))
        if not scored:
            return CombinationOutcome(
                strategy=self.name,
                selected=None,
                reason="no_scored_candidate",
                evidence=tuple(evidence),
            )
        maximum_score = max(score for _candidate, score in scored)
        best = [candidate for candidate, score in scored if score == maximum_score]
        if len(best) != 1:
            return CombinationOutcome(
                strategy=self.name,
                selected=None,
                reason="score_tie",
                evidence=tuple(evidence),
            )
        return CombinationOutcome(
            strategy=self.name,
            selected=best[0],
            reason="highest_score",
            evidence=tuple(evidence),
        )
