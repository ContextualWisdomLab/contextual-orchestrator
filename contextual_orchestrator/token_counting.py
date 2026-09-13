"""Authoritative raw-text token counting for accounting boundaries.

Provider-reported chat usage is authoritative. Local counters handle raw text
only; they never reconstruct provider chat framing, tool schemas, or
multimodal serialization. Exact full model identifiers select the packaged
Rust tokenizer. Unknown identifiers and missing native code are explicitly
unavailable rather than estimated.
"""

from __future__ import annotations

import re

import importlib
import operator
from typing import Any, Optional, Protocol

_CL100K_EMBEDDING_MODELS = frozenset(
    {
        "text-embedding-ada-002",
        "text-embedding-3-small",
        "text-embedding-3-large",
    }
)
_CL100K_MODELS = _CL100K_EMBEDDING_MODELS | frozenset(
    {
        "gpt-4",
        "gpt-3.5-turbo",
        "gpt-3.5",
        "gpt-35-turbo",
        "davinci-002",
        "babbage-002",
    }
)
_O200K_MODELS = frozenset({"o1", "o3", "o4-mini", "gpt-5", "gpt-4.1", "gpt-4o"})


class TokenCountingStrategy(Protocol):
    """Contract for an authoritative raw-text token counter."""

    def count_text(self, text: str, model: str) -> int:
        """Return the exact token count for ``text`` under ``model``."""
        ...


class TokenCountUnavailable(RuntimeError):
    """An authoritative tokenizer or provider count is unavailable."""


def _validated_count(value: Any) -> int:
    """Normalize a tokenizer count and reject invalid numeric evidence."""
    if isinstance(value, bool):
        raise TokenCountUnavailable("the tokenizer returned an invalid count")
    try:
        count = operator.index(value)
    except TypeError as exc:
        raise TokenCountUnavailable("the tokenizer returned an invalid count") from exc
    if count < 0:
        raise TokenCountUnavailable("the tokenizer returned an invalid count")
    return count


class PgTiktokenAdapter:
    """Adapter delegating raw-text counts to ``pg_llm_batch.TokenCounter``."""

    def __init__(self, pg_counter: Any) -> None:
        self._counter = pg_counter

    def count_text(self, text: str, model: str = "") -> int:
        """Count raw text through the configured PostgreSQL tokenizer."""
        try:
            return _validated_count(self._counter.count_tokens(text, model))
        except TokenCountUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - external tokenizer boundary.
            raise TokenCountUnavailable("the PostgreSQL tokenizer is unavailable") from exc

    def count_messages(self, messages: list[dict], model: str = "") -> int:
        """Reject chat prompts whose provider framing is unreconstructible."""
        raise TokenCountUnavailable("provider chat framing is unavailable")


class NativeExactTokenCounter:
    """Dispatch exact raw-text counts for explicitly mapped model identifiers."""

    def __init__(self, native_module: Any) -> None:
        self._native_module = native_module

    def count_text(self, text: str, model: str = "") -> int:
        """Count raw text for a declared model or fail closed."""
        if model in _CL100K_MODELS:
            function_name = "count_cl100k"
        elif model in _O200K_MODELS:
            function_name = "count_o200k"
        else:
            raise TokenCountUnavailable(
                f"no authoritative tokenizer is declared for {model!r}"
            )
        try:
            function = getattr(self._native_module, function_name)
            return _validated_count(function(text))
        except Exception as exc:  # noqa: BLE001 - optional native boundary.
            raise TokenCountUnavailable("the native tokenizer is unavailable") from exc

    def count_messages(self, messages: list[dict], model: str = "") -> int:
        """Reject chat prompts whose framing/tools cannot be counted as raw text."""
        raise TokenCountUnavailable("provider chat framing is unavailable")

    def pack_text(self, text: str, model: str, max_tokens: int) -> list[tuple[str, int]]:
        """Split one declared cl100k input at exact native token boundaries."""
        if model not in _CL100K_EMBEDDING_MODELS:
            raise TokenCountUnavailable(f"no authoritative tokenizer is declared for {model!r}")
        try:
            parts, _shards = self._native_module.pack_cl100k(
                [text], max_tokens, 1, max_tokens
            )
            return [(part.text, _validated_count(part.token_count)) for part in parts]
        except Exception as exc:  # noqa: BLE001 - optional native boundary.
            raise TokenCountUnavailable("the native cl100k packer is unavailable") from exc


# Compatibility name retained for embedding callers; behavior remains exact.
NativeCl100kTokenCounter = NativeExactTokenCounter


class UnavailableTokenCounter:
    """Represent absence of an authoritative tokenizer."""

    def count_text(self, text: str, model: str = "") -> int:
        """Fail closed instead of fabricating a raw-text token count."""
        raise TokenCountUnavailable(f"no authoritative tokenizer is available for {model!r}")

    def count_messages(self, messages: list[dict], model: str = "") -> int:
        """Fail closed instead of fabricating a chat prompt count."""
        raise TokenCountUnavailable("provider chat framing is unavailable")


UnavailableEmbeddingTokenCounter = UnavailableTokenCounter


def _native_token_counter() -> NativeExactTokenCounter | None:
    """Load the optional extension without making startup depend on it."""
    try:
        module = importlib.import_module("contextual_orchestrator._token_packer")
    except Exception:  # noqa: BLE001 - incompatible wheel equals absence.
        return None
    functions = ("count_cl100k", "count_o200k", "pack_cl100k")
    if not all(callable(getattr(module, name, None)) for name in functions):
        return None
    return NativeExactTokenCounter(module)


def _build_counter(postgres_dsn: Optional[str], config: Any) -> Any:
    """Build the configured authoritative counter or unavailable seam."""
    if postgres_dsn:
        try:  # pragma: no cover - needs Postgres + pg_tiktoken extension
            from pg_llm_batch import TokenCounter as PgTokenCounter  # type: ignore

            return PgTiktokenAdapter(PgTokenCounter(postgres_dsn, config=config))
        except Exception:  # pragma: no cover - optional authoritative boundary
            pass
    return _native_token_counter() or UnavailableTokenCounter()


def build_embedding_token_counter(
    postgres_dsn: Optional[str] = None,
    *,
    config: Any = None,
) -> PgTiktokenAdapter | NativeExactTokenCounter | UnavailableTokenCounter:
    """Return an authoritative embedding counter or explicit unavailable seam."""
    return _build_counter(postgres_dsn, config)


def build_token_counter(
    postgres_dsn: Optional[str] = None,
    *,
    config: Any = None,
) -> PgTiktokenAdapter | NativeExactTokenCounter | UnavailableTokenCounter:
    """Return an authoritative raw-text counter or explicit unavailable seam."""
    return _build_counter(postgres_dsn, config)


# Conservative divisor for the character-based token lower bound. Chosen well
# above the ~4 characters/token average documented for the BPE tokenizers this
# module maps exactly (cl100k/o200k) on English prose, so that
# ``len(text) // _LOWER_BOUND_CHARS_PER_TOKEN`` stays at or below the true
# token count even for highly compressible/repetitive text, whose realized
# ratio can climb toward the high single digits as long common substrings
# collapse into single vocabulary entries. Denser scripts (CJK, code, heavy
# punctuation) tokenize at a much lower ratio in practice (often 1-3
# characters/token), so the same divisor undercounts them by an even wider
# margin -- always safe as a lower bound, just looser. This is a documented
# engineering approximation, not a formal proof against adversarial input;
# callers must always attribute it via the ``"estimate_lower_bound"`` source
# label rather than presenting it as a measured count.
_LOWER_BOUND_CHARS_PER_TOKEN = 7


_REPEATED_CHARACTER_RUN = re.compile(r"(.)\1{2,}", re.DOTALL)


def estimate_lower_bound_tokens(text: str) -> int:
    """Conservative, non-overestimating token-count lower bound for raw text.

    Intended only for callers that have already tried and failed to obtain an
    authoritative count (see :func:`prompt_token_lower_bound`). Character-count
    based: ``len(text) // _LOWER_BOUND_CHARS_PER_TOKEN``; see that module
    constant's comment for why the divisor is deliberately conservative
    (biased toward under-counting) rather than tuned for typical-case
    accuracy.
    """
    if not text:
        return 0
    # Runs of one repeated character (indentation spaces, "-----" rules,
    # "=====" banners) tokenize into a handful of multi-character tokens, so a
    # raw character count would *over*estimate them and break the lower-bound
    # guarantee. Collapse every run to at most two characters before dividing;
    # for ordinary prose and code this changes little, for run-heavy text it
    # only makes the bound looser, never larger than the true count.
    collapsed = _REPEATED_CHARACTER_RUN.sub(lambda m: m.group(1) * 2, text)
    return len(collapsed) // _LOWER_BOUND_CHARS_PER_TOKEN


def prompt_token_lower_bound(text: str, model: str, token_counter: Any) -> tuple[int, str]:
    """Return a conservative prompt-token lower bound and its evidence source.

    Tries ``token_counter.count_text`` first: when a native tokenizer is
    mapped for ``model``, its exact count is returned labelled ``"exact"`` (an
    exact count is trivially also a valid lower bound). When no authoritative
    tokenizer is available for ``model`` (:class:`TokenCountUnavailable`),
    falls back to :func:`estimate_lower_bound_tokens`, labelled
    ``"estimate_lower_bound"`` -- mirroring how ``usage_source`` /
    ``measurement_status`` are labelled elsewhere in this codebase, so a
    caller never mistakes a heuristic for a measured count.
    """
    try:
        return token_counter.count_text(text, model), "exact"
    except TokenCountUnavailable:
        return estimate_lower_bound_tokens(text), "estimate_lower_bound"
