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
    orchestrator.run_evaluation(["Replay this saleability prompt."], mode="route")


def test_saleability_decision_report_classifies_warnings_and_non_blockers() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    report = orchestrator.saleability_decision_report(
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

    assert report["saleability_status"] == "saleability_ready_with_warnings"
    assert report["target_contract_value_krw"] == TARGET_CONTRACT_VALUE_KRW
    assert report["measurement_status"] == "local_saleability_decision"
    assert "not a valuation guarantee" in report["source_note"]
    assert report["review_process_policy"]["is_blocker"] is False
    assert report["review_process_policy"]["blocker_definition"] == "concrete security, API contract, document, or product defect"
    assert report["concrete_blockers"] == []
    assert report["warning_conditions"][0]["evidence_type"] == "proposed_until_production"
    assert report["warning_conditions"][1]["evidence_type"] == "proposed_until_buyer_specific"
    assert report["decision_summary"]["blocked_count"] == 0
    assert report["decision_summary"]["warning_count"] == 2
    assert report["related_runtime_reports"]["buyer_handoff_status"] == "buyer_handoff_ready_with_warnings"
    assert report["library_split_decision"]["decision"] == "keep_single_product"


def test_saleability_decision_endpoint_openapi_admin_and_docs_contract() -> None:
    assert "/api/v1/saleability_decisions/latest" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/api/v1/saleability_decisions/latest"]["get"]["operationId"] == (
        "get_latest_saleability_decision"
    )
    assert "/api/v1/saleability_decisions/latest" in ADMIN_HTML
    assert "saleability_decision_title" in ADMIN_TRANSLATIONS["en"]
    assert "saleability_decision_title" in ADMIN_TRANSLATIONS["ko"]

    decision_doc = Path("docs/commercial_saleability_decision.md").read_text(encoding="utf-8")
    assert "Commercial Saleability Decision" in decision_doc
    assert "/api/v1/saleability_decisions/latest" in decision_doc
    assert "KRW 2B Saleability Decision Gate" in decision_doc
    assert "Figma Code Connect is not used" in decision_doc
    assert "Review process is not a blocker" in decision_doc
    assert "Do not create a separate library, Git submodule, or extracted package now" in decision_doc

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
            f"http://127.0.0.1:{port}/api/v1/saleability_decisions/latest",
            "inference_secret",
        )
        decision_status, decision = get_json(
            f"http://127.0.0.1:{port}/api/v1/saleability_decisions/latest",
            "admin_secret",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert unauth_status == 401
    assert unauth_body["error"]["code"] == "unauthorized"
    assert decision_status == 200
    assert decision["saleability_status"] in {
        "saleability_ready",
        "saleability_ready_with_warnings",
        "saleability_blocked",
    }
    assert decision["measurement_status"] == "local_saleability_decision"
    assert "decision_summary" in decision


if __name__ == "__main__":  # pragma: no cover
    test_saleability_decision_report_classifies_warnings_and_non_blockers()
    test_saleability_decision_endpoint_openapi_admin_and_docs_contract()
    print("ok")
