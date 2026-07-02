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
    return {str(row["item_name"]): row for row in report["items"]}


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
    orchestrator.run_evaluation(["Replay this commercial readiness prompt."], mode="route")


def test_buyer_evidence_manifest_report_indexes_runtime_and_caveat_evidence() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    report = orchestrator.buyer_evidence_manifest_report(
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

    assert report["manifest_status"] == "buyer_review_ready_with_warnings"
    assert report["target_contract_value_krw"] == TARGET_CONTRACT_VALUE_KRW
    assert report["measurement_status"] == "local_buyer_evidence_manifest"
    assert "not a valuation guarantee" in report["source_note"]
    assert report["summary"]["by_completion_state"]["blocked"] == 0
    assert report["summary"]["by_completion_state"]["warning"] >= 2
    assert report["summary"]["by_evidence_type"]["measured_local"] >= 5
    assert items["commercial_readiness"]["completion_state"] == "ready"
    assert items["analytics_honesty"]["sources"] == ["/api/v1/analytics_snapshots/latest", "docs/analytics_spec.md"]
    assert items["visual_stakeholder_evidence"]["evidence_type"] == "figma_artifact"
    assert items["production_slo_support"]["evidence_type"] == "proposed_until_production"
    assert items["buyer_specific_roi_legal"]["evidence_type"] == "proposed_until_buyer_specific"
    assert report["related_runtime_reports"]["commercial_status"] == "commercial_ready"


def test_buyer_evidence_manifest_endpoint_openapi_admin_and_docs_contract() -> None:
    assert "/api/v1/buyer_evidence_manifests/latest" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/api/v1/buyer_evidence_manifests/latest"]["get"]["operationId"] == (
        "get_latest_buyer_evidence_manifest"
    )
    assert "/api/v1/buyer_evidence_manifests/latest" in ADMIN_HTML
    assert "buyer_evidence_manifest_title" in ADMIN_TRANSLATIONS["en"]
    assert "buyer_evidence_manifest_title" in ADMIN_TRANSLATIONS["ko"]

    manifest_doc = Path("docs/commercial_buyer_evidence_manifest.md").read_text(encoding="utf-8")
    assert "Commercial Buyer Evidence Manifest" in manifest_doc
    assert "/api/v1/buyer_evidence_manifests/latest" in manifest_doc
    assert "Figma Code Connect is not used" in manifest_doc
    assert "Review process is not a blocker" in manifest_doc

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
            f"http://127.0.0.1:{port}/api/v1/buyer_evidence_manifests/latest",
            "inference_secret",
        )
        manifest_status, manifest = get_json(
            f"http://127.0.0.1:{port}/api/v1/buyer_evidence_manifests/latest",
            "admin_secret",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert unauth_status == 401
    assert unauth_body["error"]["code"] == "unauthorized"
    assert manifest_status == 200
    assert manifest["manifest_status"] in {
        "buyer_review_ready",
        "buyer_review_ready_with_warnings",
        "buyer_review_blocked",
    }
    assert manifest["measurement_status"] == "local_buyer_evidence_manifest"
    assert "items" in manifest


if __name__ == "__main__":  # pragma: no cover
    test_buyer_evidence_manifest_report_indexes_runtime_and_caveat_evidence()
    test_buyer_evidence_manifest_endpoint_openapi_admin_and_docs_contract()
    print("ok")
