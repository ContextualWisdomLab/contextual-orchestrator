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
    return {str(row["section_name"]): row for row in report["proposal_sections"]}


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
        [{"role": "user", "content": "Prepare a buyer proposal with trace, access, replay, and readiness proof."}],
        mode="conduct",
    )
    orchestrator.run_evaluation(["Replay this buyer proposal prompt."], mode="route")


def test_commercial_proposal_packet_report_packages_buyer_proposal() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    report = orchestrator.commercial_proposal_packet_report(
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

    assert report["proposal_status"] == "commercial_proposal_ready_with_warnings"
    assert report["target_contract_value_krw"] == TARGET_CONTRACT_VALUE_KRW
    assert report["measurement_status"] == "local_commercial_proposal_packet"
    assert "not a valuation guarantee" in report["source_note"]
    assert report["proposal_summary"]["blocked_count"] == 0
    assert report["proposal_summary"]["warning_count"] == 2
    assert report["proposal_summary"]["section_count"] == 10
    assert report["proposal_summary"]["review_process_is_blocker"] is False
    assert report["proposal_summary"]["code_connect_used"] is False
    assert report["concrete_blockers"] == []
    for section_name in [
        "executive_summary",
        "product_scope",
        "buyer_value_case",
        "demo_and_acceptance_path",
        "technical_evidence",
        "security_and_compliance",
        "implementation_and_operations",
        "proposal_review_packet",
    ]:
        assert sections[section_name]["completion_state"] == "ready"
    assert sections["commercial_terms_followups"]["completion_state"] == "warning"
    assert sections["production_buyer_inputs"]["completion_state"] == "warning"
    assert "/api/v1/commercial_proposal_packets/latest" in report["required_runtime_endpoints"]
    assert "/api/v1/commercial_demo_scenarios/latest" in report["required_runtime_endpoints"]
    assert report["related_runtime_reports"]["commercial_demo_status"] == "commercial_demo_ready_with_warnings"
    assert report["related_runtime_reports"]["commercial_completion_status"] == "commercial_completion_ready_with_warnings"
    assert report["related_runtime_reports"]["buyer_acceptance_workflow_status"] == "buyer_acceptance_workflow_ready_with_warnings"
    assert report["library_split_decision"]["decision"] == "keep_single_product"
    assert report["proposal_links"]["runtime_endpoint"] == "/api/v1/commercial_proposal_packets/latest"


def test_commercial_proposal_packet_endpoint_openapi_admin_and_docs_contract() -> None:
    assert "/api/v1/commercial_proposal_packets/latest" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/api/v1/commercial_proposal_packets/latest"]["get"]["operationId"] == (
        "get_latest_commercial_proposal_packet"
    )
    assert "/api/v1/commercial_proposal_packets/latest" in ADMIN_HTML
    assert "commercial_proposal_packet_title" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_proposal_packet_title" in ADMIN_TRANSLATIONS["ko"]
    assert "commercial_proposal_ready_with_warnings" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_proposal_ready_with_warnings" in ADMIN_TRANSLATIONS["ko"]

    proposal_doc = Path("docs/commercial_proposal_packet.md").read_text(encoding="utf-8")
    for expected_text in [
        "Commercial Proposal Packet",
        "Runtime endpoint: `/api/v1/commercial_proposal_packets/latest`",
        "Runtime Shape",
        "Proposal Status Rules",
        "KRW 2B Commercial Proposal Packet",
        "local_commercial_proposal_packet",
        "Figma Code Connect is not used",
        "Review process is not a blocker",
        "Do not create a separate library, Git submodule, or extracted package now",
    ]:
        assert expected_text in proposal_doc

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
            f"http://127.0.0.1:{port}/api/v1/commercial_proposal_packets/latest",
            "inference_secret",
        )
        proposal_status, proposal = get_json(
            f"http://127.0.0.1:{port}/api/v1/commercial_proposal_packets/latest",
            "admin_secret",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert unauth_status == 401
    assert unauth_body["error"]["code"] == "unauthorized"
    assert proposal_status == 200
    assert proposal["proposal_status"] in {
        "commercial_proposal_ready",
        "commercial_proposal_ready_with_warnings",
        "commercial_proposal_blocked",
    }
    assert proposal["measurement_status"] == "local_commercial_proposal_packet"
    assert "proposal_sections" in proposal


if __name__ == "__main__":  # pragma: no cover
    test_commercial_proposal_packet_report_packages_buyer_proposal()
    test_commercial_proposal_packet_endpoint_openapi_admin_and_docs_contract()
    print("ok")

