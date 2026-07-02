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


def post_json(url: str, payload: dict[str, object], token: str) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


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


def criteria_by_name(report: dict[str, object]) -> dict[str, dict[str, object]]:
    return {str(row["criterion_name"]): row for row in report["criteria"]}


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


def test_commercial_readiness_report_marks_due_diligence_ready() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    report = orchestrator.commercial_readiness_report(
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
    rows = criteria_by_name(report)

    assert report["target_contract_value_krw"] == TARGET_CONTRACT_VALUE_KRW
    assert report["commercial_status"] == "commercial_ready"
    assert report["measurement_status"] == "local_due_diligence_snapshot"
    assert report["commercial_summary"] == report["summary"]
    assert report["commercial_summary"]["fail"] == 0
    assert report["commercial_summary"]["warn"] == 0
    assert "not a valuation guarantee" in report["source_note"]
    assert "sales_readiness" in report
    assert {
        "product_capability_evidence",
        "security_and_access_control",
        "operational_resilience",
        "audit_and_compliance_evidence",
        "buyer_due_diligence_packet",
        "support_and_localization",
        "commercial_value_case",
    }.issubset(rows)
    for row in report["criteria"]:
        assert {"criterion_name", "status", "label", "evidence", "remediation"}.issubset(row)


def test_commercial_readiness_warns_when_value_target_is_too_small() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    report = orchestrator.commercial_readiness_report(
        target_contract_value_krw=500_000_000,
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile={
            "auth_mode": "split_token",
            "allow_public_bind": False,
            "expose_trace_by_default": False,
            "rate_limit_requests": 60,
            "max_concurrent_runs": 8,
        },
    )
    rows = criteria_by_name(report)

    assert report["commercial_status"] == "commercial_ready_with_warnings"
    assert report["commercial_summary"]["fail"] == 0
    assert rows["commercial_value_case"]["status"] == "warn"
    assert "KRW 2,000,000,000" in rows["commercial_value_case"]["remediation"]


def test_commercial_readiness_endpoint_openapi_admin_and_docs_contract() -> None:
    assert "/api/v1/commercial_readiness/latest" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/api/v1/commercial_readiness/latest"]["get"]["operationId"] == (
        "get_latest_commercial_readiness"
    )
    assert "/api/v1/commercial_readiness/latest" in ADMIN_HTML
    assert "commercial_readiness_title" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_readiness_title" in ADMIN_TRANSLATIONS["ko"]

    commercial_doc = Path("docs/commercial_readiness.md").read_text(encoding="utf-8")
    assert "KRW 2,000,000,000" in commercial_doc
    assert "not a valuation guarantee" in commercial_doc
    assert "Buyer due-diligence evidence map" in commercial_doc
    assert "Reviewer delay is not a blocker" in commercial_doc

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
            f"http://127.0.0.1:{port}/api/v1/commercial_readiness/latest",
            "inference_secret",
        )
        chat_status, _ = post_json(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            {"messages": [{"role": "user", "content": "Analyze, verify, and summarize commercial readiness."}]},
            "inference_secret",
        )
        readiness_status, readiness = get_json(
            f"http://127.0.0.1:{port}/api/v1/commercial_readiness/latest",
            "admin_secret",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert chat_status == 200
    assert unauth_status == 401
    assert unauth_body["error"]["code"] == "unauthorized"
    assert readiness_status == 200
    assert readiness["target_contract_value_krw"] == TARGET_CONTRACT_VALUE_KRW
    assert readiness["commercial_status"] in {"commercial_ready", "commercial_ready_with_warnings", "not_commercial_ready"}
    assert readiness["measurement_status"] == "local_due_diligence_snapshot"
    assert "criteria" in readiness


if __name__ == "__main__":  # pragma: no cover
    test_commercial_readiness_report_marks_due_diligence_ready()
    test_commercial_readiness_warns_when_value_target_is_too_small()
    test_commercial_readiness_endpoint_openapi_admin_and_docs_contract()
    print("ok")
