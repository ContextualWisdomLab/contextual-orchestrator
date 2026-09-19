# Spec: Autonomous PR/Product Ecosystem Loop

## Goal

Keep every ContextualWisdomLab repository the operator (seonghobae) owns at
commercial-grade quality with an empty or near-empty PR queue on `main`, by
running review → fix → recheck → merge continuously without pausing for
interim human sign-off, then moving to the next highest-leverage piece of
missing product surface. The bar is: this software should be defensible in
a due-diligence room at a nine-figure acquisition price. Every gap a real
buyer would notice on inspection gets found and closed.

## Standing authorization (confirmed 2026-08-18, do not re-ask)

- **Merge authority**: full autonomy. Merge any PR whose required checks are
  green, including security/schema/compliance-adjacent changes, without
  waiting for a human review beyond what CI already enforces.
- **PII masking**: research alternatives (field-level encryption, RBAC,
  audit-logged access, tokenization) and remove blanket PII masking where it
  blocks operations, replacing it with a compliant alternative. Do this
  immediately per repo as it comes up, don't hold for a separate approval.
- **Repo scope**: every ContextualWisdomLab org repo where `viewerPermission`
  is ADMIN (operator has full rights) — currently ~65 repos (see
  `gh repo list ContextualWisdomLab --json name,viewerPermission`).
- **Scheduling**: `/loop` dynamic pacing (ScheduleWakeup), not a GitHub
  Actions cron. The session re-enters this track's plan.md on each wake.

## Discovered infrastructure (do not duplicate or fight it)

The org-central `.github` repo already runs an automated review+merge
pipeline that most target repos inherit via reusable/dispatched workflows:

- `noema-review.yml` / `agent-mention-noema-dispatch.yml` — Noema GitHub App
  review bot (OIDC-scoped token broker, repo: `ContextualWisdomLab/noema`).
- `opencode-review.yml` / `opencode-review-dispatch.yml` — required OpenCode
  review, the actual PR-approval source that satisfies branch protection's
  1-required-review rule. **Do not touch its key/token setup.**
- `pr-review-merge-scheduler.yml` — "Required PR Review Merge Scheduler."
  Runs on push/PR events, review/security workflow completion, and a
  15/30-minute cron sweep. Dispatches OpenCode/Strix reviews, updates stale
  branches, and auto-merges current-head approved PRs
  (`enable_auto_merge`, `merge_mode: direct_or_auto`). This is the actual
  merge mechanism for most PRs — most of the time the job here is to get a
  PR's checks green and then let this scheduler merge it, not to
  `gh pr merge` by hand.
- `pr-review-fix-scheduler.yml` / `pr-review-autofix.yml` — automated fix
  dispatch for review-flagged issues.
- `strix.yml` / `strix-changed-path-quality-ci.yml` — Strix security agent,
  scoped to PR-head changed files. Required check. Uses NVIDIA NIM /
  GitHub Models / OpenAI / OpenRouter / Vertex backends per
  `STRIX_LLM`; treats backend rate-limit/connection failures as a neutral
  skip but hard-fails on any real reported finding — so a `strix` failure
  needs a human (agent) read of the job log to tell backend noise from a
  real finding (see 2026-08-18 example below).
- `hourly-nvidia-nim-review-repair.yml`, `clearfolio-hourly-review-repair.yml`,
  `disksage-hourly-review-repair.yml`, `fast-mlsirm-hourly-review-repair.yml`
  — per-repo (or generic NIM-backed) hourly review-repair jobs matching what
  this track is asked to generalize. `contextual-orchestrator` does not yet
  have one; check per repo and add if it's genuinely missing coverage,
  reusing the generic NVIDIA NIM one instead of a new Copilot-token flow —
  **NVIDIA_NIM_API_KEY, never COPILOT_GITHUB_TOKEN**, and never touch the
  existing review agents' key wiring.
- Branch protection on `main` requires 1 approving review (from OpenCode/
  Noema, not the operator) plus a fixed set of status checks (Hypothesis,
  Atheris, CodeQL, pip-audit/Python supply chain, dependency-review, OSV,
  Trivy, Scorecard, coverage-evidence, opencode-review, strix,
  scan-pr-queue).

## Working pattern per iteration

1. `gh pr list --state open` in the current target repo. Triage:
   - All green + no interim commit needed → leave it; the merge scheduler
     will land it (verify it actually does after ~30 min; if a PR sits
     approved-and-green for a full sweep cycle without merging, that's a
     real bug in the scheduler or a merge conflict, not something to wait
     out passively — fix it or merge directly with admin override
     as a last resort, logging why).
   - A required check fails → pull the job log (`gh api .../jobs/<id>/logs`
     for Actions jobs; `gh api .../code-scanning/alerts?pr=<n>` for
     CodeQL), determine real finding vs. infra flake, fix the real ones,
     re-push to the PR's own branch (not `main` directly).
   - PR is stale scope, superseded, or was a scratch/experiment → close it
     with a one-line reason instead of leaving it to rot.
2. Once a repo's queue is at zero (or everything left is legitimately
   blocked on something external, logged in plan.md), move to the next repo
   in leverage order (see plan.md), or to a product-gap item if every repo's
   queue is empty.
3. Never weaken a gate (no `continue-on-error`, no disabling a required
   check, no `--no-verify`) to get a merge through. Fix the underlying
   issue. This mirrors the repo's own CLAUDE.md security-gate rule and
   applies org-wide.
4. Every merged security/compliance-relevant change gets a one-line ADR/
   CHANGELOG entry in the target repo, not just a commit message.
5. Update this track's plan.md with what happened and what's next before
   the session ends each iteration, since the loop resumes from here.

## Non-goals for this track

- Not re-litigating already-answered scope questions (merge authority, PII
  masking approach, repo scope, scheduling mechanism) — see "Standing
  authorization" above.
- Not a place to duplicate `.github`'s merge-scheduler logic in this repo.
