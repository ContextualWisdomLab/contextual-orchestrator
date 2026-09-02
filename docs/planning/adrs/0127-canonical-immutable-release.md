---
id: "0127"
title: "Publish a canonical immutable GitHub Release, gated on protected-main evidence"
status: proposed
proposed_date: "2026-09-02"
deciders:
  - "repository maintainer"
affected_components:
  - ".github/workflows/release.yml"
  - "scripts/ci/release_notes.py"
  - "docs/RELEASING.md"
related:
  - path: "docs/planning/adrs/0020-fail-closed-release-authorization.md"
    relation: "distinct-concern-shares-fail-closed-spirit"
success_criteria:
  - metric: "consumer pin target"
    target: "GET /repos/ContextualWisdomLab/contextual-orchestrator/releases/latest returns a tag, not 404"
    source: "gh api repos/.../releases/latest after the first manual dispatch"
  - metric: "no vendored source SHA required"
    target: "a consumer can depend on the released tag/API/client/schema without vendoring this repository's source"
    source: "owner acceptance criteria, PR #971 comment 2026-09-02T18:26:04Z"
  - metric: "no paid/provider-specific fallback required"
    target: "the release mechanism itself calls no paid API and needs no new runtime dependency"
    source: "workflow uses only actions/checkout, git, and the gh CLI already available on GitHub-hosted runners"
---

# Publish a canonical immutable GitHub Release, gated on protected-main evidence

## Context

This repository has never cut a release. `git tag -l` is empty, no
`.github/workflows/*release*.yml` exists, and `GET /repos/ContextualWisdomLab/
contextual-orchestrator/releases/latest` returns 404. `pyproject.toml` has
carried `version = "0.2.0"` and `CHANGELOG.md` an `## [0.2.0] - Unreleased`
section through hundreds of merged PRs, and `CHANGELOG.md`'s own preamble
already states the intended process ("a version is released only after the
protected `main` branch, required Checks, independent review, and release
artifacts are verified on the same commit") — but nothing has ever executed
it.

This is a real, evidenced cross-repo consumer defect, not a hypothetical
gap. On `contextual-orchestrator#971` the repository owner (seonghobae)
recorded, on the same PR body this ADR's `success_criteria` cite, four
independent consumer-owner handoffs that all hit the same wall:

- **`ContextualWisdomLab/keyverse#132`** (2026-09-02T09:42:46Z): Keyverse
  vendors `contextual-orchestrator` at commit `045d17da5e2aea56a97e241ee158ab1
  628d78660`, 175 commits behind protected `main`. A later comment
  (2026-09-02T18:26:04Z) confirms Keyverse is still pinning source revision
  `464da4715b495b5eaaa593eba3796e2d976ee0c9` because "[t]he owner repository
  currently has no GitHub `latest` release endpoint (`/releases/latest`
  returns 404)."
- **`ContextualWisdomLab/bandscope#881`** (2026-09-02T11:15:54Z): explicitly
  told not to copy the mutable owner branch or invent a direct provider
  fallback; waiting on "an immutable contextual-orchestrator release with
  the compatible OpenAI-style gateway/API contract."
- **Wardnet** (2026-09-02T11:42:50Z): "[f]resh release inventory for
  `ContextualWisdomLab/contextual-orchestrator` is empty, so Wardnet cannot
  correctly replace these seams with a mutable branch or copied source."
- **EgressWeave#235** (referenced 2026-09-02T18:26:04Z): a 45-minute Actions
  job timeout on the same gateway-backed pattern — a related but distinct
  resumable-long-running-execution gap, explicitly out of scope for this ADR
  (see Non-Goals).

The owner's stated RED/GREEN acceptance for the release piece, verbatim from
that last comment: "the resulting released API/client/schema is immutable
enough for consumers to pin without vendoring this repository's source ...
No paid/provider-specific fallback should be required to consume it."

### Does this compose with `release_authorization.py`, or is it a new concern?

`contextual_orchestrator/release_authorization.py`
(`evaluate_release_authorization`), its ADR (0020), and every test/doc that
touches it (`tests/test_release_authorization.py`,
`tests/test_release_authority_snapshot.py`,
`tests/test_commercial_release_candidate.py`,
`docs/commercial_release_candidate.md`, `docs/doctoring/
release-authorization.md`) were read in full before writing this ADR. That
machinery:

- is a **pure evaluator function** plus a **read-only collector script**
  (`scripts/ci/release_authority_snapshot.py`) that together answer "does
  this GitHub *pull request*'s exact head currently satisfy protected-`main`
  governance (checks, independent review, findings)?";
- feeds exactly one caller: `TaskOrchestrator`'s
  `commercial_release_candidate_report()` behind
  `/api/v1/commercial_release_candidates/latest` — a **buyer-facing product
  evidence report inside the running gateway service**, gated behind admin
  auth, consumed by a human/procurement audience;
- requires `--pr <number>` and a KV-registered HMAC signing key
  (`CONTEXTUAL_ORCHESTRATOR_RELEASE_AUTHORITY_SIGNING_KEY`) before a server
  operator can even load a snapshot;
- is **never invoked by any GitHub Actions workflow today** — it is a manual/
  administrative tool, run by a human or agent with an authenticated `gh` CLI,
  its own docs say to "[r]egister ... in the KV for both the protected CI
  collector and the gateway";
- has **no code path that creates a git tag, a GitHub Release, or any
  publication artifact**. `docs/commercial_release_candidate.md`'s own scope
  section says as much: it is "a local product readiness artifact, not a
  valuation guarantee, purchase commitment, or production compliance
  certificate."

**Conclusion: this is a new, distinct concern that must not be built as a
duplicate of the same governance.** The two do not compose at the function-
call level, for a concrete reason that is not merely "different endpoint":
`collect_authority()` is *PR-scoped* (it reads `pulls/{pr}/reviews`,
`pulls/{pr}/commits`, and a PR's `head`/`base`). Protected `main`'s tip after
a merge is not "a pull request" — there is no stable, non-fragile way to
keep re-deriving "which PR produced this exact main commit" arbitrarily far
into a release workflow's future without either (a) hardcoding a PR number
that goes stale the moment another PR merges, or (b) reverse-searching GitHub
for the merging PR by commit SHA, which is unreliable across squash/rebase/
merge-commit strategies and would itself duplicate GitHub's own merge
bookkeeping inside this repository — exactly what ADR 0020 already warns
against: "GitHub governance remains in the central `.github` repository
rather than being duplicated in the inference runtime."

That said, the two **do share the same fail-closed spirit**, and the release
mechanism must honor it without re-implementing it:

- Branch protection (the active ruleset `release_authority_snapshot.py`
  itself inspects via `rulesets?includes_parents=true`) is the actual
  enforcement point. It already refuses to let a PR merge into `main` without
  every required check terminal-success and the required independent
  approval on that exact head. Any commit that is genuinely the current tip
  of protected `main` has therefore already passed the same evidence
  `evaluate_release_authorization()` would demand of a PR — enforced once, at
  the authoritative point, not re-derived speculatively per release.
  Composing "in spirit" means the release workflow's job is to verify that a
  commit **is, in fact, untampered current protected-`main` tip** (guards
  against a stale ref, a race with a concurrent merge, or a direct push that
  bypassed the ruleset) and to re-run this repository's own primary
  regression gate fresh, immediately before cutting an immutable artifact —
  not to re-ask "was this PR reviewed," which branch protection already
  answered irrevocably before the merge could exist.
- `docs/commercial_release_candidate.md` frames buyer-facing "release
  authorization" and "product evidence" as deliberately separate concerns
  that must never be conflated ("Product evidence and release authorization
  are separate ... Reviewer delay ... never authorizes a release"). A GitHub
  Release/tag is neither of those two things; it is a third, narrower
  concern — "does this exact artifact exist at an immutable, citable
  address" — and folding it into either existing surface would blur a
  boundary this repository has already deliberately drawn.

## Decision

### Trigger

`workflow_dispatch` only, with a required `version` input (e.g. `0.2.0`, no
leading `v`). No `push`, `schedule`, or tag-push trigger. Releases are
deliberate, maintainer-initiated actions, never an automatic side effect of
merging to `main` — consistent with the owner's explicit request in the task
that spawned this ADR and with `CHANGELOG.md`'s own stated process. Manually
dispatching a workflow already requires write access to the repository, which
is the same friction this repository already relies on elsewhere (e.g. no
separate actor allowlist exists for `workflow_dispatch` in `nim-benchmark.yml`
or `provider-catalog-sync.yml`); adding a bespoke actor check here would be
new, unproven ceremony this repository has not needed before.

### Gate (never weakened, never skipped)

Before any tag or Release is created, the release job:

1. Confirms the ref is `refs/heads/main`.
2. Re-fetches protected `main`'s current tip via `gh api repos/$REPO/commits/
   main --jq .sha` and fails closed if it does not exactly equal the checked-
   out commit — guards against a stale dispatch racing a concurrent merge, or
   a detached/rewritten ref. This needs only `contents: read`.
3. Parses `pyproject.toml`'s `version = "..."` and fails closed unless it is
   byte-for-byte equal to the `version` input. A release never redefines what
   version a commit is; the version bump is a normal, already-reviewed PR
   that must land first.
4. Fails closed if git tag `v${version}` already exists locally or on the
   remote — an existing tag is never moved, deleted, or overwritten
   (immutability).
5. Runs this repository's own full test suite fresh, on the exact commit
   about to be tagged (`uv run --locked --extra api --extra db --extra queue
   --group dev python -m pytest -q`, the same invocation `ci.yml`'s "Full
   unit and contract suite" job uses) — a genuine, no-stale-cache
   confirmation of the single most likely regression surface, not merely a
   read of a prior run's status.
6. Extracts `CHANGELOG.md`'s `## [${version}]` section (`scripts/ci/
   release_notes.py`, new, tested) and fails closed if that section is
   missing or empty — a Release is never published without real notes.

Steps 5 (full local suite) and 6 (real content) are direct, cheap, in-
workflow re-verification. CodeQL, Trivy, OSV, Scorecard, Semgrep,
`opencode-review`, `noema-review`, and `strix` are **not** re-executed inside
`release.yml`: they are exactly the required checks that already had to pass
before this commit could reach protected `main` at all (step 2 confirms that
identity), several are centrally owned by `ContextualWisdomLab/.github` per
this repository's own `CLAUDE.md` ("Central PR governance ... is the
canonical implementation ... for every sibling repo"), and re-running them
here would duplicate infrastructure this repository does not own rather than
add release-specific assurance.

### What the release contains

- An **annotated** git tag `v${version}` (`git tag -a`, not lightweight —
  carries tagger identity and a message, and is the artifact GitHub's
  Release API attaches to).
- A **GitHub Release** (`gh release create`) at that tag, titled `v${version}`,
  with a body built from the extracted `CHANGELOG.md` section plus the exact
  released commit SHA.
- The workflow uploads the CycloneDX SBOM `security.yml`'s
  `python_supply_chain` job already generates as a release asset when that
  artifact is available for the released commit, giving consumers the same
  provenance evidence this repository already produces for every merge to
  `main` — reusing existing SBOM generation rather than adding a second one
  inside `release.yml`.
- `permissions: contents: write` is scoped to the one job that creates the
  tag/Release; every other job/step keeps the workflow-default `contents:
  read`.

### Non-goals (explicitly deferred — do not build now)

- **Composing with `release_authorization.py` at the function-call level.**
  Deferred per the Context section above. A future PR could extend
  `evaluate_release_authorization()`/its collector to accept a bare commit
  SHA instead of a PR number if a concrete need for that specific evidence
  shape (rather than the ruleset-tip check this ADR specifies) emerges; not
  needed for a first working mechanism.
- **Resumable long-running execution / checkpoint-and-re-dispatch** (the
  EgressWeave#235 / `OPENCODE_RUN_TIMEOUT_SECONDS` half of the owner's
  2026-09-02 comment). Real, but an orthogonal runtime concern from
  publishing an immutable release artifact; tracked separately in
  `docs/product-technical-gap-baseline.md`.
- **Publishing to PyPI or any package index.** Consumers named in the
  evidence (Keyverse, BandScope, Wardnet) vendor/pin *source*, not a Python
  package; a PyPI publish step is unevidenced scope growth for this pass.
  `pyproject.toml`'s own `version` field is exactly what a future PyPI step
  would need, so nothing here forecloses it.
- **Automatic `pyproject.toml` version bumping.** The version bump remains a
  normal, reviewed PR; `release.yml` only validates it matches the dispatch
  input.
- **A release cut on every merge to `main`.** Explicitly rejected — see
  Trigger above.
- **Re-deriving required-check names dynamically from the GitHub ruleset
  API** (as `release_authority_snapshot.py` does for its PR-scoped
  evidence). This ADR's gate does not need the exhaustive required-check
  inventory — it needs "is this commit really `main`'s tip" (step 2) plus a
  fresh regression run (step 5), both of which are simpler and do not need
  the `administration: read` permission the rulesets endpoint requires.

## Consequences

- Consumers gain a real, immutable pin target:
  `github.com/ContextualWisdomLab/contextual-orchestrator/releases/latest`
  and `.../releases/tag/v0.2.0`, satisfying the owner's stated acceptance
  criterion without any paid or provider-specific dependency.
- Releasing stays deliberate and rare (manual `workflow_dispatch`), matching
  `CHANGELOG.md`'s existing stated process instead of introducing a new,
  undocumented cadence.
- The buyer-facing `/api/v1/commercial_release_candidates/latest` surface,
  `release_authorization.py`, and ADR 0020 are untouched by this change —
  they keep answering "is this PR commercially/buyer-sale-ready," a
  different question from "does an immutable citable artifact exist."
- A future PR remains free to wire a stronger, SHA-scoped variant of
  `evaluate_release_authorization()` into this gate if a concrete gap in the
  current tip-check surfaces in practice, without needing to revisit this
  ADR's core trigger/tag/notes decisions.

## Customer next action

Run `.github/workflows/release.yml` via `workflow_dispatch` with `version`
set to `pyproject.toml`'s current value once a maintainer has confirmed the
`## [x.y.z]` `CHANGELOG.md` section is ready to publish. This ADR's own
implementation does not trigger a real release; cutting the first `v0.2.0`
tag is a separate, deliberate action left to the repository owner.
