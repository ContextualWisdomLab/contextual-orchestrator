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


TARGET_CONTRACT_VALUE_KRW = 2_000_000_000


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent("planner_agent", "mock-planner", tags=("planning", "reasoning")),
            ModelAgent("builder_agent", "mock-builder", tags=("coding", "implementation")),
            ModelAgent("reviewer_agent", "mock-reviewer", tags=("verification", "security", "review")),
        ]
    )


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


def item_by_name(report: dict[str, object]) -> dict[str, dict[str, object]]:
    return {str(row["item_name"]): row for row in report["operations_items"]}


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
        [{"role": "user", "content": "Prepare operations handoff evidence, identify production gaps, verify it."}],
        mode="conduct",
    )
    orchestrator.run_evaluation(["Replay this commercial operations readiness prompt."], mode="route")


def test_commercial_operations_readiness_report_tracks_operations_handoff_warnings() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    report = orchestrator.commercial_operations_readiness_report(
        target_contract_value_krw=TARGET_CONTRACT_VALUE_KRW,
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile={
            "auth_mode": "split_token",
            "allow_public_bind": False,
            "expose_trace_by_default": False,
            "rate_limit_requests": 60,
            "max_concurrent_runs": 8,
        },
    )
    items = item_by_name(report)

    assert report["operations_status"] == "commercial_operations_ready_with_warnings"
    assert report["target_contract_value_krw"] == TARGET_CONTRACT_VALUE_KRW
    assert report["measurement_status"] == "local_commercial_operations_readiness"
    assert "not a valuation guarantee" in report["source_note"]
    assert report["operations_summary"]["blocked_count"] == 0
    assert report["operations_summary"]["warning_count"] == 4
    assert report["operations_summary"]["production_evidence_action_count"] == 4
    assert report["operations_summary"]["review_process_is_blocker"] is False
    assert report["concrete_blockers"] == []
    assert items["deployment_runbook"]["completion_state"] == "ready"
    assert items["security_legal_handoff"]["completion_state"] == "ready"
    assert items["monitoring_telemetry_capture"]["completion_state"] == "warning"
    assert items["monitoring_telemetry_capture"]["source_gap_status"] == "production_input_required"
    assert items["incident_rollback_plan"]["completion_state"] == "warning"
    assert items["backup_recovery_plan"]["completion_state"] == "warning"
    assert items["support_slo_ownership"]["completion_state"] == "warning"
    assert report["related_runtime_reports"]["commercial_onboarding_status"] == "commercial_onboarding_ready_with_warnings"
    assert report["library_split_decision"]["decision"] == "keep_single_product"
    assert report["operations_links"]["runtime_endpoint"] == "/api/v1/commercial_operations_readiness/latest"


def test_commercial_operations_readiness_endpoint_openapi_admin_and_docs_contract() -> None:
    assert "/api/v1/commercial_operations_readiness/latest" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/api/v1/commercial_operations_readiness/latest"]["get"]["operationId"] == (
        "get_latest_commercial_operations_readiness"
    )
    assert "/api/v1/commercial_operations_readiness/latest" in ADMIN_HTML
    assert "commercial_operations_readiness_title" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_operations_readiness_title" in ADMIN_TRANSLATIONS["ko"]
    assert "commercial_operations_ready_with_warnings" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_operations_ready_with_warnings" in ADMIN_TRANSLATIONS["ko"]

    operations_doc = Path("docs/commercial_operations_readiness.md").read_text(encoding="utf-8")
    assert "Commercial Operations Readiness" in operations_doc
    assert "/api/v1/commercial_operations_readiness/latest" in operations_doc
    assert "KRW 2B Commercial Operations Readiness" in operations_doc
    assert "Figma Code Connect is not used" in operations_doc
    assert "Review process is not a blocker" in operations_doc
    assert "Do not create a separate library, Git submodule, or extracted package now" in operations_doc

    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(admin_token="admin_secret", inference_token="inference_secret"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    try:
        unauth_status, unauth_body = get_json(
            f"http://127.0.0.1:{port}/api/v1/commercial_operations_readiness/latest",
            "inference_secret",
        )
        operations_status, operations = get_json(
            f"http://127.0.0.1:{port}/api/v1/commercial_operations_readiness/latest",
            "admin_secret",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert unauth_status == 401
    assert unauth_body["error"]["code"] == "unauthorized"
    assert operations_status == 200
    assert operations["operations_status"] in {
        "commercial_operations_ready",
        "commercial_operations_ready_with_warnings",
        "commercial_operations_blocked",
    }
    assert operations["measurement_status"] == "local_commercial_operations_readiness"
    assert "operations_items" in operations


if __name__ == "__main__":  # pragma: no cover
    test_commercial_operations_readiness_report_tracks_operations_handoff_warnings()
    test_commercial_operations_readiness_endpoint_openapi_admin_and_docs_contract()
    print("ok")
