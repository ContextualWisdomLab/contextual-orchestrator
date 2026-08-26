"""Boundary tests for the token counting seam (statement + branch coverage)."""

from __future__ import annotations

import sys
import types

import pytest

from contextual_orchestrator.token_counting import (
    RustCl100kTokenCounter,
    PgTiktokenAdapter,
    RustCl100kPacker,
    build_token_counter,
)


def test_exact_cl100k_packing_fails_closed_without_rust_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "contextual_orchestrator._token_packer", None)
    with pytest.raises(RuntimeError, match="Rust token packer extension is unavailable"):
        RustCl100kPacker()


def test_exact_counter_preserves_whitespace_tokens() -> None:
    counter = RustCl100kTokenCounter()
    assert counter.count_text("") == 0
    assert counter.count_text("   \t\n  ") == 3


def test_exact_counter_counts_punctuation_with_cl100k() -> None:
    assert RustCl100kTokenCounter().count_text("!?...") == 2


def test_exact_counter_rejects_arbitrary_multiplier() -> None:
    with pytest.raises(ValueError, match="heuristics are not supported"):
        RustCl100kTokenCounter(tokens_per_word=1.0)


@pytest.mark.parametrize("bad_message", ["plain string", None, 42])
def test_exact_counter_ignores_non_mapping_message_content(bad_message: object) -> None:
    counter = RustCl100kTokenCounter()
    total = counter.count_messages([{"content": "hello"}, bad_message])  # type: ignore[list-item]
    assert total == 1


class _StubPgCounter:
    """Minimal pg_llm_batch.TokenCounter double recording calls."""

    def __init__(self, dsn: str, config: object = None) -> None:
        self.dsn = dsn
        self.config = config
        self.calls: list[tuple[str, str]] = []

    def count_tokens(self, text: str, model: str) -> float:
        self.calls.append((text, model))
        # Return a float to prove the adapter normalizes to int.
        return 7.9


def _install_stub_pg_module(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    module = types.ModuleType("pg_llm_batch")
    module.TokenCounter = _StubPgCounter  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pg_llm_batch", module)
    return module


def test_build_prefers_pg_tiktoken_when_dsn_and_dependency_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stub_pg_module(monkeypatch)
    config = {"model": "demo_model"}
    counter = build_token_counter("postgresql://ledger_user@localhost/usage_db", config=config)
    assert isinstance(counter, PgTiktokenAdapter)
    # Exact-count delegation returns an int even when the backend yields a float,
    # and forwards both text and model verbatim.
    assert counter.count_text("route me", "mock-generalist") == 7
    stub = getattr(counter, "_counter")
    assert stub.calls == [("route me", "mock-generalist")]
    assert stub.dsn == "postgresql://ledger_user@localhost/usage_db"
    assert stub.config is config


def test_pg_adapter_counts_messages_and_normalizes_non_dicts() -> None:
    stub = _StubPgCounter("postgresql://x")
    adapter = PgTiktokenAdapter(stub)
    total = adapter.count_messages([{"content": "one"}, {"content": "two"}, "junk"])
    # Non-dict messages are normalized to empty-string content and still counted
    # (the exact backend bills framing), so three calls x 7 tokens each.
    assert total == 21
    assert [call[0] for call in stub.calls] == ["one", "two", ""]


def test_build_degrades_to_heuristic_when_pg_dependency_fails_to_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = types.ModuleType("pg_llm_batch")
    monkeypatch.setitem(sys.modules, "pg_llm_batch", broken)
    # Attribute access on a bare module raises ImportError -> degrade cleanly.
    counter = build_token_counter("postgresql://ledger_user@localhost/usage_db")
    assert isinstance(counter, RustCl100kTokenCounter)


def test_build_defaults_to_heuristic_without_dsn() -> None:
    counter = build_token_counter()
    assert isinstance(counter, RustCl100kTokenCounter)
    assert counter.count_text("hello world") >= 1
