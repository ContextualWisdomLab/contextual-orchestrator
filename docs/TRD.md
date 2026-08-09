# Technical Requirements Document

**Document state:** `accepted_architecture`  
**Implementation baseline:** protected `main`; volatile evidence is recorded in
the dated audit in `TRACEABILITY.md`  
**Package baseline:** version `0.1.0`; Python `>=3.10`

## System context

Contextual Orchestrator is a Python service and library. The protected-main
runtime has no mandatory third-party runtime dependency for its standalone
path. PostgreSQL and `pg-llm-batch` are optional adapters. FastAPI, SQLAlchemy,
and Alembic are dependency/design targets but are not used by the shipped
stdlib HTTP runtime.

The public service uses `contextual_orchestrator.server`. For ordinary chat,
`CostRoutingCoordinator` first owns sync-versus-batch choice, token counting,
and the independent cost ledger; the sync path then invokes
`TaskOrchestrator`, which owns route-versus-conduct policy, model/role
selection, execution, traces, evaluation, audit, caches, workflow-derived
budget, and optional SQLite state. `ModelClient` owns provider calls. Raw
passthrough and route-streaming paths bypass parts of that composition and are
explicit gaps below. Agent definitions remain configuration data.

## Requirement identifiers

### Functional requirements

| ID | Requirement | Current state | Verification authority |
|---|---|---|---|
| FR-001 | Accept the documented OpenAI-compatible chat-completion subset. | `implemented_on_protected_main` | `tests/test_openai_passthrough.py`, `tests/test_api_contract.py` |
| FR-002 | Select `route` or `conduct` deterministically from caller mode and policy. | `implemented_on_protected_main` | `tests/test_paper_contracts.py`, `tests/test_optimizer.py` |
| FR-003 | Represent conducted work as ordered steps with role, agent, subtask, access list, latency, and output. | `implemented_on_protected_main` | `tests/test_generated_workflow.py`, `tests/test_paper_contracts.py` |
| FR-004 | Restrict each step context to its declared access list. | `implemented_on_protected_main` | `tests/test_paper_contracts.py` |
| FR-005 | Retry transient provider failures, fail over to an eligible agent, and open/close per-agent circuit state. | `implemented_on_protected_main` | `tests/test_provider_reliability.py` |
| FR-006 | Resolve provider credentials from the configured KV backend. | `implemented_on_protected_main` | `tests/test_kv_credentials.py` |
| FR-007 | Attribute usage across account, service, upstream API, model, team, group, and company. | `implemented_on_protected_main` | `tests/test_cost_ledger.py` |
| FR-008 | Route latency-tolerant work to local or injected batch backends and expose job lifecycle. | `implemented_on_protected_main` | `tests/test_batch_routing.py`, `tests/test_cost_review_server.py` |
| FR-009 | Persist workflow/evaluation/audit/analytics and agent overlays only when explicitly configured. | `implemented_on_protected_main` | `tests/test_persistence.py`, `tests/test_agent_pool_db.py` |
| FR-010 | Expose operator views without returning full traces to untrusted callers by default. | `implemented_on_protected_main` | `tests/test_security_hardening.py`, `tests/test_admin_contract.py` |
| FR-011 | Generate dispatch, OpenAPI, scopes, and endpoint documentation from one route registry. | `accepted_architecture` | parity test required; protected main is incomplete |
| FR-012 | Record or explicitly qualify workflow, persistence, budget, and usage evidence consistently across plain, passthrough, streaming, and batch paths. | `accepted_architecture` | mode-by-mode integration matrix required |
| FR-013 | Use one price/cost authority in which unknown price remains unknown and cost-based selection is claimed only when invoked. | `accepted_architecture` | ledger/spend reconciliation and unknown-price tests required |
| FR-014 | Preserve restart-safe, idempotent batch job identity and usage recording. | `accepted_architecture` | restart/retrieval/replay tests required |

### Quality and safety requirements

| ID | Requirement |
|---|---|
| NFR-001 | The standalone mock path is deterministic, offline, and installable without provider credentials. |
| NFR-002 | Public APIs and database objects use two-or-more-word snake_case except external-standard fields and documented paper roles. |
| NFR-003 | Owned production code maintains 100% statement and branch coverage and beginner-readable public docstrings before release. |
| NFR-004 | Concurrency bounds, body bounds, output-token bounds, timeouts, retries, cache limits, and budgets are explicit. |
| NFR-005 | A degraded optional store or integration cannot silently falsify success or cost evidence. |
| NFR-006 | Every measurement identifies its source as reported, measured, configured, estimated, unknown, or external. |
| NFR-007 | The module works independently and does not require a CWL control plane for basic operation. |

### Security and privacy requirements

| ID | Requirement |
|---|---|
| SEC-001 | Non-mock provider credentials are retrieved from KV at the final execution path and never fall back to ambient request-time environment values. |
| SEC-002 | Non-mock provider URLs use HTTPS and reject non-global destinations; DNS pinning, redirect/proxy rejection, and strict response bounds remain `active_pr` until PR #96 merges. |
| SEC-003 | Caller and admin bearer authority are separable; public bind requires an explicit operator choice. |
| SEC-004 | Raw secrets never enter analytics, exception text, stored evidence manifests, or model-visible context. |
| SEC-005 | PII handling is purpose- and audience-bound. Blanket masking is not a substitute for authorization, encryption, retention, deletion, or audit. |
| SEC-006 | Untrusted JSON, SSE, agent configuration, and redaction inputs have validation and fuzz seams. |
| SEC-007 | Checks, statuses, reviews, and merge authority are distinct evidence types; none may impersonate another. |

## Interfaces

### Inference and batch

- `POST /v1/chat/completions`
- `POST /v1/responses`
- `POST /v1/batch/embeddings`
- `GET /v1/batch/embeddings/{batch_id}`
- `POST /api/v1/batch_routing_jobs`
- `GET /api/v1/batch_routing_jobs/{batch_job_id}`
- `POST /api/v1/batch_routing_jobs/{batch_job_id}/results`

### Operator and evidence

- `/admin` and `/admin/state`
- `/api/v1/agent_pools/{agent_pool_id}/worker_agents`
- `/api/v1/workflow_runs` and individual workflow records
- `/api/v1/evaluation_runs`
- `/api/v1/access_reports/{workflow_run_id}`
- cost, usage, analytics, readiness, and buyer-evidence resources defined in
  `contextual_orchestrator/api_contract.py`
- `GET /healthz` for liveness only; it is not readiness or dependency proof

Current scopes are asymmetric: `/healthz` and `/openapi.json` are
unauthenticated; chat, Responses, embedding batch, chat-batch submission and
result upload, workflow creation, and evaluation creation use inference
authority; most operator routes use admin authority. In protected main, chat
batch polling by `GET` falls through the admin gate even though submit/results
are inference-scoped. Treat that as an explicit compatibility/authorization
decision before changing it.

There is no dedicated trace scope on protected main. A caller with inference
authority can set `include_orchestration_trace: true` on chat requests; separate
tenant/purpose trace authority therefore belongs at the host/gateway boundary
until runtime RBAC is added.

The dispatcher in `server.py` is the current delivery truth. `OPENAPI_SPEC` in
`api_contract.py` describes only a resource-oriented subset and omits
implemented chat, Responses, health, spend, admin, and agent create/delete
routes. The intended architecture is one shared route registry that generates
dispatch, scopes, OpenAPI, and endpoint documentation.

“OpenAI-compatible” means only the versioned subset tested here: request fields,
sync response, Chat Completions `delta`/`[DONE]` streaming, auth header, model
mapping, error behavior, and unknown-field policy. It is not standards-body
conformance. Responses API typed events are not interchangeable with Chat
Completions SSE chunks, and admin/control-plane errors need not use the vendor
envelope.

## Execution requirements

### Route

1. Authenticate and validate the request.
2. Enforce budget and concurrency policy.
3. Select one eligible model agent from current pool data.
4. Resolve its credential from KV for non-mock execution.
5. Execute with bounded transient retries, failover, and circuit policy.
6. On the ordinary synchronous coordinator path, record usage, audit, and trace
   evidence with source qualifications.
7. Return a compatible response. Route streaming may relay provider deltas,
   but protected main bypasses the cost coordinator and does not persist its
   workflow run to `_StateStore`; no cross-agent failover occurs after bytes
   are emitted.

Requests containing tools, functions, or `response_format` use raw passthrough
on protected main. They record analytics but no workflow run or cost-ledger row.
That distinction must remain visible until FR-012 is satisfied.

### Conduct

1. Classify or accept explicit conduct mode.
2. Build a bounded template or validated generated plan.
3. Execute ordered roles while including only declared predecessor outputs.
4. Verify and synthesize under the policy snapshot.
5. Persist or retain evidence according to configured runtime mode.
6. Return the answer; any stream is post-synthesis framing, not live upstream
   token pass-through.

## Persistence requirements

Protected main has four distinct persistence boundaries:

1. `_StateStore`: optional SQLite `records` table for keyed workflow/evaluation
   records and append-only audit/analytics streams.
2. `_AgentPoolStore`: optional SQLite `agent_pool` overlay with JSON payloads.
3. `PostgresCredentialBackend`: optional pgcrypto-encrypted
   `provider_credentials` registry.
4. `SqlLedgerStore`: PEP-249 tables `cost_attribution_dimensions`,
   `llm_price_entries`, and `llm_usage_records` on SQLite or Postgres.

`PriceBook` currently reads ConfigStore category `llm_price_entries`; it does
not read or write the SQL `llm_price_entries` table. Protected main also has two
unsynchronized cost authorities: workflow-derived spend analytics/budget and
the independent ledger. The default ledger price book is empty and missing
prices become `0.0`, while spend analytics reports missing price as unknown.
`cheapest_upstream()` is not invoked by orchestration, so protected main does
not ship price-based provider selection.

Coordinator batch handles and local/external request-result mappings are
process-local. Restart loses lookup authority even if an external job survives;
chat-batch result replay can duplicate usage rows. Embedding results have only a
process-local idempotency guard.

`docs/database_design.sql` is a normalized production target. It must not be
described as the schema automatically created by the standalone runtime.
External `pg-llm-batch` configuration and secret tables are owned by that
adapter/service.

## Credential requirements

- `CONTEXTUAL_ORCHESTRATOR_KV_BACKEND`, KV DSN, and KV passphrase are bootstrap
  transport to the registry.
- Provider credentials are written with `register-credential` and retrieved by
  credential name.
- Cross-process bootstrap requires the Postgres backend. The default in-memory
  backend dies with the registering CLI process and is usable only when
  registration and provider calls share one process.
- Live autonomous-development/model tests use `NVIDIA_NIM_API_KEY` only in the
  bounded job that calls the model.
- `COPILOT_GITHUB_TOKEN` is never a development-model credential.
- Automated review identities and credentials are separate from product
  execution and must not be repurposed.

## Evidence taxonomy and merge requirements

Evidence is bound to the commit actually checked out. The following are not
exact-head success: queued, pending, skipped-required, cancelled, absent,
failed, predecessor-head, stale-base, author-only, status-only, synthetic-merge,
rate-limited, or infrastructure-only results.

A protected merge requires repository policy, required checks, security gates,
zero valid unresolved findings, and a qualifying independent non-author
approval on the same unchanged head. Automated findings are triage inputs, not
human approval unless repository rules explicitly and legitimately count the
reviewing identity.

## Deployment requirements

### Standalone

- mock or provider agent JSON;
- optional in-memory-only state;
- optional SQLite state and agent-pool files;
- optional in-memory credential backend for development only;
- explicit bearer tokens and loopback bind by default.

### Modular CWL integration

- host owns ingress, identity, tenant authorization, business persistence,
  deployment, and end-user privacy obligations;
- Contextual Orchestrator owns orchestration policy and provider execution
  inside its interface;
- `pg-llm-batch` owns its batch persistence/execution contract;
- naruon, inkspan, and other consumers retain their transports and schemas;
- Clearfolio remains an optional viewer integration.

## Failure and recovery requirements

| Failure | Required behavior | Recovery evidence |
|---|---|---|
| Invalid caller request | Fail before provider egress with stable 4xx semantics. | Contract test and no provider call. |
| Missing credential | Fail closed as not configured. | KV test and no ambient fallback. |
| Transient provider failure | Bounded retry, eligible failover, circuit update. | Trace identifies attempts and serving agent. |
| Permanent provider/caller failure | No retry storm. | Stable classified error. |
| Optional ledger export failure | Completion may continue, but export health records the loss. | Prompt-safe telemetry and flush health. |
| SQLite corruption/unavailability | Startup or write fails visibly; no fabricated persisted evidence. | Operator restores a known backup or starts an explicitly new store. |
| External batch outage | Job remains classifiable and does not become a completed result. | Poll/retry under backend contract. |
| Central review outage | Merge waits; local product and documentation work continues. | Fresh exact-head review later. |

## Technical gaps

- `OPENAPI_SPEC`, runtime dispatch, scopes, and endpoint prose are not generated
  from one registry and have already drifted.
- Passthrough and route-streaming bypass coordinator usage accounting; route
  streaming also bypasses durable state. Failed mid-stream runs are not retained.
- Workflow spend/budget and the cost ledger are unsynchronized. The ledger
  treats missing price as zero, its SQL price table is dormant, and budget
  admission is pre-run and non-atomic across request threads.
- Coordinator batch state is process-local; chat-batch retrieval is not
  idempotent and can record duplicate usage.
- `route_p95_seconds` is exposed but is not used for dispatch. Agent selection
  is deterministic tag/domain/priority scoring, not learned, price-aware, or
  load-balanced.
- `get_config_store()` and token-counter construction can silently fall back to
  memory/heuristic behavior; degraded authority must be operator-visible.
- Retention pruning, encryption, tenancy, backup, and schema migrations for the
  generic SQLite `records` store are not production complete.
- Protected main validates global provider addresses but does not yet contain
  the entire DNS-pinned/strict-response boundary from PR #96.
- Production readiness and buyer-evidence endpoints are local evidence views,
  not substitutes for deployed SLOs or external attestations.
- Learned routing, adaptive reasoning, free-first fallback, and NIM benchmark
  work remain active-PR or planned capabilities.
