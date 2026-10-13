# ADR 0124: Incremental domain extraction out of `orchestrator.py`

- Status: Proposed
- Date: 2026-09-26
- Decision owners: ContextualWisdomLab
- Series: `docs/adr` only. This is not planning ADR 0124
  (`docs/planning/adrs/0124-public-healthz-minimal-liveness.md`).
- Supersedes: the module rule "Domain code stays in
  `contextual_orchestrator/orchestrator.py` until a second implementation
  forces extraction" (`docs/code_conventions.md`, Module Rules, first bullet;
  restated in `CLAUDE.md`).
- Amends: the module-location clause of planning ADR 0126
  (`docs/planning/adrs/0126-rater-contract-module-exception.md`), which made
  `orchestrator.py` "the sole owner of planning, agent selection, provider
  routing, provider calls, retry/fallback, workflow composition, and execution
  trace assembly". The Anti-Corruption Layer import restrictions of ADR 0126
  stay in force.

## Context

The product's core purpose is combining several LLMs to raise output quality.
The docs describe that domain in explicit terms: route vs conduct,
thinker/worker/verifier/synthesizer roles, workflow steps with access lists,
verification, and synthesis (`docs/architecture.md:30-47`,
`conductor/product.md:22-27`, ADR 0002). `conductor/workflow.md` and
`conductor/tech-stack.md` call the method DDD. The code, however, does not
model that domain separately from infrastructure. Figures below are from
`main` at `5665b0ad` (2026-09-19):

- `orchestrator.py` is 19,867 lines. `TaskOrchestrator` alone is 13,842 lines
  with 194 methods (`orchestrator.py:5469-19310`).
- The same file contains the provider HTTP client (`ModelClient`,
  `:2310-4247`), two SQLite stores (`_AgentPoolStore` `:4292-4946`,
  `_StateStore` `:4949-5430`), and imports `http.client`, `socket`, `ssl`,
  `sqlite3`, and `urllib.request` (`:17-38`).
- About 6,000 lines of `TaskOrchestrator` were commercial, sales, and buyer
  readiness report generators (`:12959-19032`, `:19124-19310`). They are
  read-only reporting over runtime state, not orchestration domain.
- Roles are string literals repeated across the class (for example `:1110`,
  `:5484-5491`, `:9777`, `:9815-9818`). Runs, traces, and verdicts are
  `dict[str, Any]`, and there are no `Enum` or `Protocol` types in the module.
- Combining several models' outputs has no domain type. It is a synthesizer
  prompt over concatenated step outputs (`:9488-9505`, `:6721-6727`),
  sequential failover on judge rejection (`:9171-9241`), or a fallback to one
  worker's output (`:9584-9598`).
- Because `contextual_orchestrator/__init__.py` imports `orchestrator`,
  importing even pure leaf modules such as `model_group` loads SQLite and HTTP
  code.

The "stay in `orchestrator.py` until a second implementation forces
extraction" rule was a reasonable guard against speculative frameworks. It now
blocks the work the product needs. Adding a combination strategy, a per-run
budget, or an evaluation arm means editing a 13.8k-line class whose methods
mix domain decisions with provider calls and persistence, and whose domain
rules can only be tested through the full object with fake clients.

## Decision

Extract the domain in small, behaviour-preserving steps. Each step is one or
more PRs that first move code mechanically, keeping delegating methods and
re-exports so existing callers and tests do not change. Behaviour changes land
in separate PRs after the move. The order follows how much each step unblocks
multi-model combination:

1. **Reporting.** Move the commercial/sales/buyer report generators to
   `contextual_orchestrator/reporting/commercial_reports.py` as functions that
   take the orchestrator as their first argument. `TaskOrchestrator` keeps
   delegating methods with identical signatures, and its per-request report
   cache (`_cached_commercial_report`) keeps wrapping those methods.
   `reporting` must not import `orchestrator` at module import time.
   *Implemented together with this ADR.*
2. **Ports and adapters.**
   - Add `ports.py` with `Protocol`s for what `TaskOrchestrator` actually
     calls: chat completion, workflow-run repository, agent-pool repository,
     evidence store.
   - Move `ModelClient` and the provider helpers to
     `adapters/provider_http.py`, and the SQLite stores to
     `adapters/sqlite_state.py`.
   - Move `ModelAgent`, `WorkflowStep`, and `OrchestrationPolicy` to
     `domain/`, so catalog, discovery, and evaluation modules stop importing
     `orchestrator.py`.
   - Make the package `__init__` lazy, and add an import-boundary test that
     forbids `contextual_orchestrator.domain` from importing adapters,
     `server`, `sqlite3`, `urllib`, `http`, `socket`, `ssl`, or `psycopg`.
   - The fake clients already used by the test suite count as the second
     implementation that `conductor/workflow.md` requires before adding an
     interface. That PR updates `conductor/workflow.md` and
     `conductor/tech-stack.md` accordingly.
3. **Workflow aggregate.**
   - `domain/roles.py` (`Role` string enum).
   - `domain/workflow.py`: a `WorkflowPlan` that owns plan invariants
     (sequential ids, access only to earlier steps, final producing step,
     step bound), a pure access-list context builder, and `WorkflowRun` /
     `StepResult` types whose `as_record()` produces today's dictionaries.
   - `domain/verification.py`: a `Verdict` value object and
     `VerificationPolicy`, plus a `Judge` port whose fast-mlsirm adapter moves
     to `adapters/`.
4. **Combination domain.**
   - `domain/candidates.py` (`CandidateAnswer`, `CandidateSet`,
     `CombinationOutcome`).
   - `domain/combination.py` with a `CombinationStrategy` protocol. The
     current route and conduct semantics are extracted first, unchanged, as
     strategies. New strategies follow, such as voting, judge-selected
     best-of-n, and pairwise comparison.
   - LLM synthesis becomes an application-level strategy.
   - A parallel fan-out step kind comes last.
5. **Budget and evaluation.**
   - `domain/money.py`, `domain/budget.py` (a per-run budget that stops the
     run), and a cost-preference rule inside a pure `domain/selection.py`
     ranking, all fed by one price source (the existing
     `cost_ledger.PriceBook`).
   - `domain/evaluation.py` and `application/evaluation_service.py`, which run
     combined workflows, single-model, best-single-in-hindsight, and
     mixture-of-agents arms through the same combination path, with
     per-sample usage and cost.

Rules from now on:

- New domain logic goes to `contextual_orchestrator/domain/` (standard library
  only, no IO imports), not into `orchestrator.py`.
- `TaskOrchestrator` is the application facade. It may keep delegating
  methods for compatibility until callers migrate; delegators are removed only
  in a later PR that updates the callers.
- An extracted module must not import `orchestrator` at module import time.
  Use a type-checking-only import for annotations, and a function-local
  import for any remaining runtime helper until that helper moves as well.
- A move PR states that it is mechanical, shows evidence that behaviour is
  preserved (AST comparison of the moved functions and before/after test
  counts on the same test set), and contains no behaviour changes.

## Consequences

- Step 1 removes 5,638 lines from `TaskOrchestrator` (13,842 to 8,204) and
  5,637 lines from `orchestrator.py` (19,867 to 14,230) without changing any
  public or private method signature.
- Each extracted module needs its own module and public-function docstrings
  (`tests/test_docstring_coverage.py`).
- Moved code that located repository files relative to `orchestrator.py`
  (`Path(__file__).resolve().parents[1]`) resolves the same repository root
  from its new depth (`parents[2]`). This is the only non-rename edit in
  step 1.
- Until step 2 makes the package `__init__` lazy, importing
  `contextual_orchestrator.reporting` still loads `orchestrator` through the
  package facade, even though the reporting module does not import it
  directly.
- Delegating methods temporarily duplicate each signature. Keeping them avoids
  a flag-day change for the HTTP handlers, CLI, tests, and downstream callers.

## References

Cockburn, A. (2005). *Hexagonal architecture*.
https://alistair.cockburn.us/hexagonal-architecture/

Evans, E. (2003). *Domain-driven design: Tackling complexity in the heart of
software*. Addison-Wesley.

Fowler, M. (2014). *Bounded context*. martinfowler.com.
https://martinfowler.com/bliki/BoundedContext.html

Fowler, M. (2024, August 22). *Strangler fig application*. martinfowler.com.
https://martinfowler.com/bliki/StranglerFigApplication.html
