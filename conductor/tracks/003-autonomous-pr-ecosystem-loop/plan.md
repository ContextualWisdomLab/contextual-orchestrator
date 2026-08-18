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
