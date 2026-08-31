"""Regression coverage for honest, provider-diverse discovery bootstrap."""

from __future__ import annotations

import pytest

from contextual_orchestrator.cost_ledger import PriceBook, PriceEntry
from contextual_orchestrator.kv_config import InMemoryConfigStore
from contextual_orchestrator import model_discovery
from contextual_orchestrator.model_discovery import (
    DiscoveredModel,
    refresh_price_book,
    select_cheapest_discovered_agent,
    select_top_n_cheapest_discovered_agents,
)


def _model(provider_name: str, model_id: str) -> DiscoveredModel:
    """Build one deterministic OpenAI-compatible discovery fixture."""
    credential_name = f"{provider_name.upper()}_API_KEY"
    return DiscoveredModel(
        provider_name=provider_name,
        model_id=model_id,
        credential_name=credential_name,
        chat_base_url=f"https://{provider_name}.example/v1",
        auth_scheme="Bearer",
    )


def _priced_model(
    provider_name: str,
    model_id: str,
    *,
    prompt_price_per_1k: float | None,
    completion_price_per_1k: float | None,
    currency_code: str = "USD",
) -> DiscoveredModel:
    """Build one discovery row carrying provider-reported price evidence."""
    base = _model(provider_name, model_id)
    return DiscoveredModel(
        provider_name=base.provider_name,
        model_id=base.model_id,
        credential_name=base.credential_name,
        chat_base_url=base.chat_base_url,
        auth_scheme=base.auth_scheme,
        prompt_price_per_1k=prompt_price_per_1k,
        completion_price_per_1k=completion_price_per_1k,
        currency_code=currency_code,
    )


def _set_price(
    price_book: PriceBook,
    model: DiscoveredModel,
    price_per_1k: float,
    *,
    currency_code: str = "USD",
) -> None:
    """Record one known symmetric prompt/completion price."""
    price_book.set_price(
        PriceEntry(
            model.provider_name,
            model.model_id,
            price_per_1k,
            price_per_1k,
            currency_code,
        )
    )


def test_unpriced_discovered_model_is_unknown_not_free() -> None:
    """Missing price evidence must not outrank a model with a known price."""
    price_book = PriceBook(InMemoryConfigStore())
    priced = _model("openrouter", "priced-model")
    unpriced = _model("bytez", "unpriced-model")
    _set_price(price_book, priced, 0.01)

    assert select_cheapest_discovered_agent([unpriced, priced], price_book) is priced
    assert select_top_n_cheapest_discovered_agents(
        [unpriced, priced], price_book, 2
    ) == [priced, unpriced]


def test_partial_provider_price_is_unknown_instead_of_fabricating_a_free_component() -> None:
    """A missing prompt or completion price cannot become an invented zero."""
    price_book = PriceBook(InMemoryConfigStore())
    partial = _priced_model(
        "partial_vendor",
        "partial-model",
        prompt_price_per_1k=0.001,
        completion_price_per_1k=None,
    )
    complete = _priced_model(
        "openrouter",
        "complete-model",
        prompt_price_per_1k=1.0,
        completion_price_per_1k=1.0,
    )

    assert refresh_price_book([partial, complete], price_book) == 1
    assert price_book.get_price(partial.provider_name, partial.model_id) is None
    assert select_cheapest_discovered_agent([partial, complete], price_book) is complete


def test_persisted_price_row_missing_one_component_remains_unknown() -> None:
    """KV corruption must not silently manufacture a zero-priced component."""
    store = InMemoryConfigStore()
    store.set(
        "llm_price_entries",
        "partial_vendor:partial-model",
        {
            "provider_name": "partial_vendor",
            "model_name": "partial-model",
            "prompt_price_per_1k": 0.001,
            "currency_code": "USD",
        },
    )
    price_book = PriceBook(store)

    assert price_book.get_price("partial_vendor", "partial-model") is None


def test_persisted_boolean_price_row_remains_unknown() -> None:
    """Do not coerce corrupt KV booleans into zero-cost price evidence."""
    store = InMemoryConfigStore()
    store.set(
        "llm_price_entries",
        "broken_vendor:broken-model",
        {"prompt_price_per_1k": False, "completion_price_per_1k": False},
    )

    assert PriceBook(store).get_price("broken_vendor", "broken-model") is None


def test_invalid_catalog_prices_are_unknown_not_trusted_cost_evidence() -> None:
    """Reject negative, non-finite, and boolean provider price values."""
    assert model_discovery._price_per_1k("-0.000001") is None
    assert model_discovery._price_per_1k("nan") is None
    assert model_discovery._price_per_1k("inf") is None
    assert model_discovery._price_per_1k(True) is None
    assert model_discovery._price_per_1k("0") == 0.0


def test_huge_price_values_remain_unknown_without_crashing_discovery_or_ranking() -> None:
    """Unbounded JSON or KV integers must not terminate bootstrap selection."""
    huge_price = 10**10000
    assert model_discovery._price_per_1k(huge_price) is None

    price_book = PriceBook(InMemoryConfigStore())
    huge = _model("huge_vendor", "huge-model")
    valid = _model("openrouter", "valid-model")
    _set_price(price_book, huge, huge_price)
    _set_price(price_book, valid, 1.0)

    assert select_cheapest_discovered_agent([huge, valid], price_book) is valid


def test_malformed_price_book_row_is_unknown_instead_of_crashing_selection() -> None:
    """A corrupt persisted price row must not take down the serving bootstrap."""
    store = InMemoryConfigStore()
    store.set(
        "llm_price_entries",
        "broken_vendor:broken-model",
        {
            "provider_name": "broken_vendor",
            "model_name": "broken-model",
            "prompt_price_per_1k": "not-a-number",
            "completion_price_per_1k": 0.001,
            "currency_code": "USD",
        },
    )
    price_book = PriceBook(store)
    broken = _model("broken_vendor", "broken-model")
    valid = _model("openrouter", "valid-model")
    _set_price(price_book, valid, 1.0)

    assert select_cheapest_discovered_agent([broken, valid], price_book) is valid


def test_refresh_counts_only_complete_prices_in_the_comparison_currency() -> None:
    """Cross-currency evidence is unknown until an explicit conversion exists."""
    price_book = PriceBook(InMemoryConfigStore(), default_currency="USD")
    usd = _priced_model(
        "openrouter",
        "usd-model",
        prompt_price_per_1k=1.0,
        completion_price_per_1k=1.0,
        currency_code="USD",
    )
    eur = _priced_model(
        "eur_vendor",
        "eur-model",
        prompt_price_per_1k=0.001,
        completion_price_per_1k=0.001,
        currency_code="EUR",
    )

    assert refresh_price_book([eur, usd], price_book) == 1
    assert price_book.get_price("eur_vendor", "eur-model") is None
    assert price_book.get_price("openrouter", "usd-model") is not None


def test_invalid_or_cross_currency_price_rows_do_not_outrank_comparable_usd_cost() -> None:
    """Only finite non-negative prices in the configured currency are comparable."""
    price_book = PriceBook(InMemoryConfigStore(), default_currency="USD")
    valid = _model("openrouter", "valid-model")
    negative = _model("negative_vendor", "negative-model")
    non_finite = _model("nan_vendor", "nan-model")
    foreign = _model("eur_vendor", "eur-model")

    _set_price(price_book, valid, 1.0)
    _set_price(price_book, negative, -100.0)
    _set_price(price_book, non_finite, float("nan"))
    _set_price(price_book, foreign, 0.000001, currency_code="EUR")

    assert select_cheapest_discovered_agent(
        [negative, non_finite, foreign, valid],
        price_book,
    ) is valid


def test_duplicate_serving_identity_cannot_consume_bootstrap_capacity() -> None:
    """A repeated provider/model row must not masquerade as failover diversity."""
    selector = getattr(
        model_discovery,
        "select_bootstrap_discovered_agents",
        None,
    )
    assert callable(selector), "missing provider-diverse bootstrap selector"

    price_book = PriceBook(InMemoryConfigStore())
    duplicate_first = _model("openrouter", "same-model")
    duplicate_second = _model("openrouter", "same-model")
    independent = _model("openai", "independent-model")
    _set_price(price_book, duplicate_first, 0.01)
    _set_price(price_book, independent, 0.02)

    selected = selector(
        [duplicate_second, independent, duplicate_first],
        price_book,
        3,
    )
    top_n = select_top_n_cheapest_discovered_agents(
        [duplicate_second, independent, duplicate_first],
        price_book,
        3,
    )

    assert [
        (model.provider_name, model.model_id)
        for model in selected
    ] == [
        ("openrouter", "same-model"),
        ("openai", "independent-model"),
    ]
    assert [
        (model.provider_name, model.model_id)
        for model in top_n
    ] == [
        ("openrouter", "same-model"),
        ("openai", "independent-model"),
    ]


def test_conflicting_duplicate_prices_are_withheld_as_ambiguous() -> None:
    """Do not let provider row order decide the trusted price for one agent id."""
    price_book = PriceBook(InMemoryConfigStore())
    cheap_claim = _priced_model(
        "openrouter",
        "duplicate-model",
        prompt_price_per_1k=0.000001,
        completion_price_per_1k=0.000001,
    )
    expensive_claim = _priced_model(
        "openrouter",
        "duplicate-model",
        prompt_price_per_1k=100.0,
        completion_price_per_1k=100.0,
    )
    complete = _priced_model(
        "openai",
        "complete-model",
        prompt_price_per_1k=1.0,
        completion_price_per_1k=1.0,
    )

    assert refresh_price_book(
        [cheap_claim, expensive_claim, complete],
        price_book,
    ) == 1
    assert price_book.get_price("openrouter", "duplicate-model") is None
    assert select_cheapest_discovered_agent(
        [cheap_claim, expensive_claim, complete],
        price_book,
    ) is complete


def test_bootstrap_selector_prefers_provider_diversity_before_duplicates() -> None:
    """The initial failover pool must span providers before repeating one."""
    selector = getattr(
        model_discovery,
        "select_bootstrap_discovered_agents",
        None,
    )
    assert callable(selector), "missing provider-diverse bootstrap selector"

    price_book = PriceBook(InMemoryConfigStore())
    router_cheapest = _model("openrouter", "router-cheapest")
    router_second = _model("openrouter", "router-second")
    nim_model = _model("nvidia_nim", "nim-model")
    openai_model = _model("openai", "openai-model")
    _set_price(price_book, router_cheapest, 0.01)
    _set_price(price_book, router_second, 0.02)
    _set_price(price_book, nim_model, 0.5)
    _set_price(price_book, openai_model, 1.0)

    selected = selector(
        [router_second, openai_model, nim_model, router_cheapest],
        price_book,
        3,
    )

    assert selected == [router_cheapest, nim_model, openai_model]


def test_bootstrap_selector_keeps_nim_primary_and_sub_independent() -> None:
    """A shared vendor endpoint does not collapse independent credential
    accounts: nim_primary and nim_sub each win their own diversity slot ahead
    of the unrelated, costlier openrouter candidate.
    """
    selector = getattr(
        model_discovery,
        "select_bootstrap_discovered_agents",
        None,
    )
    assert callable(selector), "missing provider-diverse bootstrap selector"

    price_book = PriceBook(InMemoryConfigStore())
    nim_primary = _model("nvidia_nim", "primary-model")
    nim_sub = _model("nvidia_nim_sub", "sub-model")
    openrouter = _model("openrouter", "router-model")
    _set_price(price_book, nim_primary, 0.01)
    _set_price(price_book, nim_sub, 0.02)
    _set_price(price_book, openrouter, 0.5)

    selected = selector(
        [nim_sub, openrouter, nim_primary],
        price_book,
        2,
    )

    assert selected == [nim_primary, nim_sub]


def test_bootstrap_selector_is_deterministic_when_every_model_is_unpriced() -> None:
    """All-unpriced discovery remains usable but never order-dependent."""
    selector = getattr(
        model_discovery,
        "select_bootstrap_discovered_agents",
        None,
    )
    assert callable(selector), "missing provider-diverse bootstrap selector"

    price_book = PriceBook(InMemoryConfigStore())
    router_z = _model("openrouter", "z-model")
    router_a = _model("openrouter", "a-model")
    nim_b = _model("nvidia_nim", "b-model")

    selected = selector(
        [router_z, nim_b, router_a],
        price_book,
        3,
    )

    assert selected == [nim_b, router_a, router_z]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
