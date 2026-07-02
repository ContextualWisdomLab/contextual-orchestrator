from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.admin import ADMIN_HTML, ADMIN_TRANSLATIONS  # noqa: E402
from contextual_orchestrator.api_contract import OPENAPI_SPEC  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent("planner_agent", "mock-planner", tags=("planning", "reasoning")),
            ModelAgent("builder_agent", "mock-builder", tags=("coding", "implementation")),
            ModelAgent("reviewer_agent", "mock-reviewer", tags=("verification", "security", "review")),
        ]
    )


def post_json(url: str, payload: dict[str, object], token: str) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def get_json(url: str, token: str) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(
        url,
        headers={"authorization": f"Bearer {token}", "connection": "close"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def by_name(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(row["metric_name"]): row for row in rows}


def test_analytics_snapshot_measures_runtime_kpis_and_guardrails() -> None:
    orchestrator = build()
    orchestrator.record_analytics_event(
        "chat_completion_requested",
        {
            "endpoint_path": "/v1/chat/completions",
            "actor_scope": "inference",
            "status_code": 200,
            "duration_ms": 12,
        },
    )
    orchestrator.run([{"role": "user", "content": "Route a short request."}], mode="route")
    orchestrator.run(
        [{"role": "user", "content": "Analyze the architecture, implement it, verify it, then synthesize."}],
        mode="conduct",
    )
    orchestrator.run_evaluation(["Replay this before rollout."], mode="route")

    snapshot = orchestrator.analytics_snapshot(locale_bundles=ADMIN_TRANSLATIONS)
    kpis = by_name(snapshot["kpis"])
    drivers = by_name(snapshot["drivers"])
    guardrails = by_name(snapshot["guardrails"])

    assert snapshot["measurement_status"] == "local_runtime_snapshot"
    assert "not production telemetry" in snapshot["source_note"]
    assert kpis["compatible_api_adoption"]["value"] == 1
    assert kpis["trace_complete_workflow_rate"]["numerator"] == 1
    assert kpis["trace_complete_workflow_rate"]["denominator"] == 1
    assert kpis["trace_complete_workflow_rate"]["value_percent"] == 100.0
    assert kpis["policy_safe_routing_rate"]["value_percent"] == 100.0
    assert drivers["route_versus_conduct_mix"]["counts"]["route"] == 2
    assert drivers["route_versus_conduct_mix"]["counts"]["conduct"] == 1
    assert drivers["evaluation_replay_usage"]["value"] == 1
    assert guardrails["provider_exclusion_miss_rate"]["value"] == 0
    assert guardrails["locale_key_parity"]["value_percent"] == 100.0


def test_analytics_endpoint_and_admin_console_use_source_backed_snapshot() -> None:
    assert "/api/v1/analytics_snapshots/latest" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/api/v1/analytics_snapshots/latest"]["get"]["operationId"] == (
        "get_latest_analytics_snapshot"
    )
    assert "/api/v1/analytics_snapshots/latest" in ADMIN_HTML
    assert "trace_complete_workflow_rate" in ADMIN_HTML
    assert "provider_exclusion_miss_rate" in ADMIN_HTML

    server = build_server(build(), port=0, security=SecurityConfig(auth_token="secret_token"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    try:
        chat_status, _ = post_json(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            {"messages": [{"role": "user", "content": "hello"}]},
            "secret_token",
        )
        snapshot_status, snapshot = get_json(
            f"http://127.0.0.1:{port}/api/v1/analytics_snapshots/latest",
            "secret_token",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    kpis = by_name(snapshot["kpis"])
    assert chat_status == 200
    assert snapshot_status == 200
    assert snapshot["measurement_status"] == "local_runtime_snapshot"
    assert kpis["compatible_api_adoption"]["value"] == 1


if __name__ == "__main__":  # pragma: no cover
    test_analytics_snapshot_measures_runtime_kpis_and_guardrails()
    test_analytics_endpoint_and_admin_console_use_source_backed_snapshot()
    print("ok")
