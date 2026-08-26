"""Token counting seam for usage/cost accounting.

The cost ledger needs prompt/completion token counts on every completion. Two
strategies are provided behind one :class:`TokenCounter`-compatible surface:

* :class:`RustCl100kTokenCounter` — the exact local cl100k authority.
* :class:`PgTiktokenAdapter` — delegates to ``pg_llm_batch.TokenCounter``
  (``pg_tiktoken`` running *inside* Postgres) when a DSN + the package are
  available, so counts match exactly what the batch engine bills against.

Selection is centralised in :func:`build_token_counter`, which never reads the
environment: the DSN is passed in by the caller.
"""

from __future__ import annotations

from typing import Any, List, Optional, Protocol


class TokenCountingStrategy(Protocol):
    """Contract for anything that can count tokens for a chunk of text."""

    def count_text(self, text: str, model: str) -> int:
        """Return the token count for ``text`` under ``model``."""
        ...


class RustCl100kTokenCounter:
    """Exact local cl100k counter backed by the Rust extension."""

    def __init__(self, tokens_per_word: float | None = None) -> None:
        if tokens_per_word is not None:
            raise ValueError("tokens_per_word heuristics are not supported")
        self._rust = RustCl100kPacker()

    def count_text(self, text: str, model: str = "") -> int:
        """Return the exact cl100k token count for ``text``."""
        return self._rust.count_text(text)

    def count_messages(self, messages: List[dict], model: str = "") -> int:
        """Count message content exactly without invented framing constants."""
        total = 0
        for message in messages:
            content = message.get("content", "") if isinstance(message, dict) else ""
            total += self.count_text(str(content), model)
        return total


# Import compatibility only; the implementation is exact and accepts no
# multiplier. New production code uses ``RustCl100kTokenCounter`` directly.
HeuristicTokenCounter = RustCl100kTokenCounter


class PgTiktokenAdapter:
    """Adapter delegating to ``pg_llm_batch.TokenCounter`` (pg_tiktoken)."""

    def __init__(self, pg_counter: Any) -> None:
        self._counter = pg_counter

    def count_text(self, text: str, model: str = "") -> int:
        """Count tokens via the Postgres ``pg_tiktoken`` extension."""
        # pg_llm_batch.TokenCounter exposes count_tokens(text, model).
        return int(self._counter.count_tokens(text, model))

    def count_messages(self, messages: List[dict], model: str = "") -> int:
        """Count prompt tokens across chat messages via pg_tiktoken."""
        total = 0
        for message in messages:
            content = message.get("content", "") if isinstance(message, dict) else ""
            total += self.count_text(str(content), model)
        return total


class RustCl100kPacker:
    """Typed PyO3 boundary for Rust/Rayon cl100k chunking and packing.

    There is intentionally no Python approximation fallback: provider limit
    enforcement must use the exact Rust authority or fail closed.
    """

    def __init__(self) -> None:
        try:
            from contextual_orchestrator._token_packer import (
                pack_cl100k,
                sum_token_counts,
                weighted_average_embeddings,
                count_cl100k,
                cosine_similarity,
                root_mean_square_error,
            )
        except ImportError as exc:
            raise RuntimeError("Rust token packer extension is unavailable") from exc
        self._pack = pack_cl100k
        self._sum_token_counts = sum_token_counts
        self._weighted_average_embeddings = weighted_average_embeddings
        self._count_cl100k = count_cl100k
        self._cosine_similarity = cosine_similarity
        self._root_mean_square_error = root_mean_square_error

    def count_text(self, text: str) -> int:
        """Return the exact cl100k count from Rust."""
        return int(self._count_cl100k(text))

    def cosine_similarity(self, vector_a: List[float], vector_b: List[float]) -> float | None:
        """Return validated cosine similarity from Rust."""
        return self._cosine_similarity(vector_a, vector_b)

    def root_mean_square_error(self, estimates: List[float], truths: List[float]) -> float:
        """Return validated RMSE from Rust."""
        return float(self._root_mean_square_error(estimates, truths))

    def pack_texts(self, texts: List[str], *, max_tokens_per_input: int,
                   max_inputs: int, max_total_tokens: int):
        """Return typed child parts and provider shards from Rust."""
        return self._pack(texts, max_tokens_per_input, max_inputs, max_total_tokens)

    def sum_token_counts(self, values: List[int]) -> int:
        """Return a checked exact token-count sum from the Rust core."""
        return int(self._sum_token_counts(values))

    def weighted_average_embeddings(
        self, parts: List[tuple[List[float], int]]
    ) -> List[float]:
        """Reduce child vectors using exact token weights in the Rust core."""
        return list(self._weighted_average_embeddings(parts))


def build_token_counter(
    postgres_dsn: Optional[str] = None,
    *,
    config: Any = None,
) -> RustCl100kTokenCounter | PgTiktokenAdapter:
    """Return the best available token counter.

    Prefers ``pg_tiktoken`` (via ``pg_llm_batch``) when a DSN is supplied and the
    dependency is importable; otherwise returns the exact Rust counter. Never
    reads the environment.
    """
    if postgres_dsn:
        try:  # pragma: no cover - needs Postgres + pg_tiktoken extension
            from pg_llm_batch import TokenCounter as PgTokenCounter  # type: ignore

            return PgTiktokenAdapter(PgTokenCounter(postgres_dsn, config=config))
        except Exception:  # pragma: no cover - exact local authority remains required
            return RustCl100kTokenCounter()
    return RustCl100kTokenCounter()
