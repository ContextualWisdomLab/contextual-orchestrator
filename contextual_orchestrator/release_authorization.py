"""Fail-closed policy for buyer-facing release authorization evidence.

The inference service can measure product evidence, but it cannot truthfully
claim that a GitHub head passed protected-branch governance without a fresh
authority snapshot.  This module validates that snapshot without retaining
tokens, prompts, reviewer credentials, or private reasoning.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .credentials import get_credential

_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
RELEASE_AUTHORITY_SIGNING_CREDENTIAL = "CONTEXTUAL_ORCHESTRATOR_RELEASE_AUTHORITY_SIGNING_KEY"
_SIGNATURE_FIELD = "signature"
_APPROVED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
_FINDING_SOURCES = frozenset(
    {
        "human",
        "coderabbit",
        "github_advanced_security",
        "dependabot",
        "opencode",
        "noema",
        "strix",
    }
)


def _valid_sha(value: Any) -> bool:
    """Return whether *value* is a lowercase forty-character Git SHA."""
    return isinstance(value, str) and _SHA_PATTERN.fullmatch(value) is not None


def _is_bool(value: Any, expected: bool) -> bool:
    """Match a boolean exactly, avoiding truthy strings and integers."""
    return type(value) is bool and value is expected


def _as_list(value: Any) -> list[Any] | None:
    """Return a mutable list view only for real sequence inputs."""
    return list(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else None


def _signature_payload(authority: Mapping[str, Any]) -> bytes:
    """Serialize a snapshot without its detached integrity signature."""
    if any(type(name) is not str for name in authority):
        raise ValueError("release authority keys must be strings")
    unsigned = {name: value for name, value in authority.items() if name != _SIGNATURE_FIELD}
    return json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sign_release_authority_snapshot(authority: Mapping[str, Any], signing_key: str) -> dict[str, Any]:
    """Return a collector snapshot bound to a non-exported KV signing credential."""
    if not isinstance(authority, Mapping) or not isinstance(signing_key, str) or not signing_key:
        raise ValueError("release authority signing input is invalid")
    signed = dict(authority)
    signed[_SIGNATURE_FIELD] = hmac.new(
        signing_key.encode("utf-8"), _signature_payload(signed), hashlib.sha256
    ).hexdigest()
    return signed


def verify_release_authority_snapshot(authority: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return only a snapshot signed by the runtime KV credential, otherwise ``None``."""
    if not isinstance(authority, Mapping):
        return None
    signature = authority.get(_SIGNATURE_FIELD)
    try:
        signing_key = get_credential(RELEASE_AUTHORITY_SIGNING_CREDENTIAL)
    except Exception:  # noqa: BLE001 - a signing-key outage must fail the release gate closed.
        return None
    if not isinstance(signature, str) or not isinstance(signing_key, str) or not signing_key:
        return None
    try:
        expected = hmac.new(
            signing_key.encode("utf-8"), _signature_payload(authority), hashlib.sha256
        ).hexdigest()
    except (TypeError, ValueError):
        return None
    if not hmac.compare_digest(signature, expected):
        return None
    return {name: value for name, value in authority.items() if name != _SIGNATURE_FIELD}


def _result(
    blockers: list[str],
    *,
    protected_head_sha: str | None = None,
    required_check_count: int = 0,
    passing_check_count: int = 0,
    independent_approval_count: int = 0,
    required_approval_count: int = 0,
    require_last_push_approval: bool = False,
    findings_inventory_complete: bool = False,
    unresolved_finding_count: int = 0,
) -> dict[str, Any]:
    """Build the stable, non-sensitive release-authority result shape."""
    authorized = not blockers
    return {
        "status": "release_authorized" if authorized else "release_authorization_blocked",
        "authorized": authorized,
        "blockers": blockers,
        "evidence_identities": {
            "protected_head_sha": protected_head_sha,
            "exact_head_required": True,
            "synthetic_merge_accepted": False,
        },
        "required_checks": {
            "required_count": required_check_count,
            "passing_exact_head_count": passing_check_count,
        },
        "review": {
            "required_independent_approval_count": required_approval_count,
            "independent_exact_head_approval_count": independent_approval_count,
            "require_last_push_approval": require_last_push_approval,
        },
        "findings": {
            "inventory_complete": findings_inventory_complete,
            "unresolved_count": unresolved_finding_count,
        },
    }


def evaluate_release_authorization(
    authority: Mapping[str, Any] | None,
    *,
    expected_repository: str = "ContextualWisdomLab/contextual-orchestrator",
) -> dict[str, Any]:
    """Evaluate one fresh protected-head authority snapshot.

    A missing or malformed snapshot is blocked.  The caller must supply the
    result of a trusted read-only GitHub collector; this function does not
    treat local product evidence, synthetic merge trees, stale checks, or an
    author-only approval as release authority.
    """
    if not isinstance(authority, Mapping):
        return _result(["authority_evidence_unavailable"])

    blockers: list[str] = []
    repository = authority.get("repository")
    if repository != expected_repository:
        blockers.append("repository_mismatch")
    if authority.get("base_branch") != "main":
        blockers.append("protected_main_required")
    if authority.get("authority_source") != "github_api":
        blockers.append("untrusted_authority_source")
    if not _is_bool(authority.get("ruleset_verified"), True):
        blockers.append("ruleset_not_verified")
    if not _is_bool(authority.get("head_is_current"), True):
        blockers.append("stale_head")
    if not _is_bool(authority.get("synthetic_merge"), False):
        blockers.append("synthetic_merge_not_accepted")

    protected_head_sha = authority.get("protected_head_sha")
    contributor_head_sha = authority.get("contributor_head_sha")
    if not _valid_sha(protected_head_sha):
        blockers.append("invalid_protected_head_sha")
    if not _valid_sha(contributor_head_sha):
        blockers.append("invalid_contributor_head_sha")
    if _valid_sha(protected_head_sha) and _valid_sha(contributor_head_sha) and protected_head_sha != contributor_head_sha:
        blockers.append("head_identity_mismatch")

    required_names = _as_list(authority.get("required_check_names"))
    checks = _as_list(authority.get("checks"))
    required_check_count = len(required_names or [])
    passing_check_count = 0
    if (
        required_names is None
        or not required_names
        or any(not isinstance(name, str) or not name for name in required_names)
    ):
        blockers.append("required_check_inventory_invalid")
        required_names = []
    if len(set(required_names)) != len(required_names):
        blockers.append("duplicate_required_check_name")
    if checks is None:
        blockers.append("check_evidence_unavailable")
        checks = []
    check_by_name: dict[str, Mapping[str, Any]] = {}
    for check in checks:
        if not isinstance(check, Mapping) or not isinstance(check.get("name"), str):
            blockers.append("check_evidence_invalid")
            continue
        name = check["name"]
        if name in check_by_name:
            blockers.append("duplicate_check_evidence")
        check_by_name[name] = check
    for name in required_names:
        check = check_by_name.get(name)
        if check is None:
            blockers.append(f"required_check_missing:{name}")
            continue
        exact_success = (
            check.get("status") == "completed"
            and check.get("conclusion") == "success"
            and check.get("head_sha") == protected_head_sha
            and _is_bool(check.get("synthetic_merge"), False)
        )
        if exact_success:
            passing_check_count += 1
        else:
            blockers.append(f"required_check_not_passing:{name}")

    review_policy = authority.get("review_policy")
    reviewers = _as_list(authority.get("reviewers"))
    required_approval_count = 1
    independent_approval_count = 0
    author_login: Any = None
    require_last_push_approval = True
    last_pusher_login: Any = None
    if not isinstance(review_policy, Mapping):
        blockers.append("review_policy_unavailable")
    else:
        required_approval_count = review_policy.get("required_independent_approval_count")
        author_login = review_policy.get("author_login")
        require_last_push_approval = review_policy.get("require_last_push_approval")
        last_pusher_login = review_policy.get("last_pusher_login")
        if (
            type(required_approval_count) is not int
            or required_approval_count < 1
            or type(author_login) is not str
            or type(require_last_push_approval) is not bool
            or (require_last_push_approval and (type(last_pusher_login) is not str or not last_pusher_login))
        ):
            blockers.append("review_policy_invalid")
            # A malformed or zero-review policy must never turn the release
            # gate into an approval-free authorization path.
            required_approval_count = 1
        if review_policy.get("head_sha") != protected_head_sha:
            blockers.append("review_head_mismatch")
    if reviewers is None:
        blockers.append("review_evidence_unavailable")
        reviewers = []
    latest_reviewers: dict[str, Mapping[str, Any]] = {}
    for reviewer in reviewers:
        if not isinstance(reviewer, Mapping):
            blockers.append("review_evidence_invalid")
            continue
        login = reviewer.get("login")
        if type(login) is not str or not login:
            blockers.append("review_evidence_invalid")
            continue
        # GitHub returns review events in submission order. Keep one latest
        # state per reviewer so repeated approvals cannot inflate the count
        # and a later changes-requested event cannot be ignored.
        latest_reviewers[login] = reviewer
    for reviewer in latest_reviewers.values():
        qualifies = (
            reviewer.get("state") == "approved"
            and reviewer.get("head_sha") == protected_head_sha
            and reviewer.get("dismissed") is False
            and reviewer.get("is_author") is False
            and reviewer.get("association") in _APPROVED_ASSOCIATIONS
            and type(author_login) is str
            and reviewer["login"] != author_login
            and (not require_last_push_approval or reviewer["login"] != last_pusher_login)
        )
        if qualifies:
            independent_approval_count += 1
    if independent_approval_count < required_approval_count:
        blockers.append("independent_approval_missing")
        if require_last_push_approval:
            blockers.append("last_push_approval_missing")

    findings = authority.get("findings_inventory")
    findings_complete = False
    unresolved_finding_count = 0
    if not isinstance(findings, Mapping):
        blockers.append("findings_inventory_unavailable")
    else:
        findings_complete = _is_bool(findings.get("complete"), True)
        if not findings_complete:
            blockers.append("findings_inventory_incomplete")
        sources = _as_list(findings.get("sources"))
        if (
            sources is None
            or any(not isinstance(source, str) or not source for source in sources)
            or not _FINDING_SOURCES.issubset(set(sources))
        ):
            blockers.append("findings_source_coverage_incomplete")
        unresolved = _as_list(findings.get("unresolved_findings"))
        if unresolved is None or any(not isinstance(finding, Mapping) for finding in unresolved):
            blockers.append("unresolved_finding_inventory_invalid")
        else:
            unresolved_finding_count = len(unresolved)
            if unresolved:
                blockers.append("unresolved_findings_present")

    return _result(
        blockers,
        protected_head_sha=protected_head_sha if _valid_sha(protected_head_sha) else None,
        required_check_count=required_check_count,
        passing_check_count=passing_check_count,
        independent_approval_count=independent_approval_count,
        required_approval_count=required_approval_count,
        require_last_push_approval=require_last_push_approval,
        findings_inventory_complete=findings_complete,
        unresolved_finding_count=unresolved_finding_count,
    )
