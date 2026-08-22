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


def test_http_spend_endpoint_returns_only_authenticated_owner() -> None:
    """Distinct verified bearers must not see each other's spend aggregates."""
    tokens = {"owner-a", "owner-b"}
    def verify(token: str, scope: str) -> bool | dict[str, str]:
        if scope == "principal":
            return {"iss": "https://issuer.example", "sub": token} if token in tokens else {}
        return token in tokens and scope == "admin"

    security = SecurityConfig(bearer_verifier=verify)
    orchestrator = TaskOrchestrator([ModelAgent("general_agent", "priced-model", tags=("reasoning",))])
    owner_a = security.principal_id({"authorization": "Bearer owner-a"})
    owner_b = security.principal_id({"authorization": "Bearer owner-b"})
    owner_a_run = orchestrator.run(
        [{"role": "user", "content": "owner a run"}], owner_id=owner_a
    )
    owner_b_first_run = orchestrator.run(
        [{"role": "user", "content": "owner b first run"}], owner_id=owner_b
    )
    owner_b_second_run = orchestrator.run(
        [{"role": "user", "content": "owner b second run"}], owner_id=owner_b
    )
    owner_a_run["trace"][0]["usage"] = {"prompt_tokens": 11, "completion_tokens": 3}
    owner_b_first_run["trace"][0]["usage"] = {
        "prompt_tokens": 17,
        "completion_tokens": 5,
    }
    owner_b_second_run["trace"][0]["usage"] = {
        "prompt_tokens": 23,
        "completion_tokens": 7,
    }
    server = build_server(orchestrator, port=0, security=security)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    def report(token: str, path: str) -> tuple[int, dict[str, object]]:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            headers={"authorization": f"Bearer {token}", "connection": "close"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    try:
        owner_a_status, owner_a_body = report("owner-a", "/api/v1/spend_analytics/latest")
        owner_b_status, owner_b_body = report("owner-b", "/api/v1/spend_analytics/latest")
        _, owner_a_admin = report("owner-a", "/admin/state")
        _, owner_b_admin = report("owner-b", "/admin/state")
        try:
            report(
                "owner-a",
                f"/api/v1/access_reports/{owner_b_first_run['workflow_run_id']}",
            )
        except urllib.error.HTTPError as error:
            assert error.code == 404
        _, owner_a_access_report = report(
            "owner-a", f"/api/v1/access_reports/{owner_a_run['workflow_run_id']}"
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert owner_a_status == owner_b_status == 200
    assert owner_a_body["measurement_status"] == "local_runtime_estimate"
    assert owner_a_body["totals"]["run_count"] == 1
    assert owner_b_body["totals"]["run_count"] == 2
    assert owner_a_body["totals"]["reported_prompt_tokens"] == 11
    assert owner_b_body["totals"]["reported_prompt_tokens"] == 40
    assert "owner-a" not in json.dumps(owner_a_body)
    assert "owner-b" not in json.dumps(owner_b_body)
    owner_a_audit = json.dumps(owner_a_admin["recent_audit_events"])
    owner_b_audit = json.dumps(owner_b_admin["recent_audit_events"])
    assert owner_a_run["workflow_run_id"] in owner_a_audit
    assert owner_b_first_run["workflow_run_id"] not in owner_a_audit
    assert owner_b_second_run["workflow_run_id"] not in owner_a_audit
    assert owner_a_run["workflow_run_id"] not in owner_b_audit
    assert owner_b_first_run["workflow_run_id"] in owner_b_audit
    assert owner_b_second_run["workflow_run_id"] in owner_b_audit
    assert owner_a_access_report["workflow_run_id"] == owner_a_run["workflow_run_id"]
    access_events = [
        event
        for event in orchestrator._analytics_events
        if event["event_name"] == "access_report_viewed"
    ]
    assert [event["event_detail"]["workflow_run_id"] for event in access_events] == [
        owner_a_run["workflow_run_id"]
    ]


def test_owner_spend_report_keeps_process_budget_global() -> None:
    """Owner filtering must not make a shared budget appear unexhausted."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "priced-model", tags=("reasoning",))],
        price_per_million={"priced-model": 10.0},
        budget_max_output_tokens=1000,
        budget_max_cost_usd=1.0,
    )
    orchestrator.run([{"role": "user", "content": "owner a spend"}], owner_id="owner_a")
    orchestrator.run([{"role": "user", "content": "owner b spend"}], owner_id="owner_b")

    global_budget = orchestrator.spend_analytics()["budget"]
    owner_budget = orchestrator.spend_analytics(owner_id="owner_a")["budget"]

    assert owner_budget == global_budget


def test_owner_spend_report_scans_runs_once() -> None:
    """Owner totals and the shared budget must come from one consistent run scan."""

    class CountingRunMap(dict):
        """Count complete values scans without changing mapping behavior."""

        values_call_count = 0

        def values(self):
            self.values_call_count += 1
            return super().values()

    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "priced-model", tags=("reasoning",))]
    )
    orchestrator.run([{"role": "user", "content": "owner a spend"}], owner_id="owner_a")
    orchestrator.run([{"role": "user", "content": "owner b spend"}], owner_id="owner_b")
    counted_runs = CountingRunMap(orchestrator._workflow_runs)
    orchestrator._workflow_runs = counted_runs

    orchestrator.spend_analytics(owner_id="owner_a")

    assert counted_runs.values_call_count == 1


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
