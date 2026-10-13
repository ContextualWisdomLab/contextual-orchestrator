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
| Run cap (`run_max_cost`) | in memory, one `RunSpendScope` per **outermost** scope (see below) | **none** (no per-run cap until an operator sets one) | never; it is per run |
| Virtual key budget (`max_budget`, `soft_budget`, `budget_duration`) | `SpendLedgerStore` | none | every `budget_duration` (`s`/`m`/`h`/`d`) from key creation |
| Tenant budget (same fields) | `SpendLedgerStore` | none | same |

**"Per run" means the outermost scope.** A decorated entry point
(`complete`, `run`, `route_once`, `conduct`, `stream_route`,
`proxy_completion`, `compare_to_baseline`, `batch_route`, `proxy_capability`)
opens a run scope only when none is active. A nested decorated call, a nested
`SpendGuard.run_scope()`, and the implicit single-call scope below all *join*
the active scope: same run id, same cap, same ledger. A caller that wants one
cap across a whole session (for example a paid routing test run with many
`route_once` or `batch_route` rows) wraps it in one
`with orchestrator.spend_guard.run_scope(): ...`; without that wrapper each
top-level call gets its own fresh run cap. `run_evaluation` is deliberately
not decorated, so each prompt's `run` keeps its own cap unless the caller
wraps the evaluation. The virtual-key and tenant budgets are the cross-run
limits; the run cap is never a substitute for them.

**No scope never means no guard.** A paid send reached with no active run
(a direct `ModelClient` call, a readiness `probe`, a library caller) runs in
an *implicit* single-call scope of the client's `SpendGuard`
(`ModelClient.spend_guard`, attached by `TaskOrchestrator`): the configured
run cap, key and tenant budgets, the reservation and the metering all apply.
Implicit scopes are counted (`SpendGuard.implicit_scope_count`) and their last
summary is kept separately (`last_implicit_run_summary()`, `budget.implicit_scope:
true`) so they never overwrite the last real run summary. Only a `ModelClient`
with no guard attached at all (constructed outside a `TaskOrchestrator`)
passes through unmetered.

Before every paid provider send the guard computes a conservative total-cost
upper bound from the single PriceBook-backed catalogue. That covers chat,
streamed chat, passthrough (`proxy_send`, `proxy_send_once`,
`probe_structured_chat`, the fast-mlsirm judge), binary passthrough
(`proxy_send_bytes`), embeddings, one Batch API submission, the readiness
`probe`, and the sampled baseline:

- **Narrow bound (preferred).** When the request carries an exact,
  provenance-bound prompt token count (`describe_message_count`, never a lower
  bound) and the final `max_tokens` the transport sends, the bound is
  `prompt_tokens x prompt price + max_output_tokens x completion price`
  (`estimate_request_cost`, `AdmissionTokenBounds`). For chat the output cap
  is the effort profile's `max_output_tokens` when a profile applies (it
  overwrites `max_tokens`), otherwise `ModelClient.effective_max_output_tokens`.
  The transport then calls `enforce_admitted_output_cap` after every payload
  rewrite and immediately before egress: a missing `max_tokens` is set to the
  admitted value and a larger one is lowered to it, recorded in the run
  summary (`budget.output_cap_clamps`) and logged. The provider therefore
  cannot bill more output than the bound assumed. The bound is additionally
  capped by the context-window ceiling when that is lower
  (`estimate_source`: `prompt_and_max_output` or `context_window_ceiling`).
- **Passthrough bodies.** `passthrough_token_bounds` derives the bound from
  the caller's request body: the output cap is the largest of `max_tokens`,
  `max_completion_tokens` and `max_output_tokens`, times `n`; the prompt count
  is exact only for a chat `messages` body whose other keys are all in a
  conservative prompt-neutral whitelist (`model`, `messages`, `tools`,
  sampling knobs, `n`, `stream`, ...). Any other key (`response_format`,
  `reasoning`, `plugins`, `web_search_options`, `prediction`, `audio`, ...)
  makes the prompt count non-authoritative, so the ceiling applies. An
  embeddings `input` list counts one call per input for the ceiling. One
  Batch API submission is admitted as one call whose bound sums every row
  (`calls` = number of rows), priced at the full synchronous rate: the Batch
  API discount is not assumed.
- **Ceiling fallback.** Only when either value is unknown, the selected
  route's total-token ceiling (`context_window`) is priced with every token at
  the more expensive of the prompt and completion rates, because the
  input/output split is unknown.
- **Fail closed.** With neither, a priced route is refused
  (`missing_context_window`). A prompt-only lower bound is never admission
  authority, and a failing counter degrades to the fallback, never to
  admission.

The refusal detail records `estimate_source`, `prompt_tokens_bound` and
`max_output_tokens_bound` next to the reason. `decide_affordability` evaluates the
upper bound over every active limit. Admission and in-flight reservation occur
under one store budget transaction. The in-memory adapter serializes every run
scope that can access it. The JSONL adapter takes a POSIX file lock, refreshes
its projection, and appends a durable reservation before releasing that lock,
so separate run scopes and processes cannot spend the same remaining
headroom. A call is refused, before it is sent, when for any limit:

- the limit is already spent (`budget_exhausted`);
- the price is unknown for a billable endpoint (`price_unknown`, fail closed);
- the price and active hard limit use different currencies and no exchange-rate
  evidence exists (`price_currency_mismatch`, fail closed);
- a priced route has neither request token bounds nor an authoritative
  total-token ceiling, i.e. a positive `agent.context_window`
  (`missing_context_window`, fail closed). The refusal
  is recorded with its reason, agent id, model and `context_window` in the
  run usage summary (`budget.refusals`) and in the `BudgetExceededError`
  detail. Free and evidence-backed zero-cost routes need no ceiling and still
  run under the same hard cap;
- an earlier paid call in the run, virtual-key, or tenant scope finished
  without measurable cost (`measurement_unavailable`, fail closed; free and
  local calls still run);
- the reserved total-cost upper bound would cross the cap
  (`insufficient_remaining_budget`);
- it is a paid sampled baseline and, after the call priced at its total-cost
  upper bound, less than `baseline_min_remaining_ratio` (default `0.5`) of
  that hard cap would remain (`baseline_headroom_exhausted`). Every
  applicable hard cap (run, virtual key, tenant) must keep that share.
  Zero-cost baselines are not subject to the ratio.

**An unmeasured call is never free.** Every call whose outcome has no
measurable cost (timeout, dropped connection, provider 5xx, a success without
usage) counts at its admission bound, in capped and uncapped runs alike, on
every channel including passthrough, and marks measurement incomplete. In a
capped scope that is the in-flight reservation; in an uncapped run it is the
computed bound. The ledger still stores the charged cost as unknown; the bound
is not mislabeled as an actual provider charge. The unknown usage entry
records the reservation id, the provider error class (`error_type`) and HTTP
status (`provider_status`).

The one exception is a failure that provably happened before provider
egress. Real transports call `declare_pre_egress()` first and
`mark_provider_egress()` immediately before the request is handed to the
network (the retrying sender or the provider opener). A failure raised in
between (missing credential `NotConfigured`, local validation, a refused
destination, a local shared-context `ProviderRequestTooLargeError`) sent
nothing and is metered as `zero_cost`. A transport that does not declare
egress (a fake, a patched sender) stays unknown and counts at its bound.

When a provider reports a charge larger than the admission bound (for
example a fee outside prompt/completion pricing), the actual charge counts,
and the overrun is recorded in `budget.admission_bound_overruns` with the
channel and logged.

A `measurement_unavailable` refusal surfaces the original provider failure,
not only the budget symptom: the refusal detail lists `unmeasured_calls`
(in-run failures with a truncated error message; calls from other runs or
processes with their ledgered error class, status and reservation id), the
`BudgetExceededError` message names the error, and within the same run the
refusal is chained (`__cause__`) to the provider exception.

When several limits refuse, the one with the least remaining budget is reported;
ties go run, then virtual key, then tenant. Soft budgets log a warning once per
run and never block. A refusal raises the existing `BudgetExceededError`, which
the server already maps to `429 budget_exceeded`.

Configuration: CLI `--run-max-cost-usd` and `--baseline-min-remaining-ratio`,
or the KV category `spend_guard_settings` (`run_max_cost_usd`,
`baseline_min_remaining_ratio`) via `SpendGuardConfig.from_config_store`. The
baseline ratio is an explicit owner decision (default `0.5`, range `[0, 1]`),
not an inferred value; the run usage summary reports the ratio in force.

The existing process-wide budget is extended, not duplicated:
`_raise_if_spend_budget_exceeded` now also consults the active run scope.

### 2. Sampled baselines are charged to the same guard and skipped first

`compare_to_baseline` runs each baseline inside `CallPurpose.BASELINE`. The
baseline is skipped (not failed) when the scope says it is not admissible or
when its call is refused. Skipped rows are reported as
`{"skipped": true, "reason": <refusal reason>}` (for the headroom rule,
`baseline_headroom_exhausted`; other refusals keep their own spend-guard
reason, `spend_budget` only when none is available), averages use only compared rows,
and `aggregate.baseline_skipped_count` counts the skips. Primary work keeps the
remaining budget. Under a hard cap, a paid baseline runs only while at least
`baseline_min_remaining_ratio` (default `0.5`) of every applicable cap (run,
virtual key, tenant) would remain after the call, priced at its total-cost
upper bound. Otherwise it is skipped, and the refusal is recorded in the run
usage summary with reason `baseline_headroom_exhausted` and purpose
`baseline`. A zero-cost baseline or a baseline with no active hard cap always
runs. Ensemble-vs-single-model comparisons are an owner requirement, so a
capped run keeps comparing while it has headroom instead of dropping every
paid baseline; a skipped comparison is never silent.

*Revision 2026-09-27.* Review commits `d2aae636`..`c76e6cfe` had replaced
this rule with "paid baselines under a hard cap need a future allocation
authority", which skipped every paid baseline in every capped run. The owner
restored the original ratio rule; the total-cost upper-bound admission and
zero-cost baseline admission from those commits are kept.

### 2a. Unknown-outcome reservations never lock a budget forever

An unknown provider outcome (a 5xx, timeout or crash after the request may
have been billed) keeps its reservation and marks the scope's measurement
incomplete. That is correct fail-closed behaviour, but it must end:

- **Windowed budgets (`budget_duration` set).** Reservations and unknown
  usage entries count only in the budget window in which they were made
  (`reserved_in_scope`/`spent_in_scope` filter by `window_start`). At the next
  window boundary they stop counting and stop blocking; nothing is rewritten.
- **All-time budgets (no `budget_duration`) and the current window.** They
  stay fail-closed until an operator settles the reservation with evidence
  (provider invoice, dashboard, support confirmation). The release path is
  explicit and append-only:
  - `python -m contextual_orchestrator spend-reservations --spend-ledger-path P`
    lists active reservations with their linked unknown calls (error class,
    status, provider, model);
  - `python -m contextual_orchestrator spend-settle --spend-ledger-path P
    --reservation-id ID --settled-cost-usd X --reason TEXT --operator NAME`
    appends a `spend_settlement` event (library:
    `spend_metering.operator_settle_reservation`). Reason and operator are
    mandatory; the cost is explicit (it may be `0` only with evidence that
    the call was not billed) and must be non-negative in the reservation
    currency. Unknown or already-closed reservations are rejected.
  A settlement replaces the reservation and the linked unknown cost with the
  settled cost in every budget sum, so the settled cost stays charged; it is
  not a forgiveness switch. Settlements are windowed by the reservation time.
  - A reservation with no linked usage entry belongs to a call that has not
    finished and may still be in flight in a live run, whose own settlement
    would race the operator's. `spend-settle` refuses it
    (`ReservationInFlightError`) unless `--force` is given, which is for a
    reservation left behind by a crashed process.
  - `--operator` is free-text audit data, not authentication: anyone who can
    write the ledger file can settle. Protect the ledger path accordingly.
- No elapsed-time expiry is inferred inside a window.
- At a window boundary spend can exceed a windowed cap by at most one
  in-flight reservation per concurrent call: a reservation made just before
  the boundary stops counting in the new window while its call may still be
  billed.

### 2b. Every paid send path is admitted

| Entry point | Hook | Channel | Bound source |
|---|---|---|---|
| `ModelClient.chat` | `guarded_provider_call` | `sync` | exact prompt + effort-profile / effective `max_tokens`, else ceiling |
| `ModelClient.stream_chat` | `guarded_provider_stream` | `stream` | same |
| `ModelClient.probe` (readiness) | `guarded_provider_call` | `probe` | exact prompt + `max_tokens=1` |
| `proxy_send`, `proxy_send_once` (judge) | `metered_passthrough_call` | `passthrough` | request body |
| `probe_structured_chat` | `metered_passthrough_call` | `probe` | request body |
| `proxy_send_bytes` | `metered_passthrough_call` | `passthrough_bytes` | request body |
| `embed`, `embed_with_usage` | `metered_passthrough_call` | `embeddings` | ceiling x inputs |
| `batch_chat` (remote Batch API) | `metered_passthrough_call` | `batch` | sum of rows |
| `TaskOrchestrator.proxy_capability`, `batch_route` | `@with_run_scope` | - | via the calls above |

A spend refusal is never rewritten as a provider failure: `proxy_capability`
and `batch_chat` re-raise `BudgetExceededError` instead of classifying it and
failing over. `tests/test_spend_admission_paths.py` enforces the table: a
static scan of `ModelClient` proves every public path to the HTTP opener
passes through one of the three hooks, and a runtime test calls each entry
point outside any scope with a tiny cap and asserts no send primitive runs.

Allowlisted non-inference calls (no token-priced cost, no PriceBook row):
the local `/models` registry GET in `probe`, async job status/media GETs
(`proxy_get_json`, `proxy_get_bytes`), provider file DELETE
(`proxy_delete_json`) and Files API upload (`proxy_upload`). Outside
`ModelClient`, the Wardnet policy fetch and SearXNG search are not model
providers. Operator model discovery (`model_discovery.py`) sends a
`max_tokens=32` tool-call probe on its own guard-less client; it is a known
limitation (see Consequences).

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
    `<name>.partial`; corruption anywhere else raises. `spend_reservation` and
    `spend_release` events retain admission state across processes and crashes;
    `spend_settlement` events record operator settlements (section 2a). No
    elapsed-time expiry is inferred beyond the budget window. POSIX `flock` serializes the refresh,
    decision and reservation append. Without that file-lock authority,
    uncapped metering remains available but a shared hard budget fails closed
    with `reservation_authority_unavailable`.

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
- Entry points are decorated with `@with_run_scope` (including `batch_route`
  and `proxy_capability`); a nested decorated call joins the outer scope. Where main's
  `@_request_execution_scoped` also applies, it is the outer decorator: the
  request scope validates and snapshots policy/effort state before a spend run
  scope opens, and for generators it captures the context in which the run
  scope is later entered. `compare_to_baseline` has only `@with_run_scope`.
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
- Admission reserves the proven total-cost upper bound before the provider
  boundary. Known settlement replaces the reservation with measured/zero
  usage; an unknown outcome or process crash leaves the reservation active and
  therefore fails closed without inventing a charge, until its budget window
  rolls over or an operator settles it (section 2a).
- Streaming calls often report no usage (`stream_usage_supported`). Under a cap,
  a paid streamed call without usage blocks further paid calls in that run.
- The narrow bound depends on the provider billing at most `max_tokens`
  output tokens and on the exact prompt count matching provider framing; the
  context-window ceiling still caps it.
- Key and tenant spend are computed by scanning the store on each admission.
  That is O(entries). A windowed index is deferred.
- CLI ledger open/read/lock failures use the argument-error surface instead of
  exposing an operator traceback. Untrusted recursive provider JSON degrades
  to empty limit evidence and cannot abort failure classification.
- **Known limitation: fees outside token pricing.** The PriceBook holds only
  prompt and completion prices per 1K tokens. OpenRouter per-request fees,
  image input/output pricing, `web_search` / web plugin fees, prompt-cache
  write surcharges, and non-token products (image generation, audio, video
  jobs) are not in it and are not invented here, so admission bounds do not
  include them. When the provider reports `usage.cost`, the actual charge is
  metered and any excess over the bound is recorded as an admission-bound
  overrun; when it does not, spend on such calls is under-estimated.
  Operators who route to these features under a hard cap should set a
  conservative cap or tag the model accordingly until those prices exist.
- Operator model discovery (`probe_discovered_model_tool_call_capability`)
  sends one `max_tokens=32` chat request per discovered model on a
  guard-less client. It is not metered by this guard.
- `ModelClient`'s transient retries inside one transport call
  (`_send_with_retry`, `_send_raw_with_retry`) share one admission: a call
  retried after an unknown first attempt may be billed more than once while
  only one bound is reserved.
- An uncapped run now reports unmeasured calls at their bound (and
  `measurement_complete: false`) instead of silently at zero.

## Deferred

- Server wiring: principal → tenant, virtual key header, HTTP key management,
  admin UI.
- A key-management CLI.
- Per-request cheapest-paid-first ranking (audit Gap 5). ADR 0032 bootstrap
  `--enable-cheapest` stays the pool-level mechanism.
- Removing `price_per_million`.
- Limit errors inside non-stream HTTP 200 bodies.
- A SQL-backed high-throughput adapter; JSONL intentionally serializes budget
  transactions and scans its append-only projection.
- Uploading the run artifact from workflows.
- `ModelClient`'s internal 429 retries on paths outside `_invoke` may retry once
  before the drop is observed.

## References

- ADR 0032, ADR 0041; `docs/adr/0124-incremental-domain-extraction.md` (PR #1262).
- RFC 9110, HTTP Semantics, section 15.5.3 (402 Payment Required): https://doi.org/10.17487/RFC9110
- LiteLLM proxy budgets: https://docs.litellm.ai/docs/proxy/users ; https://docs.litellm.ai/docs/proxy/virtual_keys ; https://docs.litellm.ai/docs/proxy/team_budgets
- Provider limit documentation as listed in the table in section 3.
