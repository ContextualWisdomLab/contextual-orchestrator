#!/usr/bin/env python3
"""Collect current GitHub evidence for the fail-closed release evaluator.

This read-only helper deliberately delegates authentication to the installed
``gh`` CLI. It prints one JSON authority snapshot and never prints command
output, tokens, prompts, or reviewer credentials.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


def _gh_json(repository: str, endpoint: str) -> dict[str, Any] | list[Any]:
    """Read one GitHub REST endpoint without exposing subprocess diagnostics."""
    completed = subprocess.run(
        ["gh", "api", "--repo", repository, endpoint],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError("github_authority_query_failed")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("github_authority_response_invalid") from exc
    if not isinstance(value, (dict, list)):
        raise RuntimeError("github_authority_response_invalid")
    return value


def _read_findings(path: str | None) -> dict[str, Any]:
    """Load the central governance finding inventory, or make absence blocking."""
    if path is None:
        return {"complete": False, "sources": [], "unresolved_findings": []}
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("findings_inventory_invalid") from exc
    if not isinstance(value, dict):
        raise RuntimeError("findings_inventory_invalid")
    return value


def _check_rows(check_runs: list[Any]) -> list[dict[str, Any]]:
    """Normalize GitHub check-run fields to the evaluator contract."""
    rows = []
    for check in check_runs:
        if isinstance(check, dict):
            rows.append(
                {
                    "name": check.get("name"),
                    "status": str(check.get("status", "")).lower(),
                    "conclusion": str(check.get("conclusion") or "").lower(),
                    "head_sha": check.get("head_sha"),
                    "synthetic_merge": False,
                }
            )
    return rows


def _review_rows(reviews: list[Any], *, head_sha: str, author_login: str) -> list[dict[str, Any]]:
    """Normalize review states while retaining only non-sensitive reviewer identity."""
    rows = []
    for review in reviews:
        if not isinstance(review, dict):
            continue
        user = review.get("user")
        login = user.get("login") if isinstance(user, dict) else None
        state = str(review.get("state", "")).lower()
        rows.append(
            {
                "login": login,
                "association": review.get("author_association"),
                "state": state,
                "head_sha": review.get("commit_id") or head_sha,
                "dismissed": state == "dismissed",
                "is_author": login == author_login,
            }
        )
    return rows


def collect_authority(
    repository: str,
    pull_request_number: int,
    required_check_names: list[str],
    findings_inventory: dict[str, Any],
    *,
    expected_head_sha: str | None = None,
) -> dict[str, Any]:
    """Collect a bounded exact-head snapshot for one pull request."""
    pull = _gh_json(repository, f"repos/{repository}/pulls/{pull_request_number}")
    if not isinstance(pull, dict):
        raise RuntimeError("pull_request_response_invalid")
    head = pull.get("head")
    base = pull.get("base")
    author = pull.get("user")
    if not isinstance(head, dict) or not isinstance(base, dict) or not isinstance(author, dict):
        raise RuntimeError("pull_request_response_invalid")
    head_sha = head.get("sha")
    base_branch = base.get("ref")
    author_login = author.get("login")
    if not isinstance(head_sha, str) or not isinstance(base_branch, str) or not isinstance(author_login, str):
        raise RuntimeError("pull_request_response_invalid")

    check_response = _gh_json(
        repository,
        f"repos/{repository}/commits/{head_sha}/check-runs?per_page=100",
    )
    checks = check_response.get("check_runs", []) if isinstance(check_response, dict) else []
    ruleset_verified = False
    try:
        rulesets = _gh_json(repository, f"repos/{repository}/rulesets?includes_parents=true")
        ruleset_verified = isinstance(rulesets, list) and bool(rulesets)
    except RuntimeError:
        ruleset_verified = False
    reviews = _gh_json(repository, f"repos/{repository}/pulls/{pull_request_number}/reviews")
    review_rows = reviews if isinstance(reviews, list) else []
    return {
        "authority_source": "github_api",
        "repository": repository,
        "base_branch": base_branch,
        "ruleset_verified": ruleset_verified,
        "head_is_current": expected_head_sha is None or expected_head_sha == head_sha,
        "synthetic_merge": False,
        "protected_head_sha": head_sha,
        "contributor_head_sha": head_sha,
        "required_check_names": required_check_names,
        "checks": _check_rows(checks),
        "review_policy": {
            "required_independent_approval_count": 1,
            "author_login": author_login,
            "head_sha": head_sha,
        },
        "reviewers": _review_rows(review_rows, head_sha=head_sha, author_login=author_login),
        "findings_inventory": findings_inventory,
    }


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and print one machine-readable snapshot."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/name GitHub repository")
    parser.add_argument("--pr", required=True, type=int, help="pull request number")
    parser.add_argument("--required-check", action="append", dest="required_checks", default=[])
    parser.add_argument("--findings-json", help="central governance finding inventory JSON")
    parser.add_argument("--expected-head-sha", help="fail if the PR head changed")
    args = parser.parse_args(argv)
    try:
        snapshot = collect_authority(
            args.repo,
            args.pr,
            args.required_checks,
            _read_findings(args.findings_json),
            expected_head_sha=args.expected_head_sha,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(snapshot, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
