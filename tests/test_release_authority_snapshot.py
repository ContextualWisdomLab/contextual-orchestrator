"""Tests for the read-only GitHub authority snapshot collector."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/ci/release_authority_snapshot.py"
_SPEC = importlib.util.spec_from_file_location("release_authority_snapshot", _MODULE_PATH)
assert _SPEC and _SPEC.loader
collector = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(collector)


def test_normalizers_and_missing_findings_are_fail_closed(tmp_path: Path) -> None:
    """Normalize API rows and make omitted governance findings blocking."""
    assert collector._check_rows([{"name": "Tests", "status": "COMPLETED", "conclusion": "SUCCESS", "head_sha": "a" * 40}, "bad"]) == [
        {"name": "Tests", "status": "completed", "conclusion": "success", "head_sha": "a" * 40, "synthetic_merge": False}
    ]
    assert collector._review_rows(
        [{"user": {"login": "reviewer"}, "author_association": "MEMBER", "state": "APPROVED", "commit_id": "a" * 40}],
        head_sha="a" * 40,
        author_login="author",
    )[0]["state"] == "approved"
    assert collector._read_findings(None)["complete"] is False
    findings = tmp_path / "findings.json"
    findings.write_text('{"complete": true, "sources": [], "unresolved_findings": []}', encoding="utf-8")
    assert collector._read_findings(str(findings))["complete"] is True


def test_invalid_findings_and_gh_output_are_safe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Never echo subprocess output or accept malformed inventory files."""
    bad = tmp_path / "bad.json"
    bad.write_text("not-json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="findings_inventory_invalid"):
        collector._read_findings(str(bad))

    monkeypatch.setattr(
        collector.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="secret-token", stderr="private"),
    )
    with pytest.raises(RuntimeError, match="github_authority_query_failed"):
        collector._gh_json("owner/repo", "repos/owner/repo/pulls/1")
    monkeypatch.setattr(
        collector.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(collector.subprocess.TimeoutExpired("gh", 30)),
    )
    with pytest.raises(RuntimeError, match="github_authority_query_timeout"):
        collector._gh_json("owner/repo", "repos/owner/repo/pulls/1")

    monkeypatch.setattr(
        collector.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="[]", stderr=""),
    )
    assert collector._gh_json("owner/repo", "repos/owner/repo/rulesets") == []
    monkeypatch.setattr(
        collector.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="not-json", stderr=""),
    )
    with pytest.raises(RuntimeError, match="github_authority_response_invalid"):
        collector._gh_json("owner/repo", "repos/owner/repo/rulesets")
    monkeypatch.setattr(
        collector.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="null", stderr=""),
    )
    with pytest.raises(RuntimeError, match="github_authority_response_invalid"):
        collector._gh_json("owner/repo", "repos/owner/repo/rulesets")
    invalid_findings = tmp_path / "list.json"
    invalid_findings.write_text("[]", encoding="utf-8")
    with pytest.raises(RuntimeError, match="findings_inventory_invalid"):
        collector._read_findings(str(invalid_findings))


def test_gh_api_uses_full_endpoint_and_expands_ruleset_summaries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use gh's endpoint form and fetch detail fields omitted by list responses."""
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(collector.subprocess, "run", fake_run)
    assert collector._gh_json("owner/repo", "repos/owner/repo/rulesets/7") == {"ok": True}
    assert calls[0][0:4] == ["gh", "api", "--paginate", "--slurp"]
    assert "--repo" not in calls[0]

    monkeypatch.setattr(
        collector,
        "_gh_json",
        lambda repository, endpoint: {
            "id": 7,
            "enforcement": "active",
            "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}},
            "rules": [
                {"type": "workflows", "parameters": {}},
                {"type": "pull_request", "parameters": {"required_approving_review_count": 1}},
            ],
        },
    )
    rulesets = collector._ruleset_details("owner/repo", [{"id": 7}])
    assert collector._rulesets_are_verified(rulesets) is True
    assert collector._required_approval_count(rulesets) == 1


def test_collect_authority_binds_current_pull_head(monkeypatch: pytest.MonkeyPatch) -> None:
    """The collector binds checks and reviews to the current contributor SHA."""
    head = "a" * 40
    responses = {
        "pulls/7": {"head": {"sha": head}, "base": {"ref": "main"}, "user": {"login": "author"}},
        "check-runs": {"check_runs": [{"name": "Tests", "status": "COMPLETED", "conclusion": "SUCCESS", "head_sha": head}]},
        "rulesets": [
            {
                "enforcement": "active",
                "conditions": {"ref_name": {"include": ["refs/heads/main"]}},
                "rules": [
                    {
                        "type": "required_status_checks",
                        "parameters": {"required_status_checks": [{"context": "Tests"}]},
                    },
                    {
                        "type": "required_pull_request_reviews",
                        "parameters": {"required_approving_review_count": 1},
                    },
                ],
            }
        ],
        "reviews": [{"user": {"login": "reviewer"}, "author_association": "MEMBER", "state": "APPROVED", "commit_id": head}],
    }

    def fake_api(repository: str, endpoint: str):
        if "/reviews" in endpoint:
            return responses["reviews"]
        if "check-runs" in endpoint:
            return responses["check-runs"]
        if "rulesets" in endpoint:
            return responses["rulesets"]
        if "pulls/7" in endpoint:
            return responses["pulls/7"]
        raise AssertionError(endpoint)

    monkeypatch.setattr(collector, "_gh_json", fake_api)
    snapshot = collector.collect_authority("owner/repo", 7, ["Tests"], {"complete": True}, expected_head_sha=head)
    assert snapshot["head_is_current"] is True
    assert snapshot["protected_head_sha"] == head
    assert snapshot["checks"][0]["conclusion"] == "success"
    assert snapshot["reviewers"][0]["state"] == "approved"
    assert snapshot["review_policy"]["required_independent_approval_count"] == 1
    assert collector._review_rows(["bad"], head_sha=head, author_login="author") == []
    assert collector._review_rows([{"user": None, "state": "DISMISSED"}], head_sha=head, author_login="author")[0]["dismissed"] is True
    assert collector._review_rows([{"user": {"login": "reviewer"}, "state": "APPROVED"}], head_sha=head, author_login="author")[0]["head_sha"] is None


def test_pagination_and_ruleset_helpers_flatten_and_fail_closed() -> None:
    """Pagination keeps every page while only active-main CI rules authorize collection."""
    assert collector._page_items(
        [{"check_runs": [{"name": "Tests"}]}, {"check_runs": [{"name": "Security"}]}],
        "check_runs",
    ) == [{"name": "Tests"}, {"name": "Security"}]
    rulesets = [
        {
            "enforcement": "active",
            "conditions": {"ref_name": {"include": ["main"]}},
            "rules": [
                {"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "Tests"}]}},
                {"type": "required_pull_request_reviews", "parameters": {"required_approving_review_count": 2}},
            ],
        },
        {"enforcement": "disabled", "conditions": {"ref_name": {"include": ["main"]}}, "rules": []},
    ]
    assert collector._rulesets_are_verified(rulesets) is True
    assert collector._required_check_names(rulesets) == ["Tests"]
    assert collector._required_approval_count(rulesets) == 2
    assert collector._rulesets_are_verified([{"enforcement": "active", "conditions": {}, "rules": []}]) is False


def test_collect_authority_handles_missing_ruleset_and_head_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ruleset query failure and changed expected head remain fail-closed inputs."""
    head = "a" * 40

    def fake_api(repository: str, endpoint: str):
        if "pulls/7/reviews" in endpoint:
            return {}
        if "rulesets" in endpoint:
            raise RuntimeError("unavailable")
        if "check-runs" in endpoint:
            return []
        return {"head": {"sha": head}, "base": {"ref": "main"}, "user": {"login": "author"}}

    monkeypatch.setattr(collector, "_gh_json", fake_api)
    snapshot = collector.collect_authority("owner/repo", 7, [], {}, expected_head_sha="b" * 40)
    assert snapshot["ruleset_verified"] is False
    assert snapshot["head_is_current"] is False
    assert snapshot["reviewers"] == []


def test_collect_authority_rejects_malformed_pull_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """Malformed GitHub responses stop collection before evidence is emitted."""
    monkeypatch.setattr(collector, "_gh_json", lambda repository, endpoint: [])
    with pytest.raises(RuntimeError, match="pull_request_response_invalid"):
        collector.collect_authority("owner/repo", 7, [], {}, expected_head_sha="a" * 40)
    monkeypatch.setattr(collector, "_gh_json", lambda repository, endpoint: {"head": {}, "base": {}, "user": {}})
    with pytest.raises(RuntimeError, match="pull_request_response_invalid"):
        collector.collect_authority("owner/repo", 7, [], {}, expected_head_sha="a" * 40)
    monkeypatch.setattr(collector, "_gh_json", lambda repository, endpoint: {"head": [], "base": {}, "user": {}})
    with pytest.raises(RuntimeError, match="pull_request_response_invalid"):
        collector.collect_authority("owner/repo", 7, [], {}, expected_head_sha="a" * 40)
    monkeypatch.setattr(
        collector,
        "_gh_json",
        lambda repository, endpoint: {"head": {"sha": 1}, "base": {"ref": "main"}, "user": {"login": "author"}},
    )
    with pytest.raises(RuntimeError, match="pull_request_response_invalid"):
        collector.collect_authority("owner/repo", 7, [], {}, expected_head_sha="a" * 40)


def test_main_reports_collection_errors_and_success(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI returns a nonzero code for collection failure and JSON on success."""
    monkeypatch.setattr(collector, "collect_authority", lambda *args, **kwargs: {"authorized": False})
    assert collector.main(["--repo", "owner/repo", "--pr", "7", "--expected-head-sha", "a" * 40]) == 0
    assert '"authorized": false' in capsys.readouterr().out
    monkeypatch.setattr(collector, "collect_authority", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("blocked")))
    assert collector.main(["--repo", "owner/repo", "--pr", "7", "--expected-head-sha", "a" * 40]) == 2
    assert "blocked" in capsys.readouterr().err
