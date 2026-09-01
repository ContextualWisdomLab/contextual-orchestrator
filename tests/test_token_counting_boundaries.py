"""Boundary tests for authoritative token-count selection."""

from __future__ import annotations

import sys
import types

import pytest

from contextual_orchestrator.token_counting import (
    NativeExactTokenCounter,
    PgTiktokenAdapter,
    TokenCountUnavailable,
    UnavailableTokenCounter,
    build_token_counter,
)


class _StubPgCounter:
    """Minimal pg_llm_batch.TokenCounter double recording calls."""

    def __init__(self, dsn: str, config: object = None) -> None:
        self.dsn = dsn
        self.config = config
        self.calls: list[tuple[str, str]] = []

    def count_tokens(self, text: str, model: str) -> int:
        self.calls.append((text, model))
        return 7


def test_postgres_counts_raw_text_but_not_chat_framing() -> None:
    stub = _StubPgCounter("postgresql://x")
    adapter = PgTiktokenAdapter(stub)
    assert adapter.count_text("one", "gpt-4") == 7
    with pytest.raises(TokenCountUnavailable, match="chat framing"):
        adapter.count_messages([{"content": "one"}], "gpt-4")


def test_postgres_runtime_failure_is_unavailable() -> None:
    class _FailingPgCounter:
        def count_tokens(self, text: str, model: str) -> int:
            raise ConnectionError("synthetic database loss")

    with pytest.raises(TokenCountUnavailable, match="PostgreSQL tokenizer"):
        PgTiktokenAdapter(_FailingPgCounter()).count_text("one", "gpt-4")


@pytest.mark.parametrize("invalid_count", [True, -1, 7.5, "7"])
def test_postgres_rejects_non_integral_or_negative_counts(invalid_count: object) -> None:
    counter = types.SimpleNamespace(
        count_tokens=lambda _text, _model: invalid_count,
    )
    with pytest.raises(TokenCountUnavailable, match="invalid count"):
        PgTiktokenAdapter(counter).count_text("one", "gpt-4")


def test_build_prefers_configured_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("pg_llm_batch")
    module.TokenCounter = _StubPgCounter  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pg_llm_batch", module)
    config = {"model": "demo_model"}
    counter = build_token_counter("postgresql://ledger/usage", config=config)
    assert isinstance(counter, PgTiktokenAdapter)
    assert counter.count_text("route me", "gpt-4") == 7
    assert counter._counter.config is config


def test_native_exact_dispatches_only_full_declared_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    module = types.SimpleNamespace(
        count_cl100k=lambda text: calls.append(("cl100k", text)) or 2,
        count_o200k=lambda text: calls.append(("o200k", text)) or 3,
        pack_cl100k=lambda *_args: ([], []),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.token_counting.importlib.import_module",
        lambda _name: module,
    )
    counter = build_token_counter()
    assert isinstance(counter, NativeExactTokenCounter)
    assert counter.count_text("hello world", "gpt-4") == 2
    assert counter.count_text("hello world", "gpt-4o") == 3
    with pytest.raises(TokenCountUnavailable, match="no authoritative tokenizer"):
        counter.count_text("hello world", "gpt-4-2099-nonexistent")
    with pytest.raises(TokenCountUnavailable, match="chat framing"):
        counter.count_messages([{"role": "user", "content": "hello"}], "gpt-4")
    assert calls == [("cl100k", "hello world"), ("o200k", "hello world")]


def test_native_counter_does_not_flatten_multimodal_chat_prompts() -> None:
    module = types.SimpleNamespace(count_cl100k=lambda _text: 1, count_o200k=lambda _text: 1)
    counter = NativeExactTokenCounter(module)
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "inspect the image"},
                {
                    "type": "image_url",
                    "image_url": {"url": "https://example.invalid/synthetic.png"},
                },
            ],
        }
    ]

    with pytest.raises(TokenCountUnavailable, match="chat framing"):
        counter.count_messages(messages, "gpt-4o")


def test_factory_is_unavailable_when_backends_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = types.ModuleType("pg_llm_batch")
    monkeypatch.setitem(sys.modules, "pg_llm_batch", broken)
    monkeypatch.setattr(
        "contextual_orchestrator.token_counting.importlib.import_module",
        lambda _name: (_ for _ in ()).throw(ImportError("missing native")),
    )
    counter = build_token_counter("postgresql://ledger/usage")
    assert isinstance(counter, UnavailableTokenCounter)
    with pytest.raises(TokenCountUnavailable):
        counter.count_text("hello", "gpt-4")
