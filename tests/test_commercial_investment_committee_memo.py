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


def section_by_name(report: dict[str, object]) -> dict[str, dict[str, object]]:
    return {str(row["section_name"]): row for row in report["memo_sections"]}


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
        [{"role": "user", "content": "Prepare an investment committee memo for a KRW 2B commercial purchase."}],
        mode="conduct",
    )
    orchestrator.run_evaluation(["Replay this investment committee memo prompt."], mode="route")


def test_commercial_investment_committee_memo_report_packages_executive_decision() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    report = orchestrator.commercial_investment_committee_memo_report(
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
    sections = section_by_name(report)

    assert report["investment_committee_status"] == "commercial_investment_committee_ready_with_warnings"
    assert report["target_contract_value_krw"] == TARGET_CONTRACT_VALUE_KRW
    assert report["measurement_status"] == "local_commercial_investment_committee_memo"
    assert report["executive_recommendation"]["recommendation_status"] == "recommend_with_buyer_conditions"
    assert "not a valuation guarantee" in report["source_note"]
    assert report["memo_summary"]["blocked_count"] == 0
    assert report["memo_summary"]["warning_count"] == 2
    assert report["memo_summary"]["section_count"] == 10
    assert report["memo_summary"]["review_process_is_blocker"] is False
    assert report["memo_summary"]["code_connect_used"] is False
    assert report["concrete_blockers"] == []
    for section_name in [
        "executive_recommendation",
        "diligence_room_ready",
        "purchase_approval_ready",
        "financial_case",
        "risk_and_security_summary",
        "commercial_terms_summary",
        "implementation_readiness_summary",
        "design_and_figma_review",
    ]:
        assert sections[section_name]["completion_state"] == "ready"
    assert sections["buyer_final_authority"]["completion_state"] == "warning"
    assert sections["production_external_evidence"]["completion_state"] == "warning"
    assert "/api/v1/commercial_investment_committee_memos/latest" in report["required_runtime_endpoints"]
    assert "/api/v1/commercial_due_diligence_rooms/latest" in report["required_runtime_endpoints"]
    assert "/api/v1/commercial_purchase_approval_packets/latest" in report["required_runtime_endpoints"]
    assert report["committee_decision_questions"] == [
        "Is the product evidence sufficient for KRW 2B buyer review?",
        "Are buyer authority documents named and tracked?",
        "Are production and third-party evidence gaps explicit warnings?",
        "Is any concrete blocker present?",
    ]
    assert report["related_runtime_reports"]["commercial_due_diligence_status"] == (
        "commercial_due_diligence_ready_with_warnings"
    )
    assert report["library_split_decision"]["decision"] == "keep_single_product"
    assert report["committee_links"]["runtime_endpoint"] == "/api/v1/commercial_investment_committee_memos/latest"


def test_commercial_investment_committee_memo_endpoint_openapi_admin_and_docs_contract() -> None:
    assert "/api/v1/commercial_investment_committee_memos/latest" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/api/v1/commercial_investment_committee_memos/latest"]["get"]["operationId"] == (
        "get_latest_commercial_investment_committee_memo"
    )
    assert "/api/v1/commercial_investment_committee_memos/latest" in ADMIN_HTML
    assert "commercial_investment_committee_memo_title" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_investment_committee_memo_title" in ADMIN_TRANSLATIONS["ko"]
    assert "commercial_investment_committee_ready_with_warnings" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_investment_committee_ready_with_warnings" in ADMIN_TRANSLATIONS["ko"]

    memo_doc = Path("docs/commercial_investment_committee_memo.md").read_text(encoding="utf-8")
    for expected_text in [
        "Commercial Investment Committee Memo",
        "Runtime endpoint: `/api/v1/commercial_investment_committee_memos/latest`",
        "Runtime Shape",
        "Investment Committee Status Rules",
        "KRW 2B Commercial Investment Committee Memo",
        "local_commercial_investment_committee_memo",
        "Figma Code Connect is not used",
        "Review process is not a blocker",
        "Do not create a separate library, Git submodule, or extracted package now",
    ]:
        assert expected_text in memo_doc

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
            f"http://127.0.0.1:{port}/api/v1/commercial_investment_committee_memos/latest",
            "inference_secret",
        )
        memo_status, memo = get_json(
            f"http://127.0.0.1:{port}/api/v1/commercial_investment_committee_memos/latest",
            "admin_secret",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert unauth_status == 401
    assert unauth_body["error"]["code"] == "unauthorized"
    assert memo_status == 200
    assert memo["investment_committee_status"] in {
        "commercial_investment_committee_ready",
        "commercial_investment_committee_ready_with_warnings",
        "commercial_investment_committee_blocked",
    }
    assert memo["measurement_status"] == "local_commercial_investment_committee_memo"
    assert "memo_sections" in memo


if __name__ == "__main__":  # pragma: no cover
    test_commercial_investment_committee_memo_report_packages_executive_decision()
    test_commercial_investment_committee_memo_endpoint_openapi_admin_and_docs_contract()
    print("ok")
