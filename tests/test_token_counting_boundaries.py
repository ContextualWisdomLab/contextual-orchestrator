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
    estimate_lower_bound_tokens,
    prompt_token_lower_bound,
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


def test_estimate_lower_bound_tokens_is_conservative_and_zero_for_empty() -> None:
    """The character-based lower bound is empty-safe and monotone in length."""
    assert estimate_lower_bound_tokens("") == 0
    short = "hi"
    long = "hi" * 100
    assert estimate_lower_bound_tokens(short) <= estimate_lower_bound_tokens(long)
    # len(text) // 7, per the documented divisor.
    assert estimate_lower_bound_tokens("word " * 140) == 100


def test_prompt_token_lower_bound_labels_exact_when_native_tokenizer_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A declared model with a native tokenizer yields an ``"exact"``-labelled count."""
    module = types.SimpleNamespace(
        count_cl100k=lambda text: len(text.split()),
        count_o200k=lambda _text: 0,
        pack_cl100k=lambda *_args: ([], []),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.token_counting.importlib.import_module",
        lambda _name: module,
    )
    counter = build_token_counter()
    assert isinstance(counter, NativeExactTokenCounter)

    count, source = prompt_token_lower_bound("hello world review", "gpt-4", counter)

    assert count == 3
    assert source == "exact"


def test_prompt_token_lower_bound_falls_back_to_estimate_when_unavailable() -> None:
    """An unmapped model with no authoritative tokenizer falls back to the heuristic."""
    counter = UnavailableTokenCounter()
    text = "word " * 140

    count, source = prompt_token_lower_bound(text, "some-unmapped-model", counter)

    assert count == estimate_lower_bound_tokens(text)
    assert source == "estimate_lower_bound"


@pytest.mark.parametrize(
    "sample,label",
    [
        ("The quick brown fox jumps over the lazy dog. " * 20, "ascii_prose"),
        ("def add(a, b):\n    return a + b\n\nresult = add(1, 2)\n" * 20, "code"),
        ("你好世界，今天的天气非常好，我们一起去公园散步吧。" * 20, "cjk"),
    ],
)
def test_estimate_lower_bound_never_exceeds_a_real_native_exact_count(
    sample: str, label: str
) -> None:
    """Property: the heuristic estimate never overestimates a real tokenizer's count.

    Uses whatever tokenizer this environment's ``build_token_counter()``
    actually resolves (native extension or configured Postgres backend); when
    neither is available here, the case is skipped rather than faked, per the
    gap-filter spec's requirement that this only assert against a genuinely
    available native counter.
    """
    counter = build_token_counter()
    try:
        exact = counter.count_text(sample, "gpt-4")
    except TokenCountUnavailable:
        pytest.skip(f"no native tokenizer is available in this environment for {label!r}")
    assert estimate_lower_bound_tokens(sample) <= exact


def test_estimate_lower_bound_collapses_repeated_character_runs() -> None:
    """Whitespace and rule runs must not inflate the bound above a real count.

    Native tokenizers fold long runs of one character into a few multi-character
    tokens, so a raw ``len // 7`` over-counts them; the estimator collapses each
    run to two characters first.
    """
    from contextual_orchestrator.token_counting import estimate_lower_bound_tokens

    assert estimate_lower_bound_tokens(" " * 1000) == 0
    assert estimate_lower_bound_tokens("-" * 400) == 0
    indented = ("        return value\n") * 40
    assert estimate_lower_bound_tokens(indented) <= len(indented.replace("        ", "  ")) // 7
