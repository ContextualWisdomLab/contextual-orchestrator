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


def gate_by_name(report: dict[str, object]) -> dict[str, dict[str, object]]:
    return {str(row["gate_name"]): row for row in report["approval_gates"]}


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
        [{"role": "user", "content": "Prepare purchase approval evidence for finance, procurement, legal, and security."}],
        mode="conduct",
    )
    orchestrator.run_evaluation(["Replay this purchase approval prompt."], mode="route")


def test_commercial_purchase_approval_packet_report_packages_buyer_approval() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    report = orchestrator.commercial_purchase_approval_packet_report(
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
    gates = gate_by_name(report)

    assert report["purchase_approval_status"] == "commercial_purchase_approval_ready_with_warnings"
    assert report["target_contract_value_krw"] == TARGET_CONTRACT_VALUE_KRW
    assert report["measurement_status"] == "local_commercial_purchase_approval_packet"
    assert "not a valuation guarantee" in report["source_note"]
    assert report["approval_summary"]["blocked_count"] == 0
    assert report["approval_summary"]["warning_count"] == 2
    assert report["approval_summary"]["gate_count"] == 10
    assert report["approval_summary"]["review_process_is_blocker"] is False
    assert report["approval_summary"]["code_connect_used"] is False
    assert report["concrete_blockers"] == []
    for gate_name in [
        "proposal_packet_ready",
        "procurement_path_ready",
        "contract_legal_packet_ready",
        "financial_value_case_ready",
        "security_acceptance_ready",
        "implementation_readiness_ready",
        "close_readiness_ready",
        "approval_runtime_packet_ready",
    ]:
        assert gates[gate_name]["completion_state"] == "ready"
    assert gates["buyer_signature_authority"]["completion_state"] == "warning"
    assert gates["buyer_budget_po_authority"]["completion_state"] == "warning"
    assert "/api/v1/commercial_purchase_approval_packets/latest" in report["required_runtime_endpoints"]
    assert "/api/v1/commercial_proposal_packets/latest" in report["required_runtime_endpoints"]
    assert "/api/v1/commercial_close_readiness/latest" in report["required_runtime_endpoints"]
    assert report["related_runtime_reports"]["commercial_proposal_status"] == "commercial_proposal_ready_with_warnings"
    assert report["related_runtime_reports"]["commercial_close_status"] == "commercial_close_ready_with_warnings"
    assert report["library_split_decision"]["decision"] == "keep_single_product"
    assert report["approval_links"]["runtime_endpoint"] == "/api/v1/commercial_purchase_approval_packets/latest"


def test_commercial_purchase_approval_packet_endpoint_openapi_admin_and_docs_contract() -> None:
    assert "/api/v1/commercial_purchase_approval_packets/latest" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/api/v1/commercial_purchase_approval_packets/latest"]["get"]["operationId"] == (
        "get_latest_commercial_purchase_approval_packet"
    )
    assert "/api/v1/commercial_purchase_approval_packets/latest" in ADMIN_HTML
    assert "commercial_purchase_approval_packet_title" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_purchase_approval_packet_title" in ADMIN_TRANSLATIONS["ko"]
    assert "commercial_purchase_approval_ready_with_warnings" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_purchase_approval_ready_with_warnings" in ADMIN_TRANSLATIONS["ko"]

    approval_doc = Path("docs/commercial_purchase_approval_packet.md").read_text(encoding="utf-8")
    for expected_text in [
        "Commercial Purchase Approval Packet",
        "Runtime endpoint: `/api/v1/commercial_purchase_approval_packets/latest`",
        "Runtime Shape",
        "Purchase Approval Status Rules",
        "KRW 2B Commercial Purchase Approval Packet",
        "local_commercial_purchase_approval_packet",
        "Figma Code Connect is not used",
        "Review process is not a blocker",
        "Do not create a separate library, Git submodule, or extracted package now",
    ]:
        assert expected_text in approval_doc

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
            f"http://127.0.0.1:{port}/api/v1/commercial_purchase_approval_packets/latest",
            "inference_secret",
        )
        approval_status, approval = get_json(
            f"http://127.0.0.1:{port}/api/v1/commercial_purchase_approval_packets/latest",
            "admin_secret",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert unauth_status == 401
    assert unauth_body["error"]["code"] == "unauthorized"
    assert approval_status == 200
    assert approval["purchase_approval_status"] in {
        "commercial_purchase_approval_ready",
        "commercial_purchase_approval_ready_with_warnings",
        "commercial_purchase_approval_blocked",
    }
    assert approval["measurement_status"] == "local_commercial_purchase_approval_packet"
    assert "approval_gates" in approval


if __name__ == "__main__":  # pragma: no cover
    test_commercial_purchase_approval_packet_report_packages_buyer_approval()
    test_commercial_purchase_approval_packet_endpoint_openapi_admin_and_docs_contract()
    print("ok")

