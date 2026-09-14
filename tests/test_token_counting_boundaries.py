"""Boundary tests for authoritative token-count selection."""

from __future__ import annotations

import sys
import types

import pytest

from contextual_orchestrator.token_counting import (
    COUNTING_PROVENANCE_REGISTRY,
    FRAMING_SOURCE_UNVERIFIED,
    MessageCountResult,
    NativeExactTokenCounter,
    PgTiktokenAdapter,
    TokenCountUnavailable,
    UnavailableTokenCounter,
    build_token_counter,
    describe_message_count,
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


def _stub_native_counter() -> NativeExactTokenCounter:
    """A NativeExactTokenCounter over a deterministic stub encoder for behavior tests."""
    module = types.SimpleNamespace(
        count_cl100k=lambda text: len(text.split()),
        count_o200k=lambda text: len(text.split()),
        pack_cl100k=lambda *_args: ([], []),
    )
    return NativeExactTokenCounter(module)


def test_registry_entries_carry_a_source_and_scope() -> None:
    assert COUNTING_PROVENANCE_REGISTRY, "registry must not be empty"
    for model, entry in COUNTING_PROVENANCE_REGISTRY.items():
        assert entry.framing_source != FRAMING_SOURCE_UNVERIFIED
        assert entry.framing_source_url.startswith("https://")
        assert model in entry.framing_scope
        assert entry.tokenizer in {"cl100k", "o200k"}
        assert entry.supported_fields
        assert entry.unsupported_fields


def test_verified_family_counts_exactly_with_real_native_tokenizer() -> None:
    counter = build_token_counter()
    if not isinstance(counter, NativeExactTokenCounter):
        pytest.skip("native tokenizer extension is not installed locally")
    model = "gpt-4o-2024-08-06"
    messages = [
        {"role": "system", "content": "You are terse."},
        {"role": "user", "content": "Say hi.", "name": "alice"},
    ]
    result = counter.describe_messages(messages, model)
    assert isinstance(result, MessageCountResult)
    assert result.token_count > 0
    assert result.tokenizer == "o200k"
    assert result.count_source == "provenance_exact"
    assert result.framing_source == COUNTING_PROVENANCE_REGISTRY[model].framing_source
    assert result.token_count == counter.count_messages(messages, model)


def test_supported_fields_count_exactly_with_stub_encoder() -> None:
    counter = _stub_native_counter()
    model = "gpt-4o-2024-08-06"
    messages = [{"role": "user", "content": "one two three"}]
    result = counter.describe_messages(messages, model)
    entry = COUNTING_PROVENANCE_REGISTRY[model]
    # tokens_per_message + role("user" -> 1 word) + content("one two three" -> 3 words)
    # + reply priming, with the deterministic word-count stub encoder.
    expected = entry.tokens_per_message + 1 + 3 + entry.reply_priming_tokens
    assert result.token_count == expected
    assert describe_message_count(counter, messages, model).token_count == expected


def test_tools_field_raises_unavailable_naming_tools() -> None:
    counter = _stub_native_counter()
    messages = [{"role": "user", "content": "hello"}]
    with pytest.raises(TokenCountUnavailable, match="tools"):
        counter.describe_messages(messages, "gpt-4o-2024-08-06", tools=[{"type": "function"}])


def test_unsupported_message_field_raises_naming_the_field() -> None:
    counter = _stub_native_counter()
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_1", "type": "function"}],
        }
    ]
    with pytest.raises(TokenCountUnavailable, match="tool_calls"):
        counter.count_messages(messages, "gpt-4o-2024-08-06")


def test_non_text_content_part_raises_naming_content() -> None:
    counter = _stub_native_counter()
    messages = [
        {
            "role": "user",
            "content": [{"type": "text", "text": "hi"}],
        }
    ]
    with pytest.raises(TokenCountUnavailable, match="content"):
        counter.count_messages(messages, "gpt-4o-2024-08-06")


def test_model_outside_scope_raises_unavailable() -> None:
    counter = _stub_native_counter()
    messages = [{"role": "user", "content": "hello"}]
    with pytest.raises(TokenCountUnavailable, match="outside the verified"):
        counter.describe_messages(messages, "gpt-4o")


def test_describe_message_count_is_unavailable_for_counters_without_describe_messages() -> None:
    with pytest.raises(TokenCountUnavailable):
        describe_message_count(UnavailableTokenCounter(), [{"role": "user", "content": "hi"}], "gpt-4o-2024-08-06")


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
