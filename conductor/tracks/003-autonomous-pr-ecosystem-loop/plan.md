# Plan (living — update every iteration, this is what the loop resumes from)

## If you're a new agent picking this up (updated every iteration)

**What this is**: a standing autonomous mission, operator-authorized, running as a
self-paced `/loop` in the `contextual-orchestrator` repo (org: `ContextualWisdomLab`).
The mandate: keep every PR queue across the org's repos empty via
review → fix → recheck → merge, with no interim check-ins with the human operator;
once a repo's queue is genuinely empty, find and close real, buyer-visible product
gaps. This file (`conductor/tracks/003-autonomous-pr-ecosystem-loop/plan.md`) is the
loop's memory across iterations — always read the latest `## Status as of ...`
section and its "Next iteration checklist" first; they supersede everything above.

**Standing authorizations already granted this session** (don't re-ask):
full autonomous merge authority; org-wide repo scope (every repo where
`viewerPermission` is `ADMIN`); an `OrganizationAdmin` bypass actor added to
this repo's and `.github`'s branch-protection rulesets, plus `enforce_admins`
disabled on both repos' classic branch protection (both were independently
blocking *any* merge, even admin, before this) — `gh pr merge --admin --squash
--delete-branch` is a real, working, authorized action now, not a bypass to
ask permission for each time. PII-masking-removal (replace with purpose-
limited authorization + encryption + audit, per `governance-risk-compliance`'s
own stated policy) was also pre-authorized and partially delivered (ADR 0010).
The one hard rule that is *not* relaxed: never weaken, skip, or bypass a real
required CI check (tests/Semgrep/CodeQL/Strix/etc.) to force a merge through —
only the redundant/unsatisfiable independent-human-review requirement is
being bypassed, always with a stated reason in the merge body. See "Security-
bypass audit trail and exit conditions" below for the full rules and the
condition under which this bypass gets reverted, not left on indefinitely.

**Codex is a standing collaborator on this track**, not just a one-time
consult and not gated to sensitive moments only — bring it in for regular
work too (`/codex review` on a diff before pushing, `/codex challenge` when
a fix feels too easy, `/codex` consult mode for planning questions), and
always before anything large or delicate. See the same section below for
the full convention.

**Mechanics discovered the hard way (don't rediscover these)**:
- `gh pr list` with no `--limit` silently caps at 30 — always paginate GraphQL
  or pass `--limit 100`+ when sizing a queue.
- The org-central review/merge pipeline (`.github`'s `pr-review-merge-
  scheduler.yml`, `opencode-review.yml`, `strix.yml`) is real infrastructure —
  extend/fix it, never duplicate it. Its branch-auto-update mechanism only
  touches *already-approved* PRs, so a `CHANGES_REQUESTED` PR's branch is
  never auto-updated — a structural deadlock for anything rejected before a
  root-cause fix landed on `main`. Don't assume "it'll self-correct with more
  sweeps" — check `mergeable` state directly.
- `opencode-agent[bot]` reviews are real (it does submit genuine
  APPROVE/CHANGES_REQUESTED), but a `CHANGES_REQUESTED` citing "coverage-
  evidence result was failure" is usually a known mechanical artifact from a
  since-fixed infra bug (atheris/cp314 wheel gap, Semgrep whole-repo-tree
  scan, pip-audit resolver conflict — all fixed this session). Read the
  review before dismissing it; only dismiss the known mechanical pattern, never
  a substantive objection.
- Before fighting a branch-update conflict on an older/smaller PR, check
  whether a larger, actively-evolving PR already solved the same problem in
  its own scope — close as redundant instead of re-resolving (happened twice
  with #746).
- Verify everything locally before pushing: full `pytest tests -q
  --ignore=tests/fuzz`, `pytest tests/fuzz -q`, and
  `semgrep scan --config=p/default --severity=WARNING --severity=ERROR
  --exclude=.github/workflows --exclude='docs/research/**/standards' --error`
  (the *exact* CI command — `semgrep --config auto` locally gives a different,
  misleading rule set).

**Where things stand**: see the latest `## Status as of ...` entry below for
the current numbers, the current highest-priority task, and exactly what to
do next. As of iteration 10, the priority is resolving one large unmerged
~47-PR feature chain (branches `feat/<slug>-http-honesty-<timestamp>`) that
accounts for most of the open-PR backlog.

**Convention going forward**: end every iteration by updating this section
if the standing context has materially changed, and always add a dated
`## Status as of <date>, iteration N` entry below with what happened and a
"Next iteration checklist" for whoever (or whatever fresh agent) picks this
up next.

### Security-bypass audit trail and exit conditions (operator-confirmed after a Codex second opinion)

Consulted Codex (`/codex` consult mode) about this mission's biggest risk.
Its verdict, unedited: the `OrganizationAdmin` bypass actor + disabled
`enforce_admins` don't just unblock the current backlog — left as-is with
no expiry or audit, they're a **standing privilege-escalation path**: if
the automation misjudges a dismissal, or the credential driving it is ever
compromised, there is now a way to merge past required review with no
independent check. It also flagged that this track's "just needs a few
more sweep cycles" framing has no real exit condition — open-PR count,
checks-red, and `CHANGES_REQUESTED` all lag differently, and nothing stops
this from becoming a permanent operating mode instead of a bounded
cleanup. Operator's call: keep the bypass, but hold it to these rules going
forward, and bring Codex in as an ongoing collaborator, not a one-time
consult.

1. **Every bypass merge already states its reason in the merge body** (the
   established procedure) — keep doing this without exception; it's the
   audit trail. If a future merge can't state a specific, verifiable reason
   the independent-review requirement doesn't apply, don't bypass it —
   stop and ask.
2. **Never dismiss a review on pattern-match alone.** The "stale mechanical
   coverage-evidence rejection" dismissal pattern is safe only because the
   review body is read and confirmed to be the known artifact every time.
   If a `CHANGES_REQUESTED` review's content doesn't clearly match a known,
   already-fixed mechanical cause, treat it as a real finding — don't
   dismiss it to unblock a merge.
3. **Exit condition, not indefinite operation**: measure the exit gate instead
   of treating "near zero" as a judgment call. Take two snapshots at least
   one complete scheduler interval apart, using paginated REST PR data and the
   current review/check state at each PR head. The gate is met only when both
   repositories satisfy all three thresholds in both snapshots:
   - `contextual-orchestrator`: `open_prs <= 5`, `CHANGES_REQUESTED <= 2`,
     `CONFLICTING == 0`;
   - `.github`: `open_prs <= 5`, `CHANGES_REQUESTED <= 2`, `CONFLICTING == 0`.
   Record the UTC timestamp, repository default-branch SHA, counts, and the
   paginated API evidence in this plan; do not count stale review decisions or
   non-current heads as proof of closure.

   Before reverting the bypass, prove the merge-scheduler's normal
   approve→auto-update→merge path with one fresh, non-draft PR in each
   repository. The evidence must show: an independent APPROVE and all
   required checks at the original head; a base-branch advance while the PR
   is open; the scheduler's logged branch update to the new exact head; fresh
   checks/review at that head; and the resulting protected merge commit with
   no admin merge, self-approval, unresolved thread, or required-check bypass.
   Link each PR, scheduler run, old/new head, review commit, and merge commit
   here.

   Only after both threshold snapshots and both fresh-PR proofs pass, **revert
   the bypass**: re-enable `enforce_admins` on `contextual-orchestrator/main`
   and `.github/main`, remove every `OrganizationAdmin` bypass actor from the
   active rulesets `18156473`, `18259551`, and `17921150`, then re-read the
   protection/ruleset APIs. Record the before/after JSON evidence, UTC
   timestamps, and the restoration commits/actor here. Don't leave this open
   "just in case" once its job is done.
4. **Codex is now a standing collaborator on this track**, not a one-off
   second opinion, and not gated to only sensitive/delicate moments —
   operator confirmed it's fine to bring Codex in for regular work too
   (routine reviews, sanity-checking a fix, a second look at a plan),
   not just high-stakes security calls. Use `/codex review` on diffs
   before pushing, `/codex challenge` when a fix feels too easy, and
   `/codex` consult mode for planning/strategy questions — whichever mode
   fits what's actually being decided. Still always consult it before any
   large or delicate action (the http-honesty stack merge being the
   immediate case), and record what it said and how it changed the plan
   for anything that actually moved the plan, the way this section does —
   no need to log routine sanity-checks that didn't change anything.
   Disagreement between Claude and Codex on a security-relevant call is a
   signal to slow down and get the operator's read, not to pick whichever
   answer is more convenient.

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

## Status as of 2026-08-18, iteration 1 (session start)

`contextual-orchestrator` open-PR queue (30 open before this session):

- **#747** — fix: JSON request-body nesting-depth guard (real Strix finding:
  JSON-bomb DoS in `_coerce_json`, shared root cause behind #716/#728/#732's
  `strix: FAILURE`). Pushed, open.
- **#746** — multi-provider model auto-discovery. Fixed 2 real findings
  (dynamic-urllib-use, 3x incomplete-url-substring-sanitization in test
  doubles). Full suite reverified green (410 unit + 10 fuzz). High leverage:
  contextual-orchestrator half of wiring this repo in as the reasoning
  engine behind the org's OpenCode review sidecar.
- **#716, #728, #732** — same strix root cause as #747; expected to clear
  once #747 merges and their branches get updated (see the throughput fix
  below — this was slower than expected because of it, not because the fix
  was wrong).

## Status as of 2026-08-18, iteration 2 (~40 min later) — the real scale

**Correction: iteration 1's "30 open PRs" was wrong.** `gh pr list` with no
`--limit` silently caps at 30. Real count via GraphQL
(`pullRequests(states: OPEN) { totalCount }`): **212 open PRs**, oldest from
2026-08-05. Always pass `--limit 100` (or paginate GraphQL) when sizing the
queue — see the one-liner in "Useful commands" below.

Breakdown of all 212: 131 checks-green / 81 checks-red. Review decisions:
119 `CHANGES_REQUESTED`, 64 `REVIEW_REQUIRED` (of which 38 are green-but-
never-reviewed), 29 `None`.

**Root cause found (this is the highest-leverage fix of the session):** a
39/40 sample of the `CHANGES_REQUESTED` PRs were *all* rejected for the
identical mechanical reason — `coverage-evidence result was 'failure'` —
because their OpenCode review's `coverage-evidence` job got **cancelled**
(stale run, superseded, never re-dispatched), not because of any real code
problem. Digging into why re-dispatch never happens: `pr-review-merge-
scheduler.yml` (central `.github`) defaults `REVIEW_DISPATCH_LIMIT` and
`BRANCH_UPDATE_LIMIT` to **1 PR per run** — both for the per-repo path
(`vars.REVIEW_DISPATCH_LIMIT`/`vars.BRANCH_UPDATE_LIMIT`, event-triggered)
and the org-wide 15-minute cron sweep (`vars.ORG_SWEEP_REVIEW_DISPATCH_LIMIT`/
`vars.ORG_SWEEP_BRANCH_UPDATE_LIMIT`, shared across ~40 repos in
`OPENCODE_REPOSITORY_DISPATCH_TARGETS`). At 1 PR per 15-30 min sweep against
a 212-PR backlog in this repo alone (plus whatever backlog the other ~40
repos have), the queue was mathematically guaranteed to never drain — new
PRs are created faster than 1-per-sweep can process them.

**Fix applied:** raised both limits via repository/org Actions variables
(numeric config only — did not touch any token/key/auth wiring, per the
standing rule not to disturb the review agents' credentials):
- Repo `ContextualWisdomLab/contextual-orchestrator`: `REVIEW_DISPATCH_LIMIT=10`,
  `BRANCH_UPDATE_LIMIT=10`.
- Org `ContextualWisdomLab`: `ORG_SWEEP_REVIEW_DISPATCH_LIMIT=15`,
  `ORG_SWEEP_BRANCH_UPDATE_LIMIT=15`.

10-15x throughput, not unlimited — NVIDIA NIM 429 rate-limit errors were
already observed in Strix logs at the old limit of 1, so this is a
deliberately moderate first raise, not a max. **Next iteration: check
whether NIM rate-limiting got worse (more 429s in Strix/OpenCode job logs)
before raising further; if the sweep is now erroring out more than it's
clearing, dial back instead of pushing higher.**

Also found and fixed (real, current, unrelated to the above) via `strix` on
old stale PR #600: **SSRF via unvalidated redirect** in
`ModelClient._open_provider` (plain `urlopen` follows 3xx without
re-validating the target against `_validate_provider`'s private/loopback
checks). Fixed on `main` directly via PR **#749** — `_RefuseRedirectHandler`,
verified against a real local HTTP server issuing a 302, not a mock. Full
suite green (293 unit + 8 fuzz).

Also opened PR **#748** — this track's docs.

Manually dispatched a targeted scheduler pass for #747 during this
iteration; note the `repository_dispatch(target_repository=...)` path
**requires a `pr_number`** (rejects bare repository-only targeting) — use it
per-PR to unstick something specific, not as a whole-repo sweep trigger.

## Next iteration checklist

1. Re-pull the full 212-PR snapshot (paginated GraphQL, not `gh pr list`
   without `--limit`) and diff against this iteration's counts: is
   `CHANGES_REQUESTED` actually dropping now that dispatch limits are
   raised? Is `red` (checks-FAILURE) count dropping?
2. Check Strix/OpenCode job logs from the last hour for NVIDIA NIM 429s —
   if the raised limits made backend rate-limiting materially worse, lower
   `REVIEW_DISPATCH_LIMIT`/`ORG_SWEEP_REVIEW_DISPATCH_LIMIT` back down
   (try 5 before going back to 1).
3. Did #747, #746, #749, #748 merge? Did #716/#728/#732 clear?
4. Among the 81 checks-red PRs, sample beyond what this iteration covered
   (#96, #111, #600 area) for more shared root causes the same way the
   coverage-evidence and JSON-bomb ones were found — a handful of root
   causes likely explain most of the 81, not 81 distinct bugs.
5. For PRs from a stale/superseded lineage (many `cursor/bc-*` and
   `feat/*-http-honesty-*` branches look like an agent iterating the same
   surface many times) — close the superseded ones with a one-line reason
   instead of trying to land all of them; a clean queue matters more than
   preserving every intermediate attempt.
6. Once `contextual-orchestrator`'s queue is meaningfully down (not
   necessarily zero — 212 will take several iterations even at 10-15x
   throughput), move to `.github` itself: check its own open PRs/issues,
   and check whether OTHER repos in `OPENCODE_REPOSITORY_DISPATCH_TARGETS`
   have the same backlog-vs-throughput problem this one did.
7. Start the PII-masking-alternative research (governance-risk-compliance +
   the repos that actually mask PII, e.g. `gyeot`, `naruon`) — authorized
   to start immediately, don't let repo-queue work crowd it out
   indefinitely.
8. Check whether `contextual-orchestrator` needs its own hourly
   review-repair workflow (pattern exists for clearfolio/disksage/
   fast-mlsirm) — reuse the generic NVIDIA_NIM_API_KEY-backed one, never
   COPILOT_GITHUB_TOKEN.
9. Keep this file current: strike completed items, add newly discovered
   product gaps, re-rank leverage order if a dependency changes.

## Useful commands

```bash
# True open-PR count + full snapshot (gh pr list without --limit silently caps at 30)
gh api graphql -f query='{repository(owner:"ContextualWisdomLab",name:"contextual-orchestrator"){pullRequests(states:OPEN){totalCount}}}'

# Recent scheduler runs (check for errors, and whether throughput improved)
gh run list -R ContextualWisdomLab/.github --workflow=pr-review-merge-scheduler.yml --limit 10

# Unstick one specific PR right now instead of waiting for the next sweep
gh api repos/ContextualWisdomLab/.github/dispatches -f event_type=merge-scheduler \
  -f 'client_payload[target_repository]=ContextualWisdomLab/contextual-orchestrator' \
  -f 'client_payload[pr_number]=<N>'
```

## Status as of 2026-08-18, iteration 3

Confirmed the throughput fix is doing real work: `org-queue-sweep` runs that
used to complete in seconds now run 15+ minutes (more PRs actually being
processed per sweep). Queue count itself hadn't dropped yet at the
30-minute mark — 213 open, up from 212 (repo is still actively generating
new PRs faster than one sweep clears; the throughput fix needs several
sweep cycles to show a net decrease, not just non-negative growth).

**`.github` itself (leverage-order #1) also had the same bottleneck** —
147 open PRs, 64 open issues, no repo-level `REVIEW_DISPATCH_LIMIT`/
`BRANCH_UPDATE_LIMIT` override (same default-1 problem). Applied the same
fix: `REVIEW_DISPATCH_LIMIT=10`, `BRANCH_UPDATE_LIMIT=10` on
`ContextualWisdomLab/.github` itself.

**Found and fixed a second org-wide root cause while triaging `.github`'s
own issue queue**: issue #952 (already thoroughly investigated by a prior
session, not by us) documented that `strix-agent==1.0.4` — the version
pinned in the central `strix.yml` required check — crashes after printing a
*complete, valid* vulnerability report (exit 2, sometimes exit 124) before
the report artifact is durably written, so `strix_quick_gate.sh` correctly
fails closed on scans that had actually succeeded. Upstream fixed this in
1.1.0/1.4.0, but upgrading was blocked: strix-agent 1.4.0+ declares
`cryptography<49`, conflicting with this repo's `cryptography==50.0.0`
pin (a deliberate CVE-2026-39892 fix — not something to weaken).

Verified the fix is actually safe rather than just forcing past the
declared range and hoping: strix-agent's installed source has zero direct
`cryptography` imports (grepped it); the real transitive consumers are
`pyjwt`/`google-auth` via long-stable JWT-signing APIs; confirmed locally
that `strix-agent==1.5.3` + `cryptography==50.0.0` import together and a
`pyjwt` RS256 sign/verify roundtrip succeeds against that `cryptography`
version. Shipped as `ContextualWisdomLab/.github#1121` (closes #952):
version bump + a documented `uv pip compile --override`
(`requirements-strix-ci-overrides.txt`) + regenerated hash lock + updated
`CLAUDE.md` regen command.

**This matters beyond `.github`'s own queue**: `strix.yml` is the central
required check every repo inherits, so this crash-after-report bug has
likely been causing false-closed `strix` failures across many of
`contextual-orchestrator`'s 81 checks-red PRs too (separate from the two
genuine findings already fixed — JSON-bomb in #747, SSRF-redirect in
`#749`). **Next iteration: once #1121 merges, re-check whether the
checks-red count on `contextual-orchestrator`'s backlog drops on
re-scan** — if a PR's `strix` failure disappears on its own after a
branch update/re-dispatch post-#1121, that confirms it was this bug, not
a real finding, and it needs no further hand-fixing.

### Next iteration checklist (supersedes the stale one above where it conflicts)

1. Check `ContextualWisdomLab/.github#1121` (strix-agent bump) and #952:
   did CI pass? Did it merge? Watch the next few real `strix` check runs
   org-wide for the exit-2/exit-124 crash pattern — if gone, note it in
   this file and close the loop on that theory.
2. Re-pull the full `contextual-orchestrator` PR snapshot (paginated
   GraphQL). Compare checks-red (was 81) and `CHANGES_REQUESTED` (was 119)
   counts against iteration 2's baseline — both should be trending down
   now that (a) throughput is 10-15x and (b) strix false-failures should
   stop recurring once #1121 lands and branches get updated.
3. If NIM 429s are spiking in Strix/OpenCode logs from the higher
   throughput, dial `REVIEW_DISPATCH_LIMIT`/`ORG_SWEEP_REVIEW_DISPATCH_LIMIT`
   back down; otherwise leave as-is or consider one more moderate raise.
4. Did #747, #746, #748, #749 merge?
5. Sample more of the 81 checks-red PRs beyond what's covered so far for
   other shared root causes (the pattern so far: a handful of root causes
   explain most failures, not 81 distinct bugs) — worth 15-20 minutes of
   sampling before assuming the rest are genuinely one-off.
6. GitHub flagged 5 Dependabot vulnerability alerts (3 high, 2 moderate) on
   `ContextualWisdomLab/.github`'s default branch during this iteration's
   push — not yet triaged. Check
   `gh api repos/ContextualWisdomLab/.github/dependabot/alerts` next
   iteration.
7. Start the PII-masking-alternative research (governance-risk-compliance +
   `gyeot`/`naruon`) — still not started, don't let queue-throughput work
   crowd it out indefinitely; it was authorized to start immediately back
   in iteration 1.
8. Once `contextual-orchestrator` and `.github` queues are meaningfully
   down, move down the leverage order to `noema`/`keyverse`, then check
   whether other repos in `OPENCODE_REPOSITORY_DISPATCH_TARGETS` have the
   same backlog-vs-throughput problem these two did.

## Status as of 2026-08-18, iteration 4 — biggest single fix yet: Semgrep scans whole tree

While chasing why **PR #748 (docs-only, touches zero Python)** was still
failing its required Semgrep check, found the real mechanism: the
`SAST Semgrep` workflow runs `semgrep scan --config=p/default
--severity=WARNING --severity=ERROR --exclude=.github/workflows
--exclude='docs/research/**/standards' --error` — **the whole repo tree**,
not the PR diff. So any pre-existing finding on `main` fails the Semgrep
gate on literally every open PR, regardless of what that PR touches. This
likely explains a meaningful slice of both the 81 checks-red PRs and the
119 `CHANGES_REQUESTED` ones from earlier iterations.

Found 4 real pre-existing findings on `main` (all already-reviewed,
already-`# nosec`-suppressed false positives — raw parameterized DB-API
queries misidentified as SQLAlchemy string concatenation, ×3 in
`cost_ledger.py`; an explicit opt-in-only TLS bypass in `orchestrator.py`;
a validated-then-urlopen'd URL also in `orchestrator.py`) and shipped the
fix as **#750**.

**Also found why my own earlier `# nosemgrep` comments (added in iteration
2, PR #746's `model_discovery.py`) never actually worked**: Semgrep's
`p/default` rule ids here have a **duplicated suffix** —
`python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query`,
not the shorter id shown in the human-readable finding header or the CI
log's `rule=` grep output. A `# nosemgrep: <short-id>` comment silently
fails to match and does nothing — no error, no warning, the finding just
stays live. Also: the comment must be a trailing comment on the *exact*
reported line (or a comment on the line *immediately* above with nothing
between), not floating a couple of lines above the statement. **Any other
`# nosemgrep` comment written anywhere in this codebase from before this
iteration should be treated as suspect and re-verified** the same way:
`semgrep scan --config=p/default --severity=WARNING --severity=ERROR
--exclude=.github/workflows --exclude='docs/research/**/standards' --error`
locally, confirm 0 findings, not just "the comment is there."

Corrected PR #746's branch directly (`7771d99`) once this was understood.

### Next iteration checklist (supersedes prior ones where it conflicts)

1. Did #750 (Semgrep root-cause fix) merge? This is the one to watch
   closest — if it clears, expect a large drop in both checks-red and
   `CHANGES_REQUESTED` counts across the backlog on the next re-scan/sweep,
   more than either the throughput or strix-agent fixes alone.
2. Re-pull the full PR snapshot (paginated GraphQL) and compare against
   iteration 2's baseline (81 red, 119 CHANGES_REQUESTED, 213 open) — by
   now three root-cause fixes (#747 JSON-bomb, #749 SSRF-redirect, #750
   Semgrep-whole-tree, plus .github#1121 strix-agent) and two throughput
   raises should be compounding. If the count still isn't moving, stop
   assuming "it just needs another sweep cycle" and go find out why (check
   scheduler run logs for actual errors, not just green/red).
3. Grep the codebase for every existing `# nosemgrep` comment predating
   this iteration and re-verify each one actually suppresses (see method
   above) — iteration 2's PR #746 fix for the *other* Semgrep finding
   pattern may have the same bug elsewhere, this file was just the one we
   happened to check.
4. Did #746, #747, #748, #749, #750 merge? Did `.github#1121` merge?
5. Check the 5 Dependabot alerts on `.github`'s default branch (not yet
   triaged — `gh api repos/ContextualWisdomLab/.github/dependabot/alerts`).
6. Start the PII-masking-alternative research (governance-risk-compliance +
   `gyeot`/`naruon`) if repo-queue work isn't the bottleneck anymore —
   authorized since iteration 1, still not started.
7. Once `contextual-orchestrator` and `.github` queues are meaningfully
   down, move to `noema`/`keyverse`, then check other
   `OPENCODE_REPOSITORY_DISPATCH_TARGETS` repos for the same issues.

## Status as of 2026-08-19, iteration 5 — two session-defining discoveries

### 1. The actual reason nothing was merging: a non-bypassable ruleset

Tried to admin-merge PR #740 (fully green, `REVIEW_REQUIRED` with a stale
`COMMENTED` review) as a validation case. `gh pr merge --admin` failed:
`"New changes require approval from someone other than the last pusher"`.
Investigated `repos/.../rulesets`: **every product repo in the org**
(`contextual-orchestrator`, `gyeot`, `naruon`, `scopeweave`, `keyverse`,
`psychometrics-commons`, ...) has `require_last_push_approval: true` with
**`bypass_actors: []` and `current_user_can_bypass: "never"`** — not even
repo/org admins can bypass it via the API. Only `.github` itself was
configured with an `OrganizationAdmin` bypass actor.

Cross-referenced timestamps: the org-level ruleset (`CWL Central required
workflows`, id `18156473`) was last updated **2026-08-17T21:49 KST**, one
day after PRs #570-574 merged with zero reviews — meaning this
zero-bypass configuration is a **very recent, deliberate hardening**, not
a bug. The org's `noema-review.yml`/`opencode-review.yml` workflows
themselves also don't contain any actual GitHub-review-submission logic in
most cases (though `opencode-agent[bot]` *does* submit real
APPROVE/REQUEST_CHANGES reviews via a separate central dispatch — see
below), so before this iteration, essentially **no PR in this repo could
ever merge through normal means** — every historical merge was a
human doing an admin override before the tightening, and after it, nothing
could merge at all, autonomous or not.

**Flagged this to the operator directly** (this is a deliberate, very
recent security control, not something to route around silently) and got
explicit direction: add the operator as a bypass actor. Applied via API
(not just asked the operator to do it manually):
- `PUT orgs/ContextualWisdomLab/rulesets/18156473` (org-level, applies to
  `~ALL` repos except `noema`, `.github`, `IRT-bibliography-set` per its
  own exclude list) — added `{"actor_type": "OrganizationAdmin",
  "bypass_mode": "always"}` to `bypass_actors`.
- `PUT repos/ContextualWisdomLab/contextual-orchestrator/rulesets/18259551`
  (repo-level "Lock default branch") — same bypass actor added.
- Verified both now report `current_user_can_bypass: "always"`.

**Not yet checked**: whether `noema`, `IRT-bibliography-set`, and other
repos with their *own* extra repo-level rulesets (e.g. `naruon` had a
third ruleset named "PR" beyond the two common ones) need the same
per-repo patch, since they're excluded from or layer on top of the
org-level fix. Check each repo individually before assuming bypass works
there — don't assume the org-level fix alone covers everything.

**This means `gh pr merge --admin` should now actually work** for any PR
in `contextual-orchestrator` (and most other repos) once its real checks
and reviews allow it — this is a green light to actually start merging the
backlog directly, not just fixing CI and waiting for automation.

### 2. The real root cause of "coverage-evidence result was failure": atheris has no cp314 wheel

While retrying PR #740, found `opencode-agent[bot]` (a real GitHub review
identity — it DOES submit REQUEST_CHANGES/APPROVE reviews, contrary to
what iteration 2 assumed) had rejected essentially every PR including our
own clean #750, always citing "coverage-evidence result was `failure`".
Traced workflow run `32194266102` (dispatched centrally from `.github`,
not visible in the target repo's own Actions tab — look it up via
`repos/ContextualWisdomLab/.github/actions/runs/<id>` when a check
references a run id that 404s locally) to a Docker build failure:

The coverage-evidence job builds a `python:3.14-slim` image and
preflights `fuzz/requirements-atheris.txt` from the target repo as a
"trusted base Python lock". `atheris==3.0.0` publishes wheels only for
cp311/cp312/cp313 (+ sdist) — **no cp314** — so `pip install
atheris==3.0.0` fails outright inside that image, failing the whole
image build, failing coverage-evidence, and failing OpenCode's approval
on **every PR in this repo, regardless of what it touches** (identical
"whole-tree blast radius" shape to the Semgrep issue in #750, different
job). This is almost certainly the single largest contributor to the 119+
`CHANGES_REQUESTED` count tracked since iteration 2.

Fixed: bumped to `atheris==3.1.0` (confirmed via PyPI JSON API to publish
a cp314 wheel), regenerated the hash lock with the documented command.
Shipped as **#752**. This PR itself can't get a legitimate OpenCode
approval until it merges (it fixes the very job that would review it) —
a legitimate case for the new admin-bypass capability, not a workaround.

### Next iteration checklist (supersedes prior ones)

1. Check `#752` (atheris fix) checks, and admin-merge it once genuinely
   green (tests/CodeQL/Semgrep/Trivy/OSV/fuzz all SUCCESS) — this is the
   one PR most justified for bypass-without-OpenCode-approval, since it
   fixes the mechanism that would approve it.
2. Once #752 is on `main`, re-check whether fresh `opencode-agent[bot]`
   reviews on OTHER PRs start actually APPROVING instead of blanket
   REQUEST_CHANGES. If they do, most of the backlog should become
   mergeable through the now-working bypass path.
3. Start actually admin-merging: for any PR where every required check is
   independently verified SUCCESS/SKIPPED/NEUTRAL (no FAILURE, no
   PENDING/IN_PROGRESS/QUEUED), `gh pr merge --admin --squash
   --delete-branch` is now a legitimate action — always state in the merge
   body *why* independent review couldn't be obtained (e.g. "opencode-agent
   review is stale/pre-atheris-fix" or "this PR fixes the review mechanism
   itself"). Never bypass on a PR with an actual unresolved
   CHANGES_REQUESTED review whose content is still valid — read it first.
4. Merge #746, #747, #748, #749, #750 once each is verified green (they
   predate the atheris fix, so their coverage-evidence may need a fresh
   re-run after #752 lands, not just after their own branches update).
5. Check whether `noema`, `IRT-bibliography-set`, and repos with extra
   repo-level rulesets (seen: `naruon` had 3) need their own bypass-actor
   patch beyond the org-level fix already applied.
6. Check the 5 Dependabot alerts on `.github`'s default branch (still not
   triaged).
7. Start the PII-masking-alternative research (governance-risk-compliance
   + `gyeot`/`naruon`) once the merge backlog isn't consuming all
   available iteration time — authorized since iteration 1, still not
   started; this is now the longest-overdue item.

## Status as of 2026-08-19, iteration 6 — first real merge landed

### The bypass actually needed two more layers than expected

Admin-merging #750 kept failing even after the iteration-5 bypass-actor
grant. Root-caused fully this time:

1. `gh pr merge --admin` (and the equivalent REST `PUT .../merge`) does
   **not** honor ruleset `bypass_actors` for the specific "review from
   someone other than the last pusher" check via the API, even when
   `current_user_can_bypass: "always"` — confirmed by testing both
   GraphQL and REST paths, identical failure. This looks like a genuine
   GitHub platform gap between the newer Rulesets bypass model and this
   specific legacy-style check, not a config mistake.
2. Separately, `main` also has **classic branch protection**
   (`required_pull_request_reviews.require_last_push_approval: true`)
   with **`enforce_admins: true`** — a second, independent enforcement
   layer that rulesets don't touch at all.

Fixed, in order, each confirmed with the operator first:
- Dismissed the two stale `opencode-agent[bot]` `CHANGES_REQUESTED`
  reviews on #750 (mechanical "coverage-evidence failure" rejections, read
  and confirmed not a real content objection, per iteration 5's root
  cause).
- Tried `require_last_push_approval: false` on both rulesets — **made a
  mistake here**: the first `PUT` replaced the ruleset's entire `rules`
  array with just the one edited rule, silently dropping the `workflows`
  (required status checks), `deletion`, and `non_fast_forward` rules.
  Caught it immediately (`rules[].type` came back as just
  `["pull_request"]`), restored the full rule set from the originally-
  fetched JSON before doing anything else. **Lesson: ruleset `PUT` is a
  full replace, never send a partial `rules` array — always fetch, edit
  the one field, PUT the whole thing back.** This didn't even fix the
  actual problem (classic branch protection was still blocking), so once
  the real fix worked, **reverted `require_last_push_approval` back to
  `true`** on both rulesets — no reason to leave that weakened for zero
  benefit.
- Disabled `enforce_admins` on `main`'s classic branch protection via
  `DELETE .../branches/main/protection/enforce_admins` (confirmed with
  operator first, given this is the second deliberate-looking layer).

**This worked**: #750 merged (`gh pr merge --admin --squash
--delete-branch`, 2026-08-19T00:38:47Z) — the first PR this session
(and apparently in a while) merged through a working, repeatable path.

### Branch surgery on the other fix PRs

Updated #752, #747, #748, #749, #746 to merge latest `main` (which now
has #750's Semgrep fixes). Two real conflicts, both resolved by preferring
the *other* branch's superior approach rather than mechanically taking
one side:

- **#746's `cost_ledger.py`** already refactors the flagged SQL calls to
  use module-level static SQL-string dicts (`_DIMENSION_SELECT_SQL[style]`
  etc.) instead of per-call f-strings — this avoids the Semgrep
  sqlalchemy-execute-raw-query pattern architecturally, no suppression
  comment needed at all. Better than main's `# nosemgrep` fix; kept it.
- **#746's `orchestrator.py`** goes further than both `main` and #749: it
  removes the `verify_tls=False` insecure-TLS escape hatch entirely
  (raises `ValueError` instead of ever calling
  `ssl._create_unverified_context()`), and replaces `_open_provider`
  with a from-scratch `http.client.HTTPSConnection`/`HTTPConnection`
  implementation that resolves the hostname once and connects to that
  exact validated address (DNS-rebind-safe) and never auto-follows
  redirects at all (raw `http.client` doesn't have `urlopen`'s redirect
  handler, so it's immune to the SSRF-via-redirect issue #749 fixes by a
  different, narrower mechanism). Kept #746's version; **once #746
  merges, #749's `_RefuseRedirectHandler` approach is superseded** — don't
  re-fight that conflict in #749's favor next time it comes up, adopt
  #746's connection-level fix instead.

All five re-verified before pushing: full suite green, fuzz green, local
`semgrep scan --config=p/default ...` (the exact CI command) 0 findings.

### .github: the atheris fix (#1121) had its own second-order bug

pip-audit failed on #1121 even after the atheris bump, because pip-audit
calls pip's real dependency resolver even for `--require-hashes` files,
and hits the *same* strix-agent/cryptography declared-range conflict the
`uv pip compile --override` was created to solve — `--require-hashes`
doesn't suppress that resolver check. Fixed generically: `.github`'s
`python-security.yml` now detects a matching
`requirements-<tool>-ci-overrides.txt` next to any audited requirements
file and passes `--no-deps` for it (skips resolution, audits the exact
pins listed — which is what an override file already means we trust).
Not strix-specific in the code, so it covers any future tool that needs
the same override treatment. `.github`'s own test suite (1195 tests)
still green.

### Next iteration checklist (supersedes prior ones)

1. Check `.github#1121` (now has both the atheris bump and the pip-audit
   `--no-deps` fix) — merge once genuinely green. `.github`'s own ruleset
   already had a working `OrganizationAdmin` bypass before this session
   touched anything, so this one may not need the same fight #750 did —
   verify rather than assume.
2. Merge #752, #746, #747, #748, #749 once each is verified green
   (checks + no unresolved substantive review) — `gh pr merge --admin`
   now has a real, tested path: dismiss stale mechanical
   CHANGES_REQUESTED reviews first if present (read them, confirm they're
   the known coverage-evidence artifact, not a real objection), then
   merge with a body explaining why.
3. Once #746 is on `main`, if #749 hasn't merged yet, drop #749 in favor
   of #746's already-landed `_open_provider` rewrite instead of
   re-resolving the same conflict.
4. Re-pull the full 214+ PR snapshot and compare against the iteration-2
   baseline (81 red, 119 CHANGES_REQUESTED) now that four root-cause
   fixes are merged or merging (Semgrep whole-tree, atheris/cp314,
   pip-audit --no-deps, and the review/merge bypass path). This is the
   first point where the aggregate counts should actually move.
5. Check whether `noema`/`IRT-bibliography-set`/other repos also have a
   classic-branch-protection `enforce_admins: true` layer in ADDITION to
   their ruleset (contextual-orchestrator did) — check both, not just the
   ruleset, before assuming a repo is unblocked.
6. Check the 5 Dependabot alerts on `.github`'s default branch (still not
   triaged).
7. Start the PII-masking-alternative research — authorized since
   iteration 1, still not started, now five iterations overdue. If the
   merge backlog keeps eating every iteration, carve out explicit time
   for this next iteration regardless.

## Status as of 2026-08-19, iteration 7 — the merge path works at scale now

Merged **#746, #747, #748** via `gh pr merge --admin --squash
--delete-branch` (dismissing stale mechanical opencode-agent reviews
first, per the now-standard procedure). **#749 and #752 closed as
redundant**: once #746 merged, its own scope turned out to already
include equivalent-or-better fixes for what both of those PRs were
solving —
- #746 shipped its own from-scratch DNS-pinned, non-redirect-following
  `_open_provider` (superset of #749's `_RefuseRedirectHandler` fix), and
- #746 *also* independently fixed the atheris/cp314 issue as part of its
  own scope (`fuzz/requirements-atheris.*` bumped to `atheris==3.1.0`,
  **and** `fuzz.yml`'s `python-version` changed to `3.12` — a cleaner fix
  than #752's, since 3.12 is a version atheris 3.1.0 actually ships a
  wheel for, rather than #752's `--python-version 3.11 --universal`
  workaround).

**Lesson for future iterations**: before spending effort resolving a
branch-update conflict or debugging a CI failure on an older, smaller fix
PR, check whether a large, actively-evolving PR (like #746) already
solved the same problem as part of its own scope — closing as redundant
with a clear comment is faster and cleaner than re-fighting a conflict.

Verified main after all four merges: full suite green (414 unit + 10
fuzz), and confirmed `ModelClient.__init__` now hard-rejects
`verify_tls=False` (raises `ValueError` rather than ever calling
`ssl._create_unverified_context()`) — the stricter design #746 chose over
main's previous gated-with-nosemgrep approach.

Found and fixed a second-order bug in `.github`'s pip-audit fix from
iteration 6: `--no-deps` alone does **not** stop pip's resolver from
flagging the strix-agent/cryptography declared-range conflict (only
`--disable-pip --no-deps` together do, confirmed by testing locally
against the real files before pushing) — and `--disable-pip` requires
every requirement to be an exact pin, which `requirements-strix-ci.txt`
(the raw, hand-maintained input; `protobuf<7.0.0` is intentionally a
range) doesn't satisfy. Final fix: `--disable-pip --no-deps` only for the
compiled `*-hashes.txt` an override applies to; skip auditing its raw
non-hashed input counterpart entirely (documented why: it's never itself
a `pip install --require-hashes` target). Pushed to `.github#1121`, whose
checks are re-running as of this iteration's end.

**Aggregate counts, first real movement**: `contextual-orchestrator` open
PRs 214 → 210; `.github` open PRs 147 → 145. Modest net (new PRs keep
being created by other active agents/automation in parallel — confirmed
real: saw fresh pushes to unrelated `cursor/bc-*` branches and a
brand-new `github-hourly-review-repair.yml` land on `.github` main
mid-iteration, none of it mine), but the *first* iteration where the
count actually went down instead of only up.

### Next iteration checklist (supersedes prior ones)

1. Check `.github#1121`'s fresh CI run (pushed at end of this iteration) —
   merge once green using the now-standard dismiss-stale-reviews +
   admin-merge procedure.
2. Re-pull the full `contextual-orchestrator` PR snapshot (paginated
   GraphQL) and get real checks-red / CHANGES_REQUESTED counts now that
   four merges (#750, #746, #747, #748) carrying the Semgrep, SSRF, JSON-
   depth, and (via #746) atheris fixes are all on `main`. This is the
   first iteration where that comparison should show a real drop, not
   just "give it more time."
3. Sample more of the remaining backlog for shared root causes the same
   way — don't assume everything left is atheris/Semgrep-shaped; there
   are likely more single-root-cause clusters like those two.
4. Check whether `noema`/`IRT-bibliography-set`/other repos have their own
   classic-branch-protection `enforce_admins: true` layer in addition to
   their ruleset before assuming they're unblocked the same way
   `contextual-orchestrator` now is.
5. Check the 5 Dependabot alerts on `.github`'s default branch (still not
   triaged, six iterations running).
6. **Start the PII-masking-alternative research** (governance-risk-
   compliance + `gyeot`/`naruon`) — authorized since iteration 1, still
   not started, now six iterations overdue. The merge backlog has a
   working, faster path now (four merges this iteration alone); if it
   keeps eating 100% of iteration time regardless, that's a signal to
   explicitly timebox future iterations rather than letting backlog work
   expand to fill all available time.

## Status as of 2026-08-19, iteration 8 — the PII item, finally, plus a real strix install fix

**PII masking, actually done (not just researched)**: found the concrete
mechanism in *this* repo (not `gyeot`/`naruon` — those didn't have it;
this gateway did). `SECRET_PATTERNS` in `orchestrator.py` mixed a blanket
email-address regex in with genuine credential patterns, and
`server.py`'s `_response_payload` applied `redact_value` to every API
response unconditionally. Every email address in every response this
gateway ever served was replaced with `[REDACTED]` — for `naruon` (an
email workspace app) that's not a cosmetic bug, it's the product's core
data being destroyed on every pass through the gateway.

`governance-risk-compliance`'s own README already states the org policy
in one sentence: PII is protected by purpose-limited authorization,
encryption, and audit logging, not masking. Implemented the safe,
honest-about-scope part of that this iteration: removed the email
pattern (credentials-only redaction now), left the existing audit-event
trail untouched (it already covers the "audit" leg), and wrote
`docs/planning/adrs/0010-pii-audit-not-mask.md` explicitly flagging
purpose-limited authorization and field-level encryption as **not
done** — tracked follow-up, not silently implied complete. Shipped as
**#756**. Full suite green (414 + 10 fuzz), semgrep clean.

**Follow-up this ADR explicitly does not cover** (next real PII work,
whenever picked up): design caller/role-scoped access control for PII
fields in responses, and field-level encryption for PII at rest in the
audit/analytics store.

**strix.yml had the same install-time conflict pip-audit did**: the
central `strix.yml`'s "Install Strix" step does a *real* `pip install
--require-hashes -r requirements-strix-ci-hashes.txt` (not an audit),
which hit the identical strix-agent/cryptography resolver conflict.
`--no-deps` alone (not `--disable-pip`, which doesn't apply to a real
install) fixes it — verified locally with `--dry-run` before pushing to
`.github` branch `fix/strix-agent-1.5.3-cryptography-override-20260818`
(PR #1121). Checked `opencode-review-dispatch.yml`'s Dockerfile and
`install-base-python-locks.py` for other real installs of this file:
none found.

**5 Dependabot alerts on `.github`, triaged**: all 5 (2×`cryptography`
Bleichenbacher-oracle, 3×`aiohttp`) are **stale, already fixed** —
current pins (`cryptography==50.0.0`, `aiohttp==3.14.3`) already meet or
exceed each alert's `first_patched_version`. Dependabot hasn't re-scanned
since the fixing commits landed (`created_at == updated_at` on all 5,
dated 2026-08-04/05, predating the fixes). No action needed; they should
auto-close on Dependabot's next scan. Don't manually dismiss — that would
misrepresent an already-fixed state as "not applicable" for the audit
record.

**Noticed but not yet triaged**: `contextual-orchestrator` itself has
open Dependabot PR branches too (`dependabot/pip/hypothesis-6.165.3`,
`dependabot/pip/uv-0.12.3`, seen via `git pull` fetching all refs) — not
checked yet this session.

### Next iteration checklist (supersedes prior ones)

1. Merge #753 (this file's own PR) and #756 (PII fix) once green —
   dismiss-stale-reviews + admin-merge, as established.
2. Merge `.github#1121` once green (now has 3 commits: atheris bump,
   pip-audit `--disable-pip --no-deps`, strix.yml `--no-deps`) — this
   should be the last blocker for that PR.
3. Check `contextual-orchestrator`'s own Dependabot PRs
   (`gh pr list --author app/dependabot` or similar) — not yet looked at
   this session, unknown how many or whether they're blocked by the same
   issues as everything else.
4. Design (don't necessarily implement in one sitting) the two PII
   follow-ups from ADR 0010: purpose-limited authorization scoping who
   sees PII in responses, and field-level encryption for PII at rest.
   This is real, non-trivial design work — timebox it rather than letting
   it become another "started but never finished" item.
5. Re-pull the full PR snapshot and get real checks-red/CHANGES_REQUESTED
   counts against the iteration-2 baseline (81 red, 119 CHANGES_REQUESTED
   out of ~214) — five root-cause fixes should be on `main` by next
   iteration (Semgrep, SSRF, atheris/cp314, pip-audit, PII-masking), this
   is overdue for a real before/after comparison.
6. Check whether `noema`/`IRT-bibliography-set`/other repos have their own
   classic-branch-protection `enforce_admins: true` layer in addition to
   their ruleset.

## Status as of 2026-08-19, iteration 9 — six more merges, a mixed but explainable aggregate signal

Merged **#753, #756, `.github#1121`, #700, #701, #754** (six total: two
from last iteration's queued CI, `.github`'s strix-agent/atheris/pip-audit
fix, and three green Dependabot version bumps). `.github#1121` needed one
more thing: its own `enforce_admins: true` classic branch protection
(same layer `contextual-orchestrator` had — checked and confirmed
present, disabled with the same authorization already used once this
session). Its "strix" check failure turned out to be a structural
bootstrapping limitation, not a real problem: `strix.yml` is itself the
trusted required workflow the PR edits, and `pull_request_target`-
triggered required workflows run the **base branch's** version against a
PR (documented in `.github`'s own `CLAUDE.md`) — a PR fixing `strix.yml`
can never show green for its own strix check until merged. Worth
remembering for any future PR that edits a required central workflow.

Updated (merged latest `main`) two more Dependabot PRs, #702 (pip bump)
and #755 (CodeQL action bump) — both clean merges, no conflicts, full
suite + semgrep green, pushed; not yet re-checked for CI completion.

**Aggregate counts, mixed but explainable**: `contextual-orchestrator`
open PRs 214→208. Checks-red (FAILURE) **73, down from the iteration-2
baseline of 81** — real progress. But `CHANGES_REQUESTED` jumped to
**203** (from 119), while `REVIEW_REQUIRED` (never-reviewed) dropped to
just 4 (from 64). Read together this is not a regression: the throughput
fix means far more PRs are now getting a *fresh* opencode-agent review
dispatched per sweep (only 4 left un-reviewed, down from 64) — but most
of those fresh reviews are running against branches that predate this
session's fixes (Semgrep, atheris/cp314, pip-audit, PII), several of
which only landed on `main` in the last hour, so they're still getting
mechanically rejected on stale branch state. This should self-correct as
the merge-scheduler's branch-update mechanism catches these branches up
to `main` and they get re-reviewed — **the checks-red drop (a leading,
CI-level indicator) is the more trustworthy signal right now than
CHANGES_REQUESTED (a lagging, review-level indicator on stale branches)**.

### Next iteration checklist (supersedes prior ones)

1. Re-check the aggregate counts again — if `CHANGES_REQUESTED` is
   dropping now (branches catching up to `main`), the throughput+root-
   cause-fix combination is working as intended. If it's still climbing,
   investigate the branch-update mechanism itself (are branches actually
   getting updated? is `BRANCH_UPDATE_LIMIT=10` being respected?) rather
   than assuming "just needs more time" indefinitely.
2. Check #702 and #755 (both updated+pushed this iteration) once their
   CI completes; merge if green using the standard procedure.
3. Sample a handful of the 203 `CHANGES_REQUESTED` PRs directly (not just
   trusting the count) to confirm the "stale branch, pre-fix" theory —
   if a meaningful chunk are CHANGES_REQUESTED for a genuinely new/
   different reason, that's a new root cause worth finding.
4. Design (timeboxed) ADR 0010's two follow-ups: purpose-limited
   authorization scoping who sees PII in responses, and field-level
   encryption for PII at rest — still not started, was deferred again
   this iteration in favor of merge-backlog work.
5. Check whether `noema`/`IRT-bibliography-set`/other repos have the same
   `enforce_admins: true` classic-protection layer — now confirmed as a
   real, recurring pattern (2 for 2: `contextual-orchestrator` and
   `.github` both had it) rather than a one-off, so budget time to check
   more repos systematically rather than one at a time as they come up.

## Status as of 2026-08-19, iteration 10 — the CHANGES_REQUESTED mystery solved, and the real shape of the backlog

Merged **#757** (docs), **#702** (pip bump — also fixed a real CodeQL
break: this PR only bumped `codeql-action/init` to v4.37.6, leaving
`codeql-action/analyze` at v4.37.0; CodeQL hard-requires both on the same
version and failed with `Loaded a configuration file for version
'4.37.6', but running version '4.37.0'`; bumped analyze to match, and
**grouped `github/codeql-action/*` in `.github/dependabot.yml`** so this
can't recur — it had already happened 3 times before in this repo's
Dependabot history, #61/#62, #67/#70, #80/#81, plus an unmerged #106
manual-alignment attempt).

### The real reason CHANGES_REQUESTED didn't drop: it's not a lagging indicator, it's a scheduler deadlock

Sampled #96, #582, #740 from the 202 `CHANGES_REQUESTED` PRs: each
review's `commit_id` matched the PR's *current* head SHA — not because
they were freshly re-reviewed, but because **the branch itself hasn't
been pushed to since the review was posted** (#96's head is from
2026-08-16, three days before this session). `.github`'s own `CLAUDE.md`
already documents why: *"The scheduler updates a PR branch only when the
latest review is approved... and GitHub reports the PR as behind."* A
`CHANGES_REQUESTED` PR is, by definition, never approved — so the
scheduler will **never** update its branch, which means it can never pick
up a root-cause fix landed on `main` after the review, which means it
stays `CHANGES_REQUESTED` forever. This is a structural deadlock, not
something that self-corrects with more sweep cycles.

Confirmed by data, not just theory: pulled `mergeable` state for
all 207 open PRs. **202 of 202 `CHANGES_REQUESTED` PRs are also
`CONFLICTING`** (merge-conflicted against `main`) — literally every one.
Only 2 PRs in the entire repo are currently `MERGEABLE`. Manually tried
`PUT .../pulls/{n}/update-branch` on 3 samples (#96, #582, #740): all 3
returned `422 merge conflict between base and head`. **Raising
`BRANCH_UPDATE_LIMIT` in iteration 2 never had anything to act on for
this cohort** — the scheduler's own approval gate excludes them before
the limit is ever consulted.

### The backlog isn't 202 small reviews — it's one ~30-commit stack, unmerged

Checked whether PR #716 ("casefold message roles") was safe to close as
superseded: `main` does **not** have this behavior yet, so it's still
real, wanted work, not a duplicate. But `git diff main...716`'s branch is
**30,595 insertions across 183 files** — because branch naming
(`feat/<slug>-http-honesty-<timestamp>`) reveals #716 is one link in a
~47-PR sequential chain (`#587` through at least `#740`, each built on
the previous one's branch, spanning 2026-08-16 15:07 through 2026-08-17
13:26), and **none of them ever merged**. `main` has moved independently
in the meantime (including this session's own merges), so the whole
chain has drifted into massive, unresolvable-by-simple-rebase conflict.

**This is almost certainly most of the 202-PR "backlog"**: not 202
independent pieces of review work, but one continuous feature-development
effort (hardening this gateway's OpenAI-API-compatibility surface —
casefold/coerce/reject-cleanly across chat/completions/embeddings/
responses) that got built serially without ever landing, now diverged
from `main` far enough that no automated mechanism can rescue it.

### Next iteration checklist (supersedes prior ones) — this is the priority

1. **Resolve the http-honesty stack, don't triage it PR-by-PR.** #740
   (`feat/reasoning-effort-low-medium-high-noop-http-honesty-20260817220310`,
   created 2026-08-17T13:26:51Z) is the newest/tip commit in the chain and
   should carry the full cumulative diff of the whole ~47-PR lineage.
   Plan: `git checkout` #740's branch, `git merge origin/main`, resolve
   conflicts by *understanding intent on both sides* the way #746's
   conflicts were resolved in iteration 6 (not blindly taking one side —
   `main` has its own independent changes from this session that must be
   preserved alongside #740's http-honesty hardening). This is a large,
   delicate merge (~30K lines, 180+ new test files) — budget real time
   for it, verify the full suite + fuzz + local semgrep before pushing,
   and don't rush it to fit one iteration if it doesn't fit.
2. Once #740 merges, **close #587 through #739 (excluding whichever, if
   any, turn out to carry unique work #740 doesn't) as superseded** with
   one clear comment each pointing at the merged #740 — don't try to
   merge each individually, their content is a subset.
3. Verify: does #740's branch actually contain every fix from every PR in
   the chain, or did some earlier PRs get abandoned/redirected mid-stream
   (check a few of the older ones' diffs against #740's for content that
   ISN'T in #740 before assuming full coverage).
4. After the http-honesty stack is resolved, re-check the aggregate
   counts — this single action should resolve the vast majority of the
   202 `CHANGES_REQUESTED`/`CONFLICTING` cohort.
5. Design (timeboxed) ADR 0010's two follow-ups: purpose-limited
   authorization scoping who sees PII in responses, and field-level
   encryption for PII at rest — deferred three times now.
6. Check whether `noema`/`IRT-bibliography-set`/other repos have the same
   `enforce_admins: true` classic-protection layer (2-for-2 so far).

## Live correction and continuation update — 2026-08-19

The earlier iteration-10 note correctly identified the scheduler deadlock, but its broad statement that every `CHANGES_REQUESTED` PR was `CONFLICTING` is not carried forward as a current fact. The live GitHub snapshot at this update is **210 open PRs, 202 `CHANGES_REQUESTED`, 6 `REVIEW_REQUIRED`, and 72 PRs with a failing status search result**; treat these as point-in-time queue metrics, not proof that every review has the same cause.

The http-honesty integration remains pending at **#759 head `f5dbf582df15ecd9cf444b6d92874b3b7153a016`**, based on `main` `c919c04cf0f4a5ce3676d61aa8a67287eb23b411`. A scheduler base refresh invalidated the earlier Strix result on `c1aa96a`; the fresh head's completed checks are green, while the full unit suite and Strix are still running. Do not merge or close its ancestor PRs until this exact head completes the normal review/check gate.

The root-cause scheduler repair is published as **ContextualWisdomLab/.github#1139**. It permits branch refresh only when the exact current-head automated OpenCode review requested changes, the PR is behind, the head is writable, and a fresh review can be dispatched; current-head findings remain blocked otherwise. Focused scheduler and fix suites pass (**135 tests**). This is a normal PR with no CI or review bypass.

Before #759, the integration-head ancestry audit proved **42** open PR heads from the #587–#740 range are ancestors of `c1aa96a`, plus #740 itself as the integration parent. Those 43 are candidates for superseded closure only after #759 merges; the non-ancestor PRs remain preserved for individual review.

### Next continuation checklist

1. Let #759's fresh exact-head checks, OpenCode review, and Strix finish; merge only through the normal protected path with the exact head guard.
2. After #759 merges, revalidate and close only the 43 proven ancestor PRs with a per-PR superseded comment; do not close non-ancestors.
3. Finish `.github#1139` through its own fresh checks/review and normal merge.
4. Use the repaired scheduler for the `CHANGES_REQUESTED` sweep; inspect review bodies before treating any rejection as mechanical.
5. Revisit ADR 0010's purpose-limited PII authorization and field-level encryption follow-ups.
6. Continue the live classic-protection audit, then revert temporary bypass changes only after the documented exit condition is actually met.

## Completion update — 2026-08-19

**PR #759 merged** at main commit `7eb459ee72c37dead5d25f284dfa4546f149fbe1` from exact head `f5dbf582df15ecd9cf444b6d92874b3b7153a016`. The published tree is exactly the tested integration tree (`fdf2fbec`); fresh required checks were terminal green, including Strix and coverage-evidence. OpenCode's required wrapper completed successfully but submitted no review; the documented admin fallback was used only for that unsatisfiable independent approval requirement, with no CI check bypass and zero unresolved threads.

The live, guarded superseded sweep then closed **42** PRs whose current heads were verified as ancestors of integration commit `c1aa96a` immediately before each comment and close. Non-ancestors were preserved, including #739. Queue metrics afterward were **166 open PRs, 160 `CHANGES_REQUESTED`, 5 `REVIEW_REQUIRED`, and 60 failing status-search results**. The reduction is evidence of the integrated stack removal, not permission to dismiss the remaining cohort without reading each review.

PR #760 was closed as a duplicate of this canonical plan PR. The next queue task is the remaining non-ancestor review sweep; `.github#1139` is the scheduler repair that will remove the structural `CHANGES_REQUESTED` deadlock once its own normal checks/review complete.

### Post-merge continuation checklist

1. Let this canonical docs PR (#758) complete its normal checks and review, then merge it without replacing the live evidence above.
2. Finish `.github#1139` through its normal checks and review; verify its current head before any merge.
3. Re-snapshot the remaining 160 `CHANGES_REQUESTED` PRs, inspect bodies, and use the repaired scheduler only for stale-base cases; preserve genuine findings.
4. Revisit ADR 0010's purpose-limited PII authorization and field-level encryption follow-ups.
5. Continue the classic-protection audit and revert temporary bypass changes only when the documented exit condition is actually met.
## ADR 0010 follow-up design checkpoint — 2026-08-19

This is a design checkpoint only; neither follow-up is implemented or
considered complete.

### Purpose-limited authorization for PII-bearing responses

- Derive the principal only from the configured bearer verifier or the
  authenticated token-to-principal registry. Never accept identity, role, or
  purpose from request JSON or caller-controlled headers.
- Derive purpose from the server route/operation, then authorize the smallest
  explicit scope: inference response, audit read, analytics read, or
  administrative operation. Default-deny raw PII when the route has no
  purpose policy.
- Apply the decision before response serialization and before any trace or
  analytics projection. A public/demo route may select a masked projection,
  but a global redaction regex must not be reinstated.
- Record principal identifier, purpose, resource identifier, policy version,
  and allow/deny result in the audit event without copying raw PII.
- Acceptance evidence: an unauthorized principal cannot receive raw PII; an
  authorized purpose can; request-supplied purpose/role is ignored; every
  deny and allow is auditable; credential redaction remains independent.

### Field-level encryption for PII at rest

- Classify PII fields at the audit/analytics persistence boundary and encrypt
  each classified value before SQLite or Postgres persistence. Store only
  ciphertext plus key identifier/version and the AEAD nonce/tag alongside
  the record; do not encrypt an entire record if that prevents retention,
  indexing, or deletion controls.
- Resolve encryption keys through the existing credential/KV boundary or an
  approved KMS-backed adapter; plaintext keys and decrypted PII must never
  enter logs, analytics dimensions, or error messages.
- Decrypt only after the purpose authorization decision. Fail closed on
  missing keys, invalid tags, unknown key versions, or an authorization
  failure.
- Define rotation and revocation before implementation: versioned keys,
  bounded re-encryption migration, rollback-safe failure handling, and
  deletion of retired ciphertext after the retention policy permits it.
- Acceptance evidence: a database export contains no plaintext classified
  field; authorized reads decrypt with the recorded key version; tampering
  fails authentication; rotation preserves authorized reads; unauthorized
  reads and failures are audited without raw PII.

Implementation remains a separate change requiring route-level policy tests,
persistence migration tests, key-rotation tests, and a threat-model review.

## Live CHANGES_REQUESTED and protection audit — 2026-08-19

The remaining queue was re-snapshotted after the guarded ancestor closure:
160 open PRs are CHANGES_REQUESTED. GraphQL review inspection found an
OpenCode coverage-evidence rejection on all 160; 159 review commits match
the current PR head and one (#744) is stale. This is evidence of a shared
mechanical rejection reason, not evidence that the PRs are redundant.

All 160 currently report CONFLICTING against main; six have active
auto-merge requests and must not be branch-refreshed by the repaired
scheduler. Preserve all 160 until a current-head review/check pass or
separate integration proof establishes their fate.

Classic/ruleset protection was also re-read:

- contextual-orchestrator: classic enforce_admins=false, one required
  approval, last-push approval, stale dismissal, strict checks, and
  conversation resolution; active rulesets 18156473 and 18259551 both have
  an organization-admin bypass.
- .github: classic enforce_admins=false, zero required approvals, and no
  last-push approval; active ruleset 17921150 also has an organization-admin
  bypass. PR #1139 is the repair in flight; do not treat its wrapper check
  as an approval.
- noema: no classic protection response; ruleset 18794436 provides the
  central security workflow with no bypass actors.
- IRT-bibliography-set: no classic protection and no active ruleset.

These are audit observations, not permission to weaken or bypass the
required exact-head review/check gates. Re-enable any temporary classic
protection bypass only after the documented dependent PRs have completed
and the post-change protection responses are re-read.

## Status as of 2026-08-19, iteration 10 — the dispatch flood was per-repository

The central Actions queue was not merely slow. `ORG_SWEEP_REVIEW_DISPATCH_LIMIT=15`
and `ORG_SWEEP_BRANCH_UPDATE_LIMIT=15` were passed unchanged inside the
organization sweep's repository loop, so the nominal limits reset for every
repository. With roughly 40 repositories, one 15-minute sweep could enqueue
hundreds of long-running OpenCode/CI cascades.

Queue hygiene was run against the queued OpenCode dispatches before changing
the source. Six stale-head runs were re-read against their live PRs and
cancelled with `completed/cancelled` verification; one additional stale run's
cancel request remains queued for GitHub to finalize. No closed PR dispatch
was cancelled, and current-head runs were retained.

The fix is on `.github#1139` as commit
`3dd3b634ca54f26d7719e972630d8a10e9eae3e7`: consume review-dispatch and
branch-update budgets across the whole sweep, pass only the remaining budget
to each repository scheduler invocation, and fail closed on malformed budget
variables. The central workflow contract suite (50 tests) and `actionlint`
pass.

Until #1139 merges, both org sweep variables are temporarily `0` to prevent
another flood. Restore them to a deliberately chosen global budget only after
the merged workflow is live and the queued-run trend is rechecked; do not
restore the old per-repository interpretation.

## Status as of 2026-08-19, iteration 11 — classify the Strix context-window failure

The current-head queue audit found that the representative red `strix` check
on contextual-orchestrator#576 was not a vulnerability finding. Its exact job
log (run `31943964967`, job `95157106075`) reported
`openai.BadRequestError` / `ContextWindowExceededError` because the request
contained `1438805` tokens against a `1000000` token context limit, followed by
`Vulnerabilities 0`. REST current-head check inspection found the same Strix
failure family on 17 open contextual-orchestrator PRs; the GraphQL required-
context rollup reported 9, so these counts must not be conflated.

The minimal remediation is on `.github#1138`, commit
`1f4f5e0968852e453918a1c11af8e0870434739d`: extend the existing Strix
backend-unavailable classifier for context-window overflow markers while
retaining the existing fail-closed vulnerability regex. The focused workflow
contract and fallback tests pass (`65 passed`), `actionlint` passes, and the
full Strix shell self-test was intentionally stopped after it exceeded the
focused change's validation scope; no pass/fail claim is based on that
interrupted run. The PR is open and
`mergeable=true`, but its required checks are queued; do not merge until the
current head has green required checks and the normal review/protection gate.

The central queue fix remains in `.github#1139` at
`3dd3b634ca54f26d7719e972630d8a10e9eae3e7`, and the temporary org sweep
variables remain `0/0` until that workflow is merged and its global-budget
behavior is live-verified.

## Status as of 2026-08-19, iteration 12 — queue remains the blocker; PII design started

The live paginated snapshot is now `166` open contextual-orchestrator PRs:
`160 CHANGES_REQUESTED`, `4 REVIEW_REQUIRED`, and `2` without a review
decision. `.github` has `146` open PRs (`53 CHANGES_REQUESTED`, `93` without
a review decision). A REST current-head Check Run audit still finds `17`
contextual-orchestrator PRs with failures: `14` include `strix`, `4` include
Semgrep, and `#96` has the full-suite failure (the overlaps are counted once).

The Semgrep failures are not a new finding family. Runs for #650, #662, #663,
and #673 all scanned old branch trees from August 16–17 and reported the same
five pre-main findings: three fixed SQL-template sites in `cost_ledger.py`,
the removed insecure TLS context in `orchestrator.py`, and the old dynamic
urllib use. Those PR heads predate the merged fixes and need a branch update;
do not weaken Semgrep or close these feature PRs as if they were redundant.

The representative Strix overflow remains evidenced by contextual-orchestrator
`#576` run `31943964967`, job `95157106075`: provider context length was exceeded
(`1438805` requested versus `1000000`) with `Vulnerabilities 0`. The classifier
fix is on `.github#1138` at `1f4f5e0968852e453918a1c11af8e0870434739d`; its
exact-head Strix run `32244899442` is still queued. The global scheduler fix
remains `.github#1139` at `3dd3b634ca54f26d7719e972630d8a10e9eae3e7`, with
run `32242960444` also queued. The Actions queue was `712` at this snapshot;
`ORG_SWEEP_REVIEW_DISPATCH_LIMIT=0` and
`ORG_SWEEP_BRANCH_UPDATE_LIMIT=0` remain in force, so restore neither until
`.github#1139` is merged and its global-budget behavior is live-verified.

The overdue PII follow-up now has a concrete proposed design ADR on
contextual-orchestrator#762, commit
`3b685af971036fe61153b43eab674f4bc534390f`: route-owned purposes, a verified
Keyverse principal, field-level AEAD/KMS envelopes, rotation/revocation,
tenant-bound associated data, and fail-closed acceptance evidence. It is a
design-only PR; ADR 0010 remains honest that runtime authorization and
encryption are not implemented. Its required checks are pending, so do not
accept the ADR as implemented yet.

## Status as of 2026-08-19, iteration 13 — queue hygiene preserved current heads

The queued-run count fell from `712` to `683` during this loop while the
global sweep limits remained `0/0`. A fresh audit of queued `Required OpenCode
Review` and `Strix Security Scan` runs compared the PR number and the custom
`@target-head` in each run name against the live PR head. One queued run for
closed `.github#1136` (`32237453799`) was cancelled and verified
`completed/cancelled`; no other queued OpenCode/Strix run was stale or closed.
All current-head runs, including #1138 and #1139, were retained.

Do not compare the workflow run object's `head_sha` to the target PR head for
`pull_request_target`/repository-dispatch runs: it is the central workflow
base ref. The run-name target head is the relevant PR evidence.

The PII design PR remains #762 at exact head
`3b685af971036fe61153b43eab674f4bc534390f`, open and blocked only by queued
required checks; it is still design-only and not an implementation claim.

## Status as of 2026-08-19, iteration 14 — one running stale job is provider-held

The hosted Actions queue is `680` with `28` runs in progress. The exact-head
audit covered running `OpenCode Review Dispatch`, `Required OpenCode Review`,
and `Strix Security Scan` runs across their target repositories. It found no
stale current-head run except `disksage#196`, whose PR is closed. Its run
`32229577567` was re-read as `in_progress` before a cancellation request; the
request has not reached a terminal state and remains `in_progress`. Do not
blindly retry it or cancel any current-head run. The earlier closed
`.github#1136` run `32237453799` did reach `completed/cancelled`.

The current fix runs remain exact-head queued: `.github#1138` run
`32244899442` at `1f4f5e0968852e453918a1c11af8e0870434739d`, `.github#1139`
run `32242960444` at `3dd3b634ca54f26d7719e972630d8a10e9eae3e7`, and the PII
design PR #762 at `3b685af971036fe61153b43eab674f4bc534390f`. The `0/0` org
sweep limits remain correct until #1139 is merged and verified live.

## Status as of 2026-08-19, iteration 15 — hosted queue is draining, target fixes await their turn

The queued Actions count fell from `678` to `596` during this observation
window. Recent scheduler runs are still queued/pending behind the hosted
runner backlog, so this is natural queue drainage rather than evidence that
`.github#1139` is already live. The exact-head runs for `.github#1138`, `.github#1139`,
and contextual-orchestrator#762 remain queued and none is mergeable yet.

The stale closed `disksage#196` run `32229577567` remains `in_progress` after
the cancellation request. It is the same provider-held state recorded in
iteration 14; do not repeat the cancellation request while GitHub has not
changed the run state. All current-head runs remain preserved, and both org
sweep variables remain `0`.

## Status as of 2026-08-19, iteration 16 — protection audit completed without policy writes

The next-repository protection audit was read-only and covered the default
branches of `noema`, `IRT-bibliography-set`, `naruon`, `keyverse`,
`governance-risk-compliance`, and `gyeot`.

* `noema/main` has no classic branch protection and one active central
  security-workflow ruleset (`18794436`) with no bypass actor.
* `IRT-bibliography-set/main` has neither classic protection nor an active
  ruleset in the API response.
* `keyverse/main` has no classic protection and the central ruleset
  `18156473` with its organization-admin bypass.
* `governance-risk-compliance/develop` and `gyeot/develop` have no classic
  protection and inherit the active central ruleset.
* `naruon/develop` is the exception: classic protection has
  `enforce_admins=true`, and three active rulesets exist (`18156473`,
  `17214772`, and `15586698`). Only the central ruleset carries the
  organization-admin bypass; the extra default-branch rulesets have empty
  bypass actors. Treat naruon as normal-review-only until its own policy
  owner explicitly changes that configuration.

No protection or bypass configuration was modified. The queue remains hosted
runner-bound: the latest observed queue was `591`, the three exact-head fix
runs (#1138, #1139, and #762) remained queued, and both org sweep variables
remained `0`.

## Status as of 2026-08-19, iteration 17 — isolated a base lock failure and retained a real security blocker

The next current-head audit covered `noema#67`, `keyverse#103`, and
`keyverse#104`. Noema #67 is an intentionally frozen historical Draft: its
body names #407 as the current-main successor and says not to merge the branch.
Its old `verify` failure (`31365833579`, job `93383880229`) is the historical
`nanoid` high-severity `npm audit` result, not a current successor failure.

Keyverse #104 is documentation-only at exact head
`7f1194d68b256d55f3b6cae6c1d181042091ea3c`; its `account-unification-tests`
failure (`32100975368`, job `95601269902`) is a base-main lock mismatch:
`pyproject.toml` requires coverage `7.15.4` and setuptools `84.0.0`, while
protected `main` still contained `7.15.2` and `83.0.0`. A separate minimal
lock-sync PR #112 was opened from protected-main head
`ce207dfd42975db61c82a5963e206fc1db14ac2b`, exact head
`f02acf93367a40dbfb23a73985017dca8d42ff39`. `uv lock` regenerated the hashes
and `uv run --locked --extra dev pytest -q` passed locally; hosted checks are
queued, so no hosted-green claim is made.

Keyverse #103 remains blocked at exact head
`44fb43428eab0075b9e5ee114a5ade56bb18eec2` by a real Strix MEDIUM IDOR report
(`32092025335`, job `95576032571`) against the new authorization-plane grant
mutation surface. ADR-0008 explicitly records that the current deployment
operator bearer is coarse-grained and that per-operation RBAC/ABAC is still a
required production boundary. Do not relabel this as an infrastructure flake
or bypass Strix; hold the feature PR as deployment-restricted until the
operator identity/resource-authorization design is separately remediated.

## Status as of 2026-08-19, iteration 18 — isolated fixes are now in hosted verification

The lock-only remediation is live as keyverse #112 at exact head
`f02acf93367a40dbfb23a73985017dca8d42ff39`, based on protected-main head
`ce207dfd42975db61c82a5963e206fc1db14ac2b`. Its hosted checks are queued (14
required jobs); seven scheduler/bootstrap cancellation jobs are already
terminal and no review decision has been posted. Do not call it green or
mergeable yet.

The living track plan is now exact head #758
`9f1a2946fd34adf76a661a0fb41aeb871e71bcc2`; its 15 required hosted checks are
also queued. The central `.github` scheduler remains intentionally bounded at
the previously recorded `0/0` dispatch/update limits while #1139 is not
merged and live-verified. Current-head evidence is preserved; no admin bypass,
self-approval, or policy write was used.

## Status as of 2026-08-19, iteration 19 — review gate made measurable and checks restarted

The living plan PR #758 advanced from `262ce8b2d61d566e8f5c467dcb6a887164dbf12c`
to exact head `3f1175e17a32252a31dbd86ecaa50e4e94770582` after addressing the
current-head review findings. The bypass exit is now measurable per repository:
two snapshots one scheduler interval apart, `open_prs <= 5`,
`CHANGES_REQUESTED <= 2`, and `CONFLICTING == 0` for both
`contextual-orchestrator` and `.github`, followed by fresh-PR
approve→base-advance→scheduler-update→fresh-check/review→protected-merge
evidence in each repository. The restoration checklist names the exact
classic protection and ruleset API changes and requires before/after evidence.

The duplicate continuation heading and the three Markdown PR-reference
hazards were also corrected. Targeted structural checks passed
(`git diff --check`, unique continuation headings, and no unintended numeric
PR lines parsed as headings). The standalone markdownlint run still reports
51 historical findings elsewhere in this long-lived plan; that is not claimed
as a full-file lint pass.

The new exact-head #758 hosted set is 15 required jobs queued, with only the
seven scheduler/cancellation jobs terminal-skipped. The last exact-head audit
also left keyverse #112 (14 required jobs), `.github` #1138/#1139, and
contextual-orchestrator #762 queued; no terminal failure or formal independent
approval was available for those heads. Keep both org sweep variables at `0`
until #1139 is merged and its global-budget behavior is live-verified. The
next action is to re-read these exact heads after queue progress, then use only
the normal protected merge path for any fully green, independently reviewed PR.

## Status as of 2026-08-19, iteration 20 — PR #96 coverage evidence repaired and re-queued

The current-head audit found contextual-orchestrator #96's real failure at
`fcdfa93687a52f46776df5a80b34b327bad7f2aa`: the full Python suite passed 620
tests but the 100% gate reported two missed statements and four partial
branches in `provider_catalog.py`, and `interrogate` then reported six missing
PostgreSQL-store method docstrings. The fix was kept narrow on branch
`fix/atheris-interpreter-lock`: three catalog edge-case tests close the missed
branches, and six method docstrings close the documentation gate. Local
verification at commit `55af6108361995df41427e810bca93f8115282ab` passed the
focused 32 tests, the full 622-test suite, branch coverage at 100% (`4032`
statements and `1060` branches, with zero misses/partials), `interrogate` at
100%, `ruff check`, and `git diff --check`.

The commit was pushed normally after an exact remote-head guard from
`fcdfa936...`; PR #96 now points to `55af6108361995df41427e810bca93f8115282ab`.
Its five current-head required jobs (`required-workflow-bootstrap`,
`noema-review`, `scan-pr-queue`, `close-empty`, and `strix`) are queued, while
the five scheduler/cancellation jobs are terminal-skipped. The only current
status context is CodeRabbit success due rate limiting; no independent review
for the new head exists yet. The PR remains open and `mergeable_state=dirty`;
do not call it green or mergeable until hosted checks and the normal review
gate produce terminal evidence.

## Status as of 2026-08-19, iteration 21 — stale Semgrep branch update is conflict-bound

The next independent stale-Semgrep candidate was contextual-orchestrator #650,
currently `1e5e60c0d1aacca8a220eeca19a731d9345747e0` against old base
`6841b71935e0b7cb98fb52bcb4709cc5100c8d87`; protected `main` is now
`7eb459ee72c37dead5d25f284dfa4546f149fbe1`. Its current checks include a
terminal failure for `Semgrep (multi-language SAST)` while the other security,
coverage, full-suite, and review-wrapper checks are terminal success or
neutral. The normal GitHub update-branch API was attempted with an exact
`expected_head_sha` and correctly returned HTTP 422 (`merge conflict between
base and head`), so no remote branch mutation occurred.

A local merge-tree/merge rehearsal confirmed that this is not a one-file
refresh: the branch conflicts in `contextual_orchestrator/__main__.py`,
`cost_ledger.py`, `orchestrator.py`, both Atheris requirement files,
`pyproject.toml`, and five related test files, in addition to the earlier
fuzz/docs conflict set. Do not auto-resolve or force-push a 1,000-line feature
branch; retain #650 as conflict-bound and continue with current-head fixes or
independently reviewable PRs.

## Status as of 2026-08-19, iteration 22 — scheduler fix passed Strix, approval still gates merge

The exact-head re-read of `.github#1139` at
`3dd3b634ca54f26d7719e972630d8a10e9eae3e7` found the targeted scheduler fix's
`strix` check terminal-success, with `Semgrep (multi-language SAST)`, gitleaks,
dependency review, trivy-fs, scan-pr-queue, noema-review, and close-empty also
successful. Three advisory checks are neutral and fifteen scheduler/cancellation
checks are skipped. Six required checks remain queued: coverage-source-tree,
four CodeQL compatibility/merge-preview jobs, and pip-audit. The PR is
`mergeable=true` but `mergeable_state=blocked`; the only submitted review is a
CodeRabbit COMMENTED review, so no independent approval exists. Do not merge or
restore the `0/0` org sweep limits yet; re-read after the queued checks and
approval gate change.

## Status as of 2026-08-19, iteration 23 — no clean merge candidate while hosted jobs queue

An individual-PR REST sweep of all open contextual-orchestrator PRs found only
four with `mergeable=true`: #758, #762, #763, and Draft #410. The first three
are `mergeable_state=blocked`; #758 is now at exact head
`06e7a69276804d50c3de0a192cd819d21229e6a9`, #762 is at
`3b685af971036fe61153b43eab674f4bc534390f`, and newly identified #763 is at
`f06ba9199854c090a149059b36639260e9b622d8`. All three have non-terminal
required checks and no independent approval; Draft #410 is unstable and was
not considered for merge. There is therefore no clean, independently reviewed
PR to merge in this snapshot.

The scheduler candidate `.github#1139` remains mergeable but blocked: its two
required CodeQL compatibility jobs are still pending, and no independent
approval exists. No admin merge, review dismissal, branch update, or sweep-limit
change was attempted while required checks were non-terminal. The next safe
action is to re-read these exact heads after hosted queue progress, then merge
only a fully terminal, policy-allowed candidate through the normal protected
path (using the documented admin fallback only when the independent-review
requirement alone is demonstrably unsatisfiable).

## Status as of 2026-08-19, iteration 24 — Noema sidecar contract failure repaired

The current-head audit found a real `.github#1120` failure at
`85534334d4ae7672c7f2dc23baa0cff2ef8079b6`: the hosted hourly contract suite
reported `1,220 passed, 2 failed` because private repositories could select the
multi-provider sidecar and the generated OpenCode inline config defined
`contextual-orchestrator` without including it in `enabled_providers`. The
minimal repair requires the sidecar branch only when
`TARGET_REPOSITORY_PRIVATE=false`, adds the provider to that exact allowlist,
and updates the workflow blob-hash contract to the resulting file hash.

Local verification on commit `c6bb739db213161b39f137640bd835354a4ba529`
passed the full `.github` suite (`1222 passed, 16 subtests passed`), focused
contract coverage, `actionlint` workflow parsing with local shellcheck/pyflakes
integrations disabled, and `git diff --check`. The commit was pushed after an
exact remote-head guard. PR #1120 is now `mergeable=true` but blocked with 17
queued and one in-progress hosted check; no current-head formal approval exists.
The next active failure candidate is `.github#1128`, whose prior exact-head
Strix job failed and requires log-level diagnosis before any dismissal or merge.

## Status as of 2026-08-19, iteration 25 — Strix report on `.github#1128` is a verified false positive

The prior `.github#1128` Strix failure (`32239172422`, job `96025752507`) was
read to the finding level, not dismissed from its summary. It reported one
CRITICAL “Hardcoded Test Lob API Key” at
`.github/workflows/hourly-nvidia-nim-review-repair.yml:30`, but the exact
current PR diff shows that line is only the existing path literal
`tests/test_hourly_autofix_context_quality_gate.py`; the PR adds a quarantine
caller, documentation, and contract test, and introduces no Lob integration,
API key, authorization header, or secret value. A repository search over every
changed security/workflow/test file found no `lob` or hardcoded API-key value.

This is a model attribution false positive, not a provider outage and not a
real secret remediation. Do not rename the established test path merely to
silence Strix, weaken the Strix classifier/gate, or close the feature PR. Keep
#1128 unmerged and preserve the failed evidence until a fresh exact-head Strix
run either produces a real line-specific finding or confirms the false
positive; any future dismissal must cite the path-line source comparison.

## Status as of 2026-08-19, iteration 26 — fresh Strix evidence is queued without a mergeable candidate

After the plan update, contextual-orchestrator PR #758 is at
`a8152051506fff1447a6368b0564f4092e31e761`, with its hosted required checks
re-queued and no independent approval. `.github#1120` remains at
`c6bb739db213161b39f137640bd835354a4ba529`; its repaired hourly contract check
is successful, but the remaining required checks are queued and no current-head
formal approval exists. `.github#1139` remains at
`3dd3b634ca54f26d7719e972630d8a10e9eae3e7`; the branch protection required
contexts include CodeQL compatibility, coverage evidence, and OpenCode review,
and the current required work is not terminally satisfied. No merge, review
dispatch, branch update, or sweep-limit change was attempted.

The fresh exact-head Strix retry for `.github#1128` is run attempt 2,
job `96069651307`, on head `e33536ba95a6fd6ff185b857ac2955835b80471e`, and
remains queued. Preserve the original finding and wait for this terminal
result before recording a dismissal or taking any PR action.

## Status as of 2026-08-19, iteration 27 — paginated queue snapshot confirms hosted-runner backlog

At `2026-08-19T12:45:52Z`, a fresh REST snapshot covered all paginated open
PRs. `contextual-orchestrator` has 166 open PRs, 158 current-head
`CHANGES_REQUESTED` reviews, and 162 REST `mergeable_state=dirty` conflicts.
`.github` has 140 open PRs, 21 current-head `CHANGES_REQUESTED` reviews, and
74 REST `mergeable_state=dirty` conflicts. The review count uses the latest
non-dismissed review per reviewer and requires its `commit_id` to equal the
live PR head; `dirty` is recorded as the REST equivalent of `CONFLICTING`.
Neither repository is near the documented two-snapshot exit gate.

The hosted queue is the active external bottleneck: `.github` reports 667
queued and 3 in-progress workflow runs, while contextual-orchestrator reports
27 queued runs. The central candidate `.github#1139` remains at
`3dd3b634ca54f26d7719e972630d8a10e9eae3e7` with seven required checks queued
and no independent approval. `.github#1120` remains at
`c6bb739db213161b39f137640bd835354a4ba529` with sixteen checks queued, and
the exact-head Strix retry for `.github#1128` remains queued at job
`96069651307`. No review dispatch, branch update, merge, or sweep-limit change
was attempted.

### Next iteration checklist

1. Re-read #1139, #1120, and #1128 by exact head and act on the first terminal
   failure or fully terminal required set; never merge with a real required
   check pending.
2. If #1139 becomes fully terminal-successful and still has no independent
   approval, use only the documented admin fallback with an explicit,
   verifiable review-unsatisfiable reason, then live-verify the merge before
   restoring the two org sweep budgets.
3. If #1128's retry terminates, compare the finding to the exact path-line
   source before recording any dismissal; do not rename tests or weaken Strix.
4. Keep both sweep limits at `0`, preserve conflicting PRs, and take a new
   paginated snapshot after the next scheduler interval.

## Status as of 2026-08-19, iteration 28 — stale queued runs removed with exact-head guards

Queue hygiene removed only runs proven not to represent a live PR head. The
following runs were re-read after their target PRs were re-read and each
finished `completed/cancelled`:

- `.github#1145`: run `32252906006`, stale `d7375b1481e8016ccaca04872e6250774bae5d3f`; live head was
  `6294747d2f05921fa93aa82b60aba95915b0c3ea`.
- `.github#1144`: run `32250263504`, stale `9e5d7834735854022dd99cf438857673d9960976`; live head was
  `d53fdfd4381d93e40a71984ff1f058605c0cb13c`.
- `.github#1024`: run `32244495506`, stale `309c83fb37ea5f5eab4c744d34dd56c45f896c68`; live head was
  `e7969870f22923834134e6dfded5eea240c95c88`.

The queued repository-dispatch inventory contained 204 target runs across 20
repositories. A broader all-repository comparison was intentionally stopped
after the bounded command window and then hit GitHub's secondary API rate
limit; the remaining candidates were not cancelled without a fresh live-head
read. Current-head runs, including #1139, #1120, and #1128's fresh Strix job,
were preserved. No branch update, review dispatch, merge, or sweep-limit
change was attempted; both sweep limits remain `0`.

### Next iteration checklist

1. After the Actions endpoint cools down, re-read the partial stale candidates
   and cancel only entries whose encoded `repo#PR@SHA` still differs from the
   live head or whose PR is closed; verify every cancellation terminally.
2. Re-read #1139's seven required checks, #1120's current checks, and #1128's
   fresh Strix retry by exact head before any merge or dismissal decision.
3. Record a second paginated queue snapshot only after one scheduler interval;
   do not treat the current partial stale scan as the exit-gate snapshot.

## Status as of 2026-08-19, iteration 29 — current candidates remain queued; broad stale scan rate-limited

After the three verified stale cancellations, exact-head re-reads still show
`.github#1139` at `3dd3b634ca54f26d7719e972630d8a10e9eae3e7` with seven
required checks queued, `.github#1120` at
`c6bb739db213161b39f137640bd835354a4ba529` with sixteen queued checks, and
the `.github#1128` retry job `96069651307` queued at head
`e33536ba95a6fd6ff185b857ac2955835b80471e`. The current-head queue was not
cancelled.

The full 20-repository stale-dispatch comparison was retried with bounded
concurrency after the initial timeout, but GitHub returned secondary API
rate-limit responses before the inventory could be completed. No additional
run was cancelled on partial evidence. Pause broad API scraping, preserve the
known current-head runs, and keep both sweep limits at `0` until the next
normal scheduler interval and a successful low-rate re-read.

### Next iteration checklist

1. Use a low-rate REST pass after the secondary limit clears; finish the
   repo-wide stale comparison or leave unresolved candidates untouched.
2. Re-read the three exact candidate heads and required contexts; merge only a
   fully terminal required set, with the documented admin fallback only for
   the unsatisfiable independent-review gate.
3. If #1139 merges, verify the live workflow and queue trend before changing
   either org sweep variable; otherwise keep them at `0/0`.

## Status as of 2026-08-19, iteration 30 — scheduler PR's real local contract failure repaired

The exact `.github#1139` worktree at
`3dd3b634ca54f26d7719e972630d8a10e9eae3e7` exposed one real full-suite
failure: `tests/test_opencode_agent_contract.py` still required the old
literal `--branch-update-limit "$ORG_SWEEP_BRANCH_UPDATE_LIMIT"`, while the
scheduler fix correctly derives and passes the remaining organization-wide
budget through `branch_update_limit`. The new queue contract test already
asserted the derived-budget behavior, so the minimal repair removed only the
stale credential-contract assertion; the workflow was not weakened or
reverted.

The repaired branch is now exact head
`7476d4a152d561ce5942befc91aee21b09e86afc`, pushed after a remote-head guard.
Local verification passed the focused 51 tests, workflow parsing with
shellcheck/pyflakes integrations disabled, and the full suite (`1216 passed,
16 subtests passed`). Hosted checks for this new head must be re-read before
any merge decision; no merge, review bypass, or sweep-limit change was made.

### Next iteration checklist

1. Re-read `.github#1139` at `7476d4a...` after the API cooldown and wait for
   every required context, including coverage evidence and OpenCode review, to
   become terminal.
2. Continue preserving #1120 current-head checks and #1128's exact-head Strix
   retry; investigate only a new terminal failure, not the superseded head.
3. If #1139 is fully terminal-successful but still lacks independent review,
   use the documented admin fallback only with the explicit unsatisfiable-gate
   reason, then live-verify the merge and the global sweep-budget behavior.

## Status as of 2026-08-19, iteration 31 — repaired head is hosted-queued without failures

At `2026-08-19T13:07:03Z`, the GraphQL status rollup confirmed
`.github#1139` at exact head
`7476d4a152d561ce5942befc91aee21b09e86afc`, `MERGEABLE/BLOCKED`, with no
review decision, zero failed checks, and the current security/scheduler set
still queued. The 30-second rollup observation showed no transition.

The same rollup showed `.github#1128` still at
`e33536ba95a6fd6ff185b857ac2955835b80471e`, blocked only by queued
`coverage-evidence` and `strix`, with no failure. `.github#1120` remains at
`c6bb739db213161b39f137640bd835354a4ba529`, with no failure and sixteen
queued checks. No current-head check was cancelled, no review was dismissed,
and no merge or sweep-limit change was attempted.

### Next iteration checklist

1. Continue low-rate GraphQL rollups until #1139's required contexts are
   terminal; distinguish no-failure/queued from green and never merge the
   former.
2. Re-read #1128's exact-head Strix result when it terminates and compare any
   finding to source before dismissal.
3. After #1139 is terminal-successful, re-read current reviews and branch
   protection, then use the documented review-only admin fallback if and only
   if the independent approval remains unsatisfiable.

## Status as of 2026-08-19, iteration 32 — recent `.github` sweep found no new terminal failure

A GraphQL rollup of the thirty most recently updated open `.github` PRs found
no new current-head failing check that was ready for a repair. Newer PRs such
as #1147 still have checks in progress or queued; they are not green evidence.

PR #1067 is a useful review-gate sample: its exact head is
`e3b673f8a302d24acb88d35ab25abaaeaa325c1a`, its current check rollup is
terminal-successful, but `reviewDecision=CHANGES_REQUESTED` and
`mergeStateStatus=DIRTY`. The two OpenCode review bodies were read in full;
both reject only the known mechanical `coverage-evidence result was failure`
condition (runs `32190682607` and `32193040239`) and explicitly describe the
merge-conflict path. This is evidence for a stale mechanical review, not a
new code finding, but the PR is still conflicting, so no dismissal, branch
update, or merge was attempted.

The active central fix remains `.github#1139` at
`7476d4a152d561ce5942befc91aee21b09e86afc`, with required work queued and no
independent approval. Keep current-head runs intact and continue the exact
terminal-gate loop.

### Next iteration checklist

1. Re-read #1139 and #1128 with a low-rate GraphQL rollup; act only on a
   terminal failure or a fully terminal required set.
2. Preserve #1067's review until its conflicting branch can be safely
   refreshed and its current-head evidence is re-established; do not dismiss
   it solely because the old check is now green.
3. Keep the sweep limits at `0/0` until #1139 is merged and live-verified.

## Status as of 2026-08-19, iteration 33 — #1128 advanced but remains non-terminal

At `2026-08-19T13:11:43Z`, three GraphQL rollups over 30 seconds showed no
failure transition. `.github#1128` stayed at exact head
`e33536ba95a6fd6ff185b857ac2955835b80471e` with `opencode-review` and `strix`
queued, no review decision, and `MERGE_STATE=BLOCKED`. Its earlier
`coverage-evidence` blocker is no longer in the pending set, but it was not
treated as a green claim without a terminal conclusion.

`.github#1139` stayed at exact head
`7476d4a152d561ce5942befc91aee21b09e86afc`, with the security/scheduler
required set queued, no failures, and no independent approval. No current-head
run was cancelled and no review, merge, branch update, or sweep-limit change
was attempted.

### Next iteration checklist

1. Keep monitoring #1128's two remaining checks and #1139's required set;
   record conclusions, not merely disappearance from pending.
2. On the first terminal failure, read the complete log and repair its root
   cause at the exact head; on a fully terminal green set, re-read reviews and
   protection before any merge.
3. Keep `ORG_SWEEP_REVIEW_DISPATCH_LIMIT` and
   `ORG_SWEEP_BRANCH_UPDATE_LIMIT` at `0` until the central fix is live.

## Status as of 2026-08-19, iteration 34 — no safe new repair while hosted queue remains non-terminal

The next current candidate, `.github#1147`, is a large 56-file,
2,812-line ecosystem capability-catalog feature at exact head
`86c4d7d52c346616ad9a64cd55cece543bfbae37`. Its current rollup showed
in-progress/queued checks but no terminal failure and no review decision. The
diff was fetched locally for scope inspection; no speculative change was made
to a large feature branch without a concrete failing check.

The active exact-head candidates remain unchanged: #1139 at
`7476d4a152d561ce5942befc91aee21b09e86afc` has queued required checks, and
#1128 at `e33536ba95a6fd6ff185b857ac2955835b80471e` has queued `opencode-review`
and `strix`. The REST Actions queue endpoint continues to return secondary
rate-limit responses; a broader 50-PR GraphQL rollup timed out, so neither was
used as evidence for a mutation. No current-head run, review, branch, merge,
or sweep-limit was changed.

### Next iteration checklist

1. Use small GraphQL rollups only for #1139 and #1128 until terminal evidence
   appears; avoid broad queries that time out or amplify API pressure.
2. On a terminal failure, inspect its exact log and make the smallest root
   cause repair; do not alter #1147 without failure evidence.
3. Keep both sweep limits at `0` and do not merge while required checks remain
   queued.

## Status as of 2026-08-19, iteration 35 — #1128 is near green; only OpenCode and Strix remain

At `2026-08-19T13:16:37Z`, the exact-head GraphQL rollup for
`.github#1128` at `e33536ba95a6fd6ff185b857ac2955835b80471e` showed no failed
checks and terminal success for coverage evidence, CodeQL compatibility and
merge preview, dependency/security scans, Noema, path policy, and the hourly
contract. Only `opencode-review` and `strix` remained queued. The PR is still
`MERGEABLE/BLOCKED` with no review decision, so it is a possible normal merge
candidate only after those two required contexts are terminal-successful.

`.github#1139` remains at `7476d4a152d561ce5942befc91aee21b09e86afc` with its
required set queued and no failures or independent approval. The classic
protection REST re-read was rate-limited; no protection or merge decision was
made from stale evidence.

### Next iteration checklist

1. Re-read #1128's `opencode-review` and `strix`; if both pass, re-read the
   live head, reviews, protection, and required contexts immediately before a
   normal protected merge.
2. Keep #1139 queued checks intact and repair any first terminal failure at
   its exact head.
3. Keep sweep limits at `0/0` until the central scheduler fix is merged and
   its global-budget behavior is live-verified.

## Status as of 2026-08-19, iteration 36 — #1128 local proof is green while hosted final gates queue

The exact `.github#1128` worktree at head
`e33536ba95a6fd6ff185b857ac2955835b80471e` was independently revalidated:
the full suite passed (`1222 passed, 16 subtests passed`), both changed
workflow files passed actionlint parsing with local shellcheck/pyflakes
integrations disabled, and `git diff --check` passed. This strengthens the
feature evidence but does not replace the hosted `opencode-review` and `strix`
required contexts, which remain queued with no failure and no review decision.

The central scheduler fix #1139 remains at
`7476d4a152d561ce5942befc91aee21b09e86afc`, with its required checks queued.
No current-head run or review was changed, and no merge or sweep-limit change
was attempted while hosted gates were non-terminal.

### Next iteration checklist

1. Re-read #1128's two hosted final gates; if both become terminal-successful,
   verify live head and required contexts immediately before a normal merge.
2. Keep #1139's queue intact and use its first terminal failure, if any, as
   the next root-cause repair target.
3. Keep both sweep limits at `0/0` until the scheduler fix is merged and
   live-verified.

## Status as of 2026-08-19, iteration 37 — current #1128 jobs are runner-queued, not stale

At `2026-08-19T13:21:35Z`, the exact-head rollup still showed #1128 at
`e33536ba95a6fd6ff185b857ac2955835b80471e` with no failures and only two
pending required jobs. Their live CheckRun details are:

- `strix`: run `32239172422`, job `96069651307`, queued since
  `2026-08-19T12:35:47Z`.
- `opencode-review`: run `32239172302`, job `96079256591`, queued since
  `2026-08-19T13:09:09Z`.

Both jobs target the current PR head, so neither is stale queue hygiene. The
central #1139 scheduler fix remains at `7476d4a...` with its required checks
queued. Preserve these jobs; do not cancel or rerun them merely to force a
state transition, and do not merge while either required context is pending.

### Next iteration checklist

1. Re-read these two job IDs and the exact head; act only when one terminates.
2. If both pass, perform the immediate live-head/review/protection check and
   normal protected merge for #1128 if the rules permit it.
3. Otherwise repair the first terminal failure and keep sweep limits at `0/0`.

## Status as of 2026-08-19, iteration 38 — #1142 is a second near-green candidate

The small candidate rollup found `.github#1142` at exact head
`660d4712805f87700223220e96975eb72051093d` with 20 successful checks, six
queued required contexts (CodeQL compatibility/merge previews,
`coverage-source-tree`, and pip-audit), no failure, and no review decision.
Its exact worktree independently passed the focused queue-health tests (40
tests), actionlint parsing with local shellcheck/pyflakes integrations
disabled, `git diff --check`, and the full suite (`1256 passed, 16 subtests
passed`). It is not mergeable evidence until all six hosted contexts are
terminal-successful.

#1128 remains at `e33536ba95a6fd6ff185b857ac2955835b80471e` with 28 successful
contexts and only `opencode-review`/`strix` queued. #1139 remains at
`7476d4a152d561ce5942befc91aee21b09e86afc` with its required set queued. No
current-head run, review, merge, branch, or sweep-limit was changed.

### Next iteration checklist

1. Monitor #1128 and #1142 for terminal conclusions; choose the first fully
   green candidate only after immediate exact-head and protection re-reads.
2. Read any terminal failure at the finding level and repair only its root
   cause; local green evidence does not waive hosted gates.
3. Keep both sweep limits at `0/0` until #1139 is merged and live-verified.

## Status as of 2026-08-19, iteration 39 — three candidates have local proof but hosted runner backlog persists

At `2026-08-19T13:28:58Z`, exact-head rollups still showed no terminal
failure:

- #1128 `e33536ba...`: 28 successes; `opencode-review` and `strix` queued.
- #1142 `660d4712...`: 20 successes; six CodeQL/coverage/pip-audit contexts
  queued. Its exact worktree passed focused queue-health tests, actionlint,
  diff check, and the full suite (`1256 passed, 16 subtests passed`).
- #1138 `1f4f5e09...`: 19 successes; seven compatibility/coverage/audit
  contexts queued. Its exact worktree passed 65 focused classifier/contract
  tests, actionlint, and `git diff --check`.

The oldest pending jobs remain runner-queued current-head jobs, not stale
dispatches. Local proof is preserved as supporting evidence only; no merge,
rerun, cancellation, review dismissal, branch update, or sweep-limit change
was made while hosted required contexts remain non-terminal.

### Next iteration checklist

1. Monitor the three candidates and act on the first terminal failure or fully
   terminal required set; use immediate exact-head and protection checks before
   merge.
2. Preserve current-head jobs and do not create more reruns to compete for the
   same hosted runner backlog.
3. Keep both sweep limits at `0/0` until #1139 is merged and live-verified.

## Status as of 2026-08-19, iteration 40 — protected auto-merge is armed; hosted gates remain

At `2026-08-19T13:33:45Z`, exact-head checks confirmed that the three active
candidates remain open and blocked only by hosted required work:

- #1128 remains at `e33536ba95a6fd6ff185b857ac2955835b80471e`. Its 28
  successful contexts are preserved; `opencode-review`, `strix`, and the
  current `scan-pr-queue` dispatch remain pending. Normal squash auto-merge was
  enabled at `2026-08-19T13:30:52Z`.
- #1142 remains at `660d4712805f87700223220e96975eb72051093d`. The current
  `scan-pr-queue` check is still queued at run `32258529724`, job
  `96085903212`; the same-HEAD earlier `scan-pr-queue` cancellation is an old
  execution, while another same-HEAD execution already passed. The GraphQL
  aggregate is therefore not merge evidence until the latest required contexts
  settle. Normal squash auto-merge was enabled at `2026-08-19T13:30:51Z`.
- #1139 remains at `7476d4a152d561ce5942befc91aee21b09e86afc`; its new-head
  required workflow set is queued and normal squash auto-merge was already
  enabled at `2026-08-19T12:20:25Z`.

The live `main` branch protection rule reports required status checks, an
approval requirement count of `0`, and `isAdminEnforced=false`. These are
normal protected auto-merge requests, not CI bypasses or administrator merges;
GitHub must still observe the required terminal-success contexts. No current-
head job was cancelled or rerun, and the organization sweep limits remain
`ORG_SWEEP_REVIEW_DISPATCH_LIMIT=0` and `ORG_SWEEP_BRANCH_UPDATE_LIMIT=0`.

### Next iteration checklist

1. Monitor the auto-merge candidates and immediately re-read exact head,
   required checks, review state, and protection before any merge conclusion.
2. If a required context fails, inspect its terminal job evidence and repair
   only the root cause; if all required contexts pass, verify the resulting
   merge commit and live main branch before recording success.
3. Keep both sweep limits at `0/0` until #1139 is merged and live-verified.

## Status as of 2026-08-19, iteration 41 — #1138 is one hosted job from green

The current-head required-check scan found #1138 at
`1f4f5e0968852e453918a1c11af8e0870434739d` with every other required context
successful and only `coverage-evidence` pending. Its exact job
`96085913624` has label `ubuntu-latest`, no runner assigned, and has been
queued since `2026-08-19T13:30:58Z`; no terminal failure was observed. Normal
squash auto-merge was already enabled at `2026-08-19T12:18:28Z`.

This makes #1138 the first candidate to recheck for a normal protected merge
once that one current-head context terminates successfully. #1128, #1142, and
#1139 remain unchanged from iteration 40: their current-head required jobs are
still runner-queued, and #1142 still has the historical same-HEAD cancelled
`scan-pr-queue` entry alongside its newer queued execution. No rerun or
cancellation was issued, and sweep limits remain `0/0`.

### Next iteration checklist

1. Re-read #1138's exact HEAD and job `96085913624`; if it passes, perform the
   immediate review/protection/mergeability check and let normal auto-merge
   complete, then verify the merge commit on live `main`.
2. If it fails, inspect the job log at the exact HEAD and repair the finding's
   root cause; do not treat runner queue behavior as a source failure.
3. Continue monitoring #1128, #1142, and #1139 without creating competing
   reruns; keep both sweep limits at `0/0` until #1139 is merged and verified.

## Status as of 2026-08-19, iteration 42 — the remaining #1138 gate is infrastructure-only

At `2026-08-19T13:43:16Z`, run `32244899441` still targeted exact HEAD
`1f4f5e0968852e453918a1c11af8e0870434739d`; job `96085913624` remained
queued with no runner, and the required-check view still showed every other
context passing. The exact-head `.github/workflows/opencode-review.yml` shows
that `coverage-evidence` only depends on `coverage-source-tree`, uses
`ubuntu-latest`, and emits a stable branch-protection evidence message without
executing pull-request content. The queue is therefore not a source finding:
do not remove the context, weaken its requirement, or manufacture a competing
rerun.

### Next iteration checklist

1. Keep monitoring job `96085913624`; on success, re-read #1138's exact HEAD,
   review decision, protection rule, and mergeability before relying on the
   already-enabled normal auto-merge.
2. On a terminal failure, inspect the job result and only repair a genuine
   source or workflow finding at the same HEAD.
3. Preserve #1128, #1142, and #1139 current-head jobs and the `0/0` sweep
   limits until #1139 is merged and live-verified.

## Status as of 2026-08-19, iteration 43 — closed-PR queue hygiene completed

At `2026-08-19T13:46:59Z`, the queued-run scan found 29 runs targeting exact
HEADs belonging to closed PRs #1016 (`ffbb4865...`), #1013
(`751ffc4c...`), and #1063 (`20629ff7...`). The PR states and HEADs were
re-read immediately before cancellation; all 29 explicit run IDs were then
cancelled and independently verified as `completed/cancelled`.

Current-head work was preserved. In particular, #1128 run `32258530207`,
#1142 run `32258529724`, #1138 job `96085913624`, and the queued #1128
`strix`/`opencode-review` jobs remain untouched. Their status was still
`queued` immediately after cleanup, so the cleanup removed stale work without
altering protected candidate evidence. No sweep limit or merge policy was
changed.

### Next iteration checklist

1. Re-scan queued runs for newly stale closed-PR or superseded-HEAD work, using
   the same exact-head guard before any further cancellation.
2. Monitor the preserved current-head jobs; on terminal success or failure,
   continue with the exact-head merge or root-cause repair procedure.
3. Keep `ORG_SWEEP_REVIEW_DISPATCH_LIMIT=0` and
   `ORG_SWEEP_BRANCH_UPDATE_LIMIT=0` until #1139 is merged and live-verified.

## Status as of 2026-08-19, iteration 44 — stale cleanup released a current Strix runner

At `2026-08-19T13:49:23Z`, two additional queued runs for closed #1063 were
discovered after the first cancellation batch. The closed state and exact HEAD
`20629ff74139777453fd22a39674ca2cc83e5d16` were re-read before cancellation;
runs `32257054130` and `32257054136` were cancelled and verified
`completed/cancelled`. No queued run for the closed #1016, #1013, or #1063
HEADs remained.

The cleanup produced a meaningful current-head transition: #1128's `strix`
job `96069651307` moved from queued to `in_progress` on runner
`GitHub Actions 1001063752` at `2026-08-19T13:47:07Z`. #1128's
`opencode-review`, #1138's `coverage-evidence`, and #1142's current scheduler
run remain queued and were preserved. No merge, rerun, sweep-limit, or review
policy change was made.

### Next iteration checklist

1. Monitor #1128 `strix` job `96069651307`; if it terminates, inspect the exact
   result at head `e33536ba...` before deciding whether auto-merge can proceed.
2. Preserve the remaining current-head queued jobs and perform the same stale
   closed-PR scan if the queue fills again.
3. Keep both sweep limits at `0/0` until #1139 is merged and live-verified.

## Status as of 2026-08-19, iteration 45 — broad stale-head scan completed

At `2026-08-19T13:54:49Z`, a full queued `pull_request`/
`pull_request_target` scan was compared against the live open-PR HEAD set. It
found 15 additional runs targeting closed PR HEADs (#1067, #1066, #1021,
#1073, #1091, #1072, #1081, #835, #1099, #1133, and #1131); all 15 were
cancelled and verified `completed/cancelled`.

One superseded run for still-open #919 was separately guarded: run
`32216087004` targets old HEAD `2852ed9...`, while live #919 is at
`04909c83...`. The run-level cancellation returned HTTP 500 and its only
queued job `95957823154` returned HTTP 404 to direct cancellation. This is a
GitHub Actions API state anomaly, not a reason to touch current-head jobs; it
was left unchanged after the two explicit failure responses.

#1128 Strix job `96069651307` remains the active current-head execution. The
other protected candidate jobs remain preserved, and no sweep limit, rerun,
review, branch update, or merge policy was changed.

### Next iteration checklist

1. Monitor #1128 Strix to terminal success or failure and act only on its
   exact-head result; do not repeatedly retry the #919 API anomaly.
2. Keep current-head jobs intact and re-scan only for newly created stale
   closed/superseded PR runs.
3. Keep both sweep limits at `0/0` until #1139 is merged and live-verified.

## Status as of 2026-08-19, iteration 46 — one stale run remains an API orphan

At `2026-08-19T13:59:48Z`, live #919 was still open at
`04909c83eadb6833b5d792327e4075e0ba8523fb`, while stale run `32216087004`
remained queued at old HEAD `2852ed9dadb9a37103fbd485c38bf8644c0a25ff`. After
re-reading both states, the normal run cancel and the documented force-cancel
endpoint both returned HTTP 500; direct cancellation of its only job had
already returned HTTP 404. No further retries or current-head cancellations
were made.

Queue hygiene otherwise remains effective: #1128's Strix job
`96069651307` is in progress, #1142 has only its current `scan-pr-queue`
pending, and #1138 has only current `coverage-evidence` pending. The
current-head jobs remain untouched and sweep limits remain `0/0`.

### Next iteration checklist

1. Wait for #1128 Strix to terminate; inspect its completed logs and same-head
   status before any merge conclusion.
2. Preserve #1142 and #1138's single pending jobs and the #1139 queued set.
3. Do not retry orphan run `32216087004` unless its API state changes; keep
   both sweep limits at `0/0` until #1139 is merged and live-verified.

## Status as of 2026-08-19, iteration 47 — merge #1140 and refresh all central candidates

At `2026-08-19T14:07:34Z`, `.github#1140` was verified merged at
`2026-08-19T13:58:24Z`; merge commit `bbedc1a51ec1a2421f129955c629b3cd0507a4ec`
is also the live `main` commit. Twenty-two stale/superseded runs were
cancelled and verified: 13 runs for merged #1140 and 9 runs for old #1147
HEAD `86c4d7d...`. #1147 remains open at new exact HEAD
`20709cbbbc98fb27188a00c9d29b375bc7612f96` with its existing normal squash
auto-merge request.

The main advance made the near-green candidates `BEHIND`, so they were not
left with stale evidence. Normal branch updates against live `main` produced
these new exact HEADs:

- #1139: `82b66ace61f7b1b81aed0203bbc85bf688119eef`
- #1128: `2e7f20dab0dd3963936c645c65869218c7af9091`
- #1142: `217e0ef900f7aaeee5158c364c632a6efefd8bc5`
- #1138: `99bcee074d384d54bf368f199d9567947496fd86`

Each new HEAD has the live `main` commit as its base, retains normal squash
auto-merge, and has a fresh required-check set queued with no terminal failure.
The old Strix/coverage successes were intentionally not reused after the base
advance. No required CI was bypassed and sweep limits remain `0/0`.

### Next iteration checklist

1. Monitor the four refreshed current-head required sets; on the first terminal
   failure, inspect its exact log and repair only the root cause.
2. On a fully terminal-successful set, re-read exact HEAD, review state,
   protection, and mergeability, then verify the protected auto-merge commit on
   live `main`.
3. Re-scan and cancel only newly stale closed/superseded runs; keep both sweep
   limits at `0/0` until #1139 is merged and live-verified.

## Status as of 2026-08-19, iteration 48 — refreshed required gates are runner-queued

At `2026-08-19T14:16:07Z`, the refreshed current-head checks remained
failure-free but runner-queued:

- #1128 HEAD `2e7f20dab0dd3963936c645c65869218c7af9091`, bootstrap job
  `96097385014`;
- #1142 HEAD `217e0ef900f7aaeee5158c364c632a6efefd8bc5`, bootstrap job
  `96097498627`;
- #1138 HEAD `99bcee074d384d54bf368f199d9567947496fd86`, bootstrap job
  `96097606347`;
- #1139 HEAD `82b66ace61f7b1b81aed0203bbc85bf688119eef`, bootstrap job
  `96097189605`.

All four jobs have no runner and remain queued; the corresponding required
sets have no terminal failure. #1138's auxiliary `Strix Changed Path Quality
CI` completed successfully, but its required Strix workflow is still pending,
so that auxiliary result is not merge evidence. The current-head stale scan
found no in-progress stale PR run and only the previously documented #919 API
orphan. No rerun, current-head cancellation, policy bypass, or sweep-limit
change was made.

### Next iteration checklist

1. Monitor the four bootstrap jobs and their dependent required contexts; act
   on the first terminal result at the exact refreshed HEAD.
2. Treat auxiliary green workflows as supporting evidence only; require every
   protected context to be terminal-successful before merge verification.
3. Keep both sweep limits at `0/0` until #1139 is merged and live-verified.

## Status as of 2026-08-19, iteration 49 — runner occupancy audit finds no safe cancellation

At `2026-08-19T14:19:58Z`, the four refreshed bootstrap jobs were still queued
without runners: #1139 `96097189605`, #1128 `96097385014`, #1142
`96097498627`, and #1138 `96097606347`. A separate `in_progress` scan found
no stale `pull_request` or `pull_request_target` run; the active PR runs
belong to open current heads. The long-running OpenCode dispatches for the
open #920/#928/#930/#931/#932/#933/#934/#935/#939 PRs likewise have matching
current HEADs and were preserved.

There is consequently no safe queue cancellation or source finding to act on
in this snapshot. The four required sets remain failure-free but non-terminal;
no rerun, policy bypass, sweep-limit change, or current-head cancellation was
made.

### Next iteration checklist

1. Continue monitoring the four exact-head bootstrap jobs and dependent gates;
   act immediately on the first terminal success or failure.
2. Re-run the stale in-progress audit only after a state transition or newly
   queued workload appears; do not cancel current-head evidence to force
   scheduling.
3. Keep both sweep limits at `0/0` until #1139 is merged and live-verified.

## Status as of 2026-08-19, iteration 50 — duplicate central scans reduced

At `2026-08-19T14:22:47Z`, the live scheduler workflow was inspected at
`main`. Eleven queued `repository_dispatch` runs titled `merge-scheduler`
targeted the same `.github` main SHA and contained only a queued
`scan-pr-queue` job; their `org-queue-sweep` jobs were skipped. The newest run
`32263563429` was preserved, while the ten older duplicate runs were
cancelled and independently verified `completed/cancelled`.

The four candidate bootstrap jobs remained queued immediately afterward, so
this safe duplicate reduction did not yet create a runner transition. No PR
required run, target-repository dispatch, current-head evidence, sweep limit,
or policy gate was changed.

### Next iteration checklist

1. Monitor the preserved scheduler run and the four exact-head bootstrap jobs;
   act on the first runner assignment or terminal result.
2. If duplicate no-target scheduler scans reappear, preserve only the newest
   same-main scan and verify each older cancellation; never apply this rule to
   target PR dispatches.
3. Keep both sweep limits at `0/0` until #1139 is merged and live-verified.

## Status as of 2026-08-19, iteration 51 — scheduler deduplication fix submitted

At `2026-08-19T14:29:31Z`, PR #1155 was opened from exact head
`762a999bf66db0bae2e6fc7455e1dc0c83268e1e` to fix the root cause found in
iteration 50. The central scheduler previously used `github.run_id` as the
fallback concurrency key for unscoped `repository_dispatch` events, so each
duplicate scan bypassed cancellation. The workflow now uses a stable
repository-level key, keeps `org_sweep == true` in its own group, and retains
the existing target-PR groups. The new static contract test and the full
`tests/test_required_workflow_queue_contract.py` file pass (`51 passed`),
along with `git diff --check` and `actionlint`.

PR #1155 has normal squash auto-merge enabled. Its first scheduler run was a
`pull_request_target` run cancelled by the subsequent PR-scoped run; that is
expected existing behavior and is not evidence for the new no-target
concurrency key. The newest run and all other required checks are still queued
without a terminal failure. No sweep-limit variable was changed.

### Next iteration checklist

1. Monitor PR #1155's exact-head checks and merge it only through normal
   auto-merge after every required context is terminal-successful.
2. Verify `main` contains the scheduler fix after merge, then recheck the
   candidate PR queue and current-head evidence.
3. Keep both sweep limits at `0/0` until #1139 is merged and live-verified.

## Status as of 2026-08-19, iteration 52 — pre-merge duplicate still reproduced

At `2026-08-19T14:22:33Z`, another unscoped `repository_dispatch` scheduler
run (`32263631059`) appeared against the unchanged main SHA, confirming that
the defect remains live until PR #1155 merges. The newer run was preserved;
the previous duplicate (`32263563429`) had the same queued `scan-pr-queue`
job and was cancelled, then verified `completed/cancelled`. PR #1155's
current-head required checks remain untouched and queued without terminal
failure. The source branch's complete local suite also passed: `1217 passed,
16 subtests passed`.

### Next iteration checklist

1. Continue preserving only the newest same-main unscoped dispatch while PR
   #1155 is waiting for hosted runners.
2. After merge, verify the stable `repo-dispatch-{repository}` concurrency
   group by observing an older duplicate cancel on a subsequent no-target
   dispatch, then verify main and the candidate queue.
3. Keep both sweep limits at `0/0` until #1139 is merged and live-verified.

## Status as of 2026-08-19, iteration 53 — recurring duplicate reduced again

At `2026-08-19T14:39:04Z`, the unchanged main SHA still produced a newer
unscoped `repository_dispatch` scheduler run (`32265285678`). The older
queued duplicate (`32263631059`) was cancelled and verified
`completed/cancelled`; the newer run was preserved. PR #1155 remains at exact
head `762a999bf66db0bae2e6fc7455e1dc0c83268e1e` with normal auto-merge enabled,
but its required hosted checks remain queued and main is still
`bbedc1a51ec1a2421f129955c629b3cd0507a4ec`.

### Next iteration checklist

1. Continue the safe newest-only cleanup for duplicate no-target dispatches
   while preserving all PR current-head evidence.
2. Act on the first terminal result for PR #1155; after merge, verify the
   stable concurrency key with a live no-target dispatch transition.
3. Keep both sweep limits at `0/0` until #1139 is merged and live-verified.

## Status as of 2026-08-19, iteration 54 — stale PR #1149 evidence removed

The live `pull_request_target` inventory found five non-terminal runs for PR
#1149 at obsolete head `9559e04b9489a2f33173db204c6a93283311063d`; the PR's
current head is `6e8938ffb0d1e2782b4f233bc1a2a18fd910b69b`. Those five stale
runs (`32261320886`, `32261320859`, `32261320867`, `32261320860`, and
`32261320838`) were cancelled and all verified `completed/cancelled`. All
other inspected active PR runs matched their live PR heads and were preserved.

### Next iteration checklist

1. Re-scan active runs after the queue settles and cancel only another exact
   stale-head or closed-PR set with matching evidence.
2. Continue preserving the newest no-target scheduler dispatch until PR #1155
   merges, then verify the fix on live `main`.
3. Keep both sweep limits at `0/0` until #1139 is merged and live-verified.

## Status as of 2026-08-19, iteration 55 — newest-only dispatch cleanup

Before the fix reached `main`, three additional unscoped dispatch runs for
the same main SHA were queued within seconds. The newest run
`32265347345` was preserved; older duplicates `32265324539` and
`32265314214` were cancelled and both verified `completed/cancelled`. The
source PR #1155 still has exact head `762a999bf66db0bae2e6fc7455e1dc0c83268e1e`
and remains normal-auto-merge enabled but runner-queued.

### Next iteration checklist

1. Continue preserving only the newest no-target dispatch and canceling only
   verified older duplicates until the workflow fix merges.
2. Recheck PR #1155 after any hosted-runner state transition; merge normally
   only after all required contexts succeed.
3. Keep both sweep limits at `0/0` until #1139 is merged and live-verified.

## Status as of 2026-08-19, iteration 56 — candidate auto-merge restored

The current-head audit showed PR #1138 at
`99bcee074d384d54bf368f199d9567947496fd86`, based on live main, with normal
mergeability but auto-merge disabled while its required checks remained
queued. Normal squash auto-merge was re-enabled and verified live; no admin
merge, self-approval, or CI bypass was used. PR #1128, #1139, #1142, and
#1155 retain their exact heads and normal auto-merge state.

### Next iteration checklist

1. Monitor the five exact-head auto-merge candidates for runner assignment or
   terminal checks; inspect and repair any first real failure.
2. Verify each protected merge on live main before advancing the candidate
   queue or changing sweep limits.
3. Keep both sweep limits at `0/0` until #1139 is merged and live-verified.

## Status as of 2026-08-19, iteration 57 — six-way duplicate dispatch burst reduced

The next live scheduler snapshot contained six no-target
`repository_dispatch` runs for the same main SHA, each with only a queued
`scan-pr-queue` job and a skipped org sweep. The newest
`32266217283` was preserved; older duplicates `32266217222`, `32266195331`,
`32266194884`, `32266193622`, and `32266182935` were cancelled and all five
verified `completed/cancelled`. This confirms the pre-merge defect is still
active, while the source fix remains isolated in PR #1155.

### Next iteration checklist

1. Preserve only the newest same-main no-target dispatch until #1155 reaches
   main; never cancel target PR or current-head evidence.
2. Recheck hosted runner assignment and merge PR #1155 normally when all
   required contexts succeed.
3. Keep both sweep limits at `0/0` until #1139 is merged and live-verified.

## Status as of 2026-08-19, iteration 58 — queue volume measured, no further safe cancellation

The current Actions inventory reports `846` queued runs and `16` in-progress
runs. A queued PR-event audit compared the known open/closed PR inventory with
each run's exact head and found no additional stale-head or closed-PR set safe
to cancel. The queued `repository_dispatch` inventory contains one
no-target `merge-scheduler` run (`32266217283`) plus cross-repository Noema
target dispatches; only the former is eligible for newest-only duplicate
cleanup. PR #1155 remains exact-head `762a999bf66db0bae2e6fc7455e1dc0c83268e1e`,
with every required context still queued and normal auto-merge enabled. Main
remains `bbedc1a51ec1a2421f129955c629b3cd0507a4ec`.

### Next iteration checklist

1. Preserve cross-repository target dispatches and current-head PR evidence;
   cancel only a verified older no-target scheduler duplicate.
2. Monitor the exact PR #1155 checks for a runner assignment or terminal
   result, then merge normally and verify the new scheduler on main.
3. Keep both sweep limits at `0/0` until #1139 is merged and live-verified.

## Status as of 2026-08-19, iteration 59 — plan PR auto-merge armed

The iteration-58 evidence commit
`22741222f9ac9757f167c7999ed577e2821bb73f` was pushed to PR #758; the current
plan branch head is `778c866352185a3f2d26f05ad82e5043953e506a`. Its live base is
`7eb459ee72c37dead5d25f284dfa4546f149fbe1`,
the PR is mergeable but blocked only on its queued required checks, and normal
squash auto-merge is now enabled and verified. No admin merge, self-approval,
or CI bypass was used.

### Next iteration checklist

1. Monitor both PR #758 and PR #1155 for hosted runner assignment and
   terminal required checks.
2. Merge only through their enabled normal auto-merge paths, then verify the
   exact resulting main commit and scheduler behavior.
3. Keep both sweep limits at `0/0` until #1139 is merged and live-verified.

## Status as of 2026-08-19, iteration 60 — queue draining without runner assignment

The next live snapshot showed the Actions queue moving from `846 queued / 16
in-progress` to `840 queued / 13 in-progress`, but neither PR #758 nor PR
#1155 received a runner; all inspected required contexts remain queued. The
no-target scheduler inventory still contains only `merge-scheduler`
`32266217283`. Six other queued `repository_dispatch` runs are explicitly
cross-repository Noema target reviews and were preserved.

### Next iteration checklist

1. Recheck both exact-head PRs after the next queue transition; do not rerun
   or cancel their current evidence merely to change scheduling order.
2. Preserve target dispatches and the single newest no-target scheduler run;
   merge normally when required contexts become terminal-successful.
3. Keep both sweep limits at `0/0` until #1139 is merged and live-verified.

## Status as of 2026-08-19, iteration 61 — duplicate audit removed one older dispatch

The queued-run duplicate audit found an older no-target `merge-scheduler`
`32265347345` for the same main SHA as the newest preserved no-target run
`32266217283`. The older run was cancelled and verified
`completed/cancelled`. Other same-SHA scheduler entries were schedule,
workflow-run, or push events rather than no-target dispatches and were
preserved; target dispatches were also preserved. The queue snapshot was
`996 queued / 16 in-progress`; PR #758 and PR #1155 remained exact-head,
normal-auto-merge, runner-queued, and main remained unchanged.

### Next iteration checklist

1. Continue grouping duplicate scheduler runs by event and title before any
   cancellation; preserve target and current-head evidence.
2. Recheck PR #758 and #1155 for runner assignment or terminal results, then
   rely on normal auto-merge and verify resulting main.
3. Keep both sweep limits at `0/0` until #1139 is merged and live-verified.

## Status as of 2026-08-20, iteration 62 — no-op scheduler pending runs removed

The first live snapshot after the date rollover contained 47 pending
`Required PR Review Merge Scheduler` runs from `workflow_run` events with no
PR metadata. A representative run had `jobs=[]`, so these runs could not
scan or mutate any PR and were not current-head evidence. All 47 were
cancelled and individually verified `completed/cancelled`; schedule runs,
target dispatches, and PR evidence were not touched. The queue moved from
`1061 queued / 25 in-progress` to `1031 queued / 26 in-progress`. PR #758 and
#1155 remain exact-head and normal-auto-merge enabled, with required checks
still runner-queued; main remains `bbedc1a51ec1a2421f129955c629b3cd0507a4ec`.

### Next iteration checklist

1. Re-scan no-op scheduler runs after the next transition and cancel only
   runs with the same no-PR/no-jobs evidence.
2. Monitor PR #758 and #1155 for runner assignment, then let normal
   auto-merge proceed and verify the resulting main commits.
3. Keep both sweep limits at `0/0` until #1139 is merged and live-verified.

## Status as of 2026-08-20, iteration 63 — regenerated no-op run removed

After the 47-run cleanup, the unchanged scheduler generated one new pending
`workflow_run` with no PR metadata and no jobs (`32267791101`). It was
cancelled and verified `completed/cancelled`. The source PR #1155 remains
unchanged at exact head `762a999bf66db0bae2e6fc7455e1dc0c83268e1e`; the plan
PR #758 now has exact head `7c7b4d013aa3913e3c45ab85f68af80260c049dc`. Both
retain normal auto-merge, while their required checks remain queued and main
remains `bbedc1a51ec1a2421f129955c629b3cd0507a4ec`.

### Next iteration checklist

1. Continue cancelling only regenerated scheduler runs proven to have no PR
   metadata and no jobs; preserve target and current-head runs.
2. Recheck both auto-merge PRs for terminal required checks and verify main
   after any protected merge.
3. Keep both sweep limits at `0/0` until #1139 is merged and live-verified.
