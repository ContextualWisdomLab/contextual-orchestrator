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
    return {str(row["item_name"]): row for row in report["procurement_items"]}


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
    orchestrator.run_evaluation(["Replay this commercial procurement readiness prompt."], mode="route")


def test_commercial_procurement_readiness_report_tracks_ready_packet_and_warning_inputs() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    report = orchestrator.commercial_procurement_readiness_report(
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

    assert report["procurement_status"] == "commercial_procurement_ready_with_warnings"
    assert report["target_contract_value_krw"] == TARGET_CONTRACT_VALUE_KRW
    assert report["measurement_status"] == "local_commercial_procurement_readiness"
    assert "not a valuation guarantee" in report["source_note"]
    assert report["procurement_summary"]["blocked_count"] == 0
    assert report["procurement_summary"]["warning_count"] == 2
    assert report["procurement_summary"]["production_gap_count"] == 1
    assert report["procurement_summary"]["buyer_specific_gap_count"] == 1
    assert report["procurement_summary"]["review_process_is_blocker"] is False
    assert report["concrete_blockers"] == []
    assert items["license_and_rights"]["completion_state"] == "ready"
    assert items["security_package_metadata"]["completion_state"] == "ready"
    assert items["distribution_packet"]["completion_state"] == "ready"
    assert items["production_support_slo_input"]["completion_state"] == "warning"
    assert items["production_support_slo_input"]["source_gap_status"] == "production_input_required"
    assert items["buyer_legal_roi_procurement_input"]["completion_state"] == "warning"
    assert items["buyer_legal_roi_procurement_input"]["source_gap_status"] == "buyer_input_required"
    assert report["related_runtime_reports"]["commercial_gap_register_status"] == "commercial_gap_register_open"
    assert report["library_split_decision"]["decision"] == "keep_single_product"
    assert report["procurement_links"]["runtime_endpoint"] == "/api/v1/commercial_procurement_readiness/latest"


def test_commercial_procurement_readiness_endpoint_openapi_admin_and_docs_contract() -> None:
    assert "/api/v1/commercial_procurement_readiness/latest" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/api/v1/commercial_procurement_readiness/latest"]["get"]["operationId"] == (
        "get_latest_commercial_procurement_readiness"
    )
    assert "/api/v1/commercial_procurement_readiness/latest" in ADMIN_HTML
    assert "commercial_procurement_readiness_title" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_procurement_readiness_title" in ADMIN_TRANSLATIONS["ko"]
    assert "commercial_procurement_ready_with_warnings" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_procurement_ready_with_warnings" in ADMIN_TRANSLATIONS["ko"]

    procurement_doc = Path("docs/commercial_procurement_readiness.md").read_text(encoding="utf-8")
    assert "Commercial Procurement Readiness" in procurement_doc
    assert "/api/v1/commercial_procurement_readiness/latest" in procurement_doc
    assert "KRW 2B Commercial Procurement Readiness" in procurement_doc
    assert "Figma Code Connect is not used" in procurement_doc
    assert "Review process is not a blocker" in procurement_doc
    assert "Do not create a separate library, Git submodule, or extracted package now" in procurement_doc

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
            f"http://127.0.0.1:{port}/api/v1/commercial_procurement_readiness/latest",
            "inference_secret",
        )
        procurement_status, procurement = get_json(
            f"http://127.0.0.1:{port}/api/v1/commercial_procurement_readiness/latest",
            "admin_secret",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert unauth_status == 401
    assert unauth_body["error"]["code"] == "unauthorized"
    assert procurement_status == 200
    assert procurement["procurement_status"] in {
        "commercial_procurement_ready",
        "commercial_procurement_ready_with_warnings",
        "commercial_procurement_blocked",
    }
    assert procurement["measurement_status"] == "local_commercial_procurement_readiness"
    assert "procurement_items" in procurement


if __name__ == "__main__":  # pragma: no cover
    test_commercial_procurement_readiness_report_tracks_ready_packet_and_warning_inputs()
    test_commercial_procurement_readiness_endpoint_openapi_admin_and_docs_contract()
    print("ok")
