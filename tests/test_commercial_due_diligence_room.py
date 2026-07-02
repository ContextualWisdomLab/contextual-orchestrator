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
    return {str(row["section_name"]): row for row in report["diligence_sections"]}


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
        [{"role": "user", "content": "Prepare buyer due diligence evidence for a KRW 2B purchase committee."}],
        mode="conduct",
    )
    orchestrator.run_evaluation(["Replay this due diligence prompt."], mode="route")


def test_commercial_due_diligence_room_report_packages_buyer_evidence_room() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    report = orchestrator.commercial_due_diligence_room_report(
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

    assert report["due_diligence_status"] == "commercial_due_diligence_ready_with_warnings"
    assert report["target_contract_value_krw"] == TARGET_CONTRACT_VALUE_KRW
    assert report["measurement_status"] == "local_commercial_due_diligence_room"
    assert "not a valuation guarantee" in report["source_note"]
    assert report["diligence_summary"]["blocked_count"] == 0
    assert report["diligence_summary"]["warning_count"] == 2
    assert report["diligence_summary"]["section_count"] == 10
    assert report["diligence_summary"]["review_process_is_blocker"] is False
    assert report["diligence_summary"]["code_connect_used"] is False
    assert report["concrete_blockers"] == []
    for section_name in [
        "purchase_approval_packet",
        "runtime_api_evidence",
        "admin_trace_evidence",
        "security_and_compliance",
        "commercial_terms",
        "value_and_analytics",
        "implementation_readiness",
        "figma_and_design_review",
    ]:
        assert sections[section_name]["completion_state"] == "ready"
    assert sections["buyer_authority_documents"]["completion_state"] == "warning"
    assert sections["production_external_attestations"]["completion_state"] == "warning"
    assert "/api/v1/commercial_due_diligence_rooms/latest" in report["required_runtime_endpoints"]
    assert "/api/v1/commercial_purchase_approval_packets/latest" in report["required_runtime_endpoints"]
    assert "/api/v1/commercial_proposal_packets/latest" in report["required_runtime_endpoints"]
    assert report["buyer_missing_artifacts"] == [
        "named buyer signer",
        "budget owner and purchase order",
        "buyer DPA or privacy acceptance",
        "production telemetry",
        "third-party security attestation",
    ]
    assert report["related_runtime_reports"]["commercial_purchase_approval_status"] == (
        "commercial_purchase_approval_ready_with_warnings"
    )
    assert report["library_split_decision"]["decision"] == "keep_single_product"
    assert report["due_diligence_links"]["runtime_endpoint"] == "/api/v1/commercial_due_diligence_rooms/latest"


def test_commercial_due_diligence_room_endpoint_openapi_admin_and_docs_contract() -> None:
    assert "/api/v1/commercial_due_diligence_rooms/latest" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/api/v1/commercial_due_diligence_rooms/latest"]["get"]["operationId"] == (
        "get_latest_commercial_due_diligence_room"
    )
    assert "/api/v1/commercial_due_diligence_rooms/latest" in ADMIN_HTML
    assert "commercial_due_diligence_room_title" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_due_diligence_room_title" in ADMIN_TRANSLATIONS["ko"]
    assert "commercial_due_diligence_ready_with_warnings" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_due_diligence_ready_with_warnings" in ADMIN_TRANSLATIONS["ko"]

    due_diligence_doc = Path("docs/commercial_due_diligence_room.md").read_text(encoding="utf-8")
    for expected_text in [
        "Commercial Due Diligence Room",
        "Runtime endpoint: `/api/v1/commercial_due_diligence_rooms/latest`",
        "Runtime Shape",
        "Due Diligence Status Rules",
        "KRW 2B Commercial Due Diligence Room",
        "local_commercial_due_diligence_room",
        "Figma Code Connect is not used",
        "Review process is not a blocker",
        "Do not create a separate library, Git submodule, or extracted package now",
    ]:
        assert expected_text in due_diligence_doc

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
            f"http://127.0.0.1:{port}/api/v1/commercial_due_diligence_rooms/latest",
            "inference_secret",
        )
        due_diligence_status, due_diligence = get_json(
            f"http://127.0.0.1:{port}/api/v1/commercial_due_diligence_rooms/latest",
            "admin_secret",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert unauth_status == 401
    assert unauth_body["error"]["code"] == "unauthorized"
    assert due_diligence_status == 200
    assert due_diligence["due_diligence_status"] in {
        "commercial_due_diligence_ready",
        "commercial_due_diligence_ready_with_warnings",
        "commercial_due_diligence_blocked",
    }
    assert due_diligence["measurement_status"] == "local_commercial_due_diligence_room"
    assert "diligence_sections" in due_diligence


if __name__ == "__main__":  # pragma: no cover
    test_commercial_due_diligence_room_report_packages_buyer_evidence_room()
    test_commercial_due_diligence_room_endpoint_openapi_admin_and_docs_contract()
    print("ok")
