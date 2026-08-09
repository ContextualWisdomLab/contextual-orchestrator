# Product Requirements Document

**Product:** Contextual Orchestrator  
**Document state:** `accepted_architecture`  
**Audience:** product owners, platform operators, API consumers, security and
privacy reviewers, reliability engineers, and acquisition reviewers

## Product promise

Contextual Orchestrator presents one provider-neutral, OpenAI-compatible model
surface while allocating work between a single-model fast path and an explicit,
auditable multi-agent workflow. It must work as a standalone service and as a
module within the ContextualWisdomLab ecosystem without transferring host
authority for identity, tenancy, durable business data, or deployment.

The product optimizes correctness, evidence quality, reliability, control, and
cost within explicit budgets. Latency is measured and exposed, but it is not the
primary quality objective for deep orchestration.

The product targets evidence readiness for buyer CSAP and SOC 2 diligence. It
does not claim certification, attestation, or assessor acceptance; those
remain external deployment and governance outcomes.

## Problem

Application teams otherwise have to implement provider selection, credentials,
retry/failover, model-group policy, context sharing, verification, cost
attribution, batch routing, and audit evidence independently. That duplication
creates inconsistent security boundaries and makes a model answer difficult to
reconstruct or govern.

Operators need to answer five questions for every consequential run:

1. Why was route or conduct mode selected?
2. Which model agent performed each role?
3. Which prior outputs could each step see?
4. What budget, provider, credential, and failure policy applied?
5. Which evidence is measured, estimated, absent, or external?

## Users and jobs

| User | Job to be done | Required outcome |
|---|---|---|
| API consumer | Replace a compatible model endpoint without learning orchestration internals. | Stable request/response semantics and explicit errors. |
| Platform operator | Configure agent pools, policy, credentials, budgets, and exclusions. | Changes are controlled, reviewable, and recoverable. |
| AI product owner | Decide when additional test-time compute improves quality. | Comparable-budget route/conduct evidence rather than anecdotes. |
| Security/privacy reviewer | Verify egress, secret, context, PII, and audit boundaries. | Least authority, purpose limitation, retention, and evidence. |
| Reliability engineer | Diagnose provider and workflow degradation. | Bounded retries, failover, circuit state, and run identity. |
| Acquisition reviewer | Determine whether claims are implemented and reproducible. | Status-qualified traceability from requirement to protected evidence. |

## Product outcomes

- One independently usable orchestration endpoint and one operator surface.
- Provider-neutral agent pools represented as data, not provider-specific code.
- A deterministic `route` path and an inspectable `conduct` path.
- Explicit workflow roles, subtasks, step dependencies, and access lists.
- KV-backed provider credentials; environment variables are bootstrap transport,
  never request-time provider-secret authority.
- Honest cost and token evidence with estimates visibly distinguished from
  provider-reported measurements.
- Sync and latency-tolerant batch routing with a standalone local backend and an
  optional `pg-llm-batch` adapter.
- Fail-closed security and evidence gates without fabricated approvals,
  certifications, prices, or benchmark validity.

## Prioritized product requirements

Release scope describes product intent, not evidence that a capability has
shipped. The capability table below supplies implementation status.

| ID | Priority | Release scope | Accountable owner | Requirement and measurable acceptance |
|---|---|---|---|---|
| PRD-001 | P0 | current | API owner | Preserve the documented compatible subset; 100% of the versioned contract corpus passes on the release candidate. |
| PRD-002 | P0 | current | Orchestration owner | Allocate work through explicit route/conduct policy; 100% of accepted conducted runs carry one policy snapshot and ordered step evidence. |
| PRD-003 | P0 | current | Security owner | Enforce model exclusions and per-step access lists; release evidence contains zero exclusion or undeclared-access violations. |
| PRD-004 | P0 | current | Reliability owner | Bound retries, failover, circuits, concurrency, tokens, and budgets; every supported failure class terminates within its declared bound. |
| PRD-005 | P0 | current | Security owner | Resolve non-mock provider secrets from KV at final egress; credential material appears in zero logs, traces, artifacts, analytics, or model contexts. |
| PRD-006 | P0 | hardening | FinOps owner | Unify spend and ledger authorities and qualify every cost/token value as reported, measured, configured, estimated, unknown, or external; unknown price is never treated as free. |
| PRD-007 | P1 | hardening | Batch owner | Support explicit sync/batch decisions and classifiable, restart-safe, idempotent job lifecycle without coupling interactive availability to an external backend. |
| PRD-008 | P1 | production hardening | Data owner | Keep persistence opt-in and recoverable; enabled stores pass restart/restore tests and production claims wait for retention, encryption, tenancy, and backup evidence. |
| PRD-009 | P0 | next accepted stack | Security owner | Complete the DNS-pinned, proxy/redirect-safe, bounded response boundary in PR #96; acceptance requires exact-head gates and protected merge. |
| PRD-010 | P0 | every release | Release owner | Publish only one unchanged protected revision with complete functional, security, fuzz, coverage, package, SBOM/provenance, rollback, and independent-review evidence. |

## Capability status

| Capability | State | Product interpretation |
|---|---|---|
| `/v1/chat/completions`, route/conduct, trace, SSE framing | `implemented_on_protected_main` | Supported stdlib runtime surface. Conduct output is framed after synthesis; only route mode can pass through live provider tokens. |
| Configurable model agents, runtime agent-pool changes, optional SQLite overlay | `implemented_on_protected_main` | Standalone model-group management; no tenant-RBAC claim. |
| Explicit thinker/worker/verifier/synthesizer steps and access lists | `implemented_on_protected_main` | Deterministic template and validated generated-workflow seams implement the current contract. |
| Transient retry, agent failover, and per-agent circuit breaker | `implemented_on_protected_main` | Current reliability boundary; provider errors remain distinguishable from caller errors. |
| KV credential registry with in-memory and pgcrypto Postgres backends | `implemented_on_protected_main` | Provider secrets do not fall back to ambient request-time environment values. |
| Cost ledger, seven attribution dimensions, routing hints, local and `pg-llm-batch` adapters | `implemented_on_protected_main` | Two unsynchronized cost authorities exist; the SQL price table is dormant and the ledger currently treats missing price as zero. This is not cost-based provider selection and is a P0 honesty gap. |
| Optional SQLite workflow/evaluation/audit/analytics persistence | `implemented_on_protected_main` | Useful standalone durability; retention pruning and multi-tenant isolation are not complete. |
| DNS-pinned provider transport and strict bounded response parsing | `active_pr` | PR #96; do not treat it as protected-main behavior until merged. |
| Evidence-grade NVIDIA NIM discovery and modality benchmark | `active_pr` | PR #90; benchmark evidence is not product acceptance until its stack and gates pass. |
| Free-first fallback policy | `active_pr` | PR #94. |
| Adaptive provider reasoning-effort control | `active_pr` | PR #99, stacked on #94. |
| Synchronous embeddings and KV-only bootstrap expansion | `active_pr` | PR #66 on a separate historical stack. |
| Learned routing/coordinator | `planned` | Requires a versioned evaluation set and comparable-budget proof over deterministic policy. |
| Rust/GPU mathematical or psychometric compute layer | `out_of_scope` | Required only if orchestration begins owning such arithmetic; domain services should own their scientific kernels. |

## Functional scope

### In scope

- compatible chat completion and bounded streaming;
- route/conduct mode selection and policy snapshots;
- agent selection, provider exclusion, failover, and circuit state;
- workflow planning, step execution, verification, synthesis, and access lists;
- operator agent-pool, trace, audit, evaluation, cost, and readiness views;
- credential indirection and bootstrap tooling;
- honest token/cost measurement and budget enforcement;
- local and external batch adapters;
- optional standalone persistence;
- modular links to `pg-llm-batch`, Clearfolio, naruon, and other CWL hosts
  through explicit interfaces.

### Non-goals

- training or claiming equivalence to Fugu, Conductor, or TRINITY;
- acting as an identity provider, tenant directory, DLP platform, or records
  management system;
- owning another service's business data, transport, authentication, or schema;
- claiming SOC 2, CSAP, regulatory approval, production SLOs, or buyer acceptance
  from repository-local checks;
- masking all PII indiscriminately. Authorized business payloads may require PII;
  controls must instead combine purpose, scope, encryption, access, retention,
  audit, and output minimization. Telemetry and broad traces must not copy raw
  prompts or answers.

## Test-time compute requirements

The product must allocate a comparable call/token budget between:

- direct single-model execution;
- route-once selection;
- bounded conducted workflows;
- reviewed fallback or deeper-recursion policies.

Workflow stage count, recursion depth, decomposition, access lists, agent pool,
and role-specific reasoning effort are policy inputs. Evaluations report both
quality and resource use; they do not declare a deeper path better merely
because it used more calls. Fugu, Conductor, TRINITY, FrugalGPT, RouteLLM, and
newer primary work are research inputs, not compatibility claims.

## Privacy and data-governance requirements

- Provider credentials never enter prompts, traces, logs, or analytics.
- Raw prompts and outputs remain on the authorized execution path and are not
  duplicated into usage telemetry.
- Persistence is opt-in and its operator must define purpose, access, encryption,
  retention, deletion, backup, and residency.
- PII required for the authorized task is preserved inside the protected payload
  path. Derived previews, broad operator views, and telemetry use minimization or
  redaction appropriate to their audience.
- A host integrating this module owns end-user consent, legal basis, tenant
  authorization, subject-rights workflows, and business-record retention unless
  a versioned contract explicitly delegates them.

## Success measures

| Measure | Release target | Evidence status |
|---|---|---|
| Compatible request success | 100% pass on the versioned supported-request corpus. | Repository test evidence; production availability remains external. |
| Trace completeness | 100% of accepted conducted runs have one policy snapshot and ordered step/access evidence. | Repository and deployed sampling. |
| Provider exclusion miss rate | Zero. | Repository tests plus deployed policy audit. |
| Secret exposure | Zero credential material in logs, traces, artifacts, analytics, or model context. | Security tests and deployment review. |
| Cost evidence honesty | 100% of returned cost/token facts carry an allowed provenance; unknown price is never zero/free. | Target; protected main does not yet satisfy this across both cost authorities. |
| Comparable-budget uplift | No deeper policy is promoted without a predeclared threshold, common budget, repeated cells, and uncertainty. | Evaluation evidence; no universal uplift is claimed. |
| Recovery | Every supported provider, persistence, and batch degradation terminates in a documented state within configured bounds. | Target; process-local batch and stream-persistence gaps remain. |
| Documentation fitness | All canonical files, ADR schemas, diagrams, local links, runtime names, and data objects pass the documentation contract. | `tests/test_documentation_contract.py`. |

## Release and acquisition acceptance

A release candidate requires one unchanged protected head with passing
functional, security, fuzz, 100% owned production statement/branch/public
docstring, packaging, SBOM/provenance, compatibility, and reproducibility
evidence; zero valid unresolved findings; and qualifying independent non-author
approval. Repository evidence may demonstrate controls, but external audit,
production SLO, penetration-test, DPA, buyer-signature, and certification
evidence remain explicitly external.
