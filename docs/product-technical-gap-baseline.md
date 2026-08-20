# Product and Technical Gap Baseline

**As of:** 2026-08-20 19:57, Asia/Seoul
**Source of truth:** `main` at `e226e1197bdfc890c9d8e5b9b648c78857d7e465`
**Product boundary:** one OpenAI-compatible gateway plus its operator evidence
control plane. Fugu, TRINITY, and Conductor are research inputs, not separate
deployables.
**Customer next action:** use this document to select the next mergeable PR and
to verify its exact-head evidence before approving or releasing it.

> This is a dated planning snapshot, not a live merge dashboard. PR heads,
> checks, reviews, and base relationships can change after publication. Always
> refetch the remote exact head and protected rules before acting on a row.

## 1. Product requirements (PRD)

Contextual Orchestrator must let an application keep using an OpenAI-compatible
API while the platform chooses between a single-worker route and a deeper,
verifiable workflow. A buyer should be able to answer four questions without
reading source code:

1. Which provider/model handled the request and why was it selected?
2. Which workflow roles saw which prior outputs?
3. What happened when a provider, tool, cache, or verifier failed?
4. Can the same evidence be replayed, audited, and operated as a standalone
   service or an imported module?

The existing product plan covers API compatibility, managed agent pools,
latency/quality policy, trace/access evidence, evaluation replay, i18n, and
buyer-readiness endpoints. The open queue shows that reliability, provider
bootstrap, secure credential use, purpose-limited PII access, and release-grade
operability are still being closed.

## 2. Technical requirements (TRD)

| Boundary | Required behavior | Acceptance evidence |
|---|---|---|
| API | Preserve `/v1/chat/completions` and compatible error/stream contracts. | Contract tests plus hosted required workflows. |
| Routing | Select by capability, provider health, cost, model mode, and explicit exclusions; do not route embedding-only models to chat synthesis. | Exact-head capability-isolation, discovery, and failover tests. |
| Orchestration | Allocate shallow or deep work by task need; retain Thinker/Worker/Verifier/Synthesizer evidence, bounded recursion, and Conductor-style access lists. | Replayable workflow trace and equal-budget ablation evidence for #568. |
| Provider plane | Discover model capabilities and price honestly, bootstrap credentials from KV, and use secure provider transport with fail-closed malformed responses. | Catalog/bootstrap, provider-contract, and security checks for #764/#765/#768/#769/#770. |
| Failure plane | Classify tool failures, fail safely, preserve upstream truth, and retry only within a bounded policy. | #771 focused/full tests and hosted security checks. |
| Cache plane | Optional injected Redis/Dragonfly-compatible response cache; deterministic keys, strict bypass, local fallback, fail-open backend behavior, and no cross-model reuse. | #772 focused/full tests and RFC 9111 review. |
| Privacy | Do not blanket-mask operational PII. Enforce purpose-limited authorization, field-level encryption at rest, credential redaction, and auditable access. | ADR 0010 follow-up #762 plus implementation tests. |
| Persistence | Keep database objects at least two words in `snake_case` and keep schemas in third normal form. | Schema convention review and migration tests. |
| Packaging | Keep one deployable product until a second consumer, independent cadence, or security-provenance boundary requires extraction; every extracted component must work standalone and as a submodule. | Packaging ADR and consumer integration proof. |
| Operability | Maintain one hourly owner for product development; do not add a duplicate scheduler. OpenCode/Noema/Strix must use the gateway path without `COPILOT_GITHUB_TOKEN`. | Central `.github` `organization-commercial-readiness-loop.yml` (`7 * * * *`) owns the hourly product loop; `pr-review-merge-scheduler.yml` owns the more frequent protected PR sweep. |
| Release | Release only from exact-head green evidence; update version and `CHANGELOG.md`. | Protected normal merge followed by release checks. |

## 3. Current architecture and UML-level flow

```mermaid
flowchart LR
    A[OpenAI-compatible client] --> B[HTTP validation and auth]
    B --> C[CostRoutingCoordinator]
    C --> D{Route or conduct}
    D --> E[Capability and health policy]
    E --> F[Response cache]
    F --> G[ModelClient / provider transport]
    G --> H[Provider pool]
    D --> I[Thinker / Worker / Verifier / Synthesizer]
    I --> J[Access-list trace]
    J --> K[Replay and buyer evidence]
    L[KV credential registry] --> G
    M[Durable model catalog] --> E
```

The public API stays small; the control plane owns provider selection,
capability isolation, workflow evidence, cache policy, and failure truth. Rust
is not warranted for the current stdlib Python gateway solely by preference:
the current product gap is correctness and operational evidence. Revisit a
Rust boundary when profiling demonstrates transport, parsing, or concurrency
cost that the existing process cannot meet, and preserve the OpenAI-compatible
module contract.

## 4. Open PR inventory at the source-of-truth snapshot

Checks below are a snapshot, not approval. `queued` and `in_progress` are not
failures, but they also are not merge evidence. Protected main requires one
independent approving review, last-push approval, resolved threads, all
required workflows, and a normal merge.

| PR | Exact head | State / base | Evidence boundary and next action |
|---:|---|---|---|
| #783 | `6210b00` | ready, stacked on #776 | Review the total monotonic body deadline and exact-head framing regression; integrate after #776 with all protected evidence. |
| #781 | `7e6dc15` | ready, stacked on #780 | Review verified `trace` purpose scope, metadata-only pre-release audit, and generic fail-closed audit outage behavior before integrating after #780. |
| #782 | `fdbd1db` | ready, based on main | Review owner-bound workflow/access/evaluation reads, split-token admin evidence visibility, migration fail-closed behavior, and exact-head protected Checks before merge. |
| #780 | `193752f` | ready, based on main | Review the minimal `/healthz` contract, authenticated `/readyz`, optional-dependency degradation, backend-identifier non-disclosure, and fresh exact-head hosted Checks before normal merge. |
| #779 | `beb15a7` | ready, stacked on #765 | Current successor for optional-temperature capability negotiation. Review exact same-provider retry semantics, then integrate only after #765 reaches protected main. |
| #778 | `9186547` | ready, stacked on #765 | Review source-image preservation, explicit `vision` eligibility/failover, Responses normalization, and the private LineageWeave OCR recovery boundary. |
| #776 | `0ec1151` | ready, stacked on #765 | Review fixed-length framing plus the total-deadline regression; #783 supplies the root-cause implementation before retargeting onto protected main. |
| #775 | `fb8fb62` | draft, based on main | Verify the exact CPython 3.12 Atheris marker, direct test contract, hash lock, hosted Fuzz job, and independent approval before promotion. |
| #773 | `172e556` | ready, based on main | Review this dated baseline and ADR 0016; exact current head is self-referential and has no independent approval yet. |
| #772 | `1d81910` | ready, based on main | Review cache-key isolation, strict bypass parsing, fail-open backend behavior, malformed cache entries, and routing/cost/stream interactions. |
| #771 | `f60adbc` | ready, based on main | Local exact-head suite is `1533 passed`; hosted security contexts are queued after structured failure-chain and external-admin resource-policy fixes. Obtain independent approval before protected merge. |
| #770 | `0777e14` | draft, based on stale main | Reconcile after #768. Preserve complete-price evidence, provider-family diversity, corrupt-row handling, and consume the shared ordinary-chat classifier rather than a local detector. |
| #769 | `9654c28` | ready, based on main | Core repository workflows succeeded on this head; obtain exact-head independent approval and remaining protected contexts. |
| #768 | `88fee97` | ready, based on main | Review the current capability boundary, including ShieldGemma, legacy Completions, direct-run regressions, and exact-head hosted checks. |
| #765 | `d3f9a9b` | draft, based on main | Reconcile after #768/#769; preserve DNS-pinned discovery, structured-output honesty, gateway-owned reasoning policy, and omitted sampling controls. |
| #764 | `55814b9` | draft, based on main | Verify 3NF catalog persistence, credential promotion/rollback, last-known-good semantics, exact-set stale withdrawal, and shared capability-classifier adoption after rebase. |
| #763 | `385a5b4` | draft, based on main | Reconcile with #765/#768; preserve one-shot local Responses translation, local concurrency coordination, concrete-model stickiness, and adaptive provider failover. |
| #762 | `be6b6c7` | ready, based on main | Core workflows succeeded; merge the design only after current-head independent approval, then implement its authorization/encryption acceptance criteria separately. |

PR #774 was closed unmerged as the stale-base predecessor of #779. Its local
or predecessor-head evidence does not transfer. Issue #745 is represented by
#772 and issue #567 by #771. A draft or implementation PR is not treated as
completed until the protected-main contract is satisfied.

## 5. Open issue and product-gap queue

| Issue | Customer-visible gap | Planned proof / next PR |
|---:|---|---|
| #777 | Low-latency gateway routing metrics use coarse, inference-oriented histogram buckets and do not separate dispatch from upstream latency. | Add validated configurable bucket boundaries and distinct dispatch/upstream histograms; preserve metric names, labels, and bounded cardinality. |
| #568 | Operators cannot compare provider-neutral reasoning profiles at equal budget. | Add role-specific effort profiles, recursion/workflow/access-list controls, and an ablation report with reproducible fixtures. |
| #123 | A sole collaborator can be unable to satisfy last-push approval. | Add governance evidence/runbook or a protected-rule-compatible process; never bypass approval. |
| #119 | Ambiguous or unbounded inbound framing threatens request integrity. | PR #776 adds fixed-length framing and PR #783 enforces the total body deadline; merge the stack only after exact-head hosted evidence. |
| #118 | Liveness and authenticated readiness are not yet fully separated. | PR #780 implements the minimal `/healthz` and authenticated `/readyz` contract; merge only after exact-head Checks and independent approval. |
| #117 | Trace access and inference access need separate authority. | PR #781 adds a verified `trace` purpose scope, pre-release audit event, and audit-outage fail-closed tests; merge after #780 and exact-head protected evidence. |
| #116 | Browser admin sessions need separation from long-lived bearer credentials. | Add session-bound admin controls and regression tests. |
| #103 | Release readiness must fail closed on stale head, missing review, or missing Checks evidence. | Implement exact-head release gate and changelog/version proof. |
| #102 | Equivalent endpoints need race-to-first-valid completion without unsafe cancellation. | Add bounded concurrency and provider truth tests. |
| #95 | Atheris locking must work on all supported CPython interpreters. | Land portable lock implementation and run the hosted fuzz job. |
| #86 | NVIDIA NIM discovery needs live, evidence-grade capability/cost/quality measurement. | Use KV-registered NIM credentials in a controlled benchmark; publish provenance and limits. |

## 6. Prioritized gap register

| Priority | Gap | Current evidence | Definition of done |
|---:|---|---|---|
| P0 | Protected delivery cannot merge green PRs without independent approval. | Ruleset `18156473` requires one approval and last-push approval; several PRs are green but blocked. | A human/independent reviewer approves the exact current SHA, all threads resolve, hosted required workflows pass, and normal squash/merge succeeds. |
| P0 | Provider boundary is still being assembled across stacked PRs. | #768, #765, #764, #770, #763, #776, #778, and #779 are pending integration. | One current-main stack has capability isolation, secure JSON, bounded framing, multimodal evidence, KV bootstrap, honest catalog, optional-control negotiation, and failover with no duplicate logic. |
| P0 | Operational failure paths are not yet one buyer-verifiable contract. | #771 and #772 are open. | Exact-head full suite, focused edge tests, security scans, and a buyer-facing failure/rollback trace pass. |
| P1 | PII can remain usable without blanket masking, but authorization/encryption is unfinished. | ADR 0010 explicitly marks both follow-ups not started; #762 is documentation. | Purpose-scoped caller/role authorization, field-level encryption at rest, credential-only redaction, and audit tests prove raw PII is only returned to an authorized purpose. |
| P1 | Deep-workflow compute policy lacks provider-neutral measured ablation. | Product plan cites Fugu/TRINITY/Conductor; issue #568 remains open. | Equal-budget shallow/deep/role-effort/access-list replay with reproducible quality, verifier, cost, and trace metrics. |
| P1 | Model discovery lacks live NVIDIA NIM evidence. | Issue #86 remains open; local catalog is not production telemetry. | KV-backed NIM discovery benchmark records model capability, price provenance, failure class, and quality result without secret leakage. |
| P1 | Release gate and hourly loop need exact operational proof. | Rules require central scheduler workflows; issue #103 remains open. | One scheduler owner, no duplicate workflow, exact-head release gate, version/changelog update, and normal protected release evidence. |
| P2 | Ecosystem boundaries need consumer proof. | `naruon`, `.github`, and sibling components are named consumers, but this repo remains one deployable product. | Add a minimal OpenAI-compatible connector contract test for a real consumer or defer extraction with a documented trigger; do not split speculatively. |
| P2 | Frontend component inventory is not applicable here. | This repository is a backend stdlib lab and has no frontend/Storybook tree. | Keep the existing Figma artifact record; introduce Storybook only when a frontend package is actually added. |

## 7. Delivery gates

For each PR, perform the following loop on the current head: inspect changed
files and review threads, reproduce the claimed behavior, fix root causes in
the shared path, run focused and full tests, run compile/diff/security checks,
refresh the hosted Checks, and merge only after the protected rule is satisfied.
Remote agent pushes are respected by refetching the head; stale approvals or
checks are not reused. Review queues and hosted wait time remain active-work
time: use it to implement the next independent gap, not to bypass the gate.

Release is not complete until the version, `CHANGELOG.md`, release candidate,
and exact-head evidence all agree. A green local run is not production or
buyer telemetry; label local evidence accordingly.

## 8. Standards and research basis (APA 7th)

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025).
*Learning to orchestrate agents in natural language with the Conductor*
(arXiv:2512.04388). https://doi.org/10.48550/arXiv.2512.04388

OpenAI. (n.d.-a). *Create chat completion*. OpenAI Platform.
https://platform.openai.com/docs/api-reference/chat/create

OpenAI. (n.d.-b). *Create a model response*. OpenAI Platform.
https://platform.openai.com/docs/api-reference/responses/create

OpenAPI Initiative. (2025, September 19). *OpenAPI specification version 3.2.0*.
https://spec.openapis.org/oas/v3.2.0.html

Sakana AI. (2026, June 22). *Sakana Fugu: One model to command them all*.
https://sakana.ai/fugu-release/

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025).
*TRINITY: An evolved LLM coordinator* (arXiv:2512.04695).
https://doi.org/10.48550/arXiv.2512.04695

Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP caching* (RFC 9111).
RFC Editor. https://www.rfc-editor.org/rfc/rfc9111.html

National Institute of Standards and Technology. (2024). *Artificial
intelligence risk management framework: Generative artificial intelligence
profile* (NIST AI 600-1). https://doi.org/10.6028/NIST.AI.600-1

These sources support the current product shape, OpenAI-compatible wire
honesty, deep-versus-shallow orchestration allocation, cache safety, and
generative-AI risk evidence. PDFs are attached only when redistribution is
permitted; otherwise the canonical citation and link are retained.

## 9. Design and ecosystem record

- Existing editable Figma file: `Contextual Orchestrator Plugin-Driven Admin
  Design`, file ID `vsZMd8WAv42HDRgcZuNcWk`, recorded in
  [`docs/figma_artifacts.md`](figma_artifacts.md). No new Figma work is needed
  for this backend-only baseline.
- Existing FigJam architecture board is also recorded in that file.
- Storybook is not introduced because this repository has no frontend surface;
  repeated backend/API objects remain documented contracts and schemas.
- The current packaging decision is one standalone gateway that can be
  consumed as a module. A repository split requires a concrete independent
  consumer, release cadence, or security-provenance boundary.

**Customer next action:** approve the next exact-head PR only when its row above
has a concrete proof link, then use the next highest-priority unresolved gap to
create the following stacked change.
