# Changelog

All notable changes to `contextual-orchestrator` are documented here. The
project follows Semantic Versioning; a version is released only after the
protected `main` branch, required Checks, independent review, and release
artifacts are verified on the same commit.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - Unreleased

### Added

- ADR 0006 defines evidence-gated CPU, MLX, CUDA/OpenCL, Compose, and
  Kubernetes accelerator runtime boundaries.
- Fail-closed commercial release authorization bound to a signed, exact-head
  GitHub evidence snapshot, propagated through every downstream commercial
  readiness report while keeping local product evidence inspectable.
- Provider-affine asynchronous video jobs now return an opaque gateway id and
  keep status polling and content download bound to the exact provider agent
  that accepted the submission (ADR 0037).
- Batch-routing and embedding job handles are now bound to the authenticated
  principal with persistent ownership state; embedding deduplication is also
  principal-isolated and unauthorized polls, results, and cancellations return
  the existing not-found contract (Issue #117 follow-up).
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

### Fixed

- Runtime auto-discovery now applies the configured provider-host allowlist to
  both the serving client and model-catalog source, expands an allowlisted
  blank gateway seed into its exact discovered model agents, and records only
  bounded reason codes when that source is unavailable.
- Route embedding batches through configured remote embedding agents instead
  of returning the standalone deterministic vector.
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
- Mixed structured workflows now retain a cost-ledger row for calls whose
  provider omitted usage, using the existing token-counting fallback while
  preserving reported counts for the other calls in the same workflow.
- Virtual-model tools, structured-output, and Responses passthrough requests now
  advance once across distinct capability-ranked providers after explicit
  upstream rejection, stale-model responses, or temporary pre-request DNS
  failure; concrete models and ambiguous network outcomes fail closed.
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

- Fixed-window admission failures now expose an RFC 9110 `Retry-After` value
  and matching structured delay, while readiness jobs publish the
  admission-derived polling cadence so durable consumers can retry without
  guessing.
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
