#!/usr/bin/env bash
# Shared checks-green gate for .github/workflows/release.yml's `verify` and
# `publish` jobs. Extracted into one file so the fail-fast gate in `verify`
# and the authoritative recheck in `publish` can never silently drift from
# each other -- they previously duplicated this exact jq filter inline in
# two places in the workflow YAML, and a fix landed in one copy without the
# other would have gone unnoticed (CodeRabbit maintainability finding).
#
# Fails closed unless every one of this repository's REQUIRED release checks
# (the explicit allowlist RELEASE_EXPECTED_PUSH_CHECKS: the push-triggered
# security.yml job names) has registered as a check-run for TARGET_SHA and
# every check-run with one of those names completed with conclusion
# `success`. Every other check-run GitHub reports for TARGET_SHA is
# informational only and is ignored: scheduled maintenance workflows such as
# the hourly `opencode-hourly-loop.yml` and `provider-catalog-sync.yml` run
# against main's tip and attach their check-runs to the same commit, and
# their failures (or in-flight runs) must not block or certify a release.
# This release run's own check-runs never count either.
#
# Required env: GITHUB_REPOSITORY, TARGET_SHA, GITHUB_RUN_ID,
# RELEASE_EXPECTED_PUSH_CHECKS. Needs `checks: read` (for the `gh api` call)
# and `gh` + `jq` on PATH -- both already present on GitHub-hosted runners.
set -euo pipefail

checks_pages="$(gh api "repos/${GITHUB_REPOSITORY}/commits/${TARGET_SHA}/check-runs?per_page=100" --paginate --slurp)"

# An empty or malformed allowlist would make every later filter vacuous, so
# it is itself a hard failure rather than "nothing required".
if ! expected_count="$(echo "${RELEASE_EXPECTED_PUSH_CHECKS}" | jq -e 'if type == "array" and length > 0 and all(.[]; type == "string" and length > 0) then length else error("invalid") end' 2>/dev/null)"; then
  echo "::error::RELEASE_EXPECTED_PUSH_CHECKS must be a non-empty JSON array of required check names; refusing to evaluate an empty or malformed allowlist." >&2
  exit 1
fi

# Excludes this release run's own check-runs (both verify's and publish's)
# via their shared GITHUB_RUN_ID, or a workflow_dispatch would always find
# itself as an unfinished check and deadlock.
observed_checks="$(echo "${checks_pages}" | jq --arg run_id "${GITHUB_RUN_ID}" '
  [ .[] | .check_runs[]? ]
  | map(select((.details_url // "") | contains("/actions/runs/" + $run_id + "/") | not))
')"

# Only the allowlisted required checks are evaluated. Deliberately an
# allowlist, not a denylist of known noisy workflows: a newly added scheduled
# or optional workflow can neither block a release nor stand in for a
# required check. ADR 0129 rejected a live ruleset lookup (it needs
# `administration: read`), so the required names are pinned in release.yml
# and kept equal to security.yml's job names by
# tests/test_release_workflow_contract.py.
required_checks="$(echo "${observed_checks}" | jq --argjson expected "${RELEASE_EXPECTED_PUSH_CHECKS}" '
  map(select(.name as $name | ($expected | index($name)) != null))
')"
ignored_names="$(echo "${observed_checks}" | jq -c --argjson expected "${RELEASE_EXPECTED_PUSH_CHECKS}" '
  map(select(.name as $name | ($expected | index($name)) == null) | .name) | unique
')"
if [ "${ignored_names}" != "[]" ]; then
  echo "::notice::Ignoring non-required check-runs for commit ${TARGET_SHA} (they neither block nor certify a release): ${ignored_names}"
fi

# A dispatch fired moments after a merge -- or a resume shortly after an
# older TARGET_SHA's checks first registered -- can race GitHub's own
# registration of that commit's push-triggered check-runs, so the report can
# legitimately be empty or partial. Absence of a required check is "not
# ready", never "nothing to block on".
missing_checks="$(echo "${required_checks}" | jq --argjson expected "${RELEASE_EXPECTED_PUSH_CHECKS}" '
  ($expected - ([.[] | .name] | unique))
')"
missing_count="$(echo "${missing_checks}" | jq 'length')"
if [ "${missing_count}" != "0" ]; then
  echo "::error::${missing_count} expected push-triggered check(s) (of ${expected_count} required) for commit ${TARGET_SHA} have not registered yet (GitHub may still be creating check-runs for this commit): $(echo "${missing_checks}" | jq -c .). Wait a few moments and re-dispatch." >&2
  exit 1
fi

# Registering a required job name is not enough. A pending, failed, skipped
# or neutral required job cannot certify the immutable publication boundary:
# every check-run carrying a required name must be completed with the exact
# conclusion `success`.
required_not_success="$(echo "${required_checks}" | jq '
  map(select(.status != "completed" or (.conclusion // "") != "success"))
')"
required_not_success_count="$(echo "${required_not_success}" | jq 'length')"
if [ "${required_not_success_count}" != "0" ]; then
  echo "::error::${required_not_success_count} required check-run(s) for commit ${TARGET_SHA} are not complete with conclusion success: $(echo "${required_not_success}" | jq -c 'map({name, status, conclusion})')" >&2
  exit 1
fi

echo "::notice::All ${expected_count} required checks for commit ${TARGET_SHA} completed with conclusion success."
