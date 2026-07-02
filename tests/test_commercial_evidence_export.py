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
    return {str(row["item_name"]): row for row in report["export_sections"]}


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
    orchestrator.run_evaluation(["Replay this commercial evidence export prompt."], mode="route")


def test_commercial_evidence_export_report_packages_buyer_diligence_index() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    report = orchestrator.commercial_evidence_export_report(
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

    assert report["export_status"] == "commercial_export_ready_with_warnings"
    assert report["target_contract_value_krw"] == TARGET_CONTRACT_VALUE_KRW
    assert report["measurement_status"] == "local_commercial_evidence_export"
    assert "not a valuation guarantee" in report["source_note"]
    assert report["export_summary"]["blocked_count"] == 0
    assert report["export_summary"]["warning_count"] == 2
    assert report["concrete_blockers"] == []
    assert report["required_external_evidence"][0]["evidence_type"] == "proposed_until_production"
    assert report["required_external_evidence"][1]["evidence_type"] == "proposed_until_buyer_specific"
    assert sections["saleability_decision"]["sources"] == [
        "/api/v1/saleability_decisions/latest",
        "docs/commercial_saleability_decision.md",
    ]
    assert sections["runtime_reports"]["evidence_type"] == "measured_local"
    assert sections["buyer_packet_documents"]["evidence_type"] == "repository_artifact"
    assert sections["figma_stakeholder_artifacts"]["evidence_type"] == "figma_artifact"
    assert report["review_process_policy"]["is_blocker"] is False
    assert report["related_runtime_reports"]["saleability_status"] == "saleability_ready_with_warnings"
    assert report["library_split_decision"]["decision"] == "keep_single_product"
    assert report["export_links"]["runtime_endpoint"] == "/api/v1/commercial_evidence_exports/latest"


def test_commercial_evidence_export_endpoint_openapi_admin_and_docs_contract() -> None:
    assert "/api/v1/commercial_evidence_exports/latest" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/api/v1/commercial_evidence_exports/latest"]["get"]["operationId"] == (
        "get_latest_commercial_evidence_export"
    )
    assert "/api/v1/commercial_evidence_exports/latest" in ADMIN_HTML
    assert "commercial_evidence_export_title" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_evidence_export_title" in ADMIN_TRANSLATIONS["ko"]
    assert "commercial_export_ready_with_warnings" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_export_ready_with_warnings" in ADMIN_TRANSLATIONS["ko"]

    export_doc = Path("docs/commercial_evidence_export.md").read_text(encoding="utf-8")
    assert "Commercial Evidence Export" in export_doc
    assert "/api/v1/commercial_evidence_exports/latest" in export_doc
    assert "KRW 2B Commercial Evidence Export" in export_doc
    assert "Figma Code Connect is not used" in export_doc
    assert "Review process is not a blocker" in export_doc
    assert "Do not create a separate library, Git submodule, or extracted package now" in export_doc

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
            f"http://127.0.0.1:{port}/api/v1/commercial_evidence_exports/latest",
            "inference_secret",
        )
        export_status, export = get_json(
            f"http://127.0.0.1:{port}/api/v1/commercial_evidence_exports/latest",
            "admin_secret",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert unauth_status == 401
    assert unauth_body["error"]["code"] == "unauthorized"
    assert export_status == 200
    assert export["export_status"] in {
        "commercial_export_ready",
        "commercial_export_ready_with_warnings",
        "commercial_export_blocked",
    }
    assert export["measurement_status"] == "local_commercial_evidence_export"
    assert "export_sections" in export


if __name__ == "__main__":  # pragma: no cover
    test_commercial_evidence_export_report_packages_buyer_diligence_index()
    test_commercial_evidence_export_endpoint_openapi_admin_and_docs_contract()
    print("ok")
