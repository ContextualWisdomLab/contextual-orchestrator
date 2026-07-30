"""Token-counting seam: heuristic estimator edge cases, the pg_tiktoken adapter,
and the ``build_token_counter`` selector.

Dependency-free — a small fake stands in for ``pg_llm_batch.TokenCounter`` so the
adapter delegation is exercised without Postgres/pg_tiktoken (the real
pg_llm_batch import path stays ``# pragma: no cover``). These pin the cost hub's
token accounting: the heuristic is deterministic (tests can assert on it), and
the selector never reads the environment.
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


def test_heuristic_empty_and_whitespace_only_are_zero() -> None:
    """Empty text, and text with no word units (whitespace only), count as 0."""
    counter = HeuristicTokenCounter()
    assert counter.count_text("") == 0
    assert counter.count_text("   \t\n ") == 0  # no \w or punctuation units


def test_heuristic_counts_words_and_punctuation_monotonically() -> None:
    """Counting is >=1 for non-empty content and grows with more units."""
    counter = HeuristicTokenCounter()
    one = counter.count_text("hello")
    more = counter.count_text("hello, world!")
    assert one >= 1
    assert more > one


class _FakePgCounter:
    """Stand-in for ``pg_llm_batch.TokenCounter`` — records calls, returns a fixed count."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def count_tokens(self, text: str, model: str) -> int:
        self.calls.append((text, model))
        return 7


def test_pg_adapter_count_text_delegates() -> None:
    """``PgTiktokenAdapter.count_text`` forwards to the backing pg counter."""
    fake = _FakePgCounter()
    adapter = PgTiktokenAdapter(fake)
    assert adapter.count_text("hello", "gpt-x") == 7
    assert fake.calls == [("hello", "gpt-x")]


def test_pg_adapter_count_messages_sums_per_message() -> None:
    """``PgTiktokenAdapter.count_messages`` sums per-message counts (non-dict → empty)."""
    fake = _FakePgCounter()
    adapter = PgTiktokenAdapter(fake)
    total = adapter.count_messages([{"content": "a"}, {"content": "b"}, "not-a-dict"], "m")
    assert total == 21  # 3 messages * fixed 7
    assert fake.calls == [("a", "m"), ("b", "m"), ("", "m")]


def test_build_token_counter_without_dsn_is_heuristic() -> None:
    """With no DSN, the dependency-free heuristic counter is selected."""
    assert isinstance(build_token_counter(), HeuristicTokenCounter)
    assert isinstance(build_token_counter(postgres_dsn=None), HeuristicTokenCounter)
