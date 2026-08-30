# Changelog

All notable changes to `contextual-orchestrator` are documented here. The
project follows Semantic Versioning; a version is released only after the
protected `main` branch, required Checks, independent review, and release
artifacts are verified on the same commit.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - Unreleased

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
  that accepted the submission (ADR 0037).
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
- Experimental CEFR criterion-observation gateway with exact contract checks,
  independent rater blindness, bounded structured-output parsing, replay
  provenance, and human-review routing; it emits no final CEFR level or score.

### Fixed

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
- Accept the standard Chat Completions `stream_options.include_usage=true`
  request and emit provider-reported usage in a usage-only SSE chunk when
  available after the terminal stop chunk; pass the option through live provider
  streams, and reject structured `tools`/`response_format` passthrough before
  execution because it cannot emit that SSE contract; keep unsupported
  obfuscation flags fail-closed.
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
