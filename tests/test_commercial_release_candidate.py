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
from contextual_orchestrator.orchestrator import evaluate_release_authorization  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


TARGET_CONTRACT_VALUE_KRW = 2_000_000_000
_TEST_ADMIN_TOKEN = "admin_secret"  # noqa: S105
_TEST_INFERENCE_TOKEN = "inference_secret"  # noqa: S105
_HEAD = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


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


def authorized_evidence() -> dict[str, object]:
    return {
        "protected_head_sha": _HEAD,
        "exact_head_sha": _HEAD,
        "required_checks": [
            {"check_name": "Full unit and contract suite", "conclusion": "success", "head_sha": _HEAD},
            {"check_name": "CodeQL analysis", "conclusion": "success", "head_sha": _HEAD},
        ],
        "independent_approvals": [{"reviewer_login": "independent_reviewer", "author_association": "MEMBER"}],
        "unresolved_findings": [],
        "author_login": "pr_author",
    }


def test_evaluate_release_authorization_fail_closed_matrix() -> None:
    absent = evaluate_release_authorization(None)
    assert absent["authorization_status"] == "release_authorization_blocked"
    assert "release_authority_evidence_absent" in absent["blocker_reasons"]

    pending = evaluate_release_authorization(
        {
            **authorized_evidence(),
            "required_checks": [
                {"check_name": "Full unit and contract suite", "conclusion": "pending", "head_sha": _HEAD},
            ],
        }
    )
    assert pending["authorization_status"] == "release_authorization_blocked"
    assert any(reason.startswith("required_check_not_passing") for reason in pending["blocker_reasons"])

    stale = evaluate_release_authorization(
        {
            **authorized_evidence(),
            "required_checks": [
                {
                    "check_name": "Full unit and contract suite",
                    "conclusion": "success",
                    "head_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                },
            ],
        }
    )
    assert "required_check_stale_or_predecessor_head" in stale["blocker_reasons"]

    author_only = evaluate_release_authorization(
        {
            **authorized_evidence(),
            "independent_approvals": [{"reviewer_login": "pr_author", "author_association": "OWNER"}],
        }
    )
    assert author_only["authorization_status"] == "release_authorization_blocked"
    assert (
        "author_only_approval_insufficient" in author_only["blocker_reasons"]
        or "independent_approval_missing" in author_only["blocker_reasons"]
    )

    findings = evaluate_release_authorization(
        {
            **authorized_evidence(),
            "unresolved_findings": [{"finding_id": "GHSA-test", "source_name": "Dependabot"}],
        }
    )
    assert "unresolved_findings_present" in findings["blocker_reasons"]

    ok = evaluate_release_authorization(authorized_evidence())
    assert ok["authorization_status"] == "release_authorized"
    assert ok["blocker_reasons"] == []


def test_commercial_release_candidate_report_packages_ship_candidate() -> None:
    orchestrator = build()
    exercise_runtime(orchestrator)

    # Without authority evidence: product evidence may be inspectable, release is blocked.
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

    assert report["product_evidence_status"] == "commercial_release_ready_with_warnings"
    assert report["release_status"] == "commercial_release_blocked"
    assert report["release_authorization"]["authorization_status"] == "release_authorization_blocked"
    assert "release_authority_evidence_absent" in report["release_authorization"]["blocker_reasons"]
    assert report["target_contract_value_krw"] == TARGET_CONTRACT_VALUE_KRW
    assert report["measurement_status"] == "local_commercial_release_candidate"
    assert "not a valuation guarantee" in report["source_note"]
    assert report["release_summary"]["blocked_count"] == 0
    assert report["release_summary"]["warning_count"] == 2
    assert report["release_summary"]["review_process_is_blocker"] is True
    assert report["concrete_blockers"] == []
    assert report["release_authority_blockers"][0]["blocker_class"] == "release_authorization"
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

    authorized = orchestrator.commercial_release_candidate_report(
        target_contract_value_krw=TARGET_CONTRACT_VALUE_KRW,
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile={
            "auth_mode": "split_token",
            "allow_public_bind": False,
            "expose_trace_by_default": False,
            "rate_limit_requests": 60,
            "max_concurrent_runs": 8,
        },
        release_authority=authorized_evidence(),
    )
    assert authorized["product_evidence_status"] == "commercial_release_ready_with_warnings"
    assert authorized["release_status"] == "commercial_release_ready_with_warnings"
    assert authorized["release_authorization"]["authorization_status"] == "release_authorized"
    assert authorized["release_summary"]["review_process_is_blocker"] is False


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
    assert "fail-closed" in release_doc.lower() or "Fail-closed" in release_doc
    assert "product_evidence_status" in release_doc
    assert "Do not create a separate library, Git submodule, or extracted package now" in release_doc
    assert "NIST" in release_doc

    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(admin_token=_TEST_ADMIN_TOKEN, inference_token=_TEST_INFERENCE_TOKEN),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    try:
        unauth_status, unauth_body = get_json(
            f"http://127.0.0.1:{port}/api/v1/commercial_release_candidates/latest",
            _TEST_INFERENCE_TOKEN,
        )
        release_status, release = get_json(
            f"http://127.0.0.1:{port}/api/v1/commercial_release_candidates/latest",
            _TEST_ADMIN_TOKEN,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert unauth_status == 401
    assert unauth_body["error"]["code"] == "unauthorized"
    assert release_status == 200
    assert release["release_status"] == "commercial_release_blocked"
    assert release["product_evidence_status"] in {
        "commercial_release_ready",
        "commercial_release_ready_with_warnings",
        "commercial_release_blocked",
    }
    assert release["release_authorization"]["authorization_status"] == "release_authorization_blocked"


if __name__ == "__main__":  # pragma: no cover
    test_evaluate_release_authorization_fail_closed_matrix()
    test_commercial_release_candidate_report_packages_ship_candidate()
    test_commercial_release_candidate_endpoint_openapi_admin_and_docs_contract()
    print("ok")


def test_package_exports_evaluate_release_authorization() -> None:
    from contextual_orchestrator import evaluate_release_authorization as exported

    assert exported(None)["authorization_status"] == "release_authorization_blocked"
