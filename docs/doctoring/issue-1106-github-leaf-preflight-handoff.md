# Issue #1106 handoff: remove leaf preflight in `ContextualWisdomLab/.github`

- **Audience:** `.github` lead (central CI review pipeline owner)
- **Date:** 2026-09-17
- **Gateway status:** owner readiness/admission contract is on protected
  `contextual-orchestrator` `main` via [#1124](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1124)
  and free-pool failover sizing via [#1195](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1195).
- **This document:** docs-only handoff. No `.github` code changes ship from the
  gateway worker that authored it.

## Why this handoff exists

Issue [#1106](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/1106)
required a **versioned owner contract** so a leaf caller can send only the
gateway bearer plus `model: orchestrator/free` and delete its own
provider / model / credential / probing / admission preflight.

That owner half is done:

| Change | PR | What landed |
| --- | --- | --- |
| Typed readiness/admission provenance | [#1124](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1124) | `REVIEW_READINESS_CONTRACT_VERSION = "1"`, `ReviewModelAdmission`, `review_model_admission()`, `review_pool_admissions()` in `contextual_orchestrator/review_gateway.py`; contract tests in `tests/test_review_gateway_admission_contract_1106.py` |
| Free-pool failover budget sized to admitted catalog | [#1195](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1195) | `build_review_orchestrator()` sets `tool_retry_attempts = min(pool_size - 1, MAX_TOOL_RETRY_ATTEMPTS)` so a single leaf external attempt can still walk the admitted free pool |

The **consumer half** remains in `ContextualWisdomLab/.github`: the vendored
review sidecar still builds a leaf catalog, probes routes at boot, and clamps
generation with a leaf token budget.

## Pin reality check (do not skip)

Default pin in
`scripts/ci/contextual_orchestrator_review_sidecar.sh` (as of
`ContextualWisdomLab/.github` `main` @ `a9c6477d3`):

```text
ORCHESTRATOR_PIN_SHA=767e67fbc6b881a452761f32abb69b9971b9b03b
```

| Owner change | Relative to that pin |
| --- | --- |
| #1124 readiness contract | **Already contained** in `767e67fb` (`REVIEW_READINESS_CONTRACT_VERSION` / `ReviewModelAdmission` present) |
| #1195 failover budget | **Not contained** — landed later (`e64ebe38`, 2026-09-17). Advance the pin to a protected `main` SHA that includes #1195 in the same consumer PR (or as an explicit prerequisite), otherwise a leaf that stops local probing will still inherit the old two-candidate internal failover default |

Leaf code therefore already *could* consume the owner contract from the current
pin, but has not deleted the duplicate preflight path.

## What remains to remove (exact files)

### A. Runtime route probing (primary deletion target)

**File:** `scripts/ci/contextual_orchestrator_review_launcher.py`

Delete or stop calling the leaf readiness probe path:

- `_preflight_review_agents(...)`
- `_preflight_with_fallback(...)`
- Leaf constants that exist only to drive that probe:
  - `REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES` (24)
  - `REVIEW_PREFLIGHT_PRIMARY_ROUTE_LIMIT` (16)
  - `REVIEW_PREFLIGHT_TARGET_READY` (8)
  - `REVIEW_PREFLIGHT_MAX_PROBES` (16)
  - `REVIEW_PREFLIGHT_ACCOUNT_SKIP_AFTER_429`
  - `REVIEW_PREFLIGHT_BASE_TOKENS` / `REVIEW_PREFLIGHT_ESCALATED_TOKENS`
  - `REVIEW_PREFLIGHT_MAX_ESCALATIONS`
  - `REVIEW_PREFLIGHT_DEFERRABLE_HTTP_STATUS`
  - `REVIEW_PREFLIGHT_DEFERRED_PRIORITY_PENALTY`
- CLI / artifact flag `--preflight-out` and any code that fails closed on
  leaf `ready_count == 0` after probing

Today `main()` still does: build leaf catalog →
`ModelClient(max_output_tokens=REVIEW_MAX_OUTPUT_TOKENS)` →
`_preflight_with_fallback(...)` → `serve(...)`. Owner intent is: register
credentials → use owner admission (`build_review_orchestrator` /
`review_pool_admissions`) → serve → leaf sends only bearer +
`orchestrator/free`.

### B. Leaf generation budget (must not reappear)

**Same launcher file**, plus the shell sidecar:

| Location | Leaf budget still present |
| --- | --- |
| `scripts/ci/contextual_orchestrator_review_launcher.py` | `REVIEW_MAX_OUTPUT_TOKENS = 4096` passed into `ModelClient(max_output_tokens=...)` |
| `scripts/ci/contextual_orchestrator_review_sidecar.sh` | Gateway curl body hard-codes `"max_tokens":4096` for the chat/completions self-check |

Owner contract (#1124) already removed the hidden fixed client envelope on the
gateway side and exposes per-model published ceilings on
`ReviewModelAdmission`. Do not replace leaf probing with a new leaf
`max_tokens` / generation policy.

### C. Leaf catalog construction that duplicates admission

**File:** `scripts/ci/contextual_orchestrator_review_policy.py`

Still owns a second free-pool admission policy:

- `FREE_POOL_CREDENTIAL_NAMES` — today `{BYTEZ, NVIDIA_NIM, NVIDIA_NIM_SUB, OPENROUTER}` only
- Owner `REVIEW_FREE_POOL_CREDENTIAL_NAMES` also includes `OPENCODE_ZEN_API_KEY`
- `build_zdr_prioritized_catalog(...)` — tier / round-robin / account-cap /
  catalog-limit selection that decides the *served* set before the gateway sees it
- Defaults such as `DEFAULT_CATALOG_LIMIT` / `DEFAULT_ACCOUNT_CAP` and env
  `ORCHESTRATOR_CATALOG_LIMIT` / `ORCHESTRATOR_CATALOG_ACCOUNT_CAP` (wired from
  the sidecar shell)

**Keep vs delete nuance (ZDR):** private-target ZDR enforcement
(`--require-zdr`, `scripts/ci/zdr_policy.py`, OpenRouter ZDR feed) is still a
documented control-plane requirement in `.github` ADR-0003. Do **not** delete
ZDR attestation blindly. Either:

1. keep a thin leaf ZDR *filter* that only excludes non-attested routes for
   private targets **after** owner admission evidence is available, or
2. move private ZDR fail-closed into the gateway and pin a release that proves
   it, then delete the leaf filter.

What must go is leaf **probing, ranking-as-admission, credential-set drift, and
hard catalog caps** that re-decide eligibility the owner already decided.

### D. Sidecar shell coupling to leaf preflight

**File:** `scripts/ci/contextual_orchestrator_review_sidecar.sh`

Remaining leaf-preflight surface:

- Invokes the launcher with `--preflight-out`
- Treats missing runtime preflight evidence as boot failure
- Runs a separate gateway `chat/completions` curl loop
  (`REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS`, default 3) whose request body still
  carries the leaf `max_tokens:4096`
- Echoes a "runtime preflight summary" derived from the leaf probe report

After removal, the shell should:

1. vendor + hash-install the pin (unchanged),
2. bootstrap secrets into KV (unchanged),
3. start an owner-contract sidecar (prefer `review_gateway` path or a thin
   launcher that does not probe),
4. optionally keep a **liveness** loopback check that only proves the process
   answers with bearer auth (no per-route catalog probe, no leaf token budget),
5. write owner provenance (`contract_version`, admissions) into evidence
   artifacts instead of leaf `ready_count` / `probed_count` JSON.

### E. Workflows that call the sidecar (call sites, not logic owners)

These workflows invoke the sidecar script; they should keep calling it, but
must not reintroduce leaf model/provider selection after the script is
simplified:

| Workflow | Call site role |
| --- | --- |
| `.github/workflows/noema-review.yml` | Required Noema review sidecar |
| `.github/workflows/opencode-review-dispatch.yml` | Required OpenCode review sidecar |
| `.github/workflows/strix.yml` | Required Strix scan sidecar (`CONTEXTUAL_ORCHESTRATOR_POOL: free`) |
| `.github/workflows/pr-review-autofix.yml` | Autofix OpenCode sidecar |
| `.github/workflows/agent-review-runtime-quality-ci.yml` | Contract CI that materializes/exercises the sidecar scripts |

Shared client config already points at the free virtual model
(`opencode.jsonc`: `contextual-orchestrator/orchestrator/free`). Leave that
pin; do not add provider model ids back.

### F. Tests / ADRs that currently lock leaf preflight in

Rewrite or retire assertions that require leaf probing to exist:

| Artifact | Why it blocks deletion |
| --- | --- |
| `tests/test_contextual_orchestrator_review_runtime_preflight.py` (~2.8k lines) | Encodes `_preflight_review_agents`, lazy-fill, escalation, gateway curl attempt bounds |
| `tests/test_contextual_orchestrator_review_policy.py` | Encodes leaf catalog admission / ZDR ranking as the served set |
| `tests/test_contextual_orchestrator_review_sidecar_contract.py` | Sidecar boot + evidence contract around leaf preflight |
| `tests/test_orchestrator_free_sidecar_action_contract.py` | Action/workflow coupling to free-pool sidecar |
| `tests/test_strix_contextual_orchestrator_contract.py` / `scripts/ci/test_strix_quick_gate.sh` | Workflow text contracts for gateway model ids (keep model pins; drop any ready-count / leaf probe requirements) |
| `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md` | Still normative for twenty-four-candidate / sixteen-probe leaf stage budgets (ADR-0029 amendment) |
| `docs/adr/0029-sidecar-preflight-lazy-fill.md` | Defines the leaf lazy-fill probe algorithm to delete |
| `docs/adr/0005-sidecar-preflight-token-budget.md` | Already superseded historically; do not restore |

Replace with contracts that:

- pin `REVIEW_READINESS_CONTRACT_VERSION` from the vendored tree,
- assert the leaf no longer defines `_preflight_review_agents` /
  `REVIEW_PREFLIGHT_*` serving probes,
- assert `ModelClient` is not constructed with a leaf fixed
  `max_output_tokens`,
- assert workflows still request only `orchestrator/free`,
- assert private ZDR still fail-closes (wherever that ownership lands).

## Acceptance checks (`.github` PR)

Use this checklist on the exact consumer head after the leaf removal PR:

1. **Pin**
   - [ ] `ORCHESTRATOR_PIN_SHA` is a protected `contextual-orchestrator` `main`
     commit that includes both #1124 and #1195.
   - [ ] Sidecar still installs that tree with `--require-hashes` /
     `--no-deps` from `requirements.lock`.

2. **Deleted leaf preflight**
   - [ ] `rg '_preflight_review_agents|REVIEW_PREFLIGHT_TARGET_READY|REVIEW_PREFLIGHT_MAX_PROBES' scripts/ci/` returns no serving-path hits.
   - [ ] No launcher path constructs `ModelClient(max_output_tokens=<leaf constant>)`.
   - [ ] Sidecar gateway self-check (if retained) does not hard-code a leaf
     generation budget and does not probe individual provider routes.

3. **Owner contract consumption**
   - [ ] Boot evidence records `contract_version` equal to vendored
     `REVIEW_READINESS_CONTRACT_VERSION` (currently `"1"`).
   - [ ] Evidence lists owner admissions (model / provider / credential /
     published ceilings) rather than leaf `probed_count` / `ready_count`
     probe rows.
   - [ ] Leaf free-pool credential set does not silently drop
     `OPENCODE_ZEN_API_KEY` relative to owner
     `REVIEW_FREE_POOL_CREDENTIAL_NAMES` unless a dated ADR records a
     deliberate narrower leaf filter.

4. **Caller shape unchanged**
   - [ ] OpenCode / Noema / Strix / autofix still use only
     `contextual-orchestrator/orchestrator/free` (or the documented
     `orchestrator/free` Strix form) — no direct provider model ids.
   - [ ] Reviewer identity, mutation tokens, loopback binding, bearer-file
     masking, and GITHUB_TOKEN stripping remain unchanged.

5. **Regression suite**
   - [ ] Focused `.github` contract tests for the rewritten sidecar pass.
   - [ ] Full repository suite + ordinary review/security gates pass on the
     exact head (no bypass).

6. **Hosted proof (required before claiming done)**
   - [ ] At least one exact-head `noema-review` run boots the sidecar without
     leaf route probing and completes review traffic on `orchestrator/free`.
   - [ ] At least one exact-head `opencode-review` / dispatch path does the same.
   - [ ] At least one exact-head `strix` path does the same (including private
     ZDR fail-closed if the target is private).
   - [ ] Job logs/artifacts show owner contract provenance, not
     `runtime preflight summary` probe tallies.

## Explicit non-goals for the `.github` PR

- Do not re-implement gateway discovery, ranking, or failover in Actions.
- Do not weaken ZDR for private repositories.
- Do not switch GitHub Actions callers to `orchestrator/auto` to paper over
  an empty free pool.
- Do not edit `ContextualWisdomLab/contextual-orchestrator` in the same PR
  unless a true owner bug blocks consumption (file a gateway issue instead).
- Do not treat a green leaf unit suite alone as hosted proof.

## Recommended implementation order

1. Advance `ORCHESTRATOR_PIN_SHA` to a `main` SHA containing #1195; keep leaf
   preflight temporarily so pin advance is isolatable.
2. Switch launcher construction to owner `build_review_orchestrator` (or
   equivalent) while still writing admissions evidence; keep a temporary
   feature flag only if a single PR cannot land atomically.
3. Delete `_preflight_*`, leaf `REVIEW_PREFLIGHT_*`, and leaf
   `REVIEW_MAX_OUTPUT_TOKENS` client clamp in the same PR that rewrites the
   contract tests.
4. Amend ADR-0003 / supersede ADR-0029 to state readiness is owner-versioned
   (`REVIEW_READINESS_CONTRACT_VERSION`) and leaf probing is historical.
5. Run the hosted acceptance checks above; only then close the consumer half
   of #1106.

## Cross-team status message template

Copy/paste for issue comments, Slack, or PR descriptions:

```text
## #1106 consumer status — ContextualWisdomLab/.github

Gateway owner contract is on contextual-orchestrator main:
- #1124 REVIEW_READINESS_CONTRACT_VERSION=1 + ReviewModelAdmission provenance
- #1195 free-pool failover budget sized to admitted catalog

Current .github pin ORCHESTRATOR_PIN_SHA=767e67fbc6b881a452761f32abb69b9971b9b03b
already includes #1124; it does not yet include #1195.

Remaining leaf work (docs handoff):
docs path in contextual-orchestrator:
docs/doctoring/issue-1106-github-leaf-preflight-handoff.md

Delete consumer-side route probing / leaf generation budget / duplicate
admission catalog caps from:
- scripts/ci/contextual_orchestrator_review_launcher.py
- scripts/ci/contextual_orchestrator_review_sidecar.sh
- scripts/ci/contextual_orchestrator_review_policy.py (admission/caps only;
  ZDR private-target policy needs an explicit keep-or-migrate decision)
- contract tests under tests/test_contextual_orchestrator_review_*preflight*
- ADR-0003 / ADR-0029 normative leaf probe budgets

Workflows that only need the simplified sidecar (no logic rewrite expected
beyond env/evidence):
- .github/workflows/noema-review.yml
- .github/workflows/opencode-review-dispatch.yml
- .github/workflows/strix.yml
- .github/workflows/pr-review-autofix.yml

Acceptance: pin includes #1124+#1195; no REVIEW_PREFLIGHT_* serving probes;
no leaf ModelClient max_output_tokens clamp; owner contract_version in
evidence; orchestrator/free-only callers; hosted Noema+OpenCode+Strix
exact-head boots without leaf route probing.

Owner contact: contextual-orchestrator maintainers (this handoff).
Consumer owner: .github lead.
```

## References

- Gateway module: `contextual_orchestrator/review_gateway.py`
- Gateway contract tests: `tests/test_review_gateway_admission_contract_1106.py`
- Gateway Actions bootstrap proof (related, not a substitute for leaf
  deletion): `docs/doctoring/2026-09-04-actions-bootstrap-integration.md`
- Gateway hourly free-pool caller ADR:
  `docs/adr/0007-hourly-loop-orchestrator-free-pool-pin.md`
- `.github` sidecar ADR:
  `https://github.com/ContextualWisdomLab/.github/blob/main/docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`
- `.github` leaf lazy-fill ADR:
  `https://github.com/ContextualWisdomLab/.github/blob/main/docs/adr/0029-sidecar-preflight-lazy-fill.md`
