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
    return {str(row["item_name"]): row for row in report["value_items"]}


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
        [{"role": "user", "content": "Prepare KRW 2B buyer value evidence and separate ROI input gaps."}],
        mode="conduct",
    )
    orchestrator.run_evaluation(["Replay this commercial value readiness prompt."], mode="route")


def test_commercial_value_readiness_report_separates_local_evidence_from_buyer_financial_inputs() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    report = orchestrator.commercial_value_readiness_report(
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

    assert report["value_status"] == "commercial_value_ready_with_warnings"
    assert report["target_contract_value_krw"] == TARGET_CONTRACT_VALUE_KRW
    assert report["measurement_status"] == "local_commercial_value_readiness"
    assert "not a valuation guarantee" in report["source_note"]
    assert report["value_summary"]["blocked_count"] == 0
    assert report["value_summary"]["warning_count"] == 4
    assert report["value_summary"]["buyer_financial_gap_count"] == 4
    assert report["value_summary"]["external_value_proof_gap_count"] == 1
    assert report["value_summary"]["review_process_is_blocker"] is False
    assert report["concrete_blockers"] == []
    assert items["commercial_value_case_basis"]["completion_state"] == "ready"
    assert items["local_analytics_evidence"]["completion_state"] == "ready"
    assert items["buyer_evidence_export"]["completion_state"] == "ready"
    assert items["pricing_package_rationale"]["completion_state"] == "ready"
    assert items["roi_model_inputs"]["completion_state"] == "warning"
    assert items["roi_model_inputs"]["source_gap_status"] == "buyer_financial_input_required"
    assert items["reference_customer_or_case_study"]["completion_state"] == "warning"
    assert items["reference_customer_or_case_study"]["source_gap_status"] == "external_value_proof_required"
    assert items["procurement_budget_owner"]["completion_state"] == "warning"
    assert items["implementation_payback_assumption"]["completion_state"] == "warning"
    assert report["related_runtime_reports"]["commercial_security_attestation_status"] == (
        "commercial_security_attestation_ready_with_warnings"
    )
    assert report["library_split_decision"]["decision"] == "keep_single_product"
    assert report["value_links"]["runtime_endpoint"] == "/api/v1/commercial_value_readiness/latest"


def test_commercial_value_readiness_endpoint_openapi_admin_and_docs_contract() -> None:
    assert "/api/v1/commercial_value_readiness/latest" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/api/v1/commercial_value_readiness/latest"]["get"]["operationId"] == (
        "get_latest_commercial_value_readiness"
    )
    assert "/api/v1/commercial_value_readiness/latest" in ADMIN_HTML
    assert "commercial_value_readiness_title" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_value_readiness_title" in ADMIN_TRANSLATIONS["ko"]
    assert "commercial_value_ready_with_warnings" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_value_ready_with_warnings" in ADMIN_TRANSLATIONS["ko"]

    value_doc = Path("docs/commercial_value_readiness.md").read_text(encoding="utf-8")
    assert "Commercial Value Readiness" in value_doc
    assert "/api/v1/commercial_value_readiness/latest" in value_doc
    assert "KRW 2B Commercial Value Readiness" in value_doc
    assert "Figma Code Connect is not used" in value_doc
    assert "Review process is not a blocker" in value_doc
    assert "Do not create a separate library, Git submodule, or extracted package now" in value_doc

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
            f"http://127.0.0.1:{port}/api/v1/commercial_value_readiness/latest",
            "inference_secret",
        )
        value_status, value = get_json(
            f"http://127.0.0.1:{port}/api/v1/commercial_value_readiness/latest",
            "admin_secret",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert unauth_status == 401
    assert unauth_body["error"]["code"] == "unauthorized"
    assert value_status == 200
    assert value["value_status"] in {
        "commercial_value_ready",
        "commercial_value_ready_with_warnings",
        "commercial_value_blocked",
    }
    assert value["measurement_status"] == "local_commercial_value_readiness"
    assert "value_items" in value


if __name__ == "__main__":  # pragma: no cover
    test_commercial_value_readiness_report_separates_local_evidence_from_buyer_financial_inputs()
    test_commercial_value_readiness_endpoint_openapi_admin_and_docs_contract()
    print("ok")
