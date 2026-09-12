"""Authoritative per-model token and cost analytics."""

from __future__ import annotations

import json
import threading
import urllib.request

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.server import SecurityConfig, build_server
from contextual_orchestrator.token_counting import TokenCountUnavailable


class _ExactCounter:
    """Injected exact raw-output counter for synthetic fixtures."""

    def count_text(self, text: str, model: str) -> int:
        if model != "gpt-4":
            raise TokenCountUnavailable("unknown synthetic model")
        return len(text.encode("utf-8"))


def _orchestrator(*, price: float | None = None) -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "gpt-4", tags=("reasoning",))],
        price_per_million={"gpt-4": price} if price is not None else None,
        token_counter=_ExactCounter(),
    )


def test_exact_output_without_prompt_usage_is_explicitly_unavailable() -> None:
    orchestrator = _orchestrator()
    orchestrator.run([{"role": "user", "content": "account for this"}])
    report = orchestrator.spend_analytics()
    row = report["by_model"][0]

    assert report["measurement_status"] == "unavailable"
    assert report["totals"]["output_tokens"] > 0
    assert report["totals"]["prompt_tokens"] is None
    assert report["totals"]["cost_usd"] is None
    assert row["usage_source"] == "tokenizer"
    assert row["cost_usd"] is None
    assert not any("estimated" in key for key in row | report["totals"])


def test_exact_output_cost_uses_operator_price() -> None:
    orchestrator = _orchestrator(price=10.0)
    orchestrator.run([{"role": "user", "content": "calculate exact output cost"}])
    report = orchestrator.spend_analytics()
    row = report["by_model"][0]
    expected = row["output_tokens"] / 1_000_000 * 10.0
    assert row["cost_usd"] == expected
    assert report["totals"]["cost_usd"] == expected


def test_empty_analytics_are_zero_not_estimated() -> None:
    report = _orchestrator().spend_analytics()
    assert report["totals"]["run_count"] == 0
    assert report["totals"]["output_tokens"] == 0
    assert report["by_model"] == []


def test_http_spend_endpoint_preserves_unavailable_status() -> None:
    token = "spend_token"
    orchestrator = _orchestrator()
    orchestrator.run([{"role": "user", "content": "seed a run"}])
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}/api/v1/spend_analytics/latest",
        headers={"authorization": f"Bearer {token}", "connection": "close"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            status, body = response.status, json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
    assert status == 200
    assert body["measurement_status"] == "unavailable"
    assert body["totals"]["prompt_tokens"] is None
