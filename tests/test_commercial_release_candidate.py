from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request

import pytest

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


def artifact_by_name(report: dict[str, object]) -> dict[str, dict[str, object]]:
    return {str(row["item_name"]): row for row in report["release_artifacts"]}


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
    orchestrator.run_evaluation(["Replay this commercial release candidate prompt."], mode="route")


def test_commercial_release_candidate_report_packages_ship_candidate() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    report = orchestrator.commercial_release_candidate_report(
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
    artifacts = artifact_by_name(report)

    assert report["release_status"] == "commercial_release_blocked"
    assert report["product_evidence_status"] == "commercial_release_ready_with_warnings"
    assert report["target_contract_value_krw"] == TARGET_CONTRACT_VALUE_KRW
    assert report["measurement_status"] == "local_commercial_release_candidate"
    assert "not a valuation guarantee" in report["source_note"]
    assert report["release_summary"]["blocked_count"] == 0
    assert report["release_summary"]["warning_count"] == 2
    assert report["release_summary"]["review_process_is_blocker"] is True
    assert report["release_authorization"]["blocker_reasons"] == [
        "release_authorization_evidence_absent"
    ]
    assert report["concrete_blockers"] == []
    assert report["external_release_gaps"][0]["evidence_type"] == "proposed_until_production"
    assert report["external_release_gaps"][1]["evidence_type"] == "proposed_until_buyer_specific"
    assert artifacts["commercial_acceptance_check"]["sources"] == [
        "/api/v1/commercial_acceptance_checks/latest",
        "docs/commercial_acceptance_check.md",
    ]
    assert artifacts["runtime_endpoint_chain"]["evidence_type"] == "measured_local"
    assert artifacts["repository_distribution_packet"]["evidence_type"] == "repository_artifact"
    assert artifacts["security_package_metadata"]["completion_state"] == "ready"
    assert artifacts["admin_operator_surface"]["sources"] == [
        "/admin",
        "contextual_orchestrator/admin.py",
        "/api/v1/commercial_release_candidates/latest",
    ]
    assert artifacts["figma_stakeholder_artifacts"]["evidence_type"] == "figma_artifact"
    assert report["related_runtime_reports"]["commercial_acceptance_status"] == "commercial_acceptance_ready_with_warnings"
    assert report["library_split_decision"]["decision"] == "keep_single_product"
    assert report["release_links"]["runtime_endpoint"] == "/api/v1/commercial_release_candidates/latest"


def _release_evidence() -> dict[str, object]:
    """Return complete synthetic exact-head authorization evidence."""
    head = "a" * 40
    return {
        "candidate_head_sha": head,
        "protected_head_sha": head,
        "required_check_names": ["tests", "security"],
        "required_checks": [
            {"name": "tests", "head_sha": head, "status": "completed", "conclusion": "success"},
            {"name": "security", "head_sha": head, "status": "completed", "conclusion": "success"},
        ],
        "required_approvals": 1,
        "independent_approvals": [
            {
                "head_sha": head,
                "state": "APPROVED",
                "is_author": False,
                "reviewer_fingerprint": "reviewer-one",
            }
        ],
        "unresolved_finding_count": 0,
    }


def _release_report(orchestrator: TaskOrchestrator, evidence: dict[str, object]) -> dict[str, object]:
    """Build a release report with the same complete local product evidence fixture."""
    return orchestrator.commercial_release_candidate_report(
        target_contract_value_krw=TARGET_CONTRACT_VALUE_KRW,
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile={
            "auth_mode": "split_token",
            "allow_public_bind": False,
            "expose_trace_by_default": False,
            "rate_limit_requests": 60,
            "max_concurrent_runs": 8,
        },
        release_authorization_evidence=evidence,
    )


def test_release_authorization_can_pass_only_on_complete_exact_head_evidence() -> None:
    """Keep local product evidence visible while granting exact-head authority separately."""
    orchestrator = build()
    exercise_runtime(orchestrator)
    report = _release_report(orchestrator, _release_evidence())
    assert report["release_authorization"]["status"] == "release_authorization_granted"
    assert report["release_authorization"]["blocker_reasons"] == []
    assert report["release_status"] == report["product_evidence_status"]


@pytest.mark.parametrize(
    ("mutation", "expected_blocker"),
    [
        (lambda row: row["required_checks"].pop(), "required_check_absent:security"),
        (
            lambda row: row["required_checks"][0].update(status="queued", conclusion=None),
            "required_check_not_successful:tests",
        ),
        (
            lambda row: row["required_checks"][0].update(head_sha="b" * 40),
            "required_check_stale_head:tests",
        ),
        (
            lambda row: row["required_checks"].append(dict(row["required_checks"][0])),
            "required_check_evidence_duplicated",
        ),
        (
            lambda row: row["required_checks"][0].update(name=[]),
            "required_check_name_invalid",
        ),
        (
            lambda row: row["independent_approvals"][0].update(is_author=True),
            "independent_approval_requirement_unsatisfied",
        ),
        (lambda row: row.update(unresolved_finding_count=1), "unresolved_findings_present"),
        (lambda row: row.update(required_approvals=True), "required_approval_policy_invalid"),
    ],
)
def test_release_authorization_fails_closed_for_incomplete_or_confused_evidence(
    mutation,
    expected_blocker: str,
) -> None:
    """Reject absent, pending, stale, author-only, unresolved, and type-confused evidence."""
    evidence = _release_evidence()
    mutation(evidence)
    orchestrator = build()
    exercise_runtime(orchestrator)
    report = _release_report(orchestrator, evidence)
    assert report["release_status"] == "commercial_release_blocked"
    assert report["product_evidence_status"] == "commercial_release_ready_with_warnings"
    assert expected_blocker in report["release_authorization"]["blocker_reasons"]


def test_commercial_release_candidate_endpoint_openapi_admin_and_docs_contract() -> None:
    assert "/api/v1/commercial_release_candidates/latest" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/api/v1/commercial_release_candidates/latest"]["get"]["operationId"] == (
        "get_latest_commercial_release_candidate"
    )
    assert "/api/v1/commercial_release_candidates/latest" in ADMIN_HTML
    assert "commercial_release_candidate_title" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_release_candidate_title" in ADMIN_TRANSLATIONS["ko"]
    assert "commercial_release_ready_with_warnings" in ADMIN_TRANSLATIONS["en"]
    assert "commercial_release_ready_with_warnings" in ADMIN_TRANSLATIONS["ko"]

    release_doc = Path("docs/commercial_release_candidate.md").read_text(encoding="utf-8")
    assert "Commercial Release Candidate" in release_doc
    assert "/api/v1/commercial_release_candidates/latest" in release_doc
    assert "KRW 2B Commercial Release Candidate" in release_doc
    assert "Figma Code Connect is not used" in release_doc
    assert "release authorization fails closed" in release_doc
    assert "Do not create a separate library, Git submodule, or extracted package now" in release_doc

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
            f"http://127.0.0.1:{port}/api/v1/commercial_release_candidates/latest",
            "inference_secret",
        )
        release_status, release = get_json(
            f"http://127.0.0.1:{port}/api/v1/commercial_release_candidates/latest",
            "admin_secret",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert unauth_status == 401
    assert unauth_body["error"]["code"] == "unauthorized"
    assert release_status == 200
    assert release["release_status"] in {
        "commercial_release_ready",
        "commercial_release_ready_with_warnings",
        "commercial_release_blocked",
    }
    assert release["measurement_status"] == "local_commercial_release_candidate"
    assert "release_artifacts" in release


if __name__ == "__main__":  # pragma: no cover
    test_commercial_release_candidate_report_packages_ship_candidate()
    test_commercial_release_candidate_endpoint_openapi_admin_and_docs_contract()
    print("ok")
