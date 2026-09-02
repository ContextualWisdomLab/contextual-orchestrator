# ADR 0007: Pin the hourly OpenCode maintenance loop to `orchestrator/free`

- Status: Accepted
- Date: 2026-09-02
- Decision owners: ContextualWisdomLab
- Series: `docs/adr` only. This is not a planning-ADR number.

## Context

`.github/workflows/opencode-hourly-loop.yml` runs an hourly, autonomous
OpenCode agent inside this repository's own CI: it works the open-PR queue
(review, fix, recheck, merge) and advances
`docs/product-technical-gap-baseline.md`, pushing commits with
`contents: write` permission. It has run since before this ADR pointing
OpenCode at the fixed virtual model id `contextual_orchestrator_gateway/orchestrator/auto`
(three occurrences: the `opencode.json` default `model`, the `models` catalog
entry, and the `opencode run --model` flag), asserted by
`tests/test_hourly_opencode_loop_contract.py`'s
`test_hourly_loop_uses_the_local_auto_orchestrator_without_copilot_token`.
`docs/product-technical-gap-baseline.md` (PR #843 entry) records this choice
as an established fact — "The hourly OpenCode loop uses `orchestrator/auto`"
— but neither that entry nor any ADR in this repository documents *why*
`auto` was chosen for this specific workflow, as opposed to `free`.

That absence of a documented reason matters because the rest of the
ContextualWisdomLab ecosystem has an explicit, opposite default for this
exact class of consumer. `ContextualWisdomLab/.github`'s
[ADR-0003](https://github.com/ContextualWisdomLab/.github/blob/main/docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md)
(this repository is the gateway that ADR governs the CI consumption of)
states plainly: "OpenCode and Noema admit only zero-priced routes." Only
Strix — running *security analysis*, not general review/fix work — has a
documented, evidence-tiered exception onto `orchestrator/auto`, and even
that exception required its own 2026-08-30 ADR amendment reversing Strix's
*original* `auto` default, specifically because an `auto`-routed CI
consumer can silently admit a priced, non-zero-cost route without any
code-level signal that it happened. `.github`'s own directly analogous
"autofix that pushes code" workflow, `pr-review-autofix.yml`, is pinned to
`orchestrator/free`, not `auto` — and that workflow does the same class of
work this repository's hourly loop does (review → fix → push), not
security analysis. Every other config-level or code-level reference to a
pool id across `.github`'s central workflows and naruon's own contextual-
orchestrator client (see naruon
[docs/adr/0005](https://github.com/ContextualWisdomLab/naruon/blob/develop/docs/adr/0005-kg-extraction-orchestrator-free-pool-pin.md))
resolves to `orchestrator/free` for this exact reason: an operator or a
future edit cannot silently regress a fixed constant the way a
still-configurable field could.

This repository's own hourly loop is therefore the one outlier in the
ecosystem with no documented justification, and the org's standing
operating directive (`ContextualWisdomLab/.github`
`docs/product-goal-directive.md`, item 10, clarified 2026-09-02: "Contextual-
Orchestrator의 모델은 GitHub Actions Workflow 이용에 관해 orchestrator/free
로 고정" — "contextual-orchestrator's model, for GitHub Actions Workflow
usage, is pinned to `orchestrator/free`") names this repository's own
GitHub Actions workflow usage specifically.

## Decision

1. `opencode-hourly-loop.yml`'s `loop` job now points OpenCode at
   `contextual_orchestrator_gateway/orchestrator/free` in all three places
   the model id appears (the default `model` field, the `models` catalog
   entry, and the `opencode run --model` CLI flag), matching every other
   OpenCode/Noema consumer in the ecosystem.
2. `--auto-discover-model-agents` on the gateway-startup step is unchanged.
   That flag controls the gateway's own provider/credential auto-discovery
   (which of the five configured API keys have usable models) — a separate
   concern from which pool id OpenCode itself requests once the gateway is
   up. Discovery stays broad; routing is pinned.
3. No evidence-tiered exception is claimed for this workflow. Unlike Strix
   (security analysis, ADR-0003's documented exception), this loop's job is
   general PR maintenance — the same class of work `pr-review-autofix.yml`
   already does on `orchestrator/free` in `.github`. If a future, evidence-
   backed need for `orchestrator/auto` capability emerges here (e.g., a
   demonstrated free-pool capability gap for the specific fix/merge tasks
   this loop performs), it needs its own ADR amendment with that evidence —
   not a silent revert.
4. `tests/test_hourly_opencode_loop_contract.py` is updated to assert the
   `free` pool id (three occurrences) instead of `auto`, and the test is
   renamed to `test_hourly_loop_uses_the_local_free_orchestrator_without_copilot_token`
   so its name states what it actually verifies.

## Consequences

### Positive

- The hourly loop's own CI traffic now gets the same zero-cost, ZDR-first
  routing guarantee every other OpenCode-family consumer in the ecosystem
  already has, closing the one undocumented outlier `docs/product-
  technical-gap-baseline.md`'s PR #843 entry recorded without explaining.
- Consistent with naruon's own contextual-orchestrator client fix
  (naruon ADR-0005, same session): both close the same class of gap
  (an orchestrator-routed consumer not actually requesting the governed
  free pool) independently discovered in two different repositories.

### Negative

- If the free pool's zero-cost catalog is empty when the hourly loop runs
  (no admitted zero-cost route available), the gateway itself fails closed
  (`400 invalid_model`, per `.github` ADR-0003 §2) rather than silently
  falling back to a paid route through `auto`. That is the intended
  fail-closed behavior, not a regression, but it does mean an hourly run
  can now fail for a reason it previously would not have (an exhausted
  free catalog) — operators should treat a `400 invalid_model` failure on
  this workflow as free-catalog exhaustion, not a code defect, and check
  `docs/product-technical-gap-baseline.md`'s discovery evidence before
  assuming otherwise.
- `docs/product-technical-gap-baseline.md`'s PR #843 entry ("The hourly
  OpenCode loop uses `orchestrator/auto`") is now a historical record of
  the pre-this-ADR state, not current behavior; it is not rewritten (this
  repository's convention treats that file as an append-only snapshot log,
  per its own header), but this ADR is the current source of truth for the
  hourly loop's pool choice going forward.

## References

ContextualWisdomLab. (2026). *ADR-0003: Vendored contextual-orchestrator
review sidecar with governed gateway pools* [ADR, amended 2026-08-30].
`ContextualWisdomLab/.github` `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`.
https://github.com/ContextualWisdomLab/.github/blob/main/docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md

ContextualWisdomLab. (2026). *ADR-0005: Pin orchestrator-routed KG
extraction to the `orchestrator/free` pool* [ADR].
`ContextualWisdomLab/naruon` `docs/adr/0005-kg-extraction-orchestrator-free-pool-pin.md`.
https://github.com/ContextualWisdomLab/naruon/blob/develop/docs/adr/0005-kg-extraction-orchestrator-free-pool-pin.md
Companion decision, found and fixed in the same session: naruon's own
contextual-orchestrator client had the analogous gap (a request that
should have named a fixed pool id instead carried an unrelated
direct-provider model setting).
