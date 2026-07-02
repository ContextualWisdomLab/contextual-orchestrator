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
    return {str(row["item_name"]): row for row in report["acceptance_items"]}


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
    orchestrator.run_evaluation(["Replay this commercial acceptance check prompt."], mode="route")


def test_commercial_acceptance_check_report_classifies_external_gaps_as_warnings() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    report = orchestrator.commercial_acceptance_check_report(
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

    assert report["acceptance_status"] == "commercial_acceptance_ready_with_warnings"
    assert report["target_contract_value_krw"] == TARGET_CONTRACT_VALUE_KRW
    assert report["measurement_status"] == "local_commercial_acceptance_check"
    assert "not a valuation guarantee" in report["source_note"]
    assert report["acceptance_summary"]["blocked_count"] == 0
    assert report["acceptance_summary"]["warning_count"] == 2
    assert report["concrete_blockers"] == []
    assert report["follow_up_items"][0]["evidence_type"] == "proposed_until_production"
    assert report["follow_up_items"][1]["evidence_type"] == "proposed_until_buyer_specific"
    assert items["runtime_endpoint_chain"]["completion_state"] == "ready"
    assert items["buyer_packet_documents"]["evidence_type"] == "repository_artifact"
    assert items["admin_operator_surface"]["sources"] == [
        "/admin",
        "contextual_orchestrator/admin.py",
        "/api/v1/commercial_acceptance_checks/latest",
    ]
    assert items["verification_evidence"]["evidence_type"] == "measured_local"
    assert items["figma_stakeholder_artifacts"]["evidence_type"] == "figma_artifact"
    assert report["review_process_policy"]["is_blocker"] is False
    assert report["related_runtime_reports"]["commercial_export_status"] == "commercial_export_ready_with_warnings"
    assert report["library_split_decision"]["decision"] == "keep_single_product"
    assert report["acceptance_links"]["runtime_endpoint"] == "/api/v1/commercial_acceptance_checks/latest"


def test_commercial_acceptance_check_endpoint_openapi_admin_and_docs_contract() -> None:
    assert "/api/v1/commercial_acceptance_checks/latest" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/api/v1/commercial_acceptance_checks/latest"]["get"]["operationId"] == (
        "get_latest_commercial_acceptance_check"
    )
    assert "/api/v1/commercial_acceptance_checks/latest" in ADMIN_HTML
    assert "commercial_acceptance_check_title" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_acceptance_check_title" in ADMIN_TRANSLATIONS["ko"]
    assert "commercial_acceptance_ready_with_warnings" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_acceptance_ready_with_warnings" in ADMIN_TRANSLATIONS["ko"]

    acceptance_doc = Path("docs/commercial_acceptance_check.md").read_text(encoding="utf-8")
    assert "Commercial Acceptance Check" in acceptance_doc
    assert "/api/v1/commercial_acceptance_checks/latest" in acceptance_doc
    assert "KRW 2B Commercial Acceptance Check" in acceptance_doc
    assert "Figma Code Connect is not used" in acceptance_doc
    assert "Review process is not a blocker" in acceptance_doc
    assert "Do not create a separate library, Git submodule, or extracted package now" in acceptance_doc

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
            f"http://127.0.0.1:{port}/api/v1/commercial_acceptance_checks/latest",
            "inference_secret",
        )
        acceptance_status, acceptance = get_json(
            f"http://127.0.0.1:{port}/api/v1/commercial_acceptance_checks/latest",
            "admin_secret",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert unauth_status == 401
    assert unauth_body["error"]["code"] == "unauthorized"
    assert acceptance_status == 200
    assert acceptance["acceptance_status"] in {
        "commercial_acceptance_ready",
        "commercial_acceptance_ready_with_warnings",
        "commercial_acceptance_blocked",
    }
    assert acceptance["measurement_status"] == "local_commercial_acceptance_check"
    assert "acceptance_items" in acceptance


if __name__ == "__main__":  # pragma: no cover
    test_commercial_acceptance_check_report_classifies_external_gaps_as_warnings()
    test_commercial_acceptance_check_endpoint_openapi_admin_and_docs_contract()
    print("ok")
