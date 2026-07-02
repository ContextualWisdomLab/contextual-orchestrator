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
    return {str(row["item_name"]): row for row in report["go_to_market_items"]}


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
        [{"role": "user", "content": "Prepare KRW 2B go-to-market packet and separate external proof gaps."}],
        mode="conduct",
    )
    orchestrator.run_evaluation(["Replay this commercial GTM readiness prompt."], mode="route")


def test_commercial_go_to_market_readiness_report_indexes_sellable_packet_and_followups() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    report = orchestrator.commercial_go_to_market_readiness_report(
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

    assert report["go_to_market_status"] == "commercial_go_to_market_ready_with_warnings"
    assert report["target_contract_value_krw"] == TARGET_CONTRACT_VALUE_KRW
    assert report["measurement_status"] == "local_commercial_go_to_market_readiness"
    assert "not a valuation guarantee" in report["source_note"]
    assert "revenue proof" in report["source_note"]
    assert report["go_to_market_summary"]["blocked_count"] == 0
    assert report["go_to_market_summary"]["warning_count"] == 2
    assert report["go_to_market_summary"]["buyer_signature_gap_count"] == 4
    assert report["go_to_market_summary"]["external_or_production_gap_count"] == 5
    assert report["go_to_market_summary"]["review_process_is_blocker"] is False
    assert report["concrete_blockers"] == []
    for item_name in [
        "commercial_close_packet",
        "economic_value_packet",
        "security_trust_packet",
        "buyer_evidence_packet",
        "saleability_decision_packet",
        "admin_operator_evidence",
        "analytics_truthfulness_packet",
        "stakeholder_artifacts_packet",
    ]:
        assert items[item_name]["completion_state"] == "ready"
    assert items["buyer_signature_budget_follow_up"]["completion_state"] == "warning"
    assert items["buyer_signature_budget_follow_up"]["source_gap_status"] == "buyer_signature_required"
    assert items["production_external_proof_follow_up"]["completion_state"] == "warning"
    assert items["production_external_proof_follow_up"]["source_gap_status"] == (
        "external_or_production_input_required"
    )
    assert items["packaging_decision"]["completion_state"] == "ready"
    assert report["related_runtime_reports"]["commercial_close_status"] == "commercial_close_ready_with_warnings"
    assert report["library_split_decision"]["decision"] == "keep_single_product"
    assert report["go_to_market_links"]["runtime_endpoint"] == "/api/v1/commercial_go_to_market_readiness/latest"


def test_commercial_go_to_market_readiness_endpoint_openapi_admin_and_docs_contract() -> None:
    assert "/api/v1/commercial_go_to_market_readiness/latest" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/api/v1/commercial_go_to_market_readiness/latest"]["get"]["operationId"] == (
        "get_latest_commercial_go_to_market_readiness"
    )
    assert "/api/v1/commercial_go_to_market_readiness/latest" in ADMIN_HTML
    assert "commercial_go_to_market_readiness_title" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_go_to_market_readiness_title" in ADMIN_TRANSLATIONS["ko"]
    assert "commercial_go_to_market_ready_with_warnings" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_go_to_market_ready_with_warnings" in ADMIN_TRANSLATIONS["ko"]

    gtm_doc = Path("docs/commercial_go_to_market_readiness.md").read_text(encoding="utf-8")
    for expected_text in [
        "Commercial Go-To-Market Readiness",
        "KRW 2,000,000,000",
        "Figma Code Connect is not used",
        "Review process is not a blocker",
        "Do not create a separate library, Git submodule, or extracted package now",
        "Go-To-Market Inputs",
        "Runtime Shape",
        "Go-To-Market Status Rules",
        "KRW 2B Commercial Go To Market Readiness",
        "/api/v1/commercial_go_to_market_readiness/latest",
        "local_commercial_go_to_market_readiness",
    ]:
        assert expected_text in gtm_doc

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
            f"http://127.0.0.1:{port}/api/v1/commercial_go_to_market_readiness/latest",
            "inference_secret",
        )
        gtm_status, gtm = get_json(
            f"http://127.0.0.1:{port}/api/v1/commercial_go_to_market_readiness/latest",
            "admin_secret",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert unauth_status == 401
    assert unauth_body["error"]["code"] == "unauthorized"
    assert gtm_status == 200
    assert gtm["go_to_market_status"] in {
        "commercial_go_to_market_ready",
        "commercial_go_to_market_ready_with_warnings",
        "commercial_go_to_market_blocked",
    }
    assert gtm["measurement_status"] == "local_commercial_go_to_market_readiness"
    assert "go_to_market_items" in gtm


if __name__ == "__main__":  # pragma: no cover
    test_commercial_go_to_market_readiness_report_indexes_sellable_packet_and_followups()
    test_commercial_go_to_market_readiness_endpoint_openapi_admin_and_docs_contract()
    print("ok")
