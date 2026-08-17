"""Price honesty: store list price on free channels; unpriced is not free."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator, known_agent_comparison_cost  # noqa: E402
from contextual_orchestrator.cost_ledger import PriceBook, PriceEntry  # noqa: E402
from contextual_orchestrator.kv_config import InMemoryConfigStore  # noqa: E402
from contextual_orchestrator.model_discovery import (  # noqa: E402
    PROVIDER_ENDPOINTS,
    classify_price_status,
    finite_unit_price,
    normalize_catalog_payload,
)


def test_non_finite_and_boolean_prices_are_unknown() -> None:
    assert finite_unit_price(None) is None
    assert finite_unit_price(True) is None
    assert finite_unit_price(False) is None
    assert finite_unit_price("free") is None
    assert finite_unit_price(-1) is None
    assert finite_unit_price(float("nan")) is None
    assert finite_unit_price(float("inf")) is None
    assert finite_unit_price("0") == 0.0
    assert finite_unit_price(1.5) == 1.5


def test_openrouter_free_variant_keeps_sibling_list_price() -> None:
    payload = {
        "data": [
            {
                "id": "qwen/qwen3-32b",
                "pricing": {"prompt": "0.0000002", "completion": "0.0000004"},
            },
            {
                "id": "qwen/qwen3-32b:free",
                "pricing": {"prompt": "0", "completion": "0"},
            },
        ]
    }
    models = {model.model_id: model for model in normalize_catalog_payload(payload, PROVIDER_ENDPOINTS["OPENROUTER_API_KEY"])}
    free = models["qwen/qwen3-32b:free"]
    paid = models["qwen/qwen3-32b"]
    assert free.price_status == "promotional_free"
    assert free.billed_prompt_per_million == 0.0
    assert free.original_list_prompt_per_million == paid.billed_prompt_per_million
    assert free.comparison_cost() == paid.comparison_cost()
    assert free.comparison_cost() != 0.0


def test_explicit_zero_without_list_is_known_free() -> None:
    payload = {"data": [{"id": "lab/free-chat", "pricing": {"prompt": "0", "completion": "0"}}]}
    model = normalize_catalog_payload(payload, PROVIDER_ENDPOINTS["OPENROUTER_API_KEY"])[0]
    assert model.price_status == "known"
    assert model.comparison_cost() == 0.0


def test_missing_price_is_unknown_not_free() -> None:
    payload = {"data": [{"id": "nvidia/nemotron-hidden-price"}]}
    model = normalize_catalog_payload(payload, PROVIDER_ENDPOINTS["NVIDIA_NIM_API_KEY"])[0]
    assert model.price_status == "unknown"
    assert model.comparison_cost() is None
    assert classify_price_status(None, None, None, None) == "unknown"


def test_unpriced_worker_loses_known_cost_tie_break() -> None:
    cheap = ModelAgent(
        "cheap_worker",
        "priced-small",
        tags=("coding", "reasoning"),
        priority=1,
        price_per_million=1.0,
        price_status="known",
    )
    unpriced = ModelAgent(
        "mystery_worker",
        "unpriced-large",
        tags=("coding", "reasoning"),
        priority=1,
        price_status="unknown",
    )
    free_channel = ModelAgent(
        "promo_worker",
        "promo-free",
        tags=("coding", "reasoning"),
        priority=1,
        price_per_million=0.0,
        original_list_price=8.0,
        price_status="promotional_free",
    )
    orchestrator = TaskOrchestrator([unpriced, free_channel, cheap])
    ranked = orchestrator._ranked_agents("implement the parser", "worker")
    assert ranked[0].id == "cheap_worker"
    assert known_agent_comparison_cost(unpriced) is None
    assert known_agent_comparison_cost(free_channel) == 8.0
    assert known_agent_comparison_cost(cheap) == 1.0


def test_price_book_stub_without_rates_is_unknown() -> None:
    config = InMemoryConfigStore()
    book = PriceBook(config)
    config.set("llm_price_entries", "stub_co:hidden", {"provider_name": "stub_co", "model_name": "hidden"})
    assert book.get_price("stub_co", "hidden") is None
    assert book.known_compute_cost("stub_co", "hidden", 1000, 1000) == (None, "USD")
    # Ledger recording still accepts the row; selection must use known_compute_cost.
    assert book.compute_cost("stub_co", "hidden", 1000, 1000) == (0.0, "USD")


def test_price_book_uses_original_list_when_billed_is_zero() -> None:
    book = PriceBook(InMemoryConfigStore())
    book.set_price(
        PriceEntry(
            "openrouter",
            "qwen-free",
            prompt_price_per_1k=0.0,
            completion_price_per_1k=0.0,
            original_list_prompt_per_1k=0.2,
            original_list_completion_per_1k=0.4,
        )
    )
    cost, currency = book.known_compute_cost("openrouter", "qwen-free", 1000, 1000)
    assert currency == "USD"
    assert cost == 0.6


if __name__ == "__main__":  # pragma: no cover
    test_non_finite_and_boolean_prices_are_unknown()
    test_openrouter_free_variant_keeps_sibling_list_price()
    test_explicit_zero_without_list_is_known_free()
    test_missing_price_is_unknown_not_free()
    test_unpriced_worker_loses_known_cost_tie_break()
    test_price_book_stub_without_rates_is_unknown()
    test_price_book_uses_original_list_when_billed_is_zero()
    print("ok")
