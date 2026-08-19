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
#749). **Next iteration: once #1121 merges, re-check whether the
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
