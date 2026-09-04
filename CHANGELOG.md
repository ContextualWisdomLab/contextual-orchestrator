# Changelog

All notable changes to `contextual-orchestrator` are documented here. The
project follows Semantic Versioning; a version is released only after the
protected `main` branch, required Checks, independent review, and release
artifacts are verified on the same commit.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - Unreleased

- The synthetic classification benchmark now chooses a reject-option threshold
  on a development seed under a 2.5% Wilson error ceiling and evaluates it on
  an independent seed, reporting coverage, selective risk, and query burden.
- The classification screen now reports confidence-resolved coverage and
  conditional accuracy, preserving unresolved candidates instead of hiding
  forced decisions inside aggregate accuracy.
- The adaptive onboarding screen now compares a bounded 95% confidence-interval
  classification stop with fixed 12-query calibration, reporting paired query
  and decision-accuracy intervals plus near/mid/far-cut strata instead of
  treating generic score precision or an aggregate mean as the routing
  decision objective.
- The held-out psychometric benchmark now compares released maximum-information
  EAP calibration with random query ordering for unseen-candidate onboarding,
  reporting calibration-query burden, score error, and unobserved-probability
  error with paired bootstrap intervals, without treating synthetic efficiency
  as buyer or production evidence.
- Research guidance now classifies IRT-Router's unconstrained discrimination
  vectors and unidentified multidimensional coordinates as predictive features,
  not invariant psychometric measurements; production admission requires
  explicit orientation, scale identification/linking, fit, and uncertainty.

### Deprecated

- Internal callers now use
  `TaskOrchestrator.commercial_evidence_manifest_report()` /
  `commercial_handoff_bundle_report()` directly. The deprecated `buyer_*`
  Python aliases remain available for source, git, and submodule consumers;
  the deprecated HTTP compatibility routes remain available as well.

### Fixed

- The held-out psychometric benchmark now measures sequential probability-drift
  detection delay and pre-change false alarms over 500 repetitions. A bounded
  calibration search uses a 95% Wilson false-alarm bound, then evaluates the
  selected threshold on an independent 500-repetition seed.
- The held-out psychometric benchmark now distinguishes prediction for unseen
  queries from prediction for unseen candidate deployments. The latter remains
  separate and reports zero psychometric prediction coverage instead of
  inheriting accuracy evidence from known candidates.
- The held-out psychometric benchmark now reports selection success and net
  utility together, showing that higher predictive validity does not justify a
  route when its measurement cost exceeds buyer-valued outcome gains.
- The held-out psychometric benchmark now decomposes candidate, query,
  occasion, and interaction variance with a two-facet G-study and reports
  D-study generalizability and dependability across proposed evidence designs.
- The held-out psychometric benchmark now separately calibrates full and
  reduced candidate rosters, links them through common items, and reports
  common-candidate score stability without treating synthetic recovery as
  buyer invariance.
- The held-out psychometric benchmark now makes probability calibration a
  paired accuracy KPI, reporting calibration slope, intercept, and logit RMSE
  instead of relying on aggregate Brier and log loss alone.
- The held-out psychometric benchmark now recovers a known alternate-form score
  transformation and reports bootstrap equating uncertainty, while keeping
  buyer score comparability unexecuted.
- The held-out psychometric benchmark now distinguishes linked parameter drift
  from its aggregate test-characteristic-curve impact and detects the one
  injected function-changing item without claiming a universal cutoff.
- The held-out psychometric benchmark now reports the bias from treating
  adaptively selected winner observations as an ignorable sample, alongside
  the error reduction from its logged inverse-propensity estimator.
- The held-out psychometric benchmark now measures expected classification
  accuracy and consistency at a declared decision cut. Lower score error improves
  both measures, while buyer cuts, decision costs, and validity remain gated.
- The held-out psychometric benchmark now reports conditional test information
  and standard error at the center and tails. A range-matched item bank improves
  worst-case information without treating average reliability as uniform precision.
- The held-out psychometric benchmark now verifies that posterior empirical
  reliability rises when known item information increases. Reliability remains
  separate from model fit and cannot open the buyer-validity gate by itself.
- The held-out psychometric benchmark now distinguishes a fitted one-factor
  design from known two-factor misspecification with the released M2 global-fit
  diagnostics, while keeping buyer model fit and construct validity closed.
- The held-out psychometric benchmark now recovers two known latent dimensions
  with the released Horn parallel-analysis screen. It keeps buyer construct
  validity closed because Pearson-PCA screening on binary responses is not a
  confirmatory measurement model.
- Streaming automatic routing now fails when every worker candidate is excluded
  from that role, matching non-streaming selection while preserving explicit
  requested-model behavior. Benchmark propensity weights and workload receipts
  now remain aligned with the candidate and item structure actually used.
- The held-out psychometric benchmark now exercises released nonparametric
  person-fit diagnostics and ranks one injected inverted candidate response
  pattern first. It reports separation without inventing a universal cutoff or
  treating an unusual pattern as proof that a candidate is invalid.
- The held-out psychometric benchmark now links two synthetic recalibrations
  through seven stable anchors and detects the one injected item-parameter drift
  with no stable-item false positive. The tolerance is explicitly an effect-size
  screen, not a significance test or buyer-validity result.
- The held-out psychometric benchmark now uses the released Oakes-information
  API to report item-intercept RMSE, 95% Wald-interval coverage, and mean interval
  width while keeping synthetic uncertainty evidence outside the buyer gate.
- The held-out psychometric benchmark now estimates one known item-side context
  contrast through the released multigroup covariate API. It reports coefficient
  error and convergence separately while keeping synthetic recovery outside the
  buyer-validity gate.
- The held-out psychometric benchmark now fits a many-facet Rasch model to a
  connected synthetic respondent-item-judge design and reports judge-severity
  RMSE, convergence, connectedness, and severity-order recovery.
- The held-out psychometric benchmark now verifies purified logistic DIF on a
  known candidate-cohort item shift, reporting detection recall, false-positive
  count, anchor count, and purification convergence. Buyer DIF remains unexecuted.
- The held-out psychometric benchmark now verifies Stocking–Lord scale linking
  against a known affine transformation of six common-item anchors and reports
  convergence plus true-parameter RMSE. Buyer anchors remain unexecuted.
- The held-out psychometric benchmark now validates a preregistered ε-greedy
  logging design with positive assignment probability for every candidate,
  inverse-propensity value RMSE, and true-value confidence-interval coverage.
  It remains synthetic evidence and does not open the buyer-validity gate.
- Route, conducted-workflow, and streaming trace rows now retain a secret-free
  deterministic selection-design receipt: the versioned candidate set, actual
  attempted deployments, selected deployment, and policy hash. Propensity stays
  explicitly unidentified; the receipt does not fabricate counterfactual evidence.
- Adaptive-exposure evidence now distinguishes released CAT exposure control
  from the missing gateway propensity and counterfactual-observation contract.
  The unexecuted production gate remains closed.
- Item-side language/domain validity evidence now reports the released but
  limited multigroup item-covariate contract instead of claiming no owner
  implementation exists. Unexecuted buyer evidence remains fail-closed.
- Psychometric routing now normalizes retained context embeddings once when
  they are observed. Five before/after local runs reduced median candidate
  decision p50 from `0.016083` to `0.009791` ms without changing quality metrics.
- Psychometric benchmark evidence now distinguishes released owner contracts,
  a pending owner contract, and unimplemented validity checks while keeping all
  unexecuted checks fail-closed.
- The psychometric benchmark now enumerates scale linking, local independence,
  candidate-group DIF, item language/domain effects, judge effects, and adaptive
  exposure as separate measurement-validity evidence components instead of one
  opaque unavailable flag.
- Psychometric benchmark gates now distinguish `not_executed` buyer and
  measurement-validity evidence from a measured `failed` latency result while
  preserving the existing fail-closed Boolean compatibility fields.
- Semantic psychometric lookup now validates and normalizes the query embedding
  once per decision instead of once per retained context. Five paired local
  runs reduced candidate decision p50 median from `0.023167` to `0.015042` ms
  without changing Brier score, log loss, or regret.
- Experimental two-neighbor psychometric interpolation now reads each
  neighbor's score map once per candidate instead of repeating generator and
  membership passes; alternating-process measurements reduced candidate
  decision p50 by 7.39% without changing Brier score, log loss, or regret.
- Production single-neighbor psychometric selection again uses one-pass
  `max()` instead of sorting every retained context for an experimental top-2
  need; the isolated 512-row selection benchmark fell from 27 to 5.5 µs.
- The held-out psychometric benchmark now compares the production baseline and
  interpolation candidate on the same contexts and reports deterministic paired
  bootstrap 95% intervals for Brier, log-loss, and top-choice-regret deltas.
  Decision timing repeats 200 times per context, alternates baseline/candidate
  execution order, and reports each point delta beside its paired interval, so
  an accuracy interval cannot silently authorize a slower production route.
  The report also fails closed across accuracy, decision latency, buyer-heldout,
  and measurement-validity gates; synthetic evidence alone always leaves the
  production-default decision false.
- The seeded held-out benchmark can now opt into interpolation of the two
  nearest positive-cosine psychometric score rows and reports Brier score, log
  loss, top-choice regret, and decision p50/p95. Live routing retains the
  validated single-neighbor default until buyer-held-out gates pass.
- Psychometric observations are keyed by the declared deployment configuration
  and active role effort/sampling catalog, so reused agent IDs cannot carry
  scores across model, endpoint, or decode-policy changes. Overflow-safe cosine
  normalization rejects non-finite evidence; the production single-neighbor
  path retains its pre-experiment behavior while the positive-cosine cutoff
  remains confined to the opt-in interpolation experiment.
- Psychometric router mutation and durable persistence now share one lock, so a
  concurrent agent-pool change cannot prune a freshly saved valid observation.
  The paper inventory contract now scans only Git-tracked Python and Markdown
  sources, excluding ignored build artifacts from research coverage decisions.
- Psychometric observation replacement now removes only the existing row's
  contiguous trailing items instead of scanning the complete response ledger;
  the checked-in benchmark reports fit/rank and observation p50/p95 separately.
- Workflow workers now preserve the caller message array exactly once, while
  the added envelope carries only the subtask and Conductor-style prior-step
  access list instead of duplicating the task or source attachments.
- Configured-gateway discovery now removes its blank bootstrap row after a
  concrete catalog's chat candidates fail bounded readiness, so virtual
  requests cannot bypass an authentication failure through an unprobed seed;
  this retirement is process-local so a later startup can probe recovered
  credentials, while explicit model pins still return their own typed error.
- Queued embedding admissions now carry the durable registry's result
  retention and the selected backend's polling cadence, so clients can poll
  within the actual job lifecycle instead of guessing or failing closed on
  missing lifecycle metadata.
- Virtual structured workflows now exclude a same-endpoint candidate only
  after both its synthesis and bounded repair violate the caller's schema,
  then continue with the next eligible model on that endpoint. Explicit model
  pins remain single-model and exhausted virtual pools return a typed error.
- Configured-gateway runtime discovery now retains chat rows only after a
  bounded structured-output probe, and virtual structured workflows share one
  request-scoped missing-model exclusion set across evidence and synthesis.
  Probe telemetry is separate from caller attempts, and explicit structured
  requests keep their model pin throughout evidence, judgment, and synthesis.
- Chat token accounting now uses valid provider usage or exact Rust raw-output
  counts for ADR-declared tokenizer mappings. Unreconstructible prompts, tools,
  multimodal input, unknown models, and missing stream usage are explicitly
  unavailable; token-threshold routing stays synchronous, enabled budgets fail
  closed, and API usage/cost fields no longer publish heuristic estimates
  (ADR 0006).
- Provider-embedding workers now propagate durable-claim renewal loss and
  refresh ownership before terminal publication. Embedding token accounting
  uses configured `pg_tiktoken` or the packaged Rust cl100k counter for exact
  declared models, and otherwise fails closed without publishing estimated
  usage or cost (ADR 0005). Chat accounting is governed separately by ADR 0006.
- The HTTP embedding endpoints (`/v1/embeddings`, `/v1/batch/embeddings`)
  now correctly wire the coordinator's cheapest-price selection into an
  *omitted* `model` (the common case), not only an explicitly-named model or
  model-group alias. Previously the request validator resolved an omitted
  `model` to one concrete, price-blind, highest-ranked model before
  candidate collection ever ran, so cost-based selection only ever had one
  candidate to "choose" from. Candidate discovery for an omitted model now
  runs against `TaskOrchestrator.AUTO_MODEL` (the full unspecified-candidate
  pool) instead, while the validated/reported model identity for an
  *explicit* request is unchanged (Devin Review, PR #965).
- The same embedding candidate ordering now reconciles cost preference with
  the orchestrator's own measured health evidence
  (`ModelGroupRouter`/`_group_router`, fed by `observe_success`/
  `observe_failure`): `CostRoutingCoordinator._cost_ordered_capability_candidates`
  price-orders only members whose Beta-Bernoulli success posterior mean is
  still at or above the neutral baseline, keeps a repeatedly-failing
  cheapest member out of the price-preferred slot (it is retried only after
  the healthy candidates, not first on every request forever), and re-admits
  it automatically once new successes bring its posterior mean back to
  baseline. Applied consistently to both endpoints (Devin Review, PR #965).
- `/v1/embeddings`'s response `model` field, for an omitted-model request,
  now reports the completed document's actually-served model instead of the
  pre-failover, price-blind model the (now-bypassed-for-selection) validator
  resolved — a cheaper or failed-over candidate can legitimately differ from
  that guess. `/v1/batch/embeddings` already reported the correctly-served
  model (its response is the raw batch document, whose `model` field is
  derived from the actually-submitted request, not from this pre-failover
  guess) and needed no change. Explicit-model requests are unaffected on
  both endpoints. The cost ledger's own `model_name` attribution dimension
  was already protected against this staleness independently: `CostLedger
  .record_usage` deliberately strips and overwrites any caller-supplied
  `attribution["model_name"]` with the real served `model` argument
  ("execution identity always wins" — buyer-bill honesty), so ledger/spend
  rollups were never affected by this bug (Devin Review follow-up, PR #965).
- `CostRoutingCoordinator._cheapest_capability_candidate` now performs
  price-aware selection: resolving an unspecified embedding batch member
  out of several capability-matched candidates (e.g. operator-managed
  model-group members) now picks the cheapest one by the configured price
  table instead of an arbitrary first/ranked pick. It plays a role similar
  to `cheapest_upstream` (`batch_routing.py`) but does not call it — see
  below for how the two diverged. `cheapest_upstream` itself remains a
  headline-documented, `__all__`-exported utility with no production caller
  anywhere in the router.
- `CostRoutingCoordinator._cheapest_capability_candidate` no longer treats an
  unpriced or invalid `PriceBook` entry as a free (zero-cost) winner, no
  longer compares prices across mismatched currencies at face value against
  `PriceBook.default_currency`, and prices embedding candidates with
  `assumed_completion_tokens=0` (embeddings never consume completion
  tokens). Candidates with no comparable known-currency price keep the
  orchestrator's existing ranked order instead of being silently selected.
- `_cheapest_capability_candidate`'s currency-comparability check now reuses
  `model_discovery._currency_is_comparable`'s normalization (non-empty,
  trimmed, case-insensitive) instead of an exact string match, so a
  lowercase or whitespace-padded same-currency code (e.g. `"usd"` vs
  `"USD"`) is recognized as comparable rather than losing to a costlier
  candidate. `_resolve_embedding_target` now runs this cheapest-comparable-
  member selection for ordinary (non-ZDR) unspecified embedding requests
  too, not just the ZDR path.
- (Devin review on #965) `_cheapest_capability_candidate` no longer compares
  candidate prices via ledger-rounded (6-decimal-place)
  `PriceBook.compute_cost` output. Two genuinely different low per-1K prices
  (e.g. `0.00000049` and `0.00000001`) can both round to the same `0.0`
  ledger cost for the assumed request size, which collapsed a real price
  difference into a tie and let the ranked-first (possibly costlier)
  candidate win. Ranking now compares each candidate's raw, unrounded
  `PriceEntry.prompt_price_per_1k` directly (embedding requests carry zero
  completion tokens, so completion price stays out of the comparison).
  `cheapest_upstream` itself, currency filtering, the unpriced-exclusion
  behavior, and ranked-order tie-breaking on a true price tie are unchanged.
- Removed the redundant `threading.local`-backed `commercial_*_report`
  caching decorator (`_commercial_report_cached`), which an import-time
  class-dict-scanning loop applied to every `commercial_*_report` method
  *before* the still-current `ContextVar`-backed decorator
  (`_cached_commercial_report`) ran its own later loop and re-wrapped the
  already-wrapped methods. Because the `ContextVar` layer always ended up
  outermost and only calls into the inner layer on its own cache miss, the
  inner `threading.local` cache dict was reset on every call in real
  (non-reentrant) usage and its own cache-hit branch was unreachable in the
  composed call chain — real code that ran on every call with no caching
  effect. Kept the `ContextVar` strategy (the layer that actually determined
  behavior) and deleted its dead sibling along with the now-unused
  `_commercial_report_cache_local` per-instance state and `_report_cache_token`
  helper. No behavior change: the surviving decorator is unchanged and was
  already the effective caching layer.
- Added the missing CLI on-ramp for the issue #568 / ADR 0021 per-role
  reasoning-effort catalog: the new `--role-effort-catalog default` flag now
  loads `default_role_effort_catalog()` and passes it into `TaskOrchestrator`.
  Previously `role_effort_catalog` had no caller anywhere in `__main__.py`, so
  `apply_effort_profile` always ran its `profile=None` no-op branch in the
  shipped CLI/server and the catalog's temperature/top_p/seed/reasoning_effort
  injection and replayable `reasoning_effort_snapshot` were unreachable in
  production. Omitting the flag keeps every payload byte-for-byte unchanged;
  this does not touch the locked route/conduct selection defaults. Research
  grounding for `reasoning_effort_profile` (Fugu's latency-versus-quality
  split, TRINITY roles, Conductor steps/access lists) is already cited in
  [`docs/architecture.md`](docs/architecture.md#implementation-mapping) next to this
  module; this CLI on-ramp reuses that existing catalog and cites no new
  claims of its own.
- Startup now refuses `--role-effort-catalog default` when no agent in the
  configured pool proves native `reasoning_effort` support (explicit
  `"reasoning_effort_supported": true`, or a `mock://` agent). Every role in
  the default catalog fails closed (`unsupported_provider_fallback="abstain"`,
  per ADR 0021), and ordinary real-provider agent configs and auto-discovered
  agents never set `reasoning_effort_supported` — without this guard the flag
  would construct successfully and then raise `EffortProfileError` on every
  request. `--agents examples/agents.mock.json` (the CLI default) is
  unaffected; only a non-mock pool without proven support is now rejected at
  startup, before any request is attempted.
- The startup guard above only proved that *some* agent in the pool supports
  `reasoning_effort`; ordinary role-based selection (`route_once`, `conduct`,
  `stream_route`, `batch_route`, structured-synthesis passthrough) could still
  rank or select an *unsupported* agent from a mixed pool ahead of a
  supported one. `route_once`/`conduct` already recovered via `_invoke`'s
  generic tool-failure failover, but `stream_route` and `batch_route` call
  the provider directly with no failover and would raise `EffortProfileError`
  outright. `TaskOrchestrator._ranked_agents` now narrows role-based
  candidates to agents that prove `reasoning_effort` support whenever the
  role's `role_effort_catalog` entry fails closed
  (`unsupported_provider_fallback` other than `"omit"`), falling back to the
  unfiltered set only when no candidate in that narrower selection proves
  support (e.g. a required tag or free-only filter excluded the pool's only
  supporting agent). This mirrors the equivalent filter already applied on
  `proxy_completion`'s passthrough failover, which now shares the same
  `_eligible_role_effort_candidates` helper instead of a duplicated inline
  check. Runtime agent patch, removal, and discovery synchronization now
  revalidate the same catalog invariant before committing a pool mutation,
  so a live server cannot disable or remove its last eligible supporting
  agent and strand a fail-closed role after startup.
- The startup guard above still only proved that *some enabled agent
  anywhere* in the pool supports `reasoning_effort`, which is weaker than
  what role-based selection actually requires: `_ranked_agents`/
  `_select_agent` only ever offer a role a *general-chat* agent (see
  `_is_general_chat_agent`) that is not excluded from that specific role via
  `provider_exclusions`. A pool whose only proving agent was non-chat (e.g.
  an embedding-only model with `reasoning_effort_supported: true`), or was
  excluded from every active fail-closed role, passed the old check and
  still failed every request for that role (`EffortProfileError`, or
  `RuntimeError("no eligible agent available for role=...")` when the sole
  prover was role-excluded). `_require_eligible_role_effort_agents` now
  reapplies the same general-chat and `provider_exclusions` eligibility
  rules used by role selection, per active fail-closed role, reusing
  `agent_proves_reasoning_effort_support`/`_eligible_role_effort_candidates`
  rather than new logic. Deliberately does not reapply
  `_zdr_agent_allowed`, since that gate is per-request privacy-policy state,
  not a static pool property.
- The startup rejection path now closes the already-constructed
  `TaskOrchestrator` (`orchestrator.close()`) before calling argparse's
  `parser.error()` (which raises `SystemExit`), instead of relying on
  process exit to release its optional durable resources
  (`state_db`/`agents_db` connections). This only matters for an embedded
  caller of `contextual_orchestrator.__main__.main()` that catches
  `SystemExit` and keeps running in the same process; the CLI/process-exit
  path was already unaffected.
- `TaskOrchestrator.proxy_completion`'s single-agent passthrough (the
  server's `tool_loop` call site, and any other caller that omits
  `effort_profile`) now defaults an unset `effort_profile` to the opted-in
  `role_effort_catalog`'s `"worker"` entry — the role every selection/
  failover call in that method already uses — instead of silently skipping
  sampling/token/seed/reasoning-effort injection. This mirrors the
  pre-existing `effort_profile or self._role_effort_profile("synthesizer")`
  fallback `_orchestrated_provider_completion` already applies for its own
  role. A caller that passes its own `effort_profile` is unaffected, and so
  is every caller when no `role_effort_catalog` is configured.
- Batch cost retrieval now preserves cache hits, completed endpoint-race loser
  usage, and strict provider usage evidence. Remote fallbacks retain the real
  submitted prompt, repeated result retrieval reuses deterministic ledger ids,
  and mixed-currency results expose per-currency components.
- Batch result retrieval no longer converts an explicit download failure into
  a silent empty result. `PgLlmBatchBackend.retrieve()` and
  `PgLlmBatchEmbeddingBackend.retrieve()` now raise a new
  `BatchDownloadError` (carrying the job id and the client's reported
  `reason`/`error`) instead of returning `[]`, which used to be
  indistinguishable from a batch that legitimately completed with zero
  items. `CostRoutingCoordinator.retrieve_batch()` now lets the error
  propagate rather than reporting a fake `result_count: 0` success (a new
  `except BatchDownloadError` handler in `server.py` maps it to `502
  batch_download_failed`, matching how other typed batch/provider errors are
  already routed there). `embeddings_batch_document()` catches it and returns
  `status: "failed"` with an `error` field, and — the severe half of this bug
  — deliberately does **not** cache that result: a bare `return []` on
  download failure used to be treated as a legitimately completed batch and
  cached under `status: "completed"` with a fabricated `{"embedding": []}`
  for every input, permanently poisoning that `batch_id` since the cache
  short-circuits all future poll/retrieve calls before ever touching the
  backend again. A failed retrieval now stays retryable.
- `LocalBatchBackend` (the default `batch_backend` whenever
  `CostRoutingCoordinator` is constructed without an explicit override, i.e.
  every standalone/self-hosted-without-pg-llm-batch deployment) no longer
  discards the real usage its runner reports. `BatchResultItem` gained a
  `messages` field carrying the original request through, and
  `LocalBatchBackend.submit()` now aggregates real `prompt_tokens`/
  `completion_tokens` from `result["trace"][i]["usage"]` (usage has no
  top-level key on `orchestrator.complete()`'s result; it is nested per
  workflow step) instead of leaving both at the dataclass's `0` default. The
  minimal per-step usage trace is retained so heterogeneous conduct calls are
  charged to their actual served provider/model rather than collapsed into one
  `unknown` row; malformed counts fail closed to estimates without coercion.
  `retrieve_batch()`'s heuristic-estimate fallback (triggered whenever a
  batch item reports no usage) now estimates from the batch item's real
  request messages instead of a hardcoded blank `""` prompt — previously
  every such row was labeled `measurement_status="estimated"` while actually
  being a constant ~3-token count derived from empty content regardless of
  the real prompt's length, misrepresenting what "estimated" meant to a
  buyer reading the ledger.
- Fixed a stale test assumption left behind by the per-step batch usage
  attribution above:
  `test_batch_routing_jobs_endpoint_submits_multiple_requests` still
  hardcoded "one ledger row per batch item," which was already false for
  `CostRoutingCoordinator.complete()`'s documented per-trace-step
  attribution contract (each conduct-mode step is a separate billable
  provider call). Two 2-request submissions through
  `/api/v1/batch_routing_jobs` with the default single-agent mock pool
  triage to the conduct path (4 steps each), producing 8 ledger rows, not
  2 — the assertion now derives its expectation from the retrieved results'
  own `usage_record_ids`, matching the fix already applied to the sibling
  assertions in `tests/test_cost_router.py`.
- The cost ledger no longer fabricates a $0.00 price for an unpriced
  provider/model. `PriceBook.compute_cost()` now returns a
  `(cost_amount, currency_code, price_known)` 3-tuple; `UsageRecord` gains a
  `price_known: bool` field (persisted through a new `usage_price_knowledge`
  satellite table, joined the same way `usage_measurements` already is) so a
  measured-but-unpriced request is distinguishable from a genuinely free one.
  `CostLedger.rollup()`/`.report()`/`.total()` add an additive
  `cost_amount_by_status`/`record_count_by_status` breakdown
  (measured/estimated/unavailable) alongside the existing flat `cost_amount`
  total, so measured, estimated, and unavailable-priced spend are no longer
  opaquely blended into one authoritative-looking number.
- `CostLedger.rollup()`/`.report()` add the same treatment one level further:
  an additive `cost_amount_by_price_status`/`record_count_by_price_status`
  breakdown (`known`/`unknown`) alongside the measured/estimated/unavailable
  one, so an unpriced request's spend is visible even after rolling many
  records up into one bucket. `cheapest_upstream()` no longer treats an
  unpriced candidate as free (cost `0`) when selecting the lowest-cost
  upstream — an unknown price is excluded from the comparison entirely
  rather than winning it by default; `None` is returned when no candidate
  has a known price.
- (Devin review on #956) `SqlLedgerStore._append_locked()`'s satellite
  writes (`usage_measurements`, `usage_price_knowledge`, attribution) now
  only run when the parent `llm_usage_records` insert is actually accepted.
  A retried `usage_record_id` whose parent insert is correctly rejected as
  a duplicate previously still ran these satellite inserts unconditionally
  — for a parent row that predates one of these tables (e.g. an
  upgrade-migrated row with no `usage_price_knowledge` child, intentionally
  read as price-unknown) that silently backfilled its provenance from the
  retry's current price/measurement state instead of what actually priced
  the original spend. `append()` is now a true no-op on a rejected
  duplicate.
- `price_known` now propagates from the ledger into every downstream usage
  surface: `CostRoutingCoordinator.complete()`'s sync/provider-request cost
  dicts and their per-currency components, `record_stream_usage()`,
  `retrieve_batch()`'s per-item results, and `embeddings_batch_document()`.
  An unpriced request's `cost_amount` is `null` rather than a silent `0`
  wherever it surfaces, not just in the ledger's own rollups.
  `PriceBook.compute_cost()` treats zero token usage as the one exception:
  zero tokens cost zero regardless of whether the provider/model's price is
  known (zero times any finite price is still zero), so a cache hit — whose
  synthetic `("cache", "response")` provider/model never has a price row —
  is always `price_known=True`, `cost_amount=0.0` rather than being wrongly
  reported as an unpriced request.
- `retrieve_batch()`'s `item.prompt_tokens or None` treated a legitimately
  reported zero token count the same as a missing one (Python's falsy-zero),
  so a genuinely confirmed zero-usage batch item was silently downgraded to
  an unmeasured estimate instead of staying a real, priced `measured` `0`.
  `PgLlmBatchBackend.retrieve()` and `BatchResultItem` now carry an explicit
  `usage_valid` tri-state (confirmed-typed non-negative counts vs. missing/
  malformed usage), and `retrieve_batch()` reads that instead of relying on
  truthiness. That same estimation fallback also passed a hardcoded
  empty-content placeholder instead of the request actually submitted, so a
  large prompt whose provider marked usage invalid was undercounted to
  near-zero prompt tokens — understating batch cost. (CodeRabbit review)
  `submit_batch()` now computes a real prompt-token estimate per
  `custom_id` before submission and stores it as a `prompt_token_estimates`
  field on the durable `BatchJob` record itself, rather than the raw
  submitted messages (Devin review: a batch registry can be Valkey-backed
  with a multi-day retention shared across processes, and a submitted
  prompt may be ZDR-flagged or otherwise sensitive — a token count carries
  no reconstructable prompt content). Publishing it on the existing
  `BatchJob` write also means an accepted job still has exactly one
  publication write, so a metadata-only estimate can never orphan an
  already-accepted (and possibly billed) backend job behind a raised
  exception with no job id ever returned to the caller. `retrieve_batch()`
  reads that stored estimate instead of falling back to an empty
  placeholder. (Devin review) A job accepted before this fix has no
  `prompt_token_estimates` at all, and its original request never lived
  anywhere durable that a post-fix retrieval could still read — so
  `retrieve_batch()` now also reads a legacy, pre-fix `batch_requests`
  registry entry (still populated only for jobs submitted before this
  change; nothing writes new entries there anymore) whenever a custom_id
  has no stored estimate, computes the real prompt-token count from it the
  same way a fresh submission would have, and persists that estimate back
  onto the job so a re-retrieval never repeats the lookup. That legacy
  lookup initially gated on whether `job.prompt_token_estimates` was
  non-empty at all — wrong once any one custom_id had already picked up an
  estimate (including from an earlier partial retrieval of the same job),
  since every other still-unestimated custom_id would then silently stop
  being looked up for the rest of that job's lifetime. It now gates on
  whether the current retrieval actually has an item that still needs the
  legacy lookup, so a legacy job's estimates can be filled in correctly
  across as many partial retrievals as it takes; a job that has never
  needed the legacy path (everything submitted after this fix) still never
  touches that registry.
- `CostRoutingCoordinator._record_race_endpoint_usage()` no longer silently
  drops a completed, billable race-loser call's spend when its usage payload
  can't be parsed. It now writes a `measurement_status="unavailable"` ledger
  row (0 tokens) instead of returning without any row at all, mirroring
  `record_stream_usage()`'s existing "call happened, can't measure it"
  fallback. (Devin review on #955) Both of `complete()`'s cost-aggregation
  paths (the `provider_request`/race-proxy path and the ordinary
  `orchestrator.run()` sync path) previously only checked for
  `measurement_status="estimated"` when rolling records up into one
  response `cost` block, so a measured winner plus this new "unavailable"
  loser row still reported the whole completion as confidently `"measured"`
  and silently summed the loser's unknown cost as `0`. Both paths now use
  the same unavailable-outranks-estimated-outranks-measured precedence as
  `record_stream_usage()`, and `cost_amount` becomes `None` rather than a
  partial sum whenever any contributing record is unavailable. Mixed-currency
  responses also suppress their otherwise partial `currency_components`.
- `check-fast-mlsirm --help` now shows help and exits instead of running the
  diagnostic: the subcommand took no arguments and ignored everything after
  its own name, so `--help` was silently swallowed and the real diagnostic
  ran anyway. It now gets its own `argparse` parser (declaring the shared
  `--log-level`/`--verbose`/`--debug` flags, matching every other
  subcommand), so `--help` documents them and exits cleanly, and an
  unrecognized trailing option is rejected instead of being ignored.
- NVIDIA NIM benchmark cells now reconcile reported prompt and completion
  usage independently, preventing negative completion counts after failures.
- OpenRouter discovery no longer marks the entire credential account
  evidence-only. Authenticated catalog rows may serve ordinary requests, while
  ZDR-only requests still require explicit route-level ZDR evidence.
- Model discovery now treats every KV credential as an independent account/catalog boundary, removes provider-family collapsing, and offers secret-free `--verbose` progress diagnostics. Logical equivalence and latency-based switching remain explicit `model_group` decisions only.
- Model-group evidence now reports peak observed RPM and provider-reported TPM over a real 60-second completion window without generating probe traffic or inferring missing usage.
- `discover_provider_models`'s primary model-list fetch is now retried once
  (short fixed delay, shortened timeout) when the failure is transient
  (5xx/timeout/connection reset, via the existing `is_transient_error`
  classifier), instead of raising `ProviderDiscoveryError` on the first
  attempt. One provider's momentary blip (observed live: a Bytez HTTP 500)
  no longer has to zero out that provider's entire contribution to a
  discovery pass. Non-transient failures (bad credential, malformed
  response) are still never retried. Deliberately does not touch
  `ModelClient.proxy_send_once`'s single-shot completion-call contract
  ("cross-provider failover cannot amplify load") — reusing the same
  retry pattern there risks amplifying load against an already-degraded
  provider and was left out of scope for this change.
- (Devin review on #923) The retry attempt's timeout no longer expands past
  a caller-supplied budget shorter than the retry default: it is now
  `min(timeout, _DISCOVERY_RETRY_TIMEOUT_SECONDS)`, so a caller requesting
  e.g. a 2s timeout still gets a 2s retry, not a 5s one.
- (Devin review on #923) `is_transient_error` no longer misclassifies a TLS
  certificate-verification failure as transient when `urlopen` wraps it as
  `URLError(reason=ssl.SSLCertVerificationError(...))` rather than raising a
  bare `ssl.SSLError`. The existing bare-`ssl.SSLError` unwrap couldn't see
  this case, since the blanket "any `URLError` is transient" branch matched
  first and returned early — a permanently invalid trust boundary was being
  retried as if it were a network blip. Fixes the shared classifier itself
  (not just the discovery retry call site), so every current and future
  caller of `is_transient_error` benefits.
- `batch_route` no longer fabricates a hardcoded, ungated
  `{"accepted": True, "verifier_output": ""}` verification verdict for every
  batched answer regardless of `policy.realtime_judge`. It now calls the same
  `_realtime_route_judge` path `route_once`/`stream_route` use: a genuine
  fast-mlsirm judge verdict when `realtime_judge` is on (the default, feeding
  the quality ledger like serial runs already do), or the identical reviewed
  `{"accepted": True, "reason": "single route path", "verifier_output": answer}`
  fallback when an operator has explicitly turned `realtime_judge` off —
  closing the gap between the function's docstring claim of route_once parity
  and its actual (previously unguarded) behavior.
- (Devin review on #961) `batch_route` no longer feeds one shared Batch API
  call's total elapsed time into every one of its answers' synchronous-route
  quality latency EWMA. That elapsed time covers every prompt the provider
  batched together, not any single answer's honest wall-clock latency — doing
  so let one slow or large batch demote a fast model in later interactive
  `route_once` ranking. `ModelGroupRouter.observe_success` now accepts
  `latency_seconds=None` for exactly this case: stability/rate evidence (the
  judge's accept/reject verdict, request-rate tracking) is still recorded,
  but neither the latency nor tokens-per-second EWMA are updated from a
  duration that would not honestly describe one attempt. The trace row's own
  `latency_ms` keeps the real shared batch timing visible as raw evidence.
- (Devin review on #961) `batch_route`'s one-time spend-budget check at entry
  did not cover the N additional judge provider calls its loop makes
  afterward, so a large batch under a configured `budget_max_output_tokens`/
  `budget_max_cost_usd` cap could keep issuing judge calls well past the
  cap before the whole batch finally returned. The loop now re-checks
  accumulated in-batch spend before each item's judge call, the same
  per-step budget checkpoint `conduct()` already uses via
  `_trace_budget_spend`, so a batch fails closed mid-loop instead of only
  after every item has already run. That first per-item checkpoint design
  double-counted already-persisted rows (each prior row's spend is
  reflected in the budget meter as soon as `_replace_workflow_run` persists
  it, so re-adding it as "in-flight" charged it twice) — fixed to check
  only the current row. That in turn undercounted: every worker request in
  a batch actually completes together, before any judge call starts, so a
  later row's spend is real and already incurred the moment the batch
  finishes, not hidden behind a not-yet-executed provider call the way a
  later `conduct()` step's spend is. Checking only the current row let the
  aggregate spend of the rest of the batch — already incurred, just not yet
  persisted — pass every individual per-row check and reach every judge
  call uncounted. Each checkpoint now sums every row from the current index
  through the end of the batch (rows before it are already reflected in the
  meter by earlier iterations of the same loop), so a batch whose aggregate
  worker spend alone already exceeds the cap blocks its very first judge
  call. That aggregate checkpoint in turn raised `BudgetExceededError`
  before persisting any of the batch's already-completed worker rows —
  since `_replace_workflow_run` is the sole path that updates the budget
  meter, a batch that failed this checkpoint left its real, already-incurred
  provider spend completely uncounted, so a caller retrying the same
  over-budget batch could keep incurring real spend indefinitely against an
  unchanged meter. Every row's worker result is now persisted immediately
  (with no verification yet — `_is_trace_complete()` already reads that
  honestly as incomplete, the same as any other genuinely-unfinished run)
  before any budget check that could raise, so the checkpoint before each
  judge call is now the same simple "block before the next not-yet-incurred
  provider call" check `conduct()`'s entry point uses, and a retry after
  `BudgetExceededError` fails closed immediately instead of re-incurring
  the same spend. That fix still only updated the in-memory budget meter:
  a completed batch's pending rows were never written to the durable
  `--state-db` store, so a process restart before judging reloaded none of
  a failed batch's spend, and the same over-budget batch could be retried
  with a full budget again after every restart. Pending rows are now saved
  to the store too, the same as a judged run already was. That durable save
  had its own follow-up gap: `_reload_state()` unconditionally added every
  loaded `workflow_run` to `_run_order` (the recency structure behind
  `list_recent_runs()`), so a reloaded pending row -- never added to
  `_run_order` during normal, same-process operation because it is not yet
  a complete result -- would appear as a completed run in admin/API
  listings after a restart even though it never would have without one.
  `_reload_state()` now only adds a reloaded record to `_run_order` when
  `_is_trace_complete()` says it actually is one; its spend still restores
  into the budget meter either way. `_is_trace_complete()` was the wrong
  predicate for that gate, though: it also requires a truthy `"answer"`,
  so a genuinely completed `route`/`stream`/`conduct`/`batch` run that
  legitimately reported an empty answer would wrongly vanish from
  `_run_order` on reload while it would have stayed visible without a
  restart (every live-operation `_run_order.appendleft` call is
  unconditional). The pending batch row now carries an explicit
  `"pending_verification"` marker instead, and `_reload_state()` gates on
  its absence — the only thing that actually distinguishes a not-yet-judged
  batch row from every other persisted run, regardless of what its answer
  happens to be.
- `batch_route`'s real judge calls (see above) reported provider usage that
  `spend_analytics()` never counted — it only ever traversed each run's
  worker `trace` steps, so a batch under active `realtime_judge` judging
  could consume real judge tokens and budget while remaining invisible to
  buyer-facing spend/cost analytics. `spend_analytics()` now also attributes
  reported `verification.judge_usage` completion tokens to the judge's
  model, matching how `_run_budget_output_by_model` (the live budget meter)
  already counted it; missing/invalid judge usage stays absent rather than
  estimated from unrelated verifier text. (Devin review on #961) That judge
  model was being re-resolved from the *current* agent pool on every read
  (`model_by_agent.get(judge_agent_id, "unknown")` in both
  `_run_budget_output_by_model` and `spend_analytics()`), unlike worker
  steps, whose `model_name` is pinned into the persisted record at write
  time. If a judge agent's id was later reused for a different model (the
  real `sync_discovered_agents` re-discovery upsert path) or the agent left
  the pool, previously-recorded judge spend would silently reattribute to
  the new model or an unpriced/unknown bucket — a live report of judge
  spend could rewrite history on every pool change instead of describing
  what actually happened. `_model_judge_verification` now resolves and
  persists a `verification["judge_model"]` at judge-call time (the served
  agent's model at that exact moment, following failover the same way
  `judge_agent_id` already does), and both read sites prefer that stored
  value, falling back to the old live-pool resolution only for
  already-persisted records that predate this fix. (Devin review on #961)
  That first fix still resolved `judge_model` via one more `self.candidates`
  lookup performed right after the provider call returned -- narrower than
  the original bug, but not closed: `self.candidates` is a plain mutable
  list a concurrent admin request (agent add/remove/re-discovery) can
  reassign in the gap between the call completing and that lookup running,
  which could still mis-price that one call against whatever the pool
  became a moment later. `_invoke` (and the model-group endpoint race path
  inside it) now returns the exact `ModelAgent.model` of the agent object
  the call actually succeeded against, captured from the same local
  reference used for its `agent.id` -- no separate lookup, so there is no
  window left to race. `_FastMLSIJudgeAdapter` carries it the same way it
  already carries `served_agent_id`, and `_model_judge_verification` reads
  it directly instead of touching `self.candidates` at all. The two
  non-judge callers of `_invoke` (`route_once`'s worker call, `conduct()`'s
  step call) accept the new return value and discard it, unchanged from
  before -- those callers' own `trace` row `model` field already comes
  from the originally-selected candidate, not this served value, and stays
  that way; only the judge path, where this PR introduced the bug, changes
  behavior. New regression test drives the real judge harness and mutates
  the pool from inside the scripted judge's own `judge()` call --
  immediately after its provider call completes but before
  `_model_judge_verification` builds its result -- and asserts the
  persisted `judge_model` still reflects what actually served the request.
  (Devin review on #961) `batch_route` groups prompts by worker agent and
  runs one `batch_chat()` provider call per group; it built every group's
  results into one flat dict before persisting any of them, so if an
  earlier group's call already succeeded (real, incurred provider spend)
  and a later, unrelated group's call then raised, the whole `batch_route`
  call raised before the earlier group's rows were ever persisted --
  losing that spend from budget accounting entirely, not just leaving it
  pending. Each group's rows are now persisted as pending immediately after
  that group's own `batch_chat()` call validates, before the next group's
  call starts, the same as every row within one group already was.
  (Devin review on #961) `count_workflow_runs()`, `analytics_snapshot()`,
  and `sales_readiness_report()` read `_workflow_runs` directly, so an
  interrupted batch's `pending_verification` rows -- deliberately excluded
  from `_run_order`/`list_recent_runs()` -- still counted as finished
  results in those completed-run consumers (e.g. a workflow-runs API
  `total_count` that pagination could never actually reach). All three now
  read through a new `_completed_workflow_runs()` helper that excludes
  pending rows; `spend_analytics()` deliberately keeps iterating
  `_workflow_runs` directly, since a pending row's incurred spend must
  still be counted there. (Devin review on #961) Two more findings on the
  same restructured group loop: the one-time budget check at `batch_route`'s
  entry did not cover a later group's `batch_chat()` call once each group
  started persisting its own spend immediately, so a later group could
  still start unconditionally even after an earlier group's own spend
  alone already exceeded the cap -- incurring avoidable provider charges
  on an already-over-budget batch. Each group's loop iteration now re-checks
  the budget first, the same "block before the next not-yet-incurred
  provider call" check already used at entry and before each judge call.
  Conversely, the per-item checkpoint before each judge call fired
  regardless of `policy.realtime_judge`, even though `_realtime_route_judge`
  makes no provider call at all when judging is disabled (it returns a
  zero-cost reviewed fallback) -- there was no next spend for that
  checkpoint to gate, so an already-exhausted budget could strand an
  already-completed, already-paid-for worker answer that needed no further
  spend to finalize. That checkpoint now only runs when
  `policy.realtime_judge` is on. New regression tests:
  `test_batch_route_blocks_a_later_group_once_an_earlier_group_exhausts_budget`
  (two groups, the first exhausts the cap; asserts the second group's
  `batch_chat()` is never called) and
  `test_batch_route_disabled_judging_never_strands_a_completed_answer_on_budget`
  (`realtime_judge=False`, budget exhausted by the one worker call; asserts
  `batch_route` still returns the completed, reviewed-fallback-verified
  record instead of raising). (Devin review on #961) One more finding
  combining the two above: `batch_route` defers all judging to a second
  pass over every group, so the inter-group budget checkpoint could still
  raise before that pass ever reached an already-completed earlier group
  -- and with `realtime_judge` off, finalizing that group costs nothing,
  so leaving its answers stuck `pending_verification` forever (with no
  retry/resume path that would ever revisit them) served no purpose.
  Extracted the per-row judge-and-persist logic from the judging pass into
  a new `_finalize_batch_row()` helper; the inter-group checkpoint now
  calls it for every already-persisted row before raising, whenever
  `policy.realtime_judge` is off (real spend stays safe either way: only
  already-completed groups' rows are finalized, and the raise still blocks
  the next group's own not-yet-started `batch_chat()` call). New regression
  test `test_batch_route_finalizes_completed_group_before_blocking_a_later_one_when_judging_is_free`:
  two groups, `realtime_judge=False`, the first exhausts the cap; asserts
  the second group's call is still blocked while the first group's run is
  a finalized, visible result rather than a stuck pending row. (Devin
  review on #961) Two further findings, both about losing evidence for
  spend that has already genuinely happened. First: `batch_route` validated
  each group's entire response via `_validate_batch_results` before
  persisting any of it, so one malformed or missing item in an otherwise-
  valid group's response discarded every other, independently-valid item's
  already-incurred spend alongside it -- the same class of loss already
  fixed across groups, but now within one group's own paid provider call.
  `batch_route` now catches that validation failure, salvages every item in
  the raw response that independently satisfies the same per-item
  validity check, persists their spend as pending exactly like the normal
  path (extracted into a new `_persist_pending_batch_row()` helper shared
  by both), and then still raises -- the group as a whole remains correctly
  unusable as a completed run. Second: inside `_model_judge_verification`,
  the judge's provider call can complete and report real usage, with
  `judge_agent_id`/`judge_model`/`judge_usage` already captured, before the
  *separate* IRT-projection validation step rejects the result; both of its
  fail-closed branches returned a fresh dict literal that discarded those
  three fields, making an already-incurred judge spend invisible to
  `_run_budget_output_by_model`/`spend_analytics()`. Both branches now carry
  the same accounting subset forward. New/extended regression tests:
  `test_batch_route_rejects_incomplete_or_empty_provider_results` (extended
  to assert the group's two other, valid items survive as pending, with
  their spend counted, while the malformed one is excluded) and
  `test_model_judge_irt_projection_failure_fails_closed` (extended to
  assert the fail-closed verdict still carries `judge_agent_id`/
  `judge_model`/`judge_usage` from the already-completed provider call).
  (Devin review on #961) One more accounting-loss finding in the same
  vein: `_FastMLSIJudgeAdapter` only captured `served_agent_id`/
  `served_model` on completion, not usage, so a malformed structured
  verdict raised by fast-mlsirm *after* the provider call itself
  succeeded (inside `judge()`'s own response parsing, before ever
  returning a `result` object to `_model_judge_verification`) still
  discarded that call's real usage on the way to its two outer
  fail-closed returns (`except components.format_error` / generic
  `except Exception`). The adapter now also records `served_usage` at
  completion time, and both outer except blocks include whatever subset
  of `judge_agent_id`/`judge_model`/`judge_usage` a new
  `_judge_adapter_accounting_fields()` helper finds already captured on
  the adapter -- empty when the failure happened before any call
  completed (nothing to account for), populated otherwise. New
  regression test
  `test_fast_mlsirm_format_error_after_completed_call_preserves_accounting`:
  the scripted judge calls the adapter's `complete()` (a real, successful
  completion) before raising the configured format error; asserts the
  fail-closed result still carries `judge_agent_id`/`judge_model`. The
  pre-existing `test_fast_mlsirm_format_error_fails_closed` (whose judge
  raises before ever calling the adapter) is extended to assert the
  opposite: no accounting fields, since genuinely no call happened.
  (Devin review on #961) The same residual gap existed one call site
  earlier: `_FastMLSIJudgeAdapter.complete_structured()` only stored
  `served_agent_id`/`served_model`/`served_usage` via `_completion_payload`,
  which runs *after* `ModelClient._response_content()` validates the
  response has usable assistant content. A real, billed provider response
  with no usable content (reasoning-only, or a missing message) makes
  `_response_content` raise before `_completion_payload` ever runs, so that
  already-incurred structured-call spend was lost the same way the
  previous fix closed for judge-side (fast-mlsirm) failures. Accounting is
  now captured immediately once `proxy_send()` returns, before content
  validation runs. New regression test
  `test_judge_adapter_preserves_accounting_on_malformed_structured_response`:
  `proxy_send` returns a response with real `usage` but no assistant
  content; asserts the raised `ProviderResponseError` still leaves
  `served_agent_id`/`served_model`/`served_usage` populated on the adapter.
  (CodeRabbit review on #961) All of the accounting-preservation fixes
  above still had one gap: every site that builds `judge_usage` (the
  ACCEPT-path verdict, and `_judge_adapter_accounting_fields`'s two
  fail-closed branches) only included it when the provider response's own
  `usage` was a truthy dict — a completed call whose response carried no
  valid usage (missing, `None`, or the wrong type) still vanished from
  `judge_usage` entirely, making that real, incurred call invisible to
  `_run_budget_output_by_model`/`spend_analytics` — not even counted as
  estimated, just silently absent.
  **Correction (Devin review on the same #961 fix)**: the first attempt at
  this fix recorded an explicit `{"prompt_tokens": 0, "completion_tokens":
  0, "total_tokens": 0}` whenever a call completed, matching fast-mlsirm's
  own `_usage(trace)` zero-fill. That made a genuinely unmeasured call
  indistinguishable from one the provider actually reported as zero-cost
  — `spend_analytics`'s `usage_source` labeling then presented an
  unmeasured paid call as `"reported"`, contradicting this repo's own
  Honest metrics convention (`CLAUDE.md`; the
  "missing/invalid judge usage stays absent" framing several paragraphs
  above is also superseded by this correction, back to its original
  intent). `judge_usage` is now left genuinely absent when unmeasured;
  `judge_agent_id`/`judge_model` alone keep the call attributable, and
  both `_run_budget_output_by_model` (budget enforcement) and
  `spend_analytics` (buyer-facing reporting) now fall back to
  `estimate_tokens()` — the same ~4-chars/token heuristic estimate the
  worker-step trace loop already uses for a step with no reported usage —
  routed through the same `_step_output_tokens` helper so the honest
  reported-vs-estimated split (`usage_source: estimated/reported/mixed`)
  falls out for free instead of being hand-rolled. Real provider-reported
  usage still passes through unchanged and is still preferred whenever
  present.
  **Second correction (a further Devin review on the same fallback)**:
  that estimate was first taken from `verification["verifier_output"]` —
  the *worker's answer*, i.e. the judge's own *input*, not what the judge
  itself generated. A judge that reads a long answer but writes a short
  "ACCEPT" verdict (or vice versa) would be mis-sized in either direction.
  `_FastMLSIJudgeAdapter` now also records `served_output` (the judge's
  raw completion text) at the same point it already captures
  `served_agent_id`/`served_model`/`served_usage`, and the shared accounting
  helper persists it as `judge_output_text`. Both budget/spend consumers estimate from
  `judge_output_text` instead of `verifier_output`.
  `tests/test_batch_optimizer.py::test_batch_route_budget_counts_only_the_current_uncommitted_worker`
  updated twice in the course of this: its local scripted judge never
  calls the adapter at all, so the expected budget remains the 7 real
  worker tokens; no nonexistent judge call or cost is fabricated. New regression test
  `test_completed_judge_call_with_no_reported_usage_still_counts_toward_budget`
  drives the existing scripted-client ACCEPT path (which never supplies a
  usage dict), asserts `judge_usage` stays absent, `judge_output_text`
  holds the exact judge completion, and the budget contribution matches an
  estimate from that text specifically — deliberately different in length
  from `verifier_output` so the two can't pass by coincidence.
- (Devin review on #958) `_orchestrated_provider_completion`'s structured/
  Responses synthesis path (the `single_agent=False` branch of
  `proxy_completion`) resolved its caller-supplied `effort_profile` override
  only for the final `apply_effort_profile` payload call, not for the
  synthesizer's own selection (`_select_agent`), replica lookup
  (`_ranked_agents`), or failover list (`_failover_candidates`) — those three
  call sites omitted `effort_profile` entirely and so silently fell back to
  the raw `role_effort_catalog` entry inside `_ranked_agents`. A fail-closed
  override (`unsupported_provider_fallback` other than `"omit"`) could still
  rank/select an unproven-support agent ahead of a proven one, and
  `apply_effort_profile` then raised `EffortProfileError` outright — with no
  failover, unlike the identical scenario on the plain passthrough path,
  which already threads its override through every selection call site. Now
  resolves `effort_profile or self._role_effort_profile("synthesizer")` once,
  up front, and passes it to all three call sites, matching the passthrough
  path's existing pattern and `_ranked_agents`' own documented intent that
  every role-based selection path -- "structured synthesis" included -- stay
  consistent with the effort catalog's eligibility guard.
- (CodeRabbit review on #946) **Credential leak via cross-host redirect,
  doubled by #923's retry.** `_fetch_json` -- the function every standard
  provider's authenticated "list models" call goes through (openai,
  openrouter, nvidia_nim, nvidia_nim_sub, bytez), including under #923's one
  bounded retry -- called plain `urllib.request.urlopen`, whose default
  `HTTPRedirectHandler` copies the `Authorization` header onto a redirected
  request even when the redirect target is a completely different host
  (unlike some other HTTP clients, urllib never strips sensitive headers on
  cross-origin redirects). A malicious or compromised provider endpoint
  issuing a 3xx redirect could have exfiltrated the credential, and the
  retry meant up to twice per discovery attempt. `_fetch_json_same_host_https`
  already carried the correct fix for this exact risk (`_TrustedDiscoveryRedirectHandler`,
  raising on any redirect leaving the original host) for a different call
  path; `_fetch_json` now goes through the same protection via a new shared
  `_open_trusted_discovery_request` helper, so both functions get one
  single-implementation redirect guard instead of two copies that could
  drift apart. A legitimate same-host redirect (e.g. a real provider's
  `/v1/models` -> `/v2/models`) still succeeds unchanged.
- (CodeRabbit review on #946) The `configured_gateway` provider's
  `/model/info` metadata fetch now also catches `RuntimeError` (raised by
  `ModelClient._resolve_addresses`/`_open_provider` on a DNS or
  request-validation transport failure), matching the primary list-request
  retry loop's except tuple. Previously a raw `RuntimeError` from this one
  metadata fetch escaped `discover_provider_models` uncaught and aborted the
  entire discovery pass instead of just this provider's metadata.
- (CodeRabbit review on #946) `server.py`'s per-request `latency_ms` no
  longer counts a keep-alive connection's idle time between requests.
  `request_started` used to be timestamped immediately before
  `BaseHTTPRequestHandler.handle_one_request()`, whose first action is a
  blocking `self.rfile.readline()` that, on a reused connection, waits on
  the client's next request rather than doing any work. The timestamp is
  now taken inside an overridden `parse_request()`, right after that
  blocking read has already returned real request bytes, so `latency_ms`
  reflects only actual request handling.
- (CodeRabbit review on #946) `orchestrator.py`'s retry-outcome
  classification (no retry budget at all / budget exhausted / stopped early
  on a non-transient error) was duplicated verbatim in
  `ModelClient._send_with_retry` and `_send_raw_with_retry` -- duplication
  that had already caused a real regression once, when a fix landed in one
  copy but was missed in the other (see the round-4 `provider_no_retry_budget`
  fix above). Extracted into one shared `_log_retry_outcome` helper both
  methods call, so the two call sites cannot diverge again.
- (CodeRabbit review on #946) `debug_logging.response_metadata_for_log`'s
  `usage` summary now keeps only a fixed allowlist of known counter names
  (`prompt_tokens`, `completion_tokens`, `total_tokens`, `input_tokens`,
  `output_tokens`; see `SAFE_USAGE_COUNTER_KEY_NAMES`), not any string key
  with a numeric value. A provider's `usage` object is upstream-controlled
  JSON, so a key shaped like `"customer_note=<secret>"` with a throwaway
  numeric value would otherwise have sailed through the old numeric-only
  filter and reached DEBUG output verbatim (CWE-532).
- (round 6) `model_discovery.py`'s `_fetch_json` read an authenticated
  provider's entire response body into memory before parsing it as JSON
  (`response.read()`, no size bound) -- unlike `_fetch_json_same_host_https`
  and `_fetch_configured_gateway_json`, which already capped their reads at
  `MAX_DISCOVERY_RESPONSE_BYTES` (8 MiB) and failed closed on an overage.
  A large or malicious/misbehaving provider response (an outage page dumped
  as an unbounded body, or a compromised endpoint) could exhaust worker
  memory before JSON parsing ever ran (CWE-400). `_fetch_json` now shares
  the identical bounded-read-then-check pattern: it reads at most
  `MAX_DISCOVERY_RESPONSE_BYTES + 1` bytes and raises `ValueError` if the
  body exceeds the cap, applied consistently everywhere
  `_open_trusted_discovery_request`'s response body is consumed in this
  module.
- (round 6) `_log_retry_outcome`'s zero-retry-budget classification
  conflated two different situations under the same `provider_no_retry_budget`
  WARNING: an agent with a genuinely zero configured retry budget, and
  `ModelClient.proxy_send_once`'s deliberate one-shot call
  (`allow_transient_retries=False`, used so an already-failing-over
  passthrough request cannot itself amplify load with a nested retry loop).
  `_send_raw_with_retry` computes `retry_limit = self._retry_limit(agent) if
  allow_transient_retries else 0`, so the forced-to-0 one-shot case looked
  identical to a real zero-budget agent by the time it reached
  `_log_retry_outcome`, producing a false "no retry budget" warning even
  when the agent's real budget was non-zero. `_log_retry_outcome` now takes
  `allow_transient_retries` explicitly and, when a caller forced the retry
  count to zero rather than the agent's own configuration being zero, logs a
  distinctly named `provider_one_shot_call_failed` WARNING instead of
  `provider_no_retry_budget`. `_send_with_retry` has no such caller-forced
  restriction and is unaffected.
- (round 7) `server.py`'s `_send`/`_send_text`/`_send_bytes`/`_send_sse`/
  `_begin_sse` all set `self._last_status` to the *intended* status before
  handing off to `_write_response`, then ignored its boolean return value.
  `_write_response` deliberately swallows a dead peer's
  `BrokenPipeError`/`ConnectionError`/`OSError` (so a disconnected client
  cannot crash the handler thread), but that left `_last_status` claiming a
  status the client never actually received, so the per-request INFO
  summary (`_log_request_summary`) logged a false "200 delivered" for a
  request that was really cut short mid-write. `_write_response` now resets
  `_last_status` back to `None` -- this module's existing "response was
  never sent" value -- whenever it catches a disconnect, fixing every
  current and future writer uniformly at their one shared choke point
  instead of patching each writer individually.
- (round 7) `_log_request_summary` also silently dropped a request that
  *did* deliver bytes but whose request line `parse_request` rejected as
  malformed (or that stdlib's `handle_one_request` rejected outright as too
  long): a real 400/414 was sent and captured into `_last_status` via the
  `send_response` override, but `command`/`path` stay unset for these
  cases (stdlib's own `parse_request` resets `self.command` to `None` "in
  case of error on the first line" and never reaches the assignment that
  would set `path`), so the old "nothing to report" guard -- checking only
  method/path -- skipped logging it, indistinguishable from a keep-alive
  connection closing with zero bytes. The guard now also logs when
  `_last_status` was actually recorded, while still skipping the true
  no-bytes-at-all case.
- (round 7) Two CodeQL `py/clear-text-logging-sensitive-data` HIGH alerts on
  `tests/test_debug_logging.py`'s redaction positive/negative-control pair
  (lines 144 and 167) are precise, per-line `# codeql[...]` inline
  suppressions with an explanatory comment, not a code change: both lines
  log a hardcoded, non-functional fake secret (`# noqa: S105`'d against
  bandit/ruff) as a deliberate test fixture -- one proving `redact_text`
  masks it, the other (the negative control) proving the same literal
  leaks with no redactor, which is exactly what the test exists to show.
- (round 8) Follow-up correction to round 7's `_write_response` fix: clearing
  `_last_status` on *every* caught disconnect was too broad. A write failure
  can strike either before the status line/headers were ever flushed (the
  client received nothing -- clearing is correct) or after `end_headers()`
  already completed (a later body-write chunk, or a later `_write_sse` frame
  on a stream `_begin_sse` already opened -- the client genuinely received
  the real status, so clearing it would falsely report "no status" for a
  request that was, in fact, answered). Every `_send*`/`_begin_sse` writer
  now sets a new `self._response_headers_sent` marker immediately after its
  own `end_headers()` call returns (reset to `False` once per request by
  `handle_one_request`); `_write_response`'s disconnect handler now clears
  `_last_status` only when that marker is still unset, preserving it
  otherwise. `_write_sse` relies on `_begin_sse`'s already-set marker rather
  than touching it itself, since it is only ever called after a prior
  successful header flush.

### Added

- Verbose/debug logging (ADR 0005): a new stdlib-only `debug_logging.py`
  module, a `--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}` CLI flag with a
  `--verbose`/`--debug` shorthand (default unchanged: `WARNING`), and new
  instrumentation at the provider retry loop, per-agent circuit breaker, evidence-based ranking
  (`_ranked_agents`/`_select_agent`), model discovery, and one body-free
  per-request summary line in `server.py`. The DEBUG response-body summary
  logs only an allowlisted metadata shape (`debug_logging.response_metadata_for_log`:
  whether the response is error-shaped, the model name, the choice count, and
  numeric usage counts) rather than the payload itself, so ordinary response
  text (message content, tool-call arguments, an error message) never reaches
  DEBUG output — `redact_text`/`redact_value`'s in-string value-pattern
  matching and the additional key-name-aware
  `debug_logging.redact_credential_shaped_keys` pass (catches a secret nested
  under a credential-shaped JSON key regardless of its value's shape) are
  applied on top of that allowlist, defense-in-depth, plus a handler-level
  filter safety net. Raw prompt/answer text is never logged, only lengths and
  identifiers. The INFO per-request summary strips any query string before
  logging, is skipped entirely for a keep-alive connection's closing call
  that parsed no new request (previously logged the prior request a second
  time, statuslessly), and now also captures a status the framework itself
  sends (e.g. its built-in 501 for an unsupported HTTP method), not just
  status codes sent through this module's own response writers. A
  `--log-level`/`--verbose`/`--debug` flag placed before a subcommand
  (`register-credential`, `discover-models`, `check-fast-mlsirm`) no longer
  bypasses subcommand dispatch, including an abbreviated spelling of one of
  those flags (`--log-l`, `--ver`) — every CLI parser now sets
  `allow_abbrev=False` so an abbreviation is rejected consistently
  everywhere with a clear error, rather than silently accepted by one parser
  and not another. The retry loop's `provider_exhausted` WARNING now fires
  only when a real, non-zero retry budget was actually used up; an
  immediate non-transient (permanent) rejection with budget left logs the
  distinct `provider_rejected_permanent`, and any failure at all with a
  configured retry limit of 0 (there was never a budget to exhaust) logs a
  separate `provider_no_retry_budget` carrying the error's own
  transient/non-transient classification explicitly — collapsing a
  zero-budget *transient* failure into "permanent" would conflate "no retry
  budget was configured" with "this error is non-retryable by nature", two
  independent facts. The handler-level
  redaction safety net now also redacts an exception's traceback
  (`exc_info=True` / `logger.exception(...)`), not just `record.msg` — a
  secret embedded in an exception's own message (e.g. an upstream error
  reflecting `api_key=sk-...`) previously reached DEBUG output unredacted
  via the traceback even when the message-level redaction worked correctly.
- Generalized the Models.dev free-cost cross-reference (ADR 0032) beyond
  `opencode_zen` to `nvidia_nim`, `nvidia_nim_sub`, and `openai` via a new
  declared `ProviderModelSource.models_dev_provider_id` field, and hoisted
  the Models.dev fetch into `discover_all_models` so every source that wants
  it shares one fetch instead of repeating it (ADR 0041). Restores real
  `orchestrator/free` pool coverage from NVIDIA NIM; `bytez` remains a
  documented permanent gap and `openai` a self-correcting currently-empty
  one. Classification stays exact-`model_id`-match and fail-closed.
- Fail-closed commercial release authorization bound to a signed, exact-head
  GitHub evidence snapshot, propagated through every downstream commercial
  readiness report while keeping local product evidence inspectable.
- Provider-affine asynchronous video jobs now return an opaque gateway id and
  keep status polling and content download bound to the exact provider agent
  that accepted the submission (ADR 0037); new ownership and first-complete
  usage observations are stored as separate registry records.
- A fail-closed, transactional evidence boundary for the optional NVIDIA NIM
  benchmark with immutable task/scorer identities and complete provenance.
- Bounded first-valid-completion racing for operator-declared equivalent model
  group endpoints across text and media capabilities, with fail-closed contract
  comparison and winner/cancellation provenance.
- Commercial evidence and handoff resources now use customer-facing canonical
  REST and Python names; the former `buyer_*` entry points remain explicit
  deprecated aliases so existing integrations can migrate without disruption.
- An explicit `--max-body-bytes` server option that preserves the 64 KiB
  default while allowing bounded authenticated multimodal deployments.
- A fail-closed `--production` authentication gate that rejects legacy
  single-token startup and insecure admin-session cookies; canonical Compose
  now bootstraps separate admin/inference KV credentials.
- Anti-heuristic routing evidence ladder (ADR 0034): `DOMAIN_HINTS` and
  `COMPLEX_HINTS` keyword tables are deleted; ordering is now
  eligibility contracts -> declaration priority/capability fit/cosine
  affinity over operator-declared metadata (cached dense embeddings) ->
  measured intra-group quality then successful responses per second, with
  token throughput retained as diagnostic evidence. Workflow triage is
  a strict structured call that fails closed to conducted orchestration;
  verdicts are memoized by content hash. Real-time fast-mlsirm judging on
  direct routes feeds a second Beta-Bernoulli quality ledger and drives
  failover within the retry budget; `--no-realtime-judge` preserves the
  legacy verification shape. APA 7 references live in
  `docs/doctoring/measured-routing-evidence.md`.
- Product & technical gap baseline (`docs/product-technical-gap-baseline.md`)
  indexing buyer-visible gaps against open PRs/issues with update protocol.
- Reproducible k6 end-to-end concurrency coverage with a synthetic delayed
  provider, simultaneous liveness traffic, and exact baseline/candidate
  measurements.
- Citation-backed `docs/adr` set: APA 7th references on the tool-execution fallback policy, plus accepted control-plane, cost-aware sync-versus-batch, and MSA-leaf composition ADRs, indexed from `docs/adr/README.md`.
- Structured tool failure categories, stable fallback actions, and public
  adapter exceptions.
- Secret-free `tool_fallback_decision` audit events.
- Exact regression coverage for the Strix `Tool execute_command not found in agent strix` failure.
- Operator-managed model groups: `ModelAgent.group_name`, measured intra-group
  routing (Beta(1,1) posterior success probability over Jacobson-gain EWMA
  latency), group-alias model resolution, `/api/v1/model_groups` CRUD with
  normalized persistence, Admin editing, and routing-evidence display across
  text, image, video, speech, transcription, embeddings, rerank, and audio.
  (#834, ADR 0032)
- OpenCode Zen provider discovery plus explicit free-tier classification from
  structured Models.dev zero-price metadata; `discover-models --free-only`.
  (#834)
- Versioned `reasoning_effort_profile` catalog (issue #568) with fail-closed
  parse, per-role bindings, replayable snapshot hash, and an equal-budget
  true-θ RMSE ablation that emits θ̂ and RMSE(θ̂, θ). Sampling temperature
  is not reasoning effort. Production route/conduct defaults stay locked
  until `production_default_change_allowed` is true.
  Next action: run `python -m pytest -q tests/test_reasoning_effort_profile.py` and keep
  live defaults unchanged while the gate is false. Pass
  `role_effort_catalog=default_role_effort_catalog()` to attach the same
  `reasoning_effort_snapshot` on `complete`, `run`, `stream_route`, and
  `batch_route`; omit it to keep today's payload.
- Add an optional provider-neutral NVIDIA NIM benchmark harness that dynamically discovers the live `/v1/models` catalog, probes every discovered model under bounded concurrency and a hard request cap, records machine-readable capability outcomes, and compares direct, route-once, bounded-conduct, and explicit pricing-scenario policies over a locked task manifest.
- Add deterministic no-egress benchmark dry runs, secret-redacted JSON/CSV/Markdown evidence artifacts, paired bootstrap uncertainty, quality-latency and quality-hypothetical-cost Pareto frontiers, all-modality catalog fuzzing, and a manually gated benchmark workflow.
- Add a validated deterministic one-frame H.264 MP4 probe fixture, complete preflight reservation for every discovered model-capability cell plus the full evaluation envelope, and explicit evidence-sufficiency fields that keep the bundled smoke manifest from authorizing production routing.
- Add direct benchmark quality gates for 100% production statement/branch coverage, 100% public docstrings, wheel build/install/import smoke testing, and optional-import isolation.
- Streamed `/v1/responses` workflow runs now request provider usage only from
  agents explicitly marked `stream_usage_supported`, preserve provider-declared
  SSE usage, record per-step `stream` cost-ledger rows, and expose cost status
  plus usage-record identities. Missing provider usage is explicitly
  unavailable; the gateway does not estimate billing tokens from the final
  answer, and nested gateway upstreams remain compatible (ADR 0040).

### Fixed

- `TaskOrchestrator._invoke`'s route/Conduct primary chat call now classifies
  a `ProviderUpstreamError` (5xx, 429, network) directly from its own
  already-computed `retryable` flag (`tool_fallback.classify_provider_transport_failure`)
  instead of `classify_tool_failure`'s tool-execution-oriented message-text
  heuristics. A plain, side-effect-free completion request can always be
  safely retried or handed to the next ranked candidate, so this classifier
  never returns `fail_closed`; previously an upstream error body that
  happened to also contain a tool-fallback keyword (e.g. a 500 whose message
  said "invalid arguments") could be misclassified into an
  `invalid_arguments`/permission/policy fail-closed row and stop
  `orchestrator/free`/`orchestrator/auto` failover on a request that never
  touched a tool. `orchestrator/free` still never advances into a priced
  agent, and exhausting every free/auto candidate still fails closed with the
  last classified provider error; `classify_tool_failure` itself, and the
  provider's own `tool_execution_stopped` signal, are unchanged. See
  [ADR 0001's amendment](docs/adr/0001-tool-execution-fallback-policy.md#amendment-2026-08-30-explicit-provider-transport-classification).
  Motivated by the `orchestrator/free` review-sidecar reliability gap in
  `ContextualWisdomLab/.github` PR #1433.
- Discover chat models from metadata-free OpenAI-compatible gateways. A
  configured gateway whose `/v1/models` rows carry no modality/capability
  metadata previously produced empty-capability chat rows that runtime
  auto-discovery silently dropped, while embedding deployments that kept
  richer `/model/info` evidence survived ("embedding discovers, chat does
  not"). Transport-compatible identifiers now inherit the `chat`
  capability, and `--auto-discover-model-agents` uses the same
  chat-candidate rule as the serving bootstrap. (#868)
- Accept `orchestrator/auto`, `orchestrator/free`, and the advertised
  `contextual-orchestrator` gateway default on the structured chat surface:
  a requested `response_format` is a preference (never a fail-closed tag
  miss for an untagged-but-available pool), vision stays a hard
  entitlement, and a trace disclosed on the structured path authorizes
  trace purpose and audits the disclosure before release, matching the
  plain chat gate. (#868)
- Provider/model failures no longer collapse into a generic `internal_error`.
  A typed provider-error taxonomy (`contextual_orchestrator.provider_errors`)
  classifies every upstream HTTP status, network, TLS, and transport failure
  into OpenAI-compatible error codes (`rate_limit_exceeded`,
  `authentication_error`, `model_not_found`, `provider_timeout`, ...) with the
  client status, retryability, and one bounded redacted message (CWE-209).
  Chat, passthrough, stream, and batch transports all surface the classified
  cause; a fully-failed agent pool surfaces the final classified failure
  after measured failover instead of an opaque collapse. Server error
  payloads carry actionable next-step guidance per failure family.
- Telemetry spans now carry concrete GenAI semantic-convention evidence:
  `gen_ai.usage.input_tokens/output_tokens/total_tokens` from provider-reported
  counts, served `gen_ai.response.model`, `gen_ai.response.finish_reasons`,
  request latency, and classified `error.type` plus upstream status on
  failures — replacing exception-class-only error labels. Chat, streaming,
  and passthrough responses share this evidence path, and finish-reason arrays
  are bounded to the OpenTelemetry default span-attribute budget.
- Orchestration traces now include per-step telemetry evidence: streamed,
  batched, routed, and conducted steps record `model`, `provider`, and
  `latency_ms` alongside usage so workflow runs answer which model served a
  step, how long it took, and what it cost.
- Runtime agent create/PATCH now accepts and persists the explicit
  `stream_usage_supported` capability, and the admin-safe agent view exposes it.
- Require `--allow-public-bind` for every non-loopback address, not only wildcard
  binds, so a specific network interface cannot bypass the public-bind guard.
- Reject shared or identical split bearer credentials on public binds, while
  keeping the CLI's preliminary host check independent from final credentials.
- Experimental CEFR criterion-observation gateway with exact contract checks,
  independent rater blindness, bounded structured-output parsing, replay
  provenance, and human-review routing; it emits no final CEFR level or score.
- Accept the standard Chat Completions `stream_options.include_usage=true`
  request and emit provider-reported usage in a usage-only SSE chunk when
  available after the terminal stop chunk; pass the option through live provider
  streams; keep unsupported obfuscation flags fail-closed.
- Accept `stream_options.include_usage=true` for single-agent `tools`
  passthrough streaming too (e.g. an OpenAI Agents SDK client such as Strix):
  `_chat_response_sse_chunks` already frames the one non-streaming upstream
  call's response into a correctly-shaped terminal SSE chunk alongside
  `tool_call` deltas, honestly labeling usage `reported` when the provider
  returned it and falling back to its existing `estimated` labeling (never
  fabricated as `reported`) when a provider's JSON omits `usage` — the prior
  blanket rejection covering this case was an overbroad validation gate, not
  a genuine limitation of the passthrough itself. `response_format`-only
  structured passthrough (conduct mode, whose usage comes from a multi-step
  workflow's cost ledger and may be unmeasured with no per-field tag to
  distinguish it) keeps rejecting the combination rather than risk that
  estimate being framed as `reported`.
- Billing usage-export failures now appear in the operator-safe telemetry health
  counters instead of only in emitted error events.
- Billing usage export now follows accepted ledger writes and skips duplicate,
  failed, or queue-dropped records.
- Billing export from a caller-owned SQLite transaction now waits for
  `CostLedger.flush()` after commit, so rollback cannot leave a billing-only
  event.
- A billing-backed non-blocking SQL store now writes appends synchronously while
  a caller-owned SQLite transaction is open and defers billing export until
  commit confirmation, rather than moving them outside the caller's transaction.
- Generated workflow planning now advertises only agents eligible under the
  active ZDR request policy.
- Accept function-tool descriptions up to the existing bounded request-body
  limit instead of enforcing an unsupported 1,024-character gateway cap.
- Treat a provider's explicit 1,024-character tool-description rejection as a
  request-size failure eligible for virtual-model failover.
- Preserve request-size exhaustion semantics for media capability failover
  without degrading provider health.
- Allow multimodal JSON up to OpenAI's 512 MB image-input request ceiling when
  the operator raises `--max-body-bytes` above the secure 64 KiB default.
- Add principal-owned OpenAI-compatible `/v1/files` resources with disk-backed
  512 MB uploads, the 200 MB Batch JSONL limit, and provider replicas for 413
  failover without exposing upstream file IDs.
- Route initial and fallback AUTO/FREE candidates with fast-mlsirm Judge IRT
  evidence for similar system/user interactions; candidates without converged
  psychometric evidence retain the existing measured-routing order.
- Run the full test suite from the hash-locked `uv.lock` so git-backed
  `fast-mlsirm` and its `numpy` dependency are installed in CI and locally.
- Validate orchestration-trace requests before every chat execution branch and
  require trace-purpose authorization before access-report lookup.
- Bind HTTP-created batch routing jobs to the authenticated principal and
  require the same owner for status polling and trace-bearing result retrieval;
  owner mismatches fail closed as not found.
- Mixed structured workflows now retain a cost-ledger row for calls whose
  provider omitted usage, using the existing token-counting fallback while
  preserving reported counts for the other calls in the same workflow.
- Virtual-model tools, structured-output, and Responses passthrough requests now
  advance once across distinct capability-ranked providers after explicit
  upstream rejection, stale-model responses, or temporary pre-request DNS
  failure; concrete models and ambiguous network outcomes fail closed.
- Recognize string-form upstream tool-description-limit errors from providers
  that do not wrap the error in an ``invalid_tools`` object, preserving the
  bounded passthrough failover contract.
- Make per-request budget checks constant time while preserving exact parity
  with full spend analytics across persisted, replaced, estimated, and
  provider-reported workflow runs.
- Bound inactive HTTP/1.1 request reads to the configured rate-limit window so
  slow clients cannot retain unbounded request threads.
- Reject missing profiles, blank `profile_version`, and fractional seeds.
  Snapshot hashing now fails closed on extra or missing roles. The
  production-default gate returns false on junk reports and on
  `measurement_status=estimated`. Access-list scope is a real ablation
  factor, not a duplicate label.
- `free_discovered_models()` no longer admits a zero-priced model that
  declares a non-text input modality (e.g. NVIDIA NIM's
  `meta/llama-3.2-90b-vision-instruct`, whose Models.dev evidence reports
  `cost: 0/0` and, misleadingly for this exact deployment, `tool_call: true`)
  into the general-purpose `orchestrator/free` pool. That pool serves
  arbitrary request shapes -- including Strix's tool/function-calling
  requests -- without knowing in advance which capability a request needs, so
  a free model whose only price-evidenced identity requires an extra input
  modality is reserved for a caller that explicitly needs it, not a general
  worker. Fixes the required Strix Security Scan failure reproduced in
  `ContextualWisdomLab/.github` PR #1198 (run 33325907333, job 99295892400),
  where every one of 3 independent scan attempts exhausted the pool against
  this exact agent with an identical HTTP 400 `invalid_request_error`. A
  model excluded here remains fully discovered and price-evidenced; it is
  only withheld from the free/tool-calling default pool.
- Devin's review on PR #933 found the fix above incomplete: `free_discovered_models()`
  itself is now pure price-based inventory again (every zero-priced model
  counts, restoring correct `--free-only`, `free_tier_count`, and free-tier
  data-privacy totals), and a new, separately named selector,
  `general_free_serving_candidates()`, carries the modality-based exclusion
  for composing the blind `orchestrator/free` pool specifically. More
  importantly, that exclusion previously lived only inside the one function
  this PR touched: `_auto_discover_runtime_agents` (`--auto-discover-model-agents`)
  and `provider_bootstrap._active_agent_from_discovered` (used by both
  `bootstrap_provider_runtime` and, through it,
  `provider_catalog_bootstrap.bootstrap_provider_catalog_runtime`) tag an
  agent `cost:free` directly from raw price evidence and never consulted it,
  so the incident model could still reach a live `cost:free` agent through
  either path. The fix is now a single choke point, `TaskOrchestrator._is_free_agent`,
  which every `orchestrator/free` selection path shares: an agent whose tags
  declare a non-text input modality is never treated as free-pool eligible
  there, regardless of which code built it or how old that agent-pool row is
  -- while `cost:free` keeps meaning "honest zero price" everywhere else,
  preserving `provider_catalog_store.py`'s durable `is_free` round trip.
  Verified against three explicit modality fixtures (text-only, vision-only,
  and text+image); evaluated and rejected narrowing the exclusion to spare a
  model that "also declares text" (Devin's other suggestion) because the
  incident model itself declares both `text` and `image` per Models.dev, so
  that narrowing would have silently re-admitted it.
- Devin's review on the fix above found it had overshot: `TaskOrchestrator._is_free_agent`
  is also the predicate `_capability_agents` uses for every explicit
  capability-scoped free route (`/v1/audio/transcriptions`, `/v1/videos`,
  image, speech, rerank), where a free agent's non-text `input:<modality>`
  tag is the capability's own expected shape, not a surprise -- so the
  shared choke point made those genuinely free agents unreachable through
  their own free route. `_is_free_agent` now reverts to plain, modality-blind
  price evidence; a new, stricter `_is_general_free_agent` (price-blind
  `_is_free_agent` plus the non-text-input exclusion) carries the exclusion
  only at capability-blind general-chat call sites (`proxy_completion`,
  `_orchestrated_provider_completion`, `route_once`, `conduct`,
  `list_openai_models`'s advertising check, and `server.py`'s
  capability-agnostic `_require_pool_model` branch). The discovery-time and
  selection-time "what counts as non-text input" classification is now one
  shared predicate, `chat_capability.requires_non_text_input`, so
  `model_discovery._requires_non_text_input` and
  `orchestrator._agent_requires_non_text_input` cannot drift apart.
- Devin's next review pass found `general_free_serving_candidates()` still
  overcounted: it admitted a zero-priced, text-input catalog row regardless
  of whether it could ever actually become a serving agent, so an
  `evidence_only` row (`agent_from_discovered` refuses to build an agent from
  one) or a free non-chat-capable model (e.g. an embedding-only deployment)
  both inflated `general_free_serving_count`. The selector now also requires
  `is_routable_discovered_model` -- the same predicate `_auto_discover_runtime_agents`
  and `provider_bootstrap` already require before promoting a discovered row
  to an ordinary chat agent.

### Changed

- The product and technical gap baseline now records the ten open PRs,
  exact-head governance state, and current provider-backed Strix evidence.
- Web requests now use the native `SOMAXCONN` listen backlog and HTTP/1.1
  persistent connections, while the existing per-request daemon threading and
  explicit run-slot admission keep slow provider I/O from blocking liveness.
- Agent invocation now retries explicitly idempotent transient tool failures with bounded exponential backoff within a per-agent budget.
- A shared four-attempt ceiling now bounds the configured same-agent tool retry budget.
- Fail-closed tool decisions now have dedicated JSON and SSE error contracts, and preserve the observed failure kind in secret-free audit evidence.
- Missing or unavailable tools move to the next eligible agent instead of terminating the workflow immediately.
- Return the same `agent_not_found` error code for GET, PATCH, and DELETE worker
  agent requests that address an unknown or unauthorized pool member.
- Strix B105 false positives eliminated at the source: KV credential-name
  constants renamed `*_CREDENTIAL_NAME`; readiness label keys renamed
  `readiness_ok/warning/failure`. (#833)
- Expose a stable complete-run request planning view and align API, CLI, manual-workflow, and deterministic test caps with the locked thirty-task evidence floor, preserving fail-before-probe behavior.
- Fail closed after catalog discovery but before capability egress when the complete all-model probe and equal-budget evaluation plan cannot fit the configured hard request cap; the monthly 2,000-request ceiling covers the representative 127-model, thirty-task, seven-worker plan requiring 1,924 requests, including route-once's full equal-call envelope and direct-cell judge calls, and still rejects larger plans before partial probing.
- Align the monthly NIM live schedule with the reviewed access-cost evidence window while preserving fail-closed behavior after its validity horizon.
- Scale the equal NIM policy-cell token budget with the five-call envelope so the conduct arm can carry its prompts while every policy retains the same total allowance.
- Treat provider HTTP 401 and 403 responses during capability probes as authentication rejection, and keep live evaluation on the same DNS-pinned benchmark transport used by discovery and probes.
- Pin Atheris by Python interpreter so the Python 3.11 fuzz job and the newer central coverage-evidence image both install a published, hash-locked wheel.
- Record the reviewed current NVIDIA NIM General FAQ as expiring evidence for free Developer Program hosted-endpoint prototyping access, while keeping NVIDIA AI Enterprise production licensing and every hypothetical model rate explicitly separate.
- Require live hypothetical pricing scenarios to carry reviewed source, reviewer, review date, validity horizon, rate basis, uncertainty, and explicit rates; reject unreviewed, incomplete, future-dated, or expired price evidence before provider egress.
- Give direct, route-once, conduct, and reviewed cheapest-worker cells one equal total prompt-plus-completion token budget and one common five-call envelope, with configured-versus-observed evidence in every cell.
- Keep the optional NIM adapter lazy: importing the runtime package no longer imports the benchmark or mutates benchmark globals.
- Record immutable source-artifact digests and exact Git tree identity in the integration evidence so buyers and reviewers can reproduce the accepted benchmark source independently of transient workflow state.

- NIM benchmark provider responses are bounded to 8 MiB, and live HTTPS
  requests use validation-time public-address pinning with original-host TLS,
  no proxy lookup, and no redirect following.
- Live pricing evidence is rejected unless its source, reviewer, dates, rate
  basis, uncertainty, and explicit rates are complete and current.
- Direct, route-once, conduct, and reviewed cheapest-worker cells share one
  total token budget and five-call envelope, with configured and observed
  values recorded separately.
- Complete catalog probing and the full evaluation reserve are planned before
  capability egress; the benchmark fails closed when the configured cap is too
  small, and the scheduled workflow uses a reviewed 2,000-request ceiling.
- The NIM access-cost evidence, hypothetical pricing provenance, and source
  artifact digests remain explicit and independently reproducible.

### Security

- HTTP/1.1 responses now close the connection when authentication, rate
  limiting, media-type validation, or another boundary rejects a request
  before its declared body is consumed, preventing response-stream desync.
- Ambiguous non-idempotent outcomes, invalid arguments, permission denial, and policy denial fail closed.
- Fallback errors and audit events do not copy provider exception text, tool arguments, outputs, or credentials; fail-closed exceptions also sever the original cause chain so later traceback logging cannot recover them.
- Worker-agent pool boundaries are enforced beside object lookup so a
  different-pool id can no longer read or mutate another pool's agent.

- Provider hosts resolving to any non-globally-routable address are rejected,
  including RFC 6598 shared space; benchmark artifacts refuse secret leakage.

### References

- Sakana AI. (2026). *Sakana Fugu Technical Report*.
  https://github.com/SakanaAI/fugu/blob/main/Fugu_technical_report.pdf
- Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025).
  *Trinity: An evolved LLM coordinator* (arXiv:2512.04695).
  https://arxiv.org/abs/2512.04695
- Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025).
  *Learning to orchestrate agents in natural language with the Conductor*
  (arXiv:2512.04388). https://arxiv.org/abs/2512.04388
- Baker, F. B. (2001). *The basics of item response theory* (2nd ed.).
  ERIC Clearinghouse on Assessment and Evaluation.
  https://eric.ed.gov/?id=ED458219

## [0.1.0] - Unreleased

This is the current development baseline, not a published release. It
provides the OpenAI-compatible gateway, route/conduct orchestration, workflow
and access evidence, provider credential boundaries, cost and readiness
reporting, and security-focused contract tests.
