#!/usr/bin/env bash
# Shared checks-green gate for .github/workflows/release.yml's `verify` and
# `publish` jobs. Extracted into one file so the fail-fast gate in `verify`
# and the authoritative recheck in `publish` can never silently drift from
# each other -- they previously duplicated this exact jq filter inline in
# two places in the workflow YAML, and a fix landed in one copy without the
# other would have gone unnoticed (CodeRabbit maintainability finding).
#
# Fails closed unless every one of this repository's known push-triggered
# checks (RELEASE_EXPECTED_PUSH_CHECKS) has already registered as a
# check-run for TARGET_SHA, and every check GitHub reports for TARGET_SHA
# (excluding this release run's own, via GITHUB_RUN_ID) is complete with an
# acceptable conclusion.
#
# Required env: GITHUB_REPOSITORY, TARGET_SHA, GITHUB_RUN_ID,
# RELEASE_EXPECTED_PUSH_CHECKS. Needs `checks: read` (for the `gh api` call)
# and `gh` + `jq` on PATH -- both already present on GitHub-hosted runners.
set -euo pipefail

checks_pages="$(gh api "repos/${GITHUB_REPOSITORY}/commits/${TARGET_SHA}/check-runs?per_page=100" --paginate --slurp)"
# main's own required-check gate already had to pass on the *PR's* head SHA
# before this squash/merge commit could exist -- but separate
# push-triggered workflows (Security, Fuzz, ...) run again against this
# exact commit and can still be in flight or have failed. Deliberately
# checks *every* check-run GitHub reports for this SHA (not a
# ruleset-derived "required" subset -- ADR 0129 rejected the ruleset-name
# lookup specifically to avoid needing `administration: read`; checking
# everything is strictly more conservative and only needs `checks: read`).
# Excludes this release run's own check-runs (both verify's and publish's)
# via their shared GITHUB_RUN_ID, or a workflow_dispatch would always find
# itself as an unfinished check and deadlock.
observed_checks="$(echo "${checks_pages}" | jq --arg run_id "${GITHUB_RUN_ID}" '
  [ .[] | .check_runs[]? ]
  | map(select((.details_url // "") | contains("/actions/runs/" + $run_id + "/") | not))
')"
# A dispatch fired moments after a merge -- or a resume shortly after an
# older TARGET_SHA's checks first registered -- can race GitHub's own
# registration of that commit's push-triggered check-runs, so
# `observed_checks` above can legitimately be empty or partial before those
# checks exist as entries at all -- filtering an empty/partial list for
# "not complete+green" is vacuously empty too, which previously let this
# gate PASS before Security/Fuzz/CodeQL had even started. Close it the same
# conservative, no-ruleset way as above: every one of
# RELEASE_EXPECTED_PUSH_CHECKS (this repository's own known push-triggered
# job names) must already be a registered check-run for TARGET_SHA --
# absence from a report that has not caught up yet is "not ready", never
# "nothing to block on".
missing_checks="$(echo "${observed_checks}" | jq --argjson expected "${RELEASE_EXPECTED_PUSH_CHECKS}" '
  ($expected - ([.[] | .name] | unique))
')"
missing_count="$(echo "${missing_checks}" | jq 'length')"
if [ "${missing_count}" != "0" ]; then
  echo "::error::${missing_count} expected push-triggered check(s) for commit ${TARGET_SHA} have not registered yet (GitHub may still be creating check-runs for this commit): $(echo "${missing_checks}" | jq -c .). Wait a few moments and re-dispatch." >&2
  exit 1
fi
not_ready="$(echo "${observed_checks}" | jq '
  map(select(.status != "completed" or ((.conclusion // "") as $c | (["success","skipped","neutral"] | index($c)) == null)))
')"
not_ready_count="$(echo "${not_ready}" | jq 'length')"
if [ "${not_ready_count}" != "0" ]; then
  echo "::error::${not_ready_count} check(s) for commit ${TARGET_SHA} are not both complete and green (excluding this release run's own checks): $(echo "${not_ready}" | jq -c 'map({name, status, conclusion})')" >&2
  exit 1
fi
