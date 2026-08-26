from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.admin import ADMIN_HTML, ADMIN_TRANSLATIONS  # noqa: E402
from contextual_orchestrator.api_contract import OPENAPI_SPEC  # noqa: E402
from contextual_orchestrator.credentials import InMemoryCredentialBackend, set_backend  # noqa: E402
from contextual_orchestrator.release_authorization import (  # noqa: E402
    RELEASE_AUTHORITY_SIGNING_CREDENTIAL,
    sign_release_authority_snapshot,
)
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


TARGET_CONTRACT_VALUE_KRW = 2_000_000_000
AUTHORITY_HEAD = "a" * 40


def valid_release_authority() -> dict[str, object]:
    """Return a complete exact-head authority snapshot for the positive path."""
    return {
        "authority_source": "github_api",
        "collected_at_epoch": int(time.time()),
        "repository": "ContextualWisdomLab/contextual-orchestrator",
        "base_branch": "main",
        "ruleset_verified": True,
        "head_is_current": True,
        "synthetic_merge": False,
        "protected_head_sha": AUTHORITY_HEAD,
        "contributor_head_sha": AUTHORITY_HEAD,
        "required_check_names": ["Tests"],
        "checks": [
            {
                "name": "Tests",
                "status": "completed",
                "conclusion": "success",
                "head_sha": AUTHORITY_HEAD,
                "synthetic_merge": False,
            }
        ],
        "review_policy": {
            "required_independent_approval_count": 1,
            "require_last_push_approval": False,
            "last_pusher_login": None,
            "author_login": "author",
            "head_sha": AUTHORITY_HEAD,
        },
        "reviewers": [
            {
                "login": "reviewer",
                "association": "MEMBER",
                "state": "approved",
                "head_sha": AUTHORITY_HEAD,
                "dismissed": False,
                "is_author": False,
            }
        ],
        "findings_inventory": {
            "complete": True,
            "sources": ["human", "coderabbit", "github_advanced_security", "dependabot", "opencode", "noema", "strix"],
            "unresolved_findings": [],
        },
    }


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
    assert report["release_summary"]["blocked_count"] == 1
    assert report["release_summary"]["product_blocked_count"] == 0
    assert report["release_summary"]["warning_count"] == 2
    assert report["release_summary"]["release_authority_blocker_count"] == 1
    assert report["release_authorization"]["blockers"] == ["authority_evidence_unavailable"]
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

    authorized_report = orchestrator.commercial_release_candidate_report(
        target_contract_value_krw=TARGET_CONTRACT_VALUE_KRW,
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile={
            "auth_mode": "split_token",
            "allow_public_bind": False,
            "expose_trace_by_default": False,
            "rate_limit_requests": 60,
            "max_concurrent_runs": 8,
        },
        release_authority=valid_release_authority(),
    )
    assert authorized_report["release_summary"]["release_authority_blocker_count"] == 0
    assert authorized_report["release_summary"]["blocked_count"] == 0


def test_product_evidence_status_blocks_when_release_artifact_is_missing(monkeypatch) -> None:
    """A missing repository artifact must block product evidence, not only authority."""
    original_is_file = Path.is_file

    def missing_release_candidate(path: Path) -> bool:
        if path.as_posix().endswith("/docs/commercial_release_candidate.md"):
            return False
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", missing_release_candidate)

    orchestrator = build()
    exercise_runtime(orchestrator)
    report = orchestrator.commercial_release_candidate_report(
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile={
            "auth_mode": "split_token",
            "allow_public_bind": False,
            "expose_trace_by_default": False,
            "rate_limit_requests": 60,
            "max_concurrent_runs": 8,
        },
    )

    assert report["product_evidence_status"] == "commercial_release_blocked"
    assert report["release_summary"]["product_blocked_count"] == 1
    assert report["release_status"] == "commercial_release_blocked"


def test_commercial_release_candidate_endpoint_openapi_admin_and_docs_contract() -> None:
    assert "/api/v1/commercial_release_candidates/latest" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/api/v1/commercial_release_candidates/latest"]["get"]["operationId"] == (
        "get_latest_commercial_release_candidate"
    )
    response_schema = OPENAPI_SPEC["paths"]["/api/v1/commercial_release_candidates/latest"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert response_schema == {"$ref": "#/components/schemas/CommercialReleaseCandidate"}
    assert OPENAPI_SPEC["components"]["schemas"]["CommercialReleaseCandidate"]["properties"]["release_authorization"] == {
        "$ref": "#/components/schemas/ReleaseAuthorization"
    }
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
    assert "Product evidence and release authorization are separate" in release_doc
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
    assert release["release_status"] == "commercial_release_blocked"
    assert release["measurement_status"] == "local_commercial_release_candidate"
    assert "release_artifacts" in release


def test_server_blocks_an_unsigned_release_authority_snapshot() -> None:
    """A caller-controlled JSON object cannot claim protected release evidence."""
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(admin_token="admin_secret", inference_token="inference_secret"),
        release_authority={"repository": "wrong/repository"},
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, report = get_json(
            f"http://127.0.0.1:{server.server_address[1]}/api/v1/commercial_release_candidates/latest",
            "admin_secret",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert status == 200
    assert report["release_authorization"]["blockers"] == ["authority_evidence_unavailable"]


def test_server_accepts_only_a_kv_signed_release_authority_snapshot() -> None:
    backend = InMemoryCredentialBackend()
    backend.set(RELEASE_AUTHORITY_SIGNING_CREDENTIAL, "test-signing-key")
    set_backend(backend)
    try:
        server = build_server(
            build(),
            port=0,
            security=SecurityConfig(admin_token="admin_secret", inference_token="inference_secret"),
            release_authority=sign_release_authority_snapshot(valid_release_authority(), "test-signing-key"),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, report = get_json(
                f"http://127.0.0.1:{server.server_address[1]}/api/v1/commercial_release_candidates/latest",
                "admin_secret",
            )
        finally:
            server.shutdown()
            thread.join(timeout=5)
        assert status == 200
        assert report["release_authorization"]["authorized"] is True
    finally:
        set_backend(None)


if __name__ == "__main__":  # pragma: no cover
    test_commercial_release_candidate_report_packages_ship_candidate()
    test_commercial_release_candidate_endpoint_openapi_admin_and_docs_contract()
    print("ok")
