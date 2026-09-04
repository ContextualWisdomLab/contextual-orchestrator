"""Fast-MLSIRM-backed model ordering for observed prompt interactions."""

from __future__ import annotations

from collections import OrderedDict
import hashlib
import math
import threading
from typing import Iterable


class PsychometricRoutingEvidence:
    """Fit judged model-by-prompt responses and score the nearest prompt item.

    The response matrix is versioned deployment candidate by system/user
    interaction. A fast-mlsirm MLSRM fit estimates conditional response
    probabilities and latent interaction distance together. These local values
    are routing evidence, not a transportable or invariant model-ability scale.
    New prompts interpolate at most two positive-cosine observed interactions.
    Candidates without a fitted estimate remain unranked so the caller can
    preserve its existing measured-routing order.
    """

    def __init__(
        self,
        max_contexts: int = 512,
        *,
        semantic_warm_start_enabled: bool = False,
    ) -> None:
        if type(semantic_warm_start_enabled) is not bool:
            raise TypeError("semantic_warm_start_enabled must be a boolean")
        self.max_contexts = max_contexts
        self.semantic_warm_start_enabled = semantic_warm_start_enabled
        self._lock = threading.Lock()
        self._contexts: OrderedDict[str, list[float] | None] = OrderedDict()
        self._responses: dict[tuple[str, str, int], int] = {}
        self._revision = 0
        self._fit_revision = -1
        self._scores: dict[str, dict[str, float]] = {}

    @staticmethod
    def context_id(prompt_interaction: str) -> str:
        """Stable, non-reversible identity for one canonical prompt interaction."""
        return hashlib.sha256(prompt_interaction.encode("utf-8")).hexdigest()

    def observe(
        self,
        prompt_interaction: str,
        agent_id: str,
        accepted: bool,
        vector: list[float] | None,
        irt_row: Iterable[int] = (),
    ) -> None:
        """Record the latest fast-mlsirm judge outcome for one model/item cell."""
        self.observe_context_id(
            self.context_id(prompt_interaction), agent_id, accepted, vector, irt_row
        )

    def observe_context_id(
        self,
        context_id: str,
        agent_id: str,
        accepted: bool,
        vector: list[float] | None,
        irt_row: Iterable[int] = (),
    ) -> None:
        """Restore or record one observation using a non-reversible context id."""
        with self._lock:
            self._contexts[context_id] = vector
            self._contexts.move_to_end(context_id)
            values = (int(accepted), *(int(value) for value in irt_row))
            if any(value not in (0, 1) for value in values):
                raise ValueError("judge IRT rows must be dichotomous")
            stale_index = len(values)
            while (agent_id, context_id, stale_index) in self._responses:
                del self._responses[(agent_id, context_id, stale_index)]
                stale_index += 1
            for item_index, value in enumerate(values):
                self._responses[(agent_id, context_id, item_index)] = value
            while len(self._contexts) > self.max_contexts:
                removed, _ = self._contexts.popitem(last=False)
                self._responses = {
                    key: value for key, value in self._responses.items() if key[1] != removed
                }
            self._revision += 1

    def ranked_evidence(
        self,
        agent_ids: Iterable[str],
        prompt_interaction: str,
        vector: list[float] | None,
    ) -> list[tuple[str, float]]:
        """Return only candidates with a fitted contextual success estimate."""
        agent_ids = tuple(agent_ids)
        with self._lock:
            self._fit_locked()
            if not self._scores:
                return []
            exact_id = self.context_id(prompt_interaction)
            if exact_id in self._scores:
                context_scores = self._scores[exact_id]
            elif vector is not None:
                comparable = [
                    (self._cosine(vector, stored_vector), stored_id)
                    for stored_id, stored_vector in self._contexts.items()
                    if stored_id in self._scores and stored_vector is not None
                ]
                comparable = [item for item in comparable if item[0] is not None]
                if not comparable:
                    return []
                neighbor_limit = 2 if self.semantic_warm_start_enabled else 1
                neighbors = sorted(comparable, reverse=True)[:neighbor_limit]
                if neighbors[0][0] <= 0:
                    return []
                if len(neighbors) == 1 or neighbors[1][0] <= 0:
                    context_scores = self._scores[neighbors[0][1]]
                else:
                    context_scores = {
                        agent_id: sum(
                            similarity * self._scores[context_id][agent_id]
                            for similarity, context_id in neighbors
                            if agent_id in self._scores[context_id]
                        )
                        / sum(
                            similarity
                            for similarity, context_id in neighbors
                            if agent_id in self._scores[context_id]
                        )
                        for agent_id in agent_ids
                        if any(agent_id in self._scores[context_id] for _, context_id in neighbors)
                    }
            else:
                return []
            scored = [
                (agent_id, context_scores[agent_id])
                for agent_id in agent_ids
                if agent_id in context_scores
            ]
            return sorted(scored, key=lambda item: (-item[1], item[0]))

    def has_observations(self) -> bool:
        """Return whether embedding/fit work can affect a ranking."""
        with self._lock:
            return bool(self._responses)

    def retain_agents(self, agent_ids: Iterable[str]) -> None:
        """Discard observations from deployment candidates that are no longer active."""
        allowed = set(agent_ids)
        with self._lock:
            responses = {
                key: value for key, value in self._responses.items() if key[0] in allowed
            }
            if len(responses) == len(self._responses):
                return
            self._responses = responses
            retained_contexts = {context_id for _agent_id, context_id, _item in responses}
            self._contexts = OrderedDict(
                (context_id, vector)
                for context_id, vector in self._contexts.items()
                if context_id in retained_contexts
            )
            self._revision += 1

    def records(self) -> list[dict[str, object]]:
        """Return prompt-free observations suitable for durable state storage."""
        with self._lock:
            grouped: dict[tuple[str, str], list[int]] = {}
            for (agent_id, context_id, item_index), value in self._responses.items():
                row = grouped.setdefault((agent_id, context_id), [])
                while len(row) <= item_index:
                    row.append(0)
                row[item_index] = value
            return [
                {
                    "context_id": context_id,
                    "agent_id": agent_id,
                    "accepted": bool(row[0]),
                    "irt_row": row[1:],
                    "vector": self._contexts.get(context_id),
                }
                for (agent_id, context_id), row in grouped.items()
            ]

    def _fit_locked(self) -> None:
        """Refresh the Rust-backed fit once per observation revision, fail closed."""
        if self._fit_revision == self._revision:
            return
        self._fit_revision = self._revision
        self._scores = {}
        try:
            import numpy as np
            from fast_mlsirm import FitConfig, fit, fit_irt_experiment, predict_proba

            agent_ids = sorted({agent_id for agent_id, _context_id, _item in self._responses})
            context_ids = list(self._contexts)
            context_positions = {context_id: index for index, context_id in enumerate(context_ids)}
            item_keys = sorted(
                {(context_id, item_index) for _agent, context_id, item_index in self._responses},
                key=lambda item: (context_positions[item[0]], item[1]),
            )
            matrix = np.full((len(agent_ids), len(item_keys)), np.nan, dtype=float)
            for row, agent_id in enumerate(agent_ids):
                for column, (context_id, item_index) in enumerate(item_keys):
                    value = self._responses.get((agent_id, context_id, item_index))
                    if value is not None:
                        matrix[row, column] = value
            factor_id = np.zeros(len(item_keys), dtype=int)
            result = fit_irt_experiment(
                fit,
                matrix,
                "dichotomous",
                factor_ids=factor_id,
                factor_id=factor_id,
                config=FitConfig(model="MLSRM"),
            )
            if result.convergence_status != "converged":
                return
            probabilities = predict_proba(result.params, factor_id, model=result.model)
            self._scores = {}
            for column, (context_id, item_index) in enumerate(item_keys):
                # Item zero is the judge's calibrated accepted decision. The
                # criterion items inform the joint fit but are not averaged
                # with an invented application-level weight.
                if item_index != 0:
                    continue
                self._scores[context_id] = {
                    agent_id: float(probabilities[row, column])
                    for row, agent_id in enumerate(agent_ids)
                }
        except (ImportError, RuntimeError, TypeError, ValueError):
            # Missing package, insufficient IRT evidence, or failed native fit
            # means "no psychometric evidence", never a fabricated rank.
            return

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float | None:
        """Cosine similarity for two finite, equal-length embedding vectors."""
        if (
            not left
            or len(left) != len(right)
            or not all(math.isfinite(value) for value in left)
            or not all(math.isfinite(value) for value in right)
        ):
            return None
        left_norm = math.hypot(*left)
        right_norm = math.hypot(*right)
        if left_norm == 0.0 or right_norm == 0.0:
            return None
        similarity = math.fsum(
            (left_value / left_norm) * (right_value / right_norm)
            for left_value, right_value in zip(left, right)
        )
        if not math.isfinite(similarity):
            return None
        return max(-1.0, min(1.0, similarity))
