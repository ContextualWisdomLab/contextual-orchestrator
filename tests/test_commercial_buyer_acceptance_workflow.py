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


def step_by_name(report: dict[str, object]) -> dict[str, dict[str, object]]:
    return {str(row["step_name"]): row for row in report["acceptance_steps"]}


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
        [{"role": "user", "content": "Run the KRW 2B buyer acceptance workflow and summarize go/no-go evidence."}],
        mode="conduct",
    )
    orchestrator.run_evaluation(["Replay this buyer acceptance workflow prompt."], mode="route")


def test_commercial_buyer_acceptance_workflow_report_maps_runbook_steps() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    report = orchestrator.commercial_buyer_acceptance_workflow_report(
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
    steps = step_by_name(report)

    assert report["workflow_status"] == "buyer_acceptance_workflow_ready_with_warnings"
    assert report["target_contract_value_krw"] == TARGET_CONTRACT_VALUE_KRW
    assert report["measurement_status"] == "local_buyer_acceptance_workflow"
    assert "not a valuation guarantee" in report["source_note"]
    assert report["workflow_summary"]["blocked_count"] == 0
    assert report["workflow_summary"]["warning_count"] == 2
    assert report["workflow_summary"]["review_process_is_blocker"] is False
    assert report["workflow_summary"]["code_connect_used"] is False
    assert report["concrete_blockers"] == []
    for step_name in [
        "confirm_product_scope",
        "confirm_integration_surface",
        "confirm_operator_evidence",
        "confirm_readiness_endpoints",
        "confirm_security_posture",
        "confirm_metric_honesty",
        "confirm_visual_review_path",
        "confirm_packaging_decision",
    ]:
        assert steps[step_name]["completion_state"] == "ready"
    assert steps["confirm_production_inputs"]["completion_state"] == "warning"
    assert steps["confirm_buyer_specific_inputs"]["completion_state"] == "warning"
    assert steps["confirm_buyer_specific_inputs"]["evidence_type"] == "proposed_until_buyer_specific"
    assert report["related_runtime_reports"]["commercial_acceptance_status"] == "commercial_acceptance_ready_with_warnings"
    assert report["related_runtime_reports"]["commercial_completion_status"] == "commercial_completion_ready_with_warnings"
    assert report["library_split_decision"]["decision"] == "keep_single_product"
    assert report["workflow_links"]["runtime_endpoint"] == "/api/v1/commercial_buyer_acceptance_workflows/latest"


def test_commercial_buyer_acceptance_workflow_endpoint_openapi_admin_and_docs_contract() -> None:
    assert "/api/v1/commercial_buyer_acceptance_workflows/latest" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/api/v1/commercial_buyer_acceptance_workflows/latest"]["get"]["operationId"] == (
        "get_latest_commercial_buyer_acceptance_workflow"
    )
    assert "/api/v1/commercial_buyer_acceptance_workflows/latest" in ADMIN_HTML
    assert "commercial_buyer_acceptance_workflow_title" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_buyer_acceptance_workflow_title" in ADMIN_TRANSLATIONS["ko"]
    assert "buyer_acceptance_workflow_ready_with_warnings" in ADMIN_TRANSLATIONS["en"]
    assert "buyer_acceptance_workflow_ready_with_warnings" in ADMIN_TRANSLATIONS["ko"]

    runbook_doc = Path("docs/commercial_buyer_acceptance_runbook.md").read_text(encoding="utf-8")
    for expected_text in [
        "Commercial Buyer Acceptance Runbook",
        "Runtime Shape",
        "Workflow Status Rules",
        "KRW 2B Buyer Acceptance Runtime Workflow",
        "/api/v1/commercial_buyer_acceptance_workflows/latest",
        "local_buyer_acceptance_workflow",
        "Figma Code Connect is not used",
        "Review process is not a blocker",
        "Do not create a separate library, Git submodule, or extracted package now",
    ]:
        assert expected_text in runbook_doc

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
            f"http://127.0.0.1:{port}/api/v1/commercial_buyer_acceptance_workflows/latest",
            "inference_secret",
        )
        workflow_status, workflow = get_json(
            f"http://127.0.0.1:{port}/api/v1/commercial_buyer_acceptance_workflows/latest",
            "admin_secret",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert unauth_status == 401
    assert unauth_body["error"]["code"] == "unauthorized"
    assert workflow_status == 200
    assert workflow["workflow_status"] in {
        "buyer_acceptance_workflow_ready",
        "buyer_acceptance_workflow_ready_with_warnings",
        "buyer_acceptance_workflow_blocked",
    }
    assert workflow["measurement_status"] == "local_buyer_acceptance_workflow"
    assert "acceptance_steps" in workflow


if __name__ == "__main__":  # pragma: no cover
    test_commercial_buyer_acceptance_workflow_report_maps_runbook_steps()
    test_commercial_buyer_acceptance_workflow_endpoint_openapi_admin_and_docs_contract()
    print("ok")
