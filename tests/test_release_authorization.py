"""Deterministic acceptance tests for the fail-closed release gate."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import evaluate_release_authorization  # noqa: E402


HEAD = "a" * 40


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
            "reviewers": ["bad"],
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
