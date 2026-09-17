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
    SharedContextBudget,
    TokenCountUnavailable,
    UnavailableTokenCounter,
    build_token_counter,
    describe_message_count,
    estimate_lower_bound_tokens,
    prompt_token_lower_bound,
    shared_context_output_budget,
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


class _Agent:
    """Minimal duck-typed stand-in for ModelAgent's fields the budget reads."""

    def __init__(self, *, model="gpt-4o-2024-08-06", context_window=None, max_output_tokens=None):
        self.model = model
        self.context_window = context_window
        self.max_output_tokens = max_output_tokens


_MESSAGES = [{"role": "user", "content": "hello there"}]
# tokens_per_message(3) + role(1) + content(2) + reply_priming(3) = 9.
_EXACT_PROMPT_TOKENS = 9


def test_shared_context_output_budget_is_none_without_a_counter() -> None:
    agent = _Agent(context_window=20, max_output_tokens=50)
    assert (
        shared_context_output_budget(agent, _MESSAGES, None, counter=None) is None
    )


def test_shared_context_output_budget_is_none_when_context_window_is_unknown() -> None:
    counter = _stub_native_counter()
    agent = _Agent(context_window=None, max_output_tokens=50)
    assert shared_context_output_budget(agent, _MESSAGES, None, counter=counter) is None


@pytest.mark.parametrize("invalid_window", [0, -1, 3.5, "20"])
def test_shared_context_output_budget_is_none_for_an_invalid_context_window(invalid_window) -> None:
    counter = _stub_native_counter()
    agent = _Agent(context_window=invalid_window, max_output_tokens=50)
    assert shared_context_output_budget(agent, _MESSAGES, None, counter=counter) is None


def test_shared_context_output_budget_is_none_when_max_output_tokens_is_unknown() -> None:
    counter = _stub_native_counter()
    agent = _Agent(context_window=20, max_output_tokens=None)
    assert shared_context_output_budget(agent, _MESSAGES, None, counter=counter) is None


def test_shared_context_output_budget_is_none_when_the_model_is_out_of_scope() -> None:
    counter = _stub_native_counter()
    agent = _Agent(model="mock-planner", context_window=20, max_output_tokens=50)
    assert shared_context_output_budget(agent, _MESSAGES, None, counter=counter) is None


def test_shared_context_output_budget_is_none_when_tools_make_the_count_unavailable() -> None:
    counter = _stub_native_counter()
    agent = _Agent(context_window=20, max_output_tokens=50)
    assert (
        shared_context_output_budget(
            agent, _MESSAGES, None, counter=counter, tools=[{"type": "function"}]
        )
        is None
    )


def test_shared_context_output_budget_computes_remaining_and_ceiling_from_exact_evidence() -> None:
    counter = _stub_native_counter()
    agent = _Agent(context_window=20, max_output_tokens=50)
    budget = shared_context_output_budget(agent, _MESSAGES, None, counter=counter)
    assert budget == SharedContextBudget(
        context_window=20,
        prompt_tokens=_EXACT_PROMPT_TOKENS,
        remaining=20 - _EXACT_PROMPT_TOKENS,
        output_ceiling=min(50, 20 - _EXACT_PROMPT_TOKENS),
        requested_output_tokens=None,
        exceeds_remaining=False,
    )
    assert budget.as_evidence() == {
        "context_window": 20,
        "prompt_tokens": _EXACT_PROMPT_TOKENS,
        "output_ceiling": 11,
        "source": "exact",
    }


def test_shared_context_output_budget_flags_an_explicit_request_over_remaining() -> None:
    counter = _stub_native_counter()
    agent = _Agent(context_window=20, max_output_tokens=50)
    budget = shared_context_output_budget(agent, _MESSAGES, 15, counter=counter)
    assert budget.remaining == 11
    assert budget.exceeds_remaining is True


def test_shared_context_output_budget_flags_remaining_below_one_even_without_a_request() -> None:
    counter = _stub_native_counter()
    agent = _Agent(context_window=5, max_output_tokens=50)
    budget = shared_context_output_budget(agent, _MESSAGES, None, counter=counter)
    assert budget.remaining == 5 - _EXACT_PROMPT_TOKENS
    assert budget.exceeds_remaining is True


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
    assert estimate_lower_bound_tokens(" " * 1000) == 0
    assert estimate_lower_bound_tokens("-" * 400) == 0
    indented = ("        return value\n") * 40
    assert estimate_lower_bound_tokens(indented) <= len(indented.replace("        ", "  ")) // 7

