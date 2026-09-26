#!/usr/bin/env bash
# Shared checks-green gate for .github/workflows/release.yml's `verify` and
# `publish` jobs. Extracted into one file so the fail-fast gate in `verify`
# and the authoritative recheck in `publish` can never silently drift from
# each other -- they previously duplicated this exact jq filter inline in
# two places in the workflow YAML, and a fix landed in one copy without the
# other would have gone unnoticed (CodeRabbit maintainability finding).
#
# What certifies a release commit: the newest `push`-event run of
# .github/workflows/security.yml on `main` for exactly TARGET_SHA, and in
# that one run, every REQUIRED job named in the explicit allowlist
# RELEASE_EXPECTED_PUSH_CHECKS completed with conclusion `success`.
#
# Why a single workflow run and not "every check-run with a required name":
#   - security.yml's weekly `schedule` runs execute on main's tip too, and
#     their jobs are `if: github.event_name != 'schedule'`, so they leave
#     skipped (or failed) check-runs under the SAME required names on the
#     same commit. Judging names across all check-runs let one scheduled run
#     block a commit forever.
#   - Hourly maintenance workflows (opencode-hourly-loop.yml,
#     provider-catalog-sync.yml) and this release run's own jobs also attach
#     check-runs to main's tip. None of them is a required check; binding to
#     one security.yml push run ignores them without a denylist and without
#     the old, brittle "exclude my own run by details_url" filter.
#
# Selection is fail-closed:
#   - runs are listed with `head_sha=TARGET_SHA&event=push`, then re-filtered
#     locally to path .github/workflows/security.yml, event push, head_branch
#     main and head_sha TARGET_SHA (the query parameters are not trusted as
#     the only filter);
#   - the newest run wins: highest run id, then highest run_attempt (a
#     re-run replaces an earlier red attempt);
#   - no such run, a run that is not `completed`, a required job that is
#     missing, or a required job whose latest attempt is not `completed` with
#     conclusion `success` (skipped and neutral included) fails the gate;
#   - jobs are read with an explicit `filter=latest`, i.e. each job's most
#     recent attempt within that run, so "re-run failed jobs" is honoured.
#
# ADR 0129 rejected a live ruleset lookup (it needs `administration: read`),
# so the required names are pinned in release.yml and kept equal to
# security.yml's job names by tests/test_release_workflow_contract.py.
#
# Required env: GITHUB_REPOSITORY, TARGET_SHA, RELEASE_EXPECTED_PUSH_CHECKS.
# Needs `actions: read` (workflow runs and jobs API) and `gh` + `jq` on PATH
# -- both already present on GitHub-hosted runners.
set -euo pipefail

readonly required_workflow_path=".github/workflows/security.yml"
readonly required_branch="main"

# An empty or malformed allowlist would make every later filter vacuous, so
# it is itself a hard failure rather than "nothing required".
if ! expected_count="$(echo "${RELEASE_EXPECTED_PUSH_CHECKS}" | jq -e 'if type == "array" and length > 0 and all(.[]; type == "string" and length > 0) then length else error("invalid") end' 2>/dev/null)"; then
  echo "::error::RELEASE_EXPECTED_PUSH_CHECKS must be a non-empty JSON array of required check names; refusing to evaluate an empty or malformed allowlist." >&2
  exit 1
fi

runs_pages="$(gh api "repos/${GITHUB_REPOSITORY}/actions/runs?head_sha=${TARGET_SHA}&event=push&per_page=100" --paginate --slurp)"
selected_run="$(echo "${runs_pages}" | jq -c \
  --arg sha "${TARGET_SHA}" --arg path "${required_workflow_path}" --arg branch "${required_branch}" '
  [ .[] | .workflow_runs[]? ]
  | map(select(.path == $path and .event == "push" and .head_branch == $branch and .head_sha == $sha))
  | sort_by(.id, (.run_attempt // 1))
  | last // empty
')"
if [ -z "${selected_run}" ]; then
  echo "::error::No push-triggered ${required_workflow_path} run on ${required_branch} exists for commit ${TARGET_SHA} (GitHub may still be creating it). The required checks are not ready; wait and re-dispatch." >&2
  exit 1
fi

run_id="$(echo "${selected_run}" | jq -r '.id')"
run_attempt="$(echo "${selected_run}" | jq -r '.run_attempt // 1')"
run_status="$(echo "${selected_run}" | jq -r '.status // ""')"
run_url="$(echo "${selected_run}" | jq -r '.html_url // ""')"
echo "::notice::Evaluating required checks from ${required_workflow_path} push run ${run_id} attempt ${run_attempt} for commit ${TARGET_SHA}: ${run_url}"
if [ "${run_status}" != "completed" ]; then
  echo "::error::The newest push-triggered ${required_workflow_path} run ${run_id} (attempt ${run_attempt}) for commit ${TARGET_SHA} is '${run_status}', not completed. Wait for it to finish and re-dispatch." >&2
  exit 1
fi

jobs_pages="$(gh api "repos/${GITHUB_REPOSITORY}/actions/runs/${run_id}/jobs?filter=latest&per_page=100" --paginate --slurp)"
jobs="$(echo "${jobs_pages}" | jq '[ .[] | .jobs[]? ]')"

# A required job name that never appeared in the run is "not certified",
# never "nothing to block on".
missing_checks="$(echo "${jobs}" | jq --argjson expected "${RELEASE_EXPECTED_PUSH_CHECKS}" '
  ($expected - ([.[] | .name] | unique))
')"
missing_count="$(echo "${missing_checks}" | jq 'length')"
if [ "${missing_count}" != "0" ]; then
  echo "::error::${missing_count} expected push-triggered check(s) (of ${expected_count} required) have not registered yet in ${required_workflow_path} run ${run_id} for commit ${TARGET_SHA}: $(echo "${missing_checks}" | jq -c .)." >&2
  exit 1
fi

# Registering a required job is not enough. A pending, failed, cancelled,
# skipped or neutral required job cannot certify the immutable publication
# boundary.
required_not_success="$(echo "${jobs}" | jq --argjson expected "${RELEASE_EXPECTED_PUSH_CHECKS}" '
  map(select((.name as $name | ($expected | index($name)) != null)
    and (.status != "completed" or (.conclusion // "") != "success")))
')"
required_not_success_count="$(echo "${required_not_success}" | jq 'length')"
if [ "${required_not_success_count}" != "0" ]; then
  echo "::error::${required_not_success_count} required job(s) in ${required_workflow_path} run ${run_id} for commit ${TARGET_SHA} are not complete with conclusion success: $(echo "${required_not_success}" | jq -c 'map({name, status, conclusion})')" >&2
  exit 1
fi

echo "::notice::All ${expected_count} required checks completed with conclusion success in ${required_workflow_path} push run ${run_id} attempt ${run_attempt} for commit ${TARGET_SHA}."
