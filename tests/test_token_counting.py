"""Token-counting seam: heuristic estimator, pg_tiktoken adapter, and factory.

Runs entirely on the dependency-free heuristic path plus a fake pg_tiktoken
counter — no Postgres or ``pg_llm_batch`` install required.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.token_counting import (  # noqa: E402
    HeuristicTokenCounter,
    PgTiktokenAdapter,
    build_token_counter,
)


def test_heuristic_counts_words_with_bpe_expansion() -> None:
    counter = HeuristicTokenCounter()
    # two word units * 1.3 -> ceil(2.6) == 3
    assert counter.count_text("hello world") == 3


def test_heuristic_empty_text_is_zero() -> None:
    assert HeuristicTokenCounter().count_text("") == 0


def test_heuristic_whitespace_only_text_is_zero() -> None:
    # non-empty but yields no word/punctuation units -> the units-empty guard
    assert HeuristicTokenCounter().count_text("   \t\n  ") == 0


def test_heuristic_count_messages_adds_per_message_framing() -> None:
    counter = HeuristicTokenCounter()
    # one dict message with content plus a non-dict entry (content -> "")
    messages = [{"role": "user", "content": "hi there"}, "not_a_dict"]
    # "hi there" -> ceil(2*1.3)=3, +3 framing; non-dict -> 0 content +3 framing
    assert counter.count_messages(messages) == 3 + 3 + 3


class _FakePgTokenCounter:
    """Stand-in for ``pg_llm_batch.TokenCounter`` (pg_tiktoken in Postgres)."""

    def count_tokens(self, text: str, model: str) -> int:
        """Return a deterministic whitespace-split count for the fake."""
        return len(text.split())


def test_pg_adapter_count_text_delegates_to_backend() -> None:
    adapter = PgTiktokenAdapter(_FakePgTokenCounter())
    assert adapter.count_text("one two three", "gpt_example") == 3


def test_pg_adapter_count_messages_sums_contents() -> None:
    adapter = PgTiktokenAdapter(_FakePgTokenCounter())
    messages = [{"content": "one two"}, {"content": "three"}, 42]
    # "one two" -> 2, "three" -> 1, non-dict -> "" -> 0
    assert adapter.count_messages(messages) == 3


def test_build_token_counter_without_dsn_is_heuristic() -> None:
    assert isinstance(build_token_counter(), HeuristicTokenCounter)
