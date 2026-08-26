"""Deterministic acceptance tests for the fail-closed release gate."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import evaluate_release_authorization  # noqa: E402
from contextual_orchestrator.credentials import InMemoryCredentialBackend, set_backend  # noqa: E402
from contextual_orchestrator.release_authorization import (  # noqa: E402
    RELEASE_AUTHORITY_SIGNING_CREDENTIAL,
    sign_release_authority_snapshot,
    verify_release_authority_snapshot,
)


HEAD = "a" * 40


class AlwaysNotEqualString(str):
    """Model an untrusted string subclass that lies to a comparison."""

    def __ne__(self, _other: object) -> bool:
        return True


class FailingCredentialBackend(InMemoryCredentialBackend):
    """Model a KV outage while release evidence is verified."""

    def get(self, name: str) -> str | None:
        """Raise the outage reported by an unavailable credential registry."""
        raise RuntimeError(name)


def authority() -> dict[str, object]:
    """Return a complete trusted-snapshot shape for the nominal case."""
    return {
        "authority_source": "github_api",
        "repository": "ContextualWisdomLab/contextual-orchestrator",
        "base_branch": "main",
        "ruleset_verified": True,
        "head_is_current": True,
        "synthetic_merge": False,
        "protected_head_sha": HEAD,
        "contributor_head_sha": HEAD,
        "required_check_names": ["Tests", "Security"],
        "checks": [
            {"name": "Tests", "status": "completed", "conclusion": "success", "head_sha": HEAD, "synthetic_merge": False},
            {"name": "Security", "status": "completed", "conclusion": "success", "head_sha": HEAD, "synthetic_merge": False},
        ],
        "review_policy": {
            "required_independent_approval_count": 1,
            "require_last_push_approval": False,
            "last_pusher_login": None,
            "author_login": "author",
            "head_sha": HEAD,
        },
        "reviewers": [
            {
                "login": "reviewer",
                "association": "MEMBER",
                "state": "approved",
                "head_sha": HEAD,
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


def test_exact_head_checks_and_independent_approval_authorize() -> None:
    """All protected evidence must agree before release authorization passes."""
    result = evaluate_release_authorization(authority())
    assert result["authorized"] is True
    assert result["status"] == "release_authorized"
    assert result["blockers"] == []
    assert result["required_checks"] == {"required_count": 2, "passing_exact_head_count": 2}
    assert result["review"]["independent_exact_head_approval_count"] == 1


def test_missing_authority_preserves_fail_closed_boundary() -> None:
    """Product evidence without a GitHub authority snapshot cannot authorize release."""
    result = evaluate_release_authorization(None)
    assert result["status"] == "release_authorization_blocked"
    assert result["blockers"] == ["authority_evidence_unavailable"]


def test_authority_snapshot_requires_a_kv_backed_signature() -> None:
    backend = InMemoryCredentialBackend()
    set_backend(backend)
    try:
        signed = sign_release_authority_snapshot(authority(), "test-signing-key")
        assert verify_release_authority_snapshot(signed) is None
        backend.set(RELEASE_AUTHORITY_SIGNING_CREDENTIAL, "test-signing-key")
        assert verify_release_authority_snapshot(signed) == authority()
        signed["head_is_current"] = False
        assert verify_release_authority_snapshot(signed) is None
    finally:
        set_backend(None)


def test_signature_boundary_rejects_malformed_inputs_and_kv_outage() -> None:
    """Malformed, unserializable, or unverifiable snapshots fail closed."""
    with pytest.raises(ValueError, match="signing input"):
        sign_release_authority_snapshot(authority(), "")
    with pytest.raises(ValueError, match="keys must be strings"):
        sign_release_authority_snapshot({1: "invalid"}, "key")

    assert verify_release_authority_snapshot(None) is None
    backend = InMemoryCredentialBackend()
    backend.set(RELEASE_AUTHORITY_SIGNING_CREDENTIAL, "key")
    set_backend(backend)
    try:
        assert verify_release_authority_snapshot({"signature": "invalid", "value": float("nan")}) is None
    finally:
        set_backend(FailingCredentialBackend())
    try:
        assert verify_release_authority_snapshot({"signature": "invalid"}) is None
    finally:
        set_backend(None)


def test_zero_required_approvals_cannot_authorize_release() -> None:
    """A zero-review policy remains blocked instead of becoming an open gate."""
    evidence = authority()
    evidence["review_policy"] = {
        **evidence["review_policy"],
        "required_independent_approval_count": 0,
    }
    evidence["reviewers"] = []

    result = evaluate_release_authorization(evidence)

    assert result["authorized"] is False
    assert {"review_policy_invalid", "independent_approval_missing"}.issubset(result["blockers"])


def test_last_pusher_cannot_supply_required_last_push_approval() -> None:
    """A ruleset last-push gate requires approval from a different principal."""
    evidence = authority()
    evidence["review_policy"] = {
        **evidence["review_policy"],
        "require_last_push_approval": True,
        "last_pusher_login": "reviewer",
    }
    assert "independent_approval_missing" in evaluate_release_authorization(evidence)["blockers"]

    evidence["review_policy"]["last_pusher_login"] = "pusher"
    assert evaluate_release_authorization(evidence)["authorized"] is True


def test_queued_stale_and_synthetic_check_evidence_blocks() -> None:
    """Queued, stale, or synthetic evidence never counts as a passing check."""
    evidence = authority()
    evidence["head_is_current"] = False
    evidence["checks"] = [
        {"name": "Tests", "status": "queued", "conclusion": "", "head_sha": HEAD, "synthetic_merge": False},
        {"name": "Security", "status": "completed", "conclusion": "success", "head_sha": "b" * 40, "synthetic_merge": True},
    ]
    result = evaluate_release_authorization(evidence)
    assert result["authorized"] is False
    assert {"stale_head", "required_check_not_passing:Tests", "required_check_not_passing:Security"}.issubset(result["blockers"])


def test_author_only_or_dismissed_approval_blocks() -> None:
    """The PR author and dismissed reviews do not satisfy independent approval."""
    evidence = authority()
    evidence["reviewers"] = [
        {"login": "author", "association": "MEMBER", "state": "approved", "head_sha": HEAD, "dismissed": False, "is_author": True},
        {"login": "dismissed", "association": "MEMBER", "state": "approved", "head_sha": HEAD, "dismissed": True, "is_author": False},
    ]
    result = evaluate_release_authorization(evidence)
    assert "independent_approval_missing" in result["blockers"]
    assert result["review"]["independent_exact_head_approval_count"] == 0


def test_string_subclass_cannot_bypass_author_exclusion() -> None:
    """Untrusted string subclasses cannot make an author approval independent."""
    evidence = authority()
    evidence["review_policy"] = {
        **evidence["review_policy"],
        "author_login": AlwaysNotEqualString("author"),
    }
    evidence["reviewers"] = [
        {
            "login": "author",
            "association": "MEMBER",
            "state": "approved",
            "head_sha": HEAD,
            "dismissed": False,
            "is_author": False,
        }
    ]

    result = evaluate_release_authorization(evidence)

    assert result["authorized"] is False
    assert "review_policy_invalid" in result["blockers"]
    assert result["review"]["independent_exact_head_approval_count"] == 0


def test_latest_review_state_is_counted_once_per_reviewer() -> None:
    """Repeated review events cannot inflate approval or hide a later rejection."""
    evidence = authority()
    evidence["review_policy"] = {**evidence["review_policy"], "required_independent_approval_count": 2}
    evidence["reviewers"] = [
        {"login": "reviewer", "association": "MEMBER", "state": "approved", "head_sha": HEAD, "dismissed": False, "is_author": False},
        {"login": "reviewer", "association": "MEMBER", "state": "changes_requested", "head_sha": HEAD, "dismissed": False, "is_author": False},
        {"login": "reviewer_two", "association": "MEMBER", "state": "approved", "head_sha": HEAD, "dismissed": False, "is_author": False},
    ]
    result = evaluate_release_authorization(evidence)
    assert result["review"]["independent_exact_head_approval_count"] == 1
    assert "independent_approval_missing" in result["blockers"]


def test_unresolved_or_incomplete_findings_block() -> None:
    """An incomplete inventory or one unresolved finding blocks authorization."""
    evidence = authority()
    evidence["findings_inventory"] = {
        "complete": False,
        "sources": ["human"],
        "unresolved_findings": [{"source": "strix", "id": "F-1"}],
    }
    result = evaluate_release_authorization(evidence)
    assert {"findings_inventory_incomplete", "findings_source_coverage_incomplete", "unresolved_findings_present"}.issubset(result["blockers"])
    assert result["findings"] == {"inventory_complete": False, "unresolved_count": 1}


def test_invalid_and_duplicate_evidence_is_not_coerced() -> None:
    """Malformed types, duplicate check names, and mismatched identities fail closed."""
    evidence = authority()
    evidence.update(
        {
            "repository": "other/repository",
            "authority_source": "local_json",
            "ruleset_verified": "true",
            "synthetic_merge": True,
            "protected_head_sha": "not-a-sha",
            "contributor_head_sha": "not-a-contributor-sha",
            "required_check_names": ["Tests", "Tests", 1],
            "checks": [{"name": "Tests"}, {"name": "Tests"}, "bad"],
            "review_policy": {"required_independent_approval_count": True, "head_sha": "wrong"},
            "reviewers": ["bad", {"login": ""}],
            "findings_inventory": {"complete": True, "sources": None, "unresolved_findings": None},
        }
    )
    result = evaluate_release_authorization(evidence, expected_repository="expected/repository")
    assert result["authorized"] is False
    assert {
        "repository_mismatch",
        "untrusted_authority_source",
        "ruleset_not_verified",
        "synthetic_merge_not_accepted",
        "invalid_protected_head_sha",
        "invalid_contributor_head_sha",
        "required_check_inventory_invalid",
        "duplicate_check_evidence",
        "check_evidence_invalid",
        "review_policy_invalid",
        "review_head_mismatch",
        "review_evidence_invalid",
        "findings_source_coverage_incomplete",
        "unresolved_finding_inventory_invalid",
    }.issubset(result["blockers"])


def test_absent_approval_requirement_and_unhashable_sources_block() -> None:
    """Missing policy keys and malformed source entries fail closed."""
    evidence = authority()
    evidence["review_policy"] = {"author_login": "author", "head_sha": HEAD}
    evidence["reviewers"] = []
    result = evaluate_release_authorization(evidence)
    assert "review_policy_invalid" in result["blockers"]

    evidence = authority()
    evidence["findings_inventory"] = {
        "complete": True,
        "sources": [{"name": "human"}],
        "unresolved_findings": [],
    }
    result = evaluate_release_authorization(evidence)
    assert "findings_source_coverage_incomplete" in result["blockers"]


def test_missing_policy_components_and_exact_head_mismatch_block() -> None:
    """Report every missing authority component instead of inferring defaults."""
    evidence = authority()
    evidence.update(
        {
            "base_branch": "develop",
            "protected_head_sha": HEAD,
            "contributor_head_sha": "b" * 40,
            "required_check_names": ["Tests", "Tests", "Security"],
            "checks": None,
            "review_policy": None,
            "reviewers": None,
            "findings_inventory": None,
        }
    )
    result = evaluate_release_authorization(evidence)
    assert {
        "protected_main_required",
        "head_identity_mismatch",
        "duplicate_required_check_name",
        "check_evidence_unavailable",
        "required_check_missing:Tests",
        "required_check_missing:Security",
        "review_policy_unavailable",
        "review_evidence_unavailable",
        "findings_inventory_unavailable",
    }.issubset(result["blockers"])


def test_product_evidence_and_release_authority_are_separate() -> None:
    """The report stays useful for demos while its release status remains blocked."""
    from contextual_orchestrator import ModelAgent, TaskOrchestrator

    orchestrator = TaskOrchestrator([ModelAgent("general_agent", "mock-generalist")])
    orchestrator.record_analytics_event(
        "chat_completion_requested",
        {"endpoint_path": "/v1/chat/completions", "actor_scope": "inference", "status_code": 200, "duration_ms": 8},
    )
    orchestrator.run([{"role": "user", "content": "release evidence"}], mode="route")
    orchestrator.run_evaluation(["release evidence replay"], mode="route")
    report = orchestrator.commercial_release_candidate_report(
        security_profile={
            "auth_mode": "split_token",
            "allow_public_bind": False,
            "expose_trace_by_default": False,
            "rate_limit_requests": 60,
            "max_concurrent_runs": 8,
        }
    )
    assert report["product_evidence_status"] in {
        "commercial_release_ready",
        "commercial_release_ready_with_warnings",
        "commercial_release_blocked",
    }
    assert report["release_status"] == "commercial_release_blocked"
    assert report["release_authorization"]["blockers"] == ["authority_evidence_unavailable"]


def test_valid_authority_flows_through_commercial_readiness_wrappers() -> None:
    """A complete authority snapshot authorizes every downstream commercial gate."""
    from contextual_orchestrator import ModelAgent, TaskOrchestrator
    from contextual_orchestrator.admin import ADMIN_TRANSLATIONS

    orchestrator = TaskOrchestrator(
        [
            ModelAgent("planner_agent", "mock-planner", tags=("planning", "reasoning")),
            ModelAgent("builder_agent", "mock-builder", tags=("coding", "implementation")),
            ModelAgent("reviewer_agent", "mock-reviewer", tags=("verification", "security", "review")),
        ]
    )
    orchestrator.record_analytics_event(
        "chat_completion_requested",
        {"endpoint_path": "/v1/chat/completions", "actor_scope": "inference", "status_code": 200, "duration_ms": 8},
    )
    orchestrator.run(
        [{"role": "user", "content": "Analyze the product, implement the control plane, verify it, and summarize."}],
        mode="conduct",
    )
    orchestrator.run_evaluation(["Replay this commercial release candidate prompt."], mode="route")
    security_profile = {
        "auth_mode": "split_token",
        "allow_public_bind": False,
        "expose_trace_by_default": False,
        "rate_limit_requests": 60,
        "max_concurrent_runs": 8,
    }
    release = orchestrator.commercial_release_candidate_report(
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile=security_profile,
        release_authority=authority(),
    )
    procurement = orchestrator.commercial_procurement_readiness_report(
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile=security_profile,
        release_authority=authority(),
    )
    contract = orchestrator.commercial_contract_readiness_report(
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile=security_profile,
        release_authority=authority(),
    )
    onboarding = orchestrator.commercial_onboarding_readiness_report(
        locale_bundles=ADMIN_TRANSLATIONS,
        security_profile=security_profile,
        release_authority=authority(),
    )

    assert release["release_authorization"]["blockers"] == []
    assert release["release_status"] == "commercial_release_ready_with_warnings"
    assert procurement["release_authorization"]["status"] == "release_authorized"
    assert contract["related_runtime_reports"]["release_authorization_status"] == "release_authorized"
    assert onboarding["release_authorization"]["blockers"] == []
    assert onboarding["related_runtime_reports"]["release_authorization_status"] == "release_authorized"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
    print("release authorization checks passed")
