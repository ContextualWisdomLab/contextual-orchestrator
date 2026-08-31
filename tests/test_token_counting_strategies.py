"""Behavioral coverage for deterministic and PostgreSQL token counters."""

from __future__ import annotations

import sys
import types
from typing import Any

from contextual_orchestrator.token_counting import (
    HeuristicTokenCounter,
    PgTiktokenAdapter,
    build_token_counter,
)


class _PgCounter:
    """Small pg_llm_batch-compatible counter with constructor evidence."""

    def __init__(self, postgres_dsn: str, *, config: Any = None) -> None:
        self.postgres_dsn = postgres_dsn
        self.config = config
        self.calls: list[tuple[str, str]] = []

    def count_tokens(self, text: str, model: str) -> str:
        """Return a string count so the adapter's integer normalization is exercised."""
        self.calls.append((text, model))
        return str(len(text))


def test_heuristic_counter_handles_empty_text_punctuation_and_calibration() -> None:
    """Keep dependency-free estimates deterministic across realistic text shapes."""
    default_counter = HeuristicTokenCounter()
    calibrated_counter = HeuristicTokenCounter(tokens_per_word=0.5)

    assert default_counter.count_text("") == 0
    assert default_counter.count_text(" \t\n") == 0
    assert default_counter.count_text("hello, world", model="ignored-model") == 4
    assert calibrated_counter.count_text("hello, world") == 2


def test_heuristic_message_count_includes_framing_for_every_input_item() -> None:
    """Count message content plus framing even when a caller supplies a non-mapping item."""
    counter = HeuristicTokenCounter(tokens_per_word=1.0)

    assert counter.count_messages(
        [
            {"role": "user", "content": "hello world"},
            {"role": "assistant"},
            "malformed-message",
        ],
        model="ignored-model",
    ) == 11


def test_postgres_adapter_delegates_text_and_message_counts() -> None:
    """Preserve exact database counts without adding heuristic framing overhead."""
    pg_counter = _PgCounter("postgresql://example/tokens")
    adapter = PgTiktokenAdapter(pg_counter)

    assert adapter.count_text("four", model="gpt-example") == 4
    assert adapter.count_messages(
        [{"content": "abc"}, {"content": "de"}, "malformed-message"],
        model="gpt-example",
    ) == 5
    assert pg_counter.calls == [
        ("four", "gpt-example"),
        ("abc", "gpt-example"),
        ("de", "gpt-example"),
        ("", "gpt-example"),
    ]


def test_counter_factory_uses_heuristic_without_a_database() -> None:
    """Keep standalone execution dependency-free when no DSN is requested."""
    assert isinstance(build_token_counter(), HeuristicTokenCounter)


def test_counter_factory_builds_postgres_adapter_with_explicit_config(monkeypatch) -> None:
    """Pass the caller DSN and tokenizer configuration to pg_llm_batch."""
    module = types.ModuleType("pg_llm_batch")
    module.TokenCounter = _PgCounter
    monkeypatch.setitem(sys.modules, "pg_llm_batch", module)
    config = {"encoding_name": "cl100k_base"}

    counter = build_token_counter("postgresql://example/tokens", config=config)

    assert isinstance(counter, PgTiktokenAdapter)
    assert counter._counter.postgres_dsn == "postgresql://example/tokens"
    assert counter._counter.config is config


def test_counter_factory_falls_back_when_postgres_counter_cannot_start(monkeypatch) -> None:
    """Retain deterministic counting when the optional database boundary is unavailable."""
    class _UnavailableCounter:
        def __init__(self, _postgres_dsn: str, *, config: Any = None) -> None:
            raise ConnectionError("database unavailable")

    module = types.ModuleType("pg_llm_batch")
    module.TokenCounter = _UnavailableCounter
    monkeypatch.setitem(sys.modules, "pg_llm_batch", module)

    assert isinstance(
        build_token_counter("postgresql://example/tokens"),
        HeuristicTokenCounter,
    )
