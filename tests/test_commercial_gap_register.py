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
    orchestrator.run_evaluation(["Replay this commercial gap register prompt."], mode="route")


def test_commercial_gap_register_report_classifies_external_gaps_without_blocking_review() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    report = orchestrator.commercial_gap_register_report(
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

    assert report["gap_register_status"] == "commercial_gap_register_open"
    assert report["target_contract_value_krw"] == TARGET_CONTRACT_VALUE_KRW
    assert report["measurement_status"] == "local_commercial_gap_register"
    assert "not a valuation guarantee" in report["source_note"]
    assert report["gap_summary"]["total_gap_count"] == 2
    assert report["gap_summary"]["production_gap_count"] == 1
    assert report["gap_summary"]["buyer_specific_gap_count"] == 1
    assert report["gap_summary"]["blocked_count"] == 0
    assert report["gap_summary"]["review_process_is_blocker"] is False
    assert report["concrete_blockers"] == []
    assert [item["gap_status"] for item in report["gap_items"]] == [
        "production_input_required",
        "buyer_input_required",
    ]
    assert report["gap_items"][0]["source_evidence_type"] == "proposed_until_production"
    assert report["gap_items"][1]["source_evidence_type"] == "proposed_until_buyer_specific"
    assert report["related_runtime_reports"]["commercial_release_status"] == "commercial_release_ready_with_warnings"
    assert report["library_split_decision"]["decision"] == "keep_single_product"
    assert report["gap_register_links"]["runtime_endpoint"] == "/api/v1/commercial_gap_registers/latest"


def test_commercial_gap_register_endpoint_openapi_admin_and_docs_contract() -> None:
    assert "/api/v1/commercial_gap_registers/latest" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/api/v1/commercial_gap_registers/latest"]["get"]["operationId"] == (
        "get_latest_commercial_gap_register"
    )
    assert "/api/v1/commercial_gap_registers/latest" in ADMIN_HTML
    assert "commercial_gap_register_title" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_gap_register_title" in ADMIN_TRANSLATIONS["ko"]
    assert "commercial_gap_register_open" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_gap_register_open" in ADMIN_TRANSLATIONS["ko"]

    gap_doc = Path("docs/commercial_gap_register.md").read_text(encoding="utf-8")
    assert "Commercial Gap Register" in gap_doc
    assert "/api/v1/commercial_gap_registers/latest" in gap_doc
    assert "KRW 2B Commercial Gap Register" in gap_doc
    assert "Figma Code Connect is not used" in gap_doc
    assert "Review process is not a blocker" in gap_doc
    assert "Do not create a separate library, Git submodule, or extracted package now" in gap_doc

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
            f"http://127.0.0.1:{port}/api/v1/commercial_gap_registers/latest",
            "inference_secret",
        )
        gap_status, gap_register = get_json(
            f"http://127.0.0.1:{port}/api/v1/commercial_gap_registers/latest",
            "admin_secret",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert unauth_status == 401
    assert unauth_body["error"]["code"] == "unauthorized"
    assert gap_status == 200
    assert gap_register["gap_register_status"] in {
        "commercial_gap_register_clear",
        "commercial_gap_register_open",
        "commercial_gap_register_blocked",
    }
    assert gap_register["measurement_status"] == "local_commercial_gap_register"
    assert "gap_items" in gap_register


if __name__ == "__main__":  # pragma: no cover
    test_commercial_gap_register_report_classifies_external_gaps_without_blocking_review()
    test_commercial_gap_register_endpoint_openapi_admin_and_docs_contract()
    print("ok")
