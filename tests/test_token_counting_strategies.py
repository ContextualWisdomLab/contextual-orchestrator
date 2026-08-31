"""Behavioral coverage for deterministic and PostgreSQL token counters."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from contextual_orchestrator.token_counting import (
    HeuristicTokenCounter,
    NativeCl100kTokenCounter,
    PgTiktokenAdapter,
    TokenCountUnavailable,
    UnavailableEmbeddingTokenCounter,
    build_embedding_token_counter,
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


def test_counter_factory_uses_native_cl100k_only_for_declared_embedding_models(
    monkeypatch,
) -> None:
    """The installed wheel is a real runtime path without guessing tokenizers."""
    calls: list[str] = []
    packed = types.SimpleNamespace(text="hello world", token_count=2)
    module = types.SimpleNamespace(
        count_cl100k=lambda text: calls.append(text) or 2,
        pack_cl100k=lambda texts, per_input, inputs, total: (
            [packed],
            [[0]],
        ),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.token_counting.importlib.import_module",
        lambda _name: module,
    )

    counter = build_embedding_token_counter()

    assert isinstance(counter, NativeCl100kTokenCounter)
    assert counter.count_text("hello world", "text-embedding-3-small") == 2
    assert counter.pack_text("hello world", "text-embedding-3-small", 8192) == [
        ("hello world", 2)
    ]
    assert calls == ["hello world"]
    with pytest.raises(TokenCountUnavailable, match="no authoritative tokenizer"):
        counter.count_text("hello world", "provider-unknown")
    assert calls == ["hello world"]


def test_native_counter_reports_unavailable_when_extension_call_fails(monkeypatch) -> None:
    """One native failure must not fabricate embedding usage."""

    def fail(_text: str) -> int:
        raise RuntimeError("synthetic native failure")

    monkeypatch.setattr(
        "contextual_orchestrator.token_counting.importlib.import_module",
        lambda _name: types.SimpleNamespace(count_cl100k=fail, pack_cl100k=fail),
    )

    counter = build_embedding_token_counter()

    assert isinstance(counter, NativeCl100kTokenCounter)
    with pytest.raises(TokenCountUnavailable, match="native cl100k"):
        counter.count_text("hello world", "text-embedding-3-large")


def test_installed_native_counter_matches_cl100k_reference_count() -> None:
    """An installed wheel preserves the Rust cl100k parity boundary."""
    module = pytest.importorskip("contextual_orchestrator._token_packer")
    counter = NativeCl100kTokenCounter(module)

    assert counter.count_text("hello world", "text-embedding-3-small") == 2


def test_embedding_counter_without_authoritative_backend_is_unavailable(monkeypatch) -> None:
    """Missing optional native code is an explicit unavailable result."""
    monkeypatch.setattr(
        "contextual_orchestrator.token_counting.importlib.import_module",
        lambda _name: (_ for _ in ()).throw(ImportError("synthetic missing wheel")),
    )

    counter = build_embedding_token_counter()

    assert isinstance(counter, UnavailableEmbeddingTokenCounter)
    with pytest.raises(TokenCountUnavailable, match="no authoritative tokenizer"):
        counter.count_text("hello world", "text-embedding-3-small")


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


def test_embedding_counter_prefers_postgres_over_native(monkeypatch) -> None:
    """An explicitly configured authoritative PostgreSQL tokenizer stays first."""
    module = types.ModuleType("pg_llm_batch")
    module.TokenCounter = _PgCounter
    monkeypatch.setitem(sys.modules, "pg_llm_batch", module)
    monkeypatch.setattr(
        "contextual_orchestrator.token_counting.importlib.import_module",
        lambda _name: pytest.fail("native fallback must not load when PostgreSQL starts"),
    )

    counter = build_embedding_token_counter("postgresql://example/tokens")

    assert isinstance(counter, PgTiktokenAdapter)
    assert counter.count_text("four", "provider-specific") == 4
