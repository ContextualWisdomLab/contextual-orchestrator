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
    return {str(row["item_name"]): row for row in report["security_attestation_items"]}


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
        [{"role": "user", "content": "Prepare buyer security attestation evidence and separate external gaps."}],
        mode="conduct",
    )
    orchestrator.run_evaluation(["Replay this commercial security attestation prompt."], mode="route")


def test_commercial_security_attestation_report_separates_local_and_external_evidence() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    report = orchestrator.commercial_security_attestation_report(
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

    assert report["security_attestation_status"] == "commercial_security_attestation_ready_with_warnings"
    assert report["target_contract_value_krw"] == TARGET_CONTRACT_VALUE_KRW
    assert report["measurement_status"] == "local_commercial_security_attestation"
    assert "not a valuation guarantee" in report["source_note"]
    assert report["security_attestation_summary"]["blocked_count"] == 0
    assert report["security_attestation_summary"]["warning_count"] == 3
    assert report["security_attestation_summary"]["external_attestation_gap_count"] == 2
    assert report["security_attestation_summary"]["buyer_privacy_gap_count"] == 1
    assert report["security_attestation_summary"]["review_process_is_blocker"] is False
    assert report["concrete_blockers"] == []
    assert items["security_policy"]["completion_state"] == "ready"
    assert items["dependency_lock_package_metadata"]["completion_state"] == "ready"
    assert items["security_workflow_metadata"]["completion_state"] == "ready"
    assert items["runtime_access_control_profile"]["completion_state"] == "ready"
    assert items["audit_export_evidence"]["completion_state"] == "ready"
    assert items["vulnerability_scan_evidence"]["completion_state"] == "warning"
    assert items["vulnerability_scan_evidence"]["source_gap_status"] == "external_attestation_required"
    assert items["third_party_attestation_pen_test"]["completion_state"] == "warning"
    assert items["third_party_attestation_pen_test"]["source_gap_status"] == "external_attestation_required"
    assert items["buyer_privacy_dpa_questionnaire"]["completion_state"] == "warning"
    assert items["buyer_privacy_dpa_questionnaire"]["source_gap_status"] == "buyer_input_required"
    assert report["related_runtime_reports"]["commercial_operations_status"] == "commercial_operations_ready_with_warnings"
    assert report["library_split_decision"]["decision"] == "keep_single_product"
    assert report["security_attestation_links"]["runtime_endpoint"] == "/api/v1/commercial_security_attestations/latest"


def test_commercial_security_attestation_endpoint_openapi_admin_and_docs_contract() -> None:
    assert "/api/v1/commercial_security_attestations/latest" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/api/v1/commercial_security_attestations/latest"]["get"]["operationId"] == (
        "get_latest_commercial_security_attestation"
    )
    assert "/api/v1/commercial_security_attestations/latest" in ADMIN_HTML
    assert "commercial_security_attestation_title" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_security_attestation_title" in ADMIN_TRANSLATIONS["ko"]
    assert "commercial_security_attestation_ready_with_warnings" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_security_attestation_ready_with_warnings" in ADMIN_TRANSLATIONS["ko"]

    attestation_doc = Path("docs/commercial_security_attestation.md").read_text(encoding="utf-8")
    assert "Commercial Security Attestation" in attestation_doc
    assert "/api/v1/commercial_security_attestations/latest" in attestation_doc
    assert "KRW 2B Commercial Security Attestation" in attestation_doc
    assert "Figma Code Connect is not used" in attestation_doc
    assert "Review process is not a blocker" in attestation_doc
    assert "Do not create a separate library, Git submodule, or extracted package now" in attestation_doc

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
            f"http://127.0.0.1:{port}/api/v1/commercial_security_attestations/latest",
            "inference_secret",
        )
        attestation_status, attestation = get_json(
            f"http://127.0.0.1:{port}/api/v1/commercial_security_attestations/latest",
            "admin_secret",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert unauth_status == 401
    assert unauth_body["error"]["code"] == "unauthorized"
    assert attestation_status == 200
    assert attestation["security_attestation_status"] in {
        "commercial_security_attestation_ready",
        "commercial_security_attestation_ready_with_warnings",
        "commercial_security_attestation_blocked",
    }
    assert attestation["measurement_status"] == "local_commercial_security_attestation"
    assert "security_attestation_items" in attestation


if __name__ == "__main__":  # pragma: no cover
    test_commercial_security_attestation_report_separates_local_and_external_evidence()
    test_commercial_security_attestation_endpoint_openapi_admin_and_docs_contract()
    print("ok")
