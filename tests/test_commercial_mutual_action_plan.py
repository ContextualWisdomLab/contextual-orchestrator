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
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def milestone_by_name(report: dict[str, object]) -> dict[str, dict[str, object]]:
    return {str(row["milestone_name"]): row for row in report["milestones"]}


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
        [{"role": "user", "content": "Prepare the KRW 2B buyer seller mutual action plan."}],
        mode="conduct",
    )
    orchestrator.run_evaluation(["Replay this mutual action plan prompt."], mode="route")


def test_commercial_mutual_action_plan_report_packages_buyer_seller_execution() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    report = orchestrator.commercial_mutual_action_plan_report(
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
    milestones = milestone_by_name(report)

    assert report["mutual_action_plan_status"] == "commercial_mutual_action_plan_ready_with_warnings"
    assert report["target_contract_value_krw"] == TARGET_CONTRACT_VALUE_KRW
    assert report["measurement_status"] == "local_commercial_mutual_action_plan"
    assert report["go_no_go_recommendation"]["recommendation_status"] == "execute_with_buyer_conditions"
    assert "not a valuation guarantee" in report["source_note"]
    assert report["plan_summary"]["milestone_count"] == 8
    assert report["plan_summary"]["ready_count"] == 6
    assert report["plan_summary"]["warning_count"] == 2
    assert report["plan_summary"]["blocked_count"] == 0
    assert report["plan_summary"]["review_process_is_blocker"] is False
    assert report["plan_summary"]["code_connect_used"] is False
    assert report["concrete_blockers"] == []
    for milestone_name in [
        "saleability_gate",
        "investment_committee_memo",
        "buyer_close_packet",
        "legal_procurement_path",
        "implementation_onboarding",
        "operations_handoff",
    ]:
        assert milestones[milestone_name]["completion_state"] == "ready"
    assert milestones["buyer_authority_confirmation"]["completion_state"] == "warning"
    assert milestones["production_external_evidence"]["completion_state"] == "warning"
    assert "/api/v1/commercial_mutual_action_plans/latest" in report["required_runtime_endpoints"]
    assert "/api/v1/commercial_saleability_gates/latest" in report["required_runtime_endpoints"]
    assert "Buyer sponsor" in report["buyer_seller_owners"]["buyer"]
    assert "Implementation owner" in report["buyer_seller_owners"]["seller"]
    assert report["exit_criteria"] == [
        "No concrete product, API, security, runtime, or document blocker remains.",
        "Buyer final authority is supplied or explicitly waived.",
        "Production telemetry and third-party evidence plan is accepted.",
    ]
    assert report["metric_provenance"]["measured_local_sources"] == [
        "/api/v1/commercial_saleability_gates/latest",
        "/api/v1/commercial_investment_committee_memos/latest",
        "/api/v1/analytics_snapshots/latest",
    ]
    assert report["operator_next_actions"] == [
        "Send the mutual action plan to buyer and seller owners.",
        "Assign dates and evidence owners to the buyer authority milestones.",
        "Attach production telemetry and third-party evidence after environment selection.",
    ]
    assert report["related_runtime_reports"]["saleability_gate_status"] == (
        "commercial_saleability_gate_ready_with_warnings"
    )
    assert report["library_split_decision"]["decision"] == "keep_single_product"
    assert report["plan_links"]["runtime_endpoint"] == "/api/v1/commercial_mutual_action_plans/latest"


def test_commercial_mutual_action_plan_endpoint_openapi_admin_and_docs_contract() -> None:
    assert "/api/v1/commercial_mutual_action_plans/latest" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/api/v1/commercial_mutual_action_plans/latest"]["get"]["operationId"] == (
        "get_latest_commercial_mutual_action_plan"
    )
    assert "/api/v1/commercial_mutual_action_plans/latest" in ADMIN_HTML
    assert "commercial_mutual_action_plan_title" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_mutual_action_plan_title" in ADMIN_TRANSLATIONS["ko"]
    assert "commercial_mutual_action_plan_ready_with_warnings" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_mutual_action_plan_ready_with_warnings" in ADMIN_TRANSLATIONS["ko"]

    plan_doc = Path("docs/commercial_mutual_action_plan.md").read_text(encoding="utf-8")
    for expected_text in [
        "Commercial Mutual Action Plan",
        "Runtime endpoint: `/api/v1/commercial_mutual_action_plans/latest`",
        "Runtime Shape",
        "Action Plan Status Rules",
        "KRW 2B Commercial Mutual Action Plan",
        "local_commercial_mutual_action_plan",
        "Figma Code Connect is not used",
        "Review process is not a blocker",
        "Do not create a separate library, Git submodule, or extracted package now",
    ]:
        assert expected_text in plan_doc

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
            f"http://127.0.0.1:{port}/api/v1/commercial_mutual_action_plans/latest",
            "inference_secret",
        )
        plan_status, plan = get_json(
            f"http://127.0.0.1:{port}/api/v1/commercial_mutual_action_plans/latest",
            "admin_secret",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert unauth_status == 401
    assert unauth_body["error"]["code"] == "unauthorized"
    assert plan_status == 200
    assert plan["mutual_action_plan_status"] in {
        "commercial_mutual_action_plan_ready",
        "commercial_mutual_action_plan_ready_with_warnings",
        "commercial_mutual_action_plan_blocked",
    }
    assert plan["measurement_status"] == "local_commercial_mutual_action_plan"
    assert "milestones" in plan


if __name__ == "__main__":  # pragma: no cover
    test_commercial_mutual_action_plan_report_packages_buyer_seller_execution()
    test_commercial_mutual_action_plan_endpoint_openapi_admin_and_docs_contract()
    print("ok")
