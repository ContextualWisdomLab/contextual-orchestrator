"""Regression coverage for honest, provider-diverse discovery bootstrap."""

from __future__ import annotations

from contextual_orchestrator.cost_ledger import PriceBook, PriceEntry
from contextual_orchestrator.kv_config import InMemoryConfigStore
from contextual_orchestrator import model_discovery
from contextual_orchestrator.model_discovery import (
    DiscoveredModel,
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


def _set_price(
    price_book: PriceBook,
    model: DiscoveredModel,
    price_per_1k: float,
) -> None:
    """Record one known symmetric prompt/completion price."""
    price_book.set_price(
        PriceEntry(
            model.provider_name,
            model.model_id,
            price_per_1k,
            price_per_1k,
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
