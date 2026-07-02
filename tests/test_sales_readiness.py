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


def criteria_by_name(report: dict[str, object]) -> dict[str, dict[str, object]]:
    return {str(row["criterion_name"]): row for row in report["criteria"]}


def exercise_runtime(orchestrator: TaskOrchestrator) -> None:
    orchestrator.record_analytics_event(
        "chat_completion_requested",
        {
            "endpoint_path": "/v1/chat/completions",
            "actor_scope": "inference",
            "status_code": 200,
            "duration_ms": 8,
        },
    )
    orchestrator.run(
        [{"role": "user", "content": "Analyze the product, implement the control plane, verify it, and summarize."}],
        mode="conduct",
    )
    orchestrator.run_evaluation(["Replay this sales readiness prompt."], mode="route")


def test_sales_readiness_report_marks_enterprise_pilot_ready() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    report = orchestrator.sales_readiness_report(
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile={
            "auth_mode": "split_token",
            "allow_public_bind": False,
            "expose_trace_by_default": False,
            "rate_limit_requests": 60,
            "max_concurrent_runs": 8,
        },
    )
    rows = criteria_by_name(report)

    assert report["readiness_status"] == "sales_ready"
    assert report["measurement_status"] == "local_runtime_snapshot"
    assert "not a production compliance certificate" in report["source_note"]
    assert report["summary"]["fail"] == 0
    assert report["summary"]["warn"] == 0
    assert {"api_compatibility", "admin_evidence", "trace_evidence", "evaluation_replay"}.issubset(rows)
    assert rows["security_posture"]["status"] == "pass"
    assert rows["analytics_truthfulness"]["status"] == "pass"
    assert rows["locale_readiness"]["status"] == "pass"
    assert rows["provider_egress_safety"]["status"] == "pass"
    for row in report["criteria"]:
        assert {"criterion_name", "status", "label", "evidence", "remediation"}.issubset(row)


def test_sales_readiness_warns_for_single_token_local_deployment() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    report = orchestrator.sales_readiness_report(
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile={
            "auth_mode": "single_token",
            "allow_public_bind": False,
            "expose_trace_by_default": False,
            "rate_limit_requests": 60,
            "max_concurrent_runs": 8,
        },
    )
    rows = criteria_by_name(report)

    assert report["readiness_status"] == "pilot_ready_with_warnings"
    assert report["summary"]["fail"] == 0
    assert rows["security_posture"]["status"] == "warn"
    assert "split admin and inference tokens" in rows["security_posture"]["remediation"]


def test_sales_readiness_endpoint_openapi_and_admin_surface() -> None:
    assert "/api/v1/sales_readiness/latest" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/api/v1/sales_readiness/latest"]["get"]["operationId"] == (
        "get_latest_sales_readiness"
    )
    assert "/api/v1/sales_readiness/latest" in ADMIN_HTML
    assert "sales_readiness" in ADMIN_HTML
    assert "sales_readiness_title" in ADMIN_TRANSLATIONS["en"]
    assert "sales_readiness_title" in ADMIN_TRANSLATIONS["ko"]

    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(admin_token="admin_secret", inference_token="inference_secret"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    try:
        chat_status, _ = post_json(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            {"messages": [{"role": "user", "content": "Analyze, verify, and summarize readiness."}]},
            "inference_secret",
        )
        readiness_status, readiness = get_json(
            f"http://127.0.0.1:{port}/api/v1/sales_readiness/latest",
            "admin_secret",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    rows = criteria_by_name(readiness)
    assert chat_status == 200
    assert readiness_status == 200
    assert readiness["measurement_status"] == "local_runtime_snapshot"
    assert rows["security_posture"]["status"] == "pass"
    assert rows["api_compatibility"]["status"] == "pass"


if __name__ == "__main__":  # pragma: no cover
    test_sales_readiness_report_marks_enterprise_pilot_ready()
    test_sales_readiness_warns_for_single_token_local_deployment()
    test_sales_readiness_endpoint_openapi_and_admin_surface()
    print("ok")
