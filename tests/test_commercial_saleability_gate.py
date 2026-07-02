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


def check_by_name(report: dict[str, object]) -> dict[str, dict[str, object]]:
    return {str(row["check_name"]): row for row in report["gate_checks"]}


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
        [{"role": "user", "content": "Prepare the final KRW 2B commercial saleability gate."}],
        mode="conduct",
    )
    orchestrator.run_evaluation(["Replay this commercial saleability gate prompt."], mode="route")


def test_commercial_saleability_gate_report_packages_final_go_no_go() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    report = orchestrator.commercial_saleability_gate_report(
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
    checks = check_by_name(report)

    assert report["saleability_gate_status"] == "commercial_saleability_gate_ready_with_warnings"
    assert report["target_contract_value_krw"] == TARGET_CONTRACT_VALUE_KRW
    assert report["measurement_status"] == "local_commercial_saleability_gate"
    assert report["go_no_go_recommendation"]["recommendation_status"] == "go_with_buyer_conditions"
    assert "not a valuation guarantee" in report["source_note"]
    assert report["gate_summary"]["blocked_count"] == 0
    assert report["gate_summary"]["warning_count"] == 2
    assert report["gate_summary"]["check_count"] == 9
    assert report["gate_summary"]["review_process_is_blocker"] is False
    assert report["gate_summary"]["code_connect_used"] is False
    assert report["concrete_blockers"] == []
    for check_name in [
        "saleability_decision",
        "investment_committee_memo",
        "due_diligence_room",
        "purchase_approval_packet",
        "close_and_terms",
        "metric_provenance",
        "figma_design_review",
    ]:
        assert checks[check_name]["completion_state"] == "ready"
    assert checks["buyer_final_authority"]["completion_state"] == "warning"
    assert checks["production_external_evidence"]["completion_state"] == "warning"
    assert "/api/v1/commercial_saleability_gates/latest" in report["required_runtime_endpoints"]
    assert "/api/v1/saleability_decisions/latest" in report["required_runtime_endpoints"]
    assert "/api/v1/commercial_investment_committee_memos/latest" in report["required_runtime_endpoints"]
    assert "docs/commercial_saleability_gate.md" in report["buyer_close_packet"]["documents"]
    assert report["metric_provenance"]["measured_local_sources"] == [
        "/api/v1/saleability_decisions/latest",
        "/api/v1/commercial_investment_committee_memos/latest",
        "/api/v1/analytics_snapshots/latest",
    ]
    assert report["metric_provenance"]["proposed_sources"] == [
        "buyer final authority",
        "production telemetry",
        "third-party security attestation",
    ]
    assert report["operator_next_actions"] == [
        "Share the commercial saleability gate with the economic buyer and committee owner.",
        "Collect final buyer authority artifacts or an explicit waiver.",
        "Collect production telemetry and third-party security evidence after environment selection.",
    ]
    assert report["related_runtime_reports"]["saleability_status"] == "saleability_ready_with_warnings"
    assert report["related_runtime_reports"]["investment_committee_status"] == (
        "commercial_investment_committee_ready_with_warnings"
    )
    assert report["library_split_decision"]["decision"] == "keep_single_product"
    assert report["gate_links"]["runtime_endpoint"] == "/api/v1/commercial_saleability_gates/latest"


def test_commercial_saleability_gate_endpoint_openapi_admin_and_docs_contract() -> None:
    assert "/api/v1/commercial_saleability_gates/latest" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/api/v1/commercial_saleability_gates/latest"]["get"]["operationId"] == (
        "get_latest_commercial_saleability_gate"
    )
    assert "/api/v1/commercial_saleability_gates/latest" in ADMIN_HTML
    assert "commercial_saleability_gate_title" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_saleability_gate_title" in ADMIN_TRANSLATIONS["ko"]
    assert "commercial_saleability_gate_ready_with_warnings" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_saleability_gate_ready_with_warnings" in ADMIN_TRANSLATIONS["ko"]

    gate_doc = Path("docs/commercial_saleability_gate.md").read_text(encoding="utf-8")
    for expected_text in [
        "Commercial Saleability Gate",
        "Runtime endpoint: `/api/v1/commercial_saleability_gates/latest`",
        "Runtime Shape",
        "Gate Status Rules",
        "KRW 2B Commercial Saleability Gate",
        "local_commercial_saleability_gate",
        "Figma Code Connect is not used",
        "Review process is not a blocker",
        "Do not create a separate library, Git submodule, or extracted package now",
    ]:
        assert expected_text in gate_doc

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
            f"http://127.0.0.1:{port}/api/v1/commercial_saleability_gates/latest",
            "inference_secret",
        )
        gate_status, gate = get_json(
            f"http://127.0.0.1:{port}/api/v1/commercial_saleability_gates/latest",
            "admin_secret",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert unauth_status == 401
    assert unauth_body["error"]["code"] == "unauthorized"
    assert gate_status == 200
    assert gate["saleability_gate_status"] in {
        "commercial_saleability_gate_ready",
        "commercial_saleability_gate_ready_with_warnings",
        "commercial_saleability_gate_blocked",
    }
    assert gate["measurement_status"] == "local_commercial_saleability_gate"
    assert "gate_checks" in gate


if __name__ == "__main__":  # pragma: no cover
    test_commercial_saleability_gate_report_packages_final_go_no_go()
    test_commercial_saleability_gate_endpoint_openapi_admin_and_docs_contract()
    print("ok")
