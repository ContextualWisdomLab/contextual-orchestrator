# Plan (living — update every iteration, this is what the loop resumes from)

## Ecosystem leverage order

Central/infra repos first (they unblock everyone downstream), then the
products that depend on them, then everything else. Re-derive with
`gh repo list ContextualWisdomLab --json name,viewerPermission` if this list
looks stale — don't trust it blindly past a few weeks.

1. **`.github`** — org-central CI/CD (review bots, merge scheduler, security
   scans). Every other repo inherits from here; a bug here is a bug
   everywhere.
2. **`contextual-orchestrator`** (this repo) — LLM gateway consumed by
   `gyeot` and `scopeweave`; also the intended reasoning engine behind the
   org's OpenCode review pipeline sidecar (see PR #746).
3. **`noema`** — review-bot token broker, required for every repo's branch
   protection to be satisfiable at all.
4. **`keyverse`** — central IdP (OIDC/SCIM). Auth foundation for
   multi-user products (`gyeot`, `life-os`, `psychometrics-commons`, etc).
5. **`governance-risk-compliance`** — owns CSAP/SOC2/ISMS-P control truth;
   relevant to the PII-masking-alternative work mandated org-wide.
6. **`egressweave`, `wardnet`** — shared security infra (SSRF-safe egress,
   WAF/IDS) other services should be consuming rather than reinventing.
7. Product repos depending on 1-6: `gyeot`, `scopeweave`, `naruon`,
   `psychometrics-commons`, `TEPP`, `life-os`, `Orgmetra`, `clearfolio`,
   `disksage`, `fast-mlsirm`, `kaefa`, `aFIPC`, `nonnest2` (psychometrics
   cluster — multilevel/longitudinal modeling mandate applies here),
   `RankWeave`, `ThreadWeave`, `CalendarWeave`, `pg-erd-cloud`,
   `mhtml-etl-gateway`, `newsdom-api`, `inkspan`, `DiagramWeave`, `9drive`,
   `EmbedRelay`, `context-graph-contracts`, `semantic-data-portal`.
8. Everything else (forks, research briefs, one-off tools) — sweep last.

## Status as of 2026-08-18 (this session)

`contextual-orchestrator` open-PR queue (30 open before this session):

- **#747 (new)** — fix: JSON request-body nesting-depth guard. Fixes the
  real Strix finding (JSON-bomb DoS in `_coerce_json`) shared by PRs
  #716/#728/#732 (all showed `strix: FAILURE` for the same root cause, since
  Strix scans PR-head changed-file state and all four touch `server.py`).
  Pushed, open, pipeline should pick it up automatically.
- **#746** — multi-provider model auto-discovery. Had 2 real findings:
  dynamic-urllib-use (now scheme-checked) and 3x incomplete-url-substring-
  sanitization in test doubles (now exact-hostname compares). Fixed and
  pushed directly to its branch, full suite reverified green (410 unit +
  10 fuzz). This PR is the contextual-orchestrator half of wiring this repo
  in as the reasoning engine behind the org's OpenCode review sidecar — high
  leverage, should merge soon after checks clear.
- **#716, #728, #732** — same strix root cause as #747. Do **not** hand-fix
  each one; once #747 merges to `main`, the merge-scheduler's
  `update_branches` behavior should rebase/update these automatically and
  their strix re-scan should pass. If they're still stuck a full sweep cycle
  (~30 min) after #747 merges, investigate `update_branches`/branch-update
  budget settings instead of assuming it'll resolve on its own.
- **#718-#745 (the rest of the "http-honesty" stack)** — all-green,
  `REVIEW_REQUIRED` with 0 reviews at last check. This is expected: OpenCode
  review is the approval source, not a human. Confirm OpenCode is actually
  dispatching/approving these (check `gh pr view <n> --json reviews`) on the
  next iteration; if a PR sits green with zero reviews for a full sweep
  cycle, that's a scheduler/dispatch bug worth root-causing, not something
  to merge around by hand.
- **#742, #741** — drafts (citation/README docs). Leave as drafts unless
  ready to flip to ready-for-review.

## Next iteration checklist

1. Re-check `gh pr list --state open` in `contextual-orchestrator`: did
   #747 and #746 merge? Did #716/#728/#732 clear once #747 landed? Did the
   REVIEW_REQUIRED-but-green PRs pick up an OpenCode approval and merge?
2. If the queue isn't draining on its own within a couple of sweep cycles,
   read `pr-review-merge-scheduler.yml`'s recent runs
   (`gh run list -R ContextualWisdomLab/.github --workflow=pr-review-merge-scheduler.yml`)
   for errors before assuming it's fine.
3. Once `contextual-orchestrator`'s queue is empty or everything left is
   logged as externally blocked, move to `.github` itself: check its own
   open PRs/issues.
4. Start the PII-masking-alternative research (governance-risk-compliance +
   the repos that actually mask PII, e.g. `gyeot`, `naruon`) — this was
   explicitly authorized to start immediately, don't let repo-queue work
   crowd it out indefinitely.
5. Check whether `contextual-orchestrator` needs its own hourly
   review-repair workflow (pattern exists for clearfolio/disksage/
   fast-mlsirm) — add via NVIDIA_NIM_API_KEY-backed OpenCode agent if
   missing, reusing the existing generic workflow rather than inventing a
   new one.
6. Keep this file current: strike completed items, add newly discovered
   product gaps, re-rank leverage order if a dependency changes.
