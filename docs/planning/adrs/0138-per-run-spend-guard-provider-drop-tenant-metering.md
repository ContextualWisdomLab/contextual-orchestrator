---
id: "0138"
title: "Per-run spend guard, provider-limit drop, and tenant metering"
status: proposed
proposed_date: "2026-09-26"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/domain/money.py"
  - "contextual_orchestrator/domain/budget.py"
  - "contextual_orchestrator/domain/pricing.py"
  - "contextual_orchestrator/domain/provider_limits.py"
  - "contextual_orchestrator/domain/tenancy.py"
  - "contextual_orchestrator/spend_guard.py"
  - "contextual_orchestrator/spend_metering.py"
  - "contextual_orchestrator/provider_errors.py"
  - "contextual_orchestrator/orchestrator.py"
  - "contextual_orchestrator/__main__.py"
related:
  - path: "docs/planning/adrs/0032-model-group-cost-aware-discovery.md"
    relation: extends
  - path: "docs/planning/adrs/0041-generalize-models-dev-cost-classification.md"
    relation: depends-on
---

# Per-run spend guard, provider-limit drop, and tenant metering

## Context

ADR 0032 (still Proposed) makes discovery cost-aware: a model is admitted to
routing only with exact-zero price evidence or an explicit paid opt-in, and the
bootstrap `--enable-cheapest` path picks the cheapest paid row at pool level.
ADR 0041 generalizes the free/paid cost classification. Neither bounds what a
single run may spend once paid models are admitted, and neither says what to do
when a provider-side spend limit trips mid-run.

The DDD audit of `main` at `5665b0ad` (section 7) found:

- The existing budget (`budget_max_cost_usd`, `_raise_if_spend_budget_exceeded`)
  is process-wide and cumulative, not per run, and `route_once` never consults it.
- There are two price sources. `price_per_million` is output-only and the CLI
  never passes it. `cost_ledger.PriceBook` is correct (prompt + completion per
  1K, currency) but is not wired into routing.
- Metering should build on `cost_ledger.UsageRecord` / `CostLedger`, not a new
  record type.

There is also no enforced tenant on `TaskOrchestrator` runs (see "Tenant
identity" below).

Discovery is not a spend control. The OpenRouter paid-inference probe (PR
#1263, `GET /api/v1/key` `limit_remaining`) admits every paid model while the
key has any headroom, and `limit_remaining` is the key's cap, not the account
balance. Per-run and per-tenant limits are therefore enforced at call time by
this guard, never by discovery.

## Decision

### 1. Three spend limits, one rule: the tightest wins

| Limit | Where it lives | Default | Resets |
|---|---|---|---|
| Run cap (`run_max_cost`) | in memory, one `RunSpendScope` per entry-point call | **none** (no per-run cap until an operator sets one) | never; it is per run |
| Virtual key budget (`max_budget`, `soft_budget`, `budget_duration`) | `SpendLedgerStore` | none | every `budget_duration` (`s`/`m`/`h`/`d`) from key creation |
| Tenant budget (same fields) | `SpendLedgerStore` | none | same |

Before every provider chat call (including `route_once`, streaming, and the
sampled baseline) the guard computes a conservative total-cost upper bound
from the single PriceBook-backed catalogue and the selected route's configured
total-token ceiling. Because input/output splits are unknown, every token is
priced at the more expensive of the prompt and completion rates. Unknown or
conflicting total-token ceilings fail closed under a hard cap; a prompt-only
lower bound is never admission authority. `decide_affordability` evaluates the
upper bound over every active limit. Admission and in-flight reservation occur
under one run-scope lock, so concurrent branches cannot spend the same
remaining headroom. A call is refused, before it is sent, when for any limit:

- the limit is already spent (`budget_exhausted`);
- the price is unknown for a billable endpoint (`price_unknown`, fail closed);
- a priced route lacks an authoritative total-token ceiling
  (`cost_upper_bound_unavailable`, fail closed);
- an earlier paid call in this run finished without measurable cost
  (`measurement_unavailable`, fail closed; free and local calls still run);
- the reserved total-cost upper bound would cross the cap
  (`insufficient_remaining_budget`);
- it is a paid sampled baseline under a hard cap without a separate versioned
  allocation authority (`baseline_allocation_unavailable`, fail closed).

An unmeasured provider outcome consumes its in-flight upper-bound reservation
for budget admission and marks measurement incomplete. The ledger still stores
the charged cost as unknown; the reservation is not mislabeled as an actual
provider charge.

When several limits refuse, the one with the least remaining budget is reported;
ties go run, then virtual key, then tenant. Soft budgets log a warning once per
run and never block. A refusal raises the existing `BudgetExceededError`, which
the server already maps to `429 budget_exceeded`.

Configuration: CLI `--run-max-cost-usd` or the KV category
`spend_guard_settings` (`run_max_cost_usd`) via
`SpendGuardConfig.from_config_store`. There is no numeric baseline threshold.

The existing process-wide budget is extended, not duplicated:
`_raise_if_spend_budget_exceeded` now also consults the active run scope.

### 2. Sampled baselines are charged to the same guard and skipped first

`compare_to_baseline` runs each baseline inside `CallPurpose.BASELINE`. The
baseline is skipped (not failed) when the scope says it is not admissible or
when its call is refused. Skipped rows are reported as
`{"skipped": true, "reason": "spend_budget"}`, averages use only compared rows,
and `aggregate.baseline_skipped_count` counts the skips. Primary work keeps the
remaining budget. Under a hard cap, a paid baseline requires a future explicit,
versioned allocation authority; absent that authority it fails closed. A
zero-cost baseline or a baseline with no active hard cap can still run.

### 3. Provider-limit exhaustion drops only that provider for the rest of the run

`domain/provider_limits.classify_provider_limit` is a pure rule over the
provider id, the HTTP status, and bounded identifier fields from the error body
(never free-text messages). It applies to status errors and to error objects
inside an HTTP 200 stream, where the numeric `error.code` stands in for the
status.

| Provider | Drop when | Not a drop | Source |
|---|---|---|---|
| OpenRouter | 402 with `error.metadata.limit_source` = `openrouter_key_limit` / `openrouter_credits`, or any other 402 | 402 `openrouter_in_flight_budget` (transient); 429 | https://openrouter.ai/docs/api/reference/limits |
| OpenAI | 429 with `error.code` or `error.type` in `project_spend_limit_exceeded`, `organization_spend_limit_exceeded`, `credit_balance_exhausted`, `insufficient_quota` | 429 `rate_limit_exceeded` | https://developers.openai.com/api/docs/guides/spend-limits ; https://developers.openai.com/api/docs/guides/error-codes |
| OpenCode Zen | 401 with `error.type` `CreditsError` / `MonthlyLimitError` / `UserLimitError`; 402 | 401 `AuthError` (bad key) | https://opencode.ai/docs/zen/ ; vendor source `anomalyco/opencode@696f41bc` `packages/console/app/src/routes/zen/util/handler.ts` |
| OpenCode Go | 429 `GoUsageLimitError`; the Zen balance types above | other 429s | https://opencode.ai/docs/go/ ; same vendor source |
| Bytez | 402 | 429 | https://docs.bytez.com/model-api/docs/billing |
| Experiential Labs | 429 `insufficient_quota`; 402 | other 429s | https://platform.experientiallabs.ai/llms.txt |
| any other provider | 402 | everything else | RFC 9110 section 15.5.3 |

An OpenRouter account at zero balance returns 402 `openrouter_credits` even
when the key still has `limit_remaining`; it is a drop of OpenRouter only, like
the key-limit 402. Only `openrouter_in_flight_budget` stays temporary (it
clears as concurrent requests finish, with `Retry-After`).

A limit error that arrived as a pre-response HTTP 402 is metered as
`zero_cost` (the provider refused before inference and does not bill it); a
limit error inside a stream may follow billed output and stays `unknown`.

`insufficient_quota` is added for OpenAI beyond the three spend-limit codes
because OpenAI documents it as the quota/billing exhaustion error. The Zen and
Go error types come from vendor source, not published docs.

On a drop the guard records the provider in the run scope,
`_failover_candidates` filters that provider out while others remain, and the
failed call is re-raised as a non-retryable `ProviderBudgetExhaustedError`.
Its `provider_status` is cleared (the upstream status is kept as
`limit_provider_status` evidence) so failover never books a rate-limit cooldown
or storm-waits on a provider that cannot recover within the run. When every
candidate's provider is dropped the list is left intact and each call raises
the typed error, so the run fails closed with an honest cause. Transient and
plain rate-limit errors keep their existing handling.

### 4. Tenant identity

Existing concepts, none of which enforce a tenant on runs today:

- `server.SecurityConfig.principal_id()` / `principal_resolver` is a hashed,
  tenant-scoped principal seam at the HTTP boundary.
- `request_partitioning.RequestScope.tenant_id` is a trusted admission identity
  in a standalone module.
- `metering.CanonicalUsageRecordSink` uses `tenant_reference` as its canonical
  identity field.
- `cost_ledger.AttributionDimensions` (`account`, `service`, `team`, `group`,
  `company`) are client-declared descriptive labels, validated by
  `server._validate_attribution`. They must never set the tenant.

Decision: tenant precedence is **virtual key → explicit trusted tenant from the
embedding application → `"default"`**. The CLI passes `--tenant-id` (for
example the calling GitHub repository) or a virtual key read from the KV via
`--virtual-key-credential`. A key asserted together with a different tenant is
rejected. Mapping the server principal to a tenant is deferred.

### 5. Virtual keys (LiteLLM-style, lean)

| LiteLLM | This ADR |
|---|---|
| per-key `max_budget`, `soft_budget`, `budget_duration`, `budget_reset_at` | same fields; `budget_reset_at` in refusal detail and the run summary |
| keys attached to a team enforce the team budget | keys belong to a tenant; the tenant budget applies to all its keys |
| key stored hashed | only `sha256:` digests persist; the `sk-co-` secret is returned once by `issue_virtual_key` |
| exceeded: HTTP 400, `type` `budget_exceeded` / `auth_error` | `BudgetExceededError` with a `Budget has been exceeded! ... Current cost: X, Max budget: Y` message; the existing server mapping returns **429** `budget_exceeded` |
| admin UI and `/key/*` endpoints | out of scope |

Sources: https://docs.litellm.ai/docs/proxy/users ;
https://docs.litellm.ai/docs/proxy/virtual_keys ;
https://docs.litellm.ai/docs/proxy/team_budgets

### 6. Metering and storage

- **Records.** Each provider call yields one `MeteredUsage`: a
  `cost_ledger.UsageRecord` (provider, model, prompt/completion tokens,
  measurement status, timestamp, run id) plus tenant, virtual key id, call
  status (`ok` / `error` / `provider_limit`), purpose, charged cost and cost
  source.
- **Cost source precedence.** provider-reported `usage.cost` (not BYOK) >
  zero-cost (local endpoint, or `cost:free` evidence) > PriceBook × measured
  usage > `unknown`. An unknown cost is stored as `null` with
  `price_unknown: true` and never as an invented price.
- **Stores.** Both sit behind the `SpendLedgerStore` port:
  - `InMemorySpendLedgerStore`.
  - `JsonlSpendLedgerStore`, a durable append-only adapter. It fsyncs each
    write and replays the file at startup. A torn final line moves to
    `<name>.partial`; corruption anywhere else raises. It assumes a single
    writer.

  Key and tenant definitions share the same store.
- **Aggregation.** `aggregate_usage` groups by tenant, tenant + provider/model,
  virtual key, run or status over a `[start, end)` window. It reports unpriced
  and unmeasured calls so a total is never presented as complete when it is
  not.
- **Run artifact.** `contextual_orchestrator.run_usage_summary.v1` holds totals,
  per provider/model rows, every call, the limits with their spend, refusals and
  dropped providers. The CLI writes it with `--run-usage-summary`.

### 7. Placement

The new logic lives in new modules (`domain/*`, `spend_guard.py`,
`spend_metering.py`). `orchestrator.py` only gets thin hooks:

- `ModelClient.chat`, `stream_chat` and the passthrough senders delegate to
  guarded wrappers around the renamed transports.
- Entry points are decorated with `@with_run_scope`.
- `_failover_candidates` has one filter line.
- A handful of failover loops re-raise `BudgetExceededError`.
- `_raise_if_spend_budget_exceeded` consults the scope.
- `compare_to_baseline` gains the skip logic.

`docs/code_conventions.md:34` ("Domain code stays in `orchestrator.py` until a
second implementation forces extraction") is being superseded by
`docs/adr/0124-incremental-domain-extraction.md` in PR #1262. That ADR's staged
plan names budget/eval as step 5. This ADR follows its direction early for new
code only and does not edit `code_conventions.md`, to avoid conflicting with
that PR.

## Consequences

- The default behaviour is unchanged: no run cap, no key or tenant budgets.
  Every run is still metered in memory, and mock or local calls are zero-cost.
- With a cap set, an endpoint without a PriceBook row (for example Bytez today)
  is refused. Operators must price it or tag it `cost:free` from evidence. This
  is deliberate fail-closed behaviour.
- Admission is check-then-call. Concurrent calls in one run (endpoint races,
  batch fallback) can each pass the check and together overshoot by up to one
  call's cost per concurrent branch.
- Streaming calls often report no usage (`stream_usage_supported`). Under a cap,
  a paid streamed call without usage blocks further paid calls in that run.
- Key and tenant spend are computed by scanning the store on each admission.
  That is O(entries). A windowed index is deferred.

## Deferred

- Server wiring: principal → tenant, virtual key header, HTTP key management,
  admin UI.
- A key-management CLI.
- Per-request cheapest-paid-first ranking (audit Gap 5). ADR 0032 bootstrap
  `--enable-cheapest` stays the pool-level mechanism.
- Removing `price_per_million`.
- Metering for embedding and Batch API calls.
- Limit errors inside non-stream HTTP 200 bodies.
- Atomic admission under concurrency.
- Multi-writer JSONL or a SQL adapter.
- Uploading the run artifact from workflows.
- `ModelClient`'s internal 429 retries on paths outside `_invoke` may retry once
  before the drop is observed.

## References

- ADR 0032, ADR 0041; `docs/adr/0124-incremental-domain-extraction.md` (PR #1262).
- RFC 9110, HTTP Semantics, section 15.5.3 (402 Payment Required): https://doi.org/10.17487/RFC9110
- LiteLLM proxy budgets: https://docs.litellm.ai/docs/proxy/users ; https://docs.litellm.ai/docs/proxy/virtual_keys ; https://docs.litellm.ai/docs/proxy/team_budgets
- Provider limit documentation as listed in the table in section 3.
