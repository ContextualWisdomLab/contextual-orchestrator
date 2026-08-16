"""Free-but-known-list-price models retain original_list_price.

Spend analytics still cost only the billed price (0 when promotional-free).
The published list price is stored and returned even when billed rates are 0.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, PriceBook, PriceEntry, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.conventions import is_two_word_snake_case  # noqa: E402
from contextual_orchestrator.kv_config import InMemoryConfigStore  # noqa: E402


def test_original_list_price_field_is_two_word_snake_case() -> None:
    assert is_two_word_snake_case("original_list_price")


def test_price_book_retains_original_list_price_when_billed_is_zero() -> None:
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    listed = {"prompt_price_per_1k": 0.15, "completion_price_per_1k": 0.60, "currency_code": "USD"}
    price_book.set_price(
        PriceEntry(
            "openrouter",
            "free-llama",
            prompt_price_per_1k=0.0,
            completion_price_per_1k=0.0,
            original_list_price=listed,
        )
    )
    entry = price_book.get_price("openrouter", "free-llama")
    assert entry is not None
    assert entry.prompt_price_per_1k == 0.0
    assert entry.completion_price_per_1k == 0.0
    assert entry.original_list_price == listed
    cost, currency = price_book.compute_cost("openrouter", "free-llama", 1000, 1000)
    assert cost == 0.0
    assert currency == "USD"


def test_spend_analytics_keeps_original_list_price_on_free_model() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent("promo_worker", "free-llama", tags=("reasoning",))],
        price_per_million={"free-llama": 0.0},
        original_list_price={"free-llama": 15.0},
    )
    orchestrator.run([{"role": "user", "content": "price this free model"}])
    report = orchestrator.spend_analytics()
    row = next(r for r in report["by_model"] if r["model"] == "free-llama")
    assert row["price_per_million_usd"] == 0.0
    assert row["estimated_cost_usd"] == 0.0
    assert row["original_list_price"] == 15.0
    assert "free-llama" not in report["unpriced_models"]


def test_unpriced_model_has_null_original_list_price() -> None:
    orchestrator = TaskOrchestrator([ModelAgent("solo_worker", "mystery-model", tags=("reasoning",))])
    orchestrator.run([{"role": "user", "content": "no price"}])
    row = next(r for r in orchestrator.spend_analytics()["by_model"] if r["model"] == "mystery-model")
    assert row["estimated_cost_usd"] is None
    assert row["original_list_price"] is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
