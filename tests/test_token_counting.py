"""Token-counting seam: heuristic estimator, pg_tiktoken adapter, and factory.

Runs entirely on the dependency-free heuristic path plus a fake pg_tiktoken
counter that records its calls — no Postgres or ``pg_llm_batch`` install.
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
    """Two word units expand to ceil(2 * 1.3) == 3 tokens."""
    assert HeuristicTokenCounter().count_text("hello world") == 3


def test_heuristic_empty_text_is_zero() -> None:
    """Empty text counts as zero tokens."""
    assert HeuristicTokenCounter().count_text("") == 0


def test_heuristic_whitespace_only_text_is_zero() -> None:
    """Non-empty text with no word/punctuation units counts as zero tokens."""
    assert HeuristicTokenCounter().count_text("   \t\n  ") == 0


def test_heuristic_count_messages_adds_per_message_framing() -> None:
    """Each message contributes its content tokens plus fixed framing overhead."""
    counter = HeuristicTokenCounter()
    # "hi there" -> ceil(2*1.3)=3, +3 framing; non-dict -> 0 content +3 framing
    messages = [{"role": "user", "content": "hi there"}, "not_a_dict"]
    assert counter.count_messages(messages) == 3 + 3 + 3


class _FakePgTokenCounter:
    """Stand-in for pg_llm_batch.TokenCounter; records each call for assertions."""

    def __init__(self) -> None:
        """Start with an empty call log."""
        self.calls: list[tuple[str, str]] = []

    def count_tokens(self, text: str, model: str) -> int:
        """Record (text, model) and return a deterministic whitespace-split count."""
        self.calls.append((text, model))
        return len(text.split())


def test_pg_adapter_count_text_delegates_text_and_model() -> None:
    """count_text forwards both the text and the model to the backend."""
    backend = _FakePgTokenCounter()
    adapter = PgTiktokenAdapter(backend)
    assert adapter.count_text("one two three", "gpt_example") == 3
    assert backend.calls == [("one two three", "gpt_example")]


def test_pg_adapter_count_messages_forwards_content_and_model() -> None:
    """count_messages forwards each message's content and the model per call."""
    backend = _FakePgTokenCounter()
    adapter = PgTiktokenAdapter(backend)
    messages = [{"content": "one two"}, {"content": "three"}, 42]
    assert adapter.count_messages(messages, "gpt_example") == 3
    assert backend.calls == [
        ("one two", "gpt_example"),
        ("three", "gpt_example"),
        ("", "gpt_example"),
    ]


def test_build_token_counter_without_dsn_is_heuristic() -> None:
    """With no DSN the factory returns the dependency-free heuristic counter."""
    assert isinstance(build_token_counter(), HeuristicTokenCounter)
