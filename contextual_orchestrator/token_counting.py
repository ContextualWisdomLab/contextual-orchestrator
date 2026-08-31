"""Token counting seam for usage/cost accounting.

The cost ledger needs prompt/completion token counts on every completion.
Strategies are provided behind one :class:`TokenCounter`-compatible surface:

* :class:`HeuristicTokenCounter` — a dependency-free estimator (the default).
  It approximates BPE token counts from whitespace/word structure so standalone
  runs and tests get stable, deterministic numbers without Postgres.
* :class:`PgTiktokenAdapter` — delegates to ``pg_llm_batch.TokenCounter``
  (``pg_tiktoken`` running *inside* Postgres) when a DSN + the package are
  available, so counts match exactly what the batch engine bills against.
* :class:`NativeCl100kTokenCounter` — delegates declared cl100k embedding
  models to the packaged Rust extension and reports all other cases as
  unavailable.

Legacy chat selection remains in :func:`build_token_counter`. Embedding
selection is isolated in :func:`build_embedding_token_counter` and never
returns a heuristic. Neither factory reads the environment: the DSN is passed
in by the caller.
"""

from __future__ import annotations

import importlib
import math
import re
from typing import Any, List, Optional, Protocol

_WORD_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)

# Rough BPE expansion: sub-word models emit slightly more tokens than words.
_TOKENS_PER_WORD = 1.3

# OpenAI's published tiktoken mapping assigns these embedding deployments to
# cl100k_base. Other model identifiers remain unavailable because a tokenizer
# must never be guessed from a provider/model name.
_CL100K_EMBEDDING_MODELS = frozenset(
    {
        "text-embedding-ada-002",
        "text-embedding-3-small",
        "text-embedding-3-large",
    }
)


class TokenCountingStrategy(Protocol):
    """Contract for anything that can count tokens for a chunk of text."""

    def count_text(self, text: str, model: str) -> int:
        """Return the token count for ``text`` under ``model``."""
        ...


class TokenCountUnavailable(RuntimeError):
    """An authoritative tokenizer is unavailable for the requested model."""


class HeuristicTokenCounter:
    """Deterministic, dependency-free token estimator.

    Counts word-ish units (words and standalone punctuation) and applies a
    fixed BPE expansion factor. Not exact, but stable and monotonic — good
    enough for legacy best-effort chat attribution when ``pg_tiktoken`` is not
    reachable, and it never varies between runs so tests can assert on it. It
    is not authoritative and must not be used for embedding limits or cost.
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


class NativeCl100kTokenCounter:
    """Use the bundled Rust cl100k counter only for explicitly mapped models."""

    def __init__(self, native_module: Any) -> None:
        self._native_module = native_module

    def count_text(self, text: str, model: str = "") -> int:
        """Count a declared cl100k embedding model or fail closed."""
        if model not in _CL100K_EMBEDDING_MODELS:
            raise TokenCountUnavailable(f"no authoritative tokenizer is declared for {model!r}")
        try:
            return int(self._native_module.count_cl100k(text))
        except Exception as exc:  # noqa: BLE001 - optional native boundary.
            raise TokenCountUnavailable("the native cl100k tokenizer is unavailable") from exc

    def count_messages(self, messages: List[dict], model: str = "") -> int:
        """Reject chat counting because this counter is embedding-only."""
        raise TokenCountUnavailable("the native cl100k counter does not count chat framing")

    def pack_text(self, text: str, model: str, max_tokens: int) -> List[tuple[str, int]]:
        """Split one declared cl100k input at exact native token boundaries."""
        if model not in _CL100K_EMBEDDING_MODELS:
            raise TokenCountUnavailable(f"no authoritative tokenizer is declared for {model!r}")
        try:
            parts, _shards = self._native_module.pack_cl100k(
                [text], max_tokens, 1, max_tokens
            )
            return [(part.text, int(part.token_count)) for part in parts]
        except Exception as exc:  # noqa: BLE001 - optional native boundary.
            raise TokenCountUnavailable("the native cl100k packer is unavailable") from exc


class UnavailableEmbeddingTokenCounter:
    """Represent the absence of an authoritative embedding tokenizer."""

    def count_text(self, text: str, model: str = "") -> int:
        """Fail closed instead of fabricating an embedding token count."""
        raise TokenCountUnavailable(f"no authoritative tokenizer is available for {model!r}")


def _native_token_counter() -> NativeCl100kTokenCounter | None:
    """Load the optional in-package extension without making startup depend on it."""
    try:
        module = importlib.import_module("contextual_orchestrator._token_packer")
    except Exception:  # noqa: BLE001 - an incompatible wheel is equivalent to absence.
        return None
    if not all(
        callable(getattr(module, name, None))
        for name in ("count_cl100k", "pack_cl100k")
    ):
        return None
    return NativeCl100kTokenCounter(module)


def build_embedding_token_counter(
    postgres_dsn: Optional[str] = None,
    *,
    config: Any = None,
) -> PgTiktokenAdapter | NativeCl100kTokenCounter | UnavailableEmbeddingTokenCounter:
    """Return an authoritative embedding counter or an explicit unavailable seam.

    PostgreSQL remains authoritative when explicitly configured. The bundled
    Rust counter is the fallback only for model identifiers whose published
    tokenizer mapping is cl100k. No heuristic estimate is returned here.
    """
    if postgres_dsn:
        try:  # pragma: no cover - needs Postgres + pg_tiktoken extension
            from pg_llm_batch import TokenCounter as PgTokenCounter  # type: ignore

            return PgTiktokenAdapter(PgTokenCounter(postgres_dsn, config=config))
        except Exception:  # pragma: no cover - optional authoritative boundary
            pass
    return _native_token_counter() or UnavailableEmbeddingTokenCounter()


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
