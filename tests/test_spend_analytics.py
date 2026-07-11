"""Spend observability — estimated per-model token + cost analytics.

The LLM-gateway category monetizes on spend tracking; this product discarded usage
entirely. These assert the token estimate, per-model aggregation, cost math when a
price is configured, honest nulls when it is not, and the read-only HTTP endpoint.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import estimate_tokens  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


def test_estimate_tokens_heuristic() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1  # 4 chars ~ 1 token
    assert estimate_tokens("abcde") == 2  # (5 + 3) // 4
    assert estimate_tokens("a" * 400) == 100


def test_spend_without_prices_reports_null_cost() -> None:
    orchestrator = TaskOrchestrator([ModelAgent("general_agent", "free-model", tags=("reasoning",))])
    orchestrator.run([{"role": "user", "content": "estimate my spend"}])
    report = orchestrator.spend_analytics()

    assert report["pricing_configured"] is False
    assert report["totals"]["run_count"] == 1
    assert report["totals"]["estimated_output_tokens"] > 0
    assert report["totals"]["estimated_cost_usd"] is None
    assert "free-model" in report["unpriced_models"]
    row = next(r for r in report["by_model"] if r["model"] == "free-model")
    assert row["estimated_cost_usd"] is None


def test_spend_with_price_computes_cost() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "priced-model", tags=("reasoning",))],
        price_per_million={"priced-model": 10.0},
    )
    orchestrator.run([{"role": "user", "content": "compute my cost please"}])
    report = orchestrator.spend_analytics()

    assert report["pricing_configured"] is True
    row = next(r for r in report["by_model"] if r["model"] == "priced-model")
    assert row["price_per_million_usd"] == 10.0
    expected = round(row["estimated_output_tokens"] / 1_000_000 * 10.0, 6)
    assert row["estimated_cost_usd"] == expected
    assert report["totals"]["estimated_cost_usd"] == expected  # single priced model
    assert report["unpriced_models"] == []


def test_call_time_price_overrides_instance() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "priced-model", tags=("reasoning",))],
        price_per_million={"priced-model": 10.0},
    )
    orchestrator.run([{"role": "user", "content": "override the price"}])
    row = next(
        r for r in orchestrator.spend_analytics(price_per_million={"priced-model": 20.0})["by_model"]
        if r["model"] == "priced-model"
    )
    assert row["price_per_million_usd"] == 20.0


def test_spend_empty_when_no_runs() -> None:
    report = TaskOrchestrator([ModelAgent("general_agent", "some-model")]).spend_analytics()
    assert report["totals"]["run_count"] == 0
    assert report["by_model"] == []
    assert report["totals"]["estimated_output_tokens"] == 0


def test_http_spend_endpoint_returns_report() -> None:
    token = "spend_token"
    orchestrator = TaskOrchestrator([ModelAgent("general_agent", "priced-model", tags=("reasoning",))])
    orchestrator.run([{"role": "user", "content": "seed a run"}])
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/v1/spend_analytics/latest",
        headers={"authorization": f"Bearer {token}", "connection": "close"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            status, body = response.status, json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
    assert status == 200
    assert body["measurement_status"] == "local_runtime_estimate"
    assert body["totals"]["run_count"] == 1


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
