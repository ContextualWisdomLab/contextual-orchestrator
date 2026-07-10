"""Token counting seam for usage/cost accounting.

The cost ledger needs prompt/completion token counts on every completion. Two
strategies are provided behind one :class:`TokenCounter`-compatible surface:

* :class:`HeuristicTokenCounter` — a dependency-free estimator (the default).
  It approximates BPE token counts from whitespace/word structure so standalone
  runs and tests get stable, deterministic numbers without Postgres.
* :class:`PgTiktokenAdapter` — delegates to ``pg_llm_batch.TokenCounter``
  (``pg_tiktoken`` running *inside* Postgres) when a DSN + the package are
  available, so counts match exactly what the batch engine bills against.

Selection is centralised in :func:`build_token_counter`, which never reads the
environment: the DSN is passed in by the caller.
"""

from __future__ import annotations

import math
import re
from typing import Any, List, Optional, Protocol

_WORD_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)

# Rough BPE expansion: sub-word models emit slightly more tokens than words.
_TOKENS_PER_WORD = 1.3


class TokenCountingStrategy(Protocol):
    """Contract for anything that can count tokens for a chunk of text."""

    def count_text(self, text: str, model: str) -> int:
        """Return the token count for ``text`` under ``model``."""
        ...


class HeuristicTokenCounter:
    """Deterministic, dependency-free token estimator.

    Counts word-ish units (words and standalone punctuation) and applies a
    fixed BPE expansion factor. Not exact, but stable and monotonic — good
    enough for cost attribution when ``pg_tiktoken`` is not reachable, and it
    never varies between runs so tests can assert on it.
    """

    def __init__(self, tokens_per_word: float = _TOKENS_PER_WORD) -> None:
        self.tokens_per_word = tokens_per_word

    def count_text(self, text: str, model: str = "") -> int:
        """Estimate the number of tokens in ``text``."""
        if not text:
            return 0
        units = _WORD_RE.findall(text)
        if not units:
            return 0
        return max(1, math.ceil(len(units) * self.tokens_per_word))

    def count_messages(self, messages: List[dict], model: str = "") -> int:
        """Estimate prompt tokens across a list of chat messages."""
        total = 0
        for message in messages:
            content = message.get("content", "") if isinstance(message, dict) else ""
            total += self.count_text(str(content), model)
            # Per-message framing overhead (role tags, delimiters).
            total += 3
        return total


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


def build_token_counter(
    postgres_dsn: Optional[str] = None,
    *,
    config: Any = None,
) -> HeuristicTokenCounter | PgTiktokenAdapter:
    """Return the best available token counter.

    Prefers ``pg_tiktoken`` (via ``pg_llm_batch``) when a DSN is supplied and the
    dependency is importable; otherwise returns the heuristic estimator. Never
    reads the environment.
    """
    if postgres_dsn:
        try:  # pragma: no cover - needs Postgres + pg_tiktoken extension
            from pg_llm_batch import TokenCounter as PgTokenCounter  # type: ignore

            return PgTiktokenAdapter(PgTokenCounter(postgres_dsn, config=config))
        except Exception:  # pragma: no cover - degrade to heuristic
            return HeuristicTokenCounter()
    return HeuristicTokenCounter()
