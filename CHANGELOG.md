# Changelog

All notable changes to `contextual-orchestrator` are documented here. The
project follows Semantic Versioning; a version is released only after the
protected `main` branch, required Checks, independent review, and release
artifacts are verified on the same commit.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - Unreleased

### Fixed

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
  still be counted there.

### Added

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

### Security

- HTTP/1.1 responses now close the connection when authentication, rate
  limiting, media-type validation, or another boundary rejects a request
  before its declared body is consumed, preventing response-stream desync.
- Ambiguous non-idempotent outcomes, invalid arguments, permission denial, and policy denial fail closed.
- Fallback errors and audit events do not copy provider exception text, tool arguments, outputs, or credentials; fail-closed exceptions also sever the original cause chain so later traceback logging cannot recover them.
- Worker-agent pool boundaries are enforced beside object lookup so a
  different-pool id can no longer read or mutate another pool's agent.

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
