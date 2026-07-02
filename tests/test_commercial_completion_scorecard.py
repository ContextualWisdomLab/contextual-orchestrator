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
    return {str(row["item_name"]): row for row in report["completion_items"]}


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
        [{"role": "user", "content": "Review KRW 2B completion scorecard and separate external gaps."}],
        mode="conduct",
    )
    orchestrator.run_evaluation(["Replay this commercial completion scorecard prompt."], mode="route")


def test_commercial_completion_scorecard_report_aggregates_program_completion() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    report = orchestrator.commercial_completion_scorecard_report(
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

    assert report["completion_status"] == "commercial_completion_ready_with_warnings"
    assert report["target_contract_value_krw"] == TARGET_CONTRACT_VALUE_KRW
    assert report["measurement_status"] == "local_commercial_completion_scorecard"
    assert "not a valuation guarantee" in report["source_note"]
    assert "production compliance certificate" in report["source_note"]
    assert report["completion_summary"]["blocked_count"] == 0
    assert report["completion_summary"]["warning_count"] == 1
    assert report["completion_summary"]["external_input_group_count"] == 3
    assert report["completion_summary"]["review_process_is_blocker"] is False
    assert report["completion_summary"]["code_connect_used"] is False
    assert report["concrete_blockers"] == []
    for item_name in [
        "product_design_evidence",
        "figma_artifacts",
        "superpowers_plan_evidence",
        "ponytail_packaging_decision",
        "data_analytics_truthfulness",
        "runtime_endpoint_chain",
        "verification_packet",
        "review_process_policy",
    ]:
        assert items[item_name]["completion_state"] == "ready"
    assert items["production_buyer_followups"]["completion_state"] == "warning"
    assert items["production_buyer_followups"]["source_gap_status"] == "external_input_required"
    assert report["related_runtime_reports"]["commercial_readiness_status"] == "commercial_ready"
    assert report["related_runtime_reports"]["commercial_launch_status"] == "commercial_launch_ready_with_warnings"
    assert report["library_split_decision"]["decision"] == "keep_single_product"
    assert report["completion_links"]["runtime_endpoint"] == "/api/v1/commercial_completion_scorecards/latest"


def test_commercial_completion_scorecard_endpoint_openapi_admin_and_docs_contract() -> None:
    assert "/api/v1/commercial_completion_scorecards/latest" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/api/v1/commercial_completion_scorecards/latest"]["get"]["operationId"] == (
        "get_latest_commercial_completion_scorecard"
    )
    assert "/api/v1/commercial_completion_scorecards/latest" in ADMIN_HTML
    assert "commercial_completion_scorecard_title" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_completion_scorecard_title" in ADMIN_TRANSLATIONS["ko"]
    assert "commercial_completion_ready_with_warnings" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_completion_ready_with_warnings" in ADMIN_TRANSLATIONS["ko"]

    scorecard_doc = Path("docs/commercial_completion_scorecard.md").read_text(encoding="utf-8")
    for expected_text in [
        "Commercial Completion Scorecard",
        "KRW 2,000,000,000",
        "Figma Code Connect is not used",
        "Review process is not a blocker",
        "Do not create a separate library, Git submodule, or extracted package now",
        "Runtime Shape",
        "Completion Status Rules",
        "KRW 2B Commercial Completion Runtime Scorecard",
        "/api/v1/commercial_completion_scorecards/latest",
        "local_commercial_completion_scorecard",
    ]:
        assert expected_text in scorecard_doc

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
            f"http://127.0.0.1:{port}/api/v1/commercial_completion_scorecards/latest",
            "inference_secret",
        )
        completion_status, completion = get_json(
            f"http://127.0.0.1:{port}/api/v1/commercial_completion_scorecards/latest",
            "admin_secret",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert unauth_status == 401
    assert unauth_body["error"]["code"] == "unauthorized"
    assert completion_status == 200
    assert completion["completion_status"] in {
        "commercial_completion_ready",
        "commercial_completion_ready_with_warnings",
        "commercial_completion_blocked",
    }
    assert completion["measurement_status"] == "local_commercial_completion_scorecard"
    assert "completion_items" in completion


if __name__ == "__main__":  # pragma: no cover
    test_commercial_completion_scorecard_report_aggregates_program_completion()
    test_commercial_completion_scorecard_endpoint_openapi_admin_and_docs_contract()
    print("ok")
