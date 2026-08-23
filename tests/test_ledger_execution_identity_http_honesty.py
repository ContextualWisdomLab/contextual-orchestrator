"""Cost-ledger execution identity honesty: clients cannot spoof model/provider."""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import (
    CostLedger,
    CostRoutingCoordinator,
    InMemoryConfigStore,
    ModelAgent,
    PriceBook,
    PriceEntry,
    TaskOrchestrator,
)
from contextual_orchestrator.server import SecurityConfig, build_server

_TEST_AUTH_TOKEN = "ledger_execution_identity_http_honesty_token"  # noqa: S105


def _serve():
    agents = [
        ModelAgent(
            id="mock_worker",
            model="mock-a",
            base_url="mock://a",
            provider_name="mock",
            tags=("reasoning", "coding", "writing", "embedding"),
            priority=1,
        )
    ]
    orchestrator = TaskOrchestrator(agents)
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(PriceEntry("mock", "mock-a", prompt_price_per_1k=1.0, completion_price_per_1k=2.0))
    coordinator = CostRoutingCoordinator(orchestrator, config, price_book=price_book)
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN),
        coordinator=coordinator,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1], coordinator


def _request(method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
        "connection": "close",
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_http_chat_usage_rollups_ignore_spoofed_model_name() -> None:
    """Buyer-facing rollups must show the model that ran, not a client tag."""

    server, thread, port, _coord = _serve()
    base = f"http://127.0.0.1:{port}"
    try:
        status, body = _request(
            "POST",
            f"{base}/v1/chat/completions",
            {
                "model": "mock-a",
                "messages": [{"role": "user", "content": "invoice line item check"}],
                "attribution": {
                    "account": "buyer_account",
                    "model_name": "text-embedding-3-large",
                    "provider": "openai",
                    "team": "finance_ops",
                },
            },
        )
        assert status == 200, body

        status, report = _request(
            "GET",
            f"{base}/api/v1/cost_reports/rollup?dimension=model_name",
        )
        assert status == 200, report
        values = {item["dimension_value"] for item in report["items"]}
        assert "mock-a" in values, report
        assert "text-embedding-3-large" not in values, report

        status, report = _request(
            "GET",
            f"{base}/api/v1/cost_reports/rollup?dimension=team",
        )
        assert status == 200, report
        teams = {item["dimension_value"] for item in report["items"]}
        assert "finance_ops" in teams, report

        status, records = _request("GET", f"{base}/api/v1/llm_usage_records")
        assert status == 200, records
        assert records["total_count"] >= 1
        row = records["items"][0]
        assert row["model_name"] == "mock-a"
        assert row["provider_name"] == "mock"
        assert row["upstream_api"] == "mock"
        assert row["account_name"] == "buyer_account"
        assert row["team_name"] == "finance_ops"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_usage_ignores_spoofed_execution_identity() -> None:
    server, thread, port, _coord = _serve()
    base = f"http://127.0.0.1:{port}"
    try:
        status, body = _request(
            "POST",
            f"{base}/v1/embeddings",
            {
                "model": "mock-a",
                "input": "semantic search chunk for invoices",
                "attribution": {
                    "model_name": "text-embedding-3-large",
                    "provider": "openai",
                    "company": "acme_buyer",
                },
            },
        )
        assert status == 200, body

        status, records = _request("GET", f"{base}/api/v1/llm_usage_records")
        assert status == 200, records
        assert records["total_count"] >= 1
        # Find the embeddings channel row if mixed, else first.
        rows = records["items"]
        row = next(
            (r for r in rows if r.get("request_channel") in {"sync", "batch"} and r.get("model_name") == "mock-a"),
            rows[0],
        )
        assert row["model_name"] == "mock-a"
        assert "text-embedding-3-large" not in json.dumps(row)
        assert row["company_name"] == "acme_buyer"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_public_cost_ledger_ignores_spoofed_execution_identity() -> None:
    """Direct ledger callers cannot overwrite provider/model execution evidence."""

    config = InMemoryConfigStore()
    ledger = CostLedger(PriceBook(config))
    ledger.record_usage(
        provider="actual_provider",
        model="actual_model",
        prompt_tokens=10,
        completion_tokens=2,
        attribution={
            "account": "buyer_account",
            "model_name": "spoofed_model",
            "provider": "spoofed_provider",
            "upstream_api": "spoofed_provider",
        },
    )
    rows = ledger.store.query(None, None)
    assert len(rows) == 1
    assert rows[0]["model_name"] == "actual_model"
    assert rows[0]["provider_name"] == "actual_provider"
    assert rows[0]["upstream_api"] == "actual_provider"
    assert rows[0]["account_name"] == "buyer_account"


if __name__ == "__main__":
    test_public_cost_ledger_ignores_spoofed_execution_identity()
    test_http_chat_usage_rollups_ignore_spoofed_model_name()
    test_http_embeddings_usage_ignores_spoofed_execution_identity()
    print("ok")
