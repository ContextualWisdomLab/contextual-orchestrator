"""Boundary tests for the token counting seam (statement + branch coverage)."""

from __future__ import annotations

import sys
import types

import pytest

from contextual_orchestrator.token_counting import (
    HeuristicTokenCounter,
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


def test_heuristic_empty_and_whitespace_only_text_count_zero() -> None:
    counter = HeuristicTokenCounter()
    assert counter.count_text("") == 0
    # Whitespace-only text matches no word units and must not round up to 1.
    assert counter.count_text("   \t\n  ") == 0


def test_heuristic_punctuation_only_counts_standalone_symbols() -> None:
    counter = HeuristicTokenCounter()
    # Five standalone punctuation units, expanded by the BPE factor: ceil(5*1.3)=7.
    assert counter.count_text("!?...") == 7


def test_heuristic_custom_tokens_per_word_scales_monotonically() -> None:
    text = "alpha beta gamma"
    low = HeuristicTokenCounter(tokens_per_word=1.0).count_text(text)
    high = HeuristicTokenCounter(tokens_per_word=2.5).count_text(text)
    assert low == 3
    assert high == 8
    assert high > low


@pytest.mark.parametrize("bad_message", ["plain string", None, 42])
def test_heuristic_non_dict_messages_contribute_framing_only(bad_message: object) -> None:
    counter = HeuristicTokenCounter()
    total = counter.count_messages([{"content": "hello"}, bad_message])  # type: ignore[list-item]
    # "hello" -> ceil(1*1.3)=2 tokens plus 3 framing for each of two messages.
    assert total == 2 + 3 + 0 + 3


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
    assert isinstance(counter, HeuristicTokenCounter)


def test_build_defaults_to_heuristic_without_dsn() -> None:
    counter = build_token_counter()
    assert isinstance(counter, HeuristicTokenCounter)
    assert counter.count_text("hello world") >= 1
