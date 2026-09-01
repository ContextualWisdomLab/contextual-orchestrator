"""Parity and failure tests for exact native token counting and packing."""

from __future__ import annotations

import types

import pytest

from contextual_orchestrator.token_counting import (
    NativeExactTokenCounter,
    TokenCountUnavailable,
    UnavailableTokenCounter,
    build_embedding_token_counter,
)


def test_native_factory_counts_and_packs_declared_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    packed = types.SimpleNamespace(text="hello world", token_count=2)
    module = types.SimpleNamespace(
        count_cl100k=lambda text: calls.append(("cl100k", text)) or 2,
        count_o200k=lambda text: calls.append(("o200k", text)) or 2,
        pack_cl100k=lambda _texts, _per_input, _inputs, _total: ([packed], [[0]]),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.token_counting.importlib.import_module",
        lambda _name: module,
    )

    counter = build_embedding_token_counter()

    assert isinstance(counter, NativeExactTokenCounter)
    assert counter.count_text("hello world", "text-embedding-3-small") == 2
    assert counter.count_text("hello world", "gpt-4o") == 2
    assert counter.pack_text("hello world", "text-embedding-3-small", 8192) == [
        ("hello world", 2)
    ]
    with pytest.raises(TokenCountUnavailable, match="no authoritative tokenizer"):
        counter.count_text("hello world", "provider-unknown")
    assert calls == [("cl100k", "hello world"), ("o200k", "hello world")]


def test_native_failure_is_unavailable() -> None:
    def fail(_text: str) -> int:
        raise RuntimeError("synthetic native failure")

    module = types.SimpleNamespace(
        count_cl100k=fail,
        count_o200k=lambda _text: 1,
        pack_cl100k=lambda *_args: ([], []),
    )
    counter = NativeExactTokenCounter(module)
    with pytest.raises(TokenCountUnavailable, match="native tokenizer"):
        counter.count_text("hello", "text-embedding-3-large")


def test_installed_native_counter_matches_declared_encoding_parity() -> None:
    module = pytest.importorskip("contextual_orchestrator._token_packer")
    counter = NativeExactTokenCounter(module)
    assert counter.count_text("hello world", "gpt-4") == 2
    assert counter.count_text("hello world", "gpt-4o") == 2
    assert counter.pack_text("hello world", "text-embedding-3-small", 8192) == [
        ("hello world", 2)
    ]


def test_embedding_factory_missing_or_incomplete_native_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "contextual_orchestrator.token_counting.importlib.import_module",
        lambda _name: types.SimpleNamespace(
            count_cl100k=lambda _text: 1,
            count_o200k=lambda _text: 1,
        ),
    )
    counter = build_embedding_token_counter()
    assert isinstance(counter, UnavailableTokenCounter)
    with pytest.raises(TokenCountUnavailable):
        counter.count_text("hello", "text-embedding-3-small")
