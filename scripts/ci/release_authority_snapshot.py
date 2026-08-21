"""Collect current GitHub evidence for the fail-closed release evaluator.

This read-only helper deliberately delegates authentication to the installed
``gh`` CLI. It prints one JSON authority snapshot and never prints command
output, tokens, prompts, or reviewer credentials.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def _gh_json(repository: str, endpoint: str) -> dict[str, Any] | list[Any]:
    """Read every page of one GitHub REST endpoint without leaking diagnostics."""
    try:
        completed = subprocess.run(
            ["gh", "api", "--paginate", "--slurp", endpoint],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("github_authority_query_timeout") from exc
    if completed.returncode != 0:
        raise RuntimeError("github_authority_query_failed")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("github_authority_response_invalid") from exc
    if not isinstance(value, (dict, list)):
        raise RuntimeError("github_authority_response_invalid")  # noqa: TRY004
    # ``gh --paginate --slurp`` wraps pages in a list. Unwrap the common
    # one-page case while retaining multiple pages for ``_page_items``.
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], (dict, list)):
        return value[0]
    return value


def _read_findings(path: str | None) -> dict[str, Any]:
    """Load the central governance finding inventory, or make absence blocking."""
    if path is None:
        return {"complete": False, "sources": [], "unresolved_findings": []}
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("findings_inventory_invalid") from exc
    if not isinstance(value, dict):
        raise RuntimeError("findings_inventory_invalid")  # noqa: TRY004
    sources = value.get("sources")
    unresolved = value.get("unresolved_findings")
    if not isinstance(sources, list) or any(not isinstance(source, str) or not source for source in sources):
        raise RuntimeError("findings_inventory_invalid")
    if not isinstance(unresolved, list) or any(not isinstance(finding, dict) for finding in unresolved):
        raise RuntimeError("findings_inventory_invalid")
    return value


def _page_items(value: dict[str, Any] | list[Any], key: str | None = None) -> list[Any]:
    """Flatten one or many GitHub JSON pages into a list of rows."""
    if isinstance(value, dict):
        rows = value.get(key, []) if key else value
        return rows if isinstance(rows, list) else []
    if key and all(isinstance(page, dict) for page in value):
        rows: list[Any] = []
        for page in value:
            page_rows = page.get(key, [])
            if isinstance(page_rows, list):
                rows.extend(page_rows)
        return rows
    if all(isinstance(page, list) for page in value):
        return [row for page in value for row in page]
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
                # A review without commit identity cannot be promoted to the
                # current head; the evaluator must reject it as stale.
                "head_sha": review.get("commit_id"),
                "dismissed": state == "dismissed",
                "is_author": login == author_login,
            }
        )
    return rows


def _main_ref(ruleset: dict[str, Any]) -> bool:
    """Return whether an active ruleset explicitly targets protected ``main``."""
    if ruleset.get("enforcement") != "active":
        return False
    conditions = ruleset.get("conditions")
    ref_name = conditions.get("ref_name") if isinstance(conditions, dict) else None
    includes = ref_name.get("include") if isinstance(ref_name, dict) else None
    return isinstance(includes, list) and any(
        include in {"main", "refs/heads/main", "~DEFAULT_BRANCH"} for include in includes
    )


def _ruleset_rules(rulesets: list[Any]) -> list[dict[str, Any]]:
    """Return active-main rulesets that contain enforceable CI governance rules."""
    verified: list[dict[str, Any]] = []
    for ruleset in rulesets:
        if not isinstance(ruleset, dict) or not _main_ref(ruleset):
            continue
        rules = ruleset.get("rules")
        if isinstance(rules, list) and any(
            isinstance(rule, dict) and rule.get("type") in {"workflows", "required_status_checks"}
            for rule in rules
        ):
            verified.append(ruleset)
    return verified


def _ruleset_details(repository: str, rulesets: list[Any]) -> list[dict[str, Any]]:
    """Expand GitHub ruleset summaries before evaluating their rules."""
    details: list[dict[str, Any]] = []
    for ruleset in rulesets:
        if not isinstance(ruleset, dict):
            continue
        if isinstance(ruleset.get("conditions"), dict) and isinstance(ruleset.get("rules"), list):
            details.append(ruleset)
            continue
        ruleset_id = ruleset.get("id")
        if type(ruleset_id) is not int or ruleset_id < 1:
            continue
        try:
            detail = _gh_json(repository, f"repos/{repository}/rulesets/{ruleset_id}")
        except RuntimeError:
            continue
        if isinstance(detail, dict):
            details.append(detail)
    return details


def _rulesets_are_verified(rulesets: list[Any]) -> bool:
    """Verify that at least one active-main ruleset enforces CI checks."""
    return bool(_ruleset_rules(rulesets))


def _required_check_names(rulesets: list[Any]) -> list[str]:
    """Extract required status-check contexts from active-main rulesets."""
    names: list[str] = []
    for ruleset in _ruleset_rules(rulesets):
        rules = ruleset.get("rules", [])
        for rule in rules:
            if not isinstance(rule, dict) or rule.get("type") != "required_status_checks":
                continue
            parameters = rule.get("parameters")
            required = parameters.get("required_status_checks") if isinstance(parameters, dict) else None
            if not isinstance(required, list):
                continue
            for item in required:
                context = item.get("context") if isinstance(item, dict) else None
                if isinstance(context, str) and context and context not in names:
                    names.append(context)
    return names


def _required_approval_count(rulesets: list[Any]) -> int:
    """Extract the repository's required independent approval count."""
    counts: list[int] = []
    for ruleset in rulesets:
        if not isinstance(ruleset, dict) or not _main_ref(ruleset):
            continue
        rules = ruleset.get("rules", [])
        if not isinstance(rules, list):
            continue
        for rule in rules:
            if not isinstance(rule, dict) or rule.get("type") not in {"pull_request", "required_pull_request_reviews"}:
                continue
            parameters = rule.get("parameters")
            count = parameters.get("required_approving_review_count") if isinstance(parameters, dict) else None
            if type(count) is int and count >= 0:
                counts.append(count)
    return max(counts, default=0)


def collect_authority(
    repository: str,
    pull_request_number: int,
    required_check_names: list[str],
    findings_inventory: dict[str, Any],
    *,
    expected_head_sha: str | None = None,
) -> dict[str, Any]:
    """Collect a bounded exact-head snapshot for one pull request."""
    if not isinstance(expected_head_sha, str) or _SHA_PATTERN.fullmatch(expected_head_sha) is None:
        raise RuntimeError("expected_head_sha_required")
    pull = _gh_json(repository, f"repos/{repository}/pulls/{pull_request_number}")
    if not isinstance(pull, dict):
        raise RuntimeError("pull_request_response_invalid")  # noqa: TRY004
    head = pull.get("head")
    base = pull.get("base")
    author = pull.get("user")
    if not isinstance(head, dict) or not isinstance(base, dict) or not isinstance(author, dict):
        raise RuntimeError("pull_request_response_invalid")  # noqa: TRY004
    head_sha = head.get("sha")
    base_branch = base.get("ref")
    author_login = author.get("login")
    if not isinstance(head_sha, str) or not isinstance(base_branch, str) or not isinstance(author_login, str):
        raise RuntimeError("pull_request_response_invalid")  # noqa: TRY004

    check_response = _gh_json(
        repository,
        f"repos/{repository}/commits/{head_sha}/check-runs?per_page=100",
    )
    checks = _page_items(check_response, "check_runs")
    ruleset_verified = False
    rulesets: list[Any] = []
    try:
        ruleset_response = _gh_json(repository, f"repos/{repository}/rulesets?includes_parents=true&per_page=100")
        rulesets = _ruleset_details(repository, _page_items(ruleset_response))
        ruleset_verified = _rulesets_are_verified(rulesets)
    except RuntimeError:
        ruleset_verified = False
    if not required_check_names:
        required_check_names = _required_check_names(rulesets)
    reviews = _gh_json(repository, f"repos/{repository}/pulls/{pull_request_number}/reviews?per_page=100")
    review_rows = _page_items(reviews)
    final_pull = _gh_json(repository, f"repos/{repository}/pulls/{pull_request_number}")
    final_head = final_pull.get("head") if isinstance(final_pull, dict) else None
    final_head_sha = final_head.get("sha") if isinstance(final_head, dict) else None
    if not isinstance(final_head_sha, str):
        raise RuntimeError("pull_request_response_invalid")  # noqa: TRY004
    if final_head_sha != head_sha:
        raise RuntimeError("pull_request_changed_during_collection")
    return {
        "authority_source": "github_api",
        "repository": repository,
        "base_branch": base_branch,
        "ruleset_verified": ruleset_verified,
        "head_is_current": expected_head_sha == head_sha == final_head_sha,
        "synthetic_merge": False,
        "protected_head_sha": head_sha,
        "contributor_head_sha": head_sha,
        "required_check_names": required_check_names,
        "checks": _check_rows(checks),
        "review_policy": {
            "required_independent_approval_count": _required_approval_count(rulesets),
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
    parser.add_argument("--expected-head-sha", required=True, help="fail if the PR head changed")
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
