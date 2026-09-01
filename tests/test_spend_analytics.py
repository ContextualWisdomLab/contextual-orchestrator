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
    # Cost is billed on output_tokens (provider-reported usage when available,
    # e.g. from a real realtime judge call, else the text estimate) -- not on
    # estimated_output_tokens, which stays a text-length estimate even when a
    # judge call reports real usage that diverges from it (see
    # test_spend_analytics_bills_reported_judge_usage_not_its_text_estimate).
    expected = round(row["output_tokens"] / 1_000_000 * 10.0, 6)
    assert row["estimated_cost_usd"] == expected
    assert report["totals"]["estimated_cost_usd"] == expected  # single priced model
    assert report["unpriced_models"] == []


def test_spend_analytics_bills_reported_judge_usage_not_its_text_estimate() -> None:
    """A realtime judge's reported usage can diverge from its own text-length estimate.

    ``spend_analytics`` folds a completed judge call's usage into the same
    per-model bucket as its worker steps (honest accounting: a real judge
    call is a real incurred cost). When the judge's provider-reported
    ``completion_tokens`` differs from ``estimate_tokens(judge_output_text)``
    -- as happens whenever a real fast-mlsirm judge call is exercised, only
    possible where that optional native dependency is actually installed --
    ``estimated_output_tokens`` (a text-length estimate, purely informational)
    and ``output_tokens`` (the actual billing basis) must diverge too, and
    cost must track ``output_tokens``, never the estimate. This is the exact
    field this repo's own CI hit and a machine without fast-mlsirm installed
    cannot reproduce locally.
    """
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "priced-model", tags=("reasoning",))],
        price_per_million={"priced-model": 10.0},
    )
    worker_output = "worker answer"
    judge_text = "judge rationale, much longer than its reported token count"
    orchestrator._replace_workflow_run(
        {
            "workflow_run_id": "run_judge_usage_divergence",
            "prompt_text": "compute my cost please",
            "trace": [
                {
                    "id": 0,
                    "role": "worker",
                    "agent_id": "general_agent",
                    "output": worker_output,
                },
            ],
            "verification": {
                "judge_agent_id": "general_agent",
                "judge_model": "priced-model",
                "judge_usage": {"completion_tokens": 3},
                "judge_output_text": judge_text,
            },
        }
    )
    report = orchestrator.spend_analytics()

    row = next(r for r in report["by_model"] if r["model"] == "priced-model")
    worker_tokens = estimate_tokens(worker_output)
    judge_text_estimate = estimate_tokens(judge_text)
    assert row["estimated_output_tokens"] == worker_tokens + judge_text_estimate
    assert row["output_tokens"] == worker_tokens + 3
    assert row["output_tokens"] != row["estimated_output_tokens"]
    expected = round(row["output_tokens"] / 1_000_000 * 10.0, 6)
    assert row["estimated_cost_usd"] == expected
    assert report["totals"]["estimated_cost_usd"] == expected


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
