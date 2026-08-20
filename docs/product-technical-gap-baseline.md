# Product and Technical Gap Baseline

**As of:** 2026-08-21 04:45, Asia/Seoul
**Source of truth:** `main` at `e226e1197bdfc890c9d8e5b9b648c78857d7e465`
**Product boundary:** one OpenAI-compatible gateway plus its operator evidence
control plane. Fugu, TRINITY, and Conductor are research inputs, not separate
deployables.
**Customer next action:** use this document to select the next mergeable PR and
to verify its exact-head evidence before approving or releasing it.

**Normative decision record:** [ADR 0023 — Product and technical gap
baseline](planning/adrs/0023-product-technical-gap-baseline.md). Privacy
requirements additionally follow [ADR 0010 — PII audit, not
masking](planning/adrs/0010-pii-audit-not-mask.md).

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
| Routing | Select by capability, provider health, cost, model mode, and explicit exclusions; do not route embedding-only models to chat synthesis. Embedding endpoints may delegate model selection to an enabled `embedding` capability agent. | Exact-head capability-isolation, discovery, failover, and [#789](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/789) embedding-contract tests. |
| Orchestration | Allocate shallow or deep work by task need; retain Thinker/Worker/Verifier/Synthesizer evidence, bounded recursion, and Conductor-style access lists. | Replayable workflow trace and equal-budget ablation evidence for [#568](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/568). |
| Provider plane | Discover model capabilities and price honestly, bootstrap credentials from KV, and use secure provider transport with fail-closed malformed responses. | Catalog/bootstrap, provider-contract, and security checks for [#764](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/764)/[#765](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/765)/[#768](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/768)/[#769](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/769)/[#770](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/770). |
| Failure plane | Classify tool failures, fail safely, preserve upstream truth, and retry only within a bounded policy. | [#771](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/771) focused/full tests and hosted security checks. |
| Cache plane | Optional injected Redis/Dragonfly-compatible response cache; deterministic keys, strict bypass, local fallback, fail-open backend behavior, and no cross-model reuse. | [#772](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/772) focused/full tests and RFC 9111 review. |
| Privacy | Do not blanket-mask operational PII. Enforce purpose-limited authorization, field-level encryption at rest, credential redaction, and auditable access. | [ADR 0010](planning/adrs/0010-pii-audit-not-mask.md) follow-up [#762](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/762) plus implementation tests. |
| Persistence | Keep database objects at least two words in `snake_case` and keep schemas in third normal form. | Schema convention review and migration tests. |
| Packaging | Keep one deployable product until a second consumer, independent cadence, or security-provenance boundary requires extraction; every extracted component must work standalone and as a submodule. | Packaging ADR and consumer integration proof. |
| Operability | Maintain one scheduler owner for product development; do not add a duplicate scheduler. The org target is for OpenCode, Noema, and Strix to use the gateway path without `COPILOT_GITHUB_TOKEN`; this repository must not claim that migration is complete until each central workflow removes its direct provider endpoint/key fallback. | Live central `.github` evidence is `pr-review-merge-scheduler.yml` (`*/30` PR sweep plus `*/15` organization sweep) and `pr-review-fix-scheduler.yml` (`23 */2`); the 30-minute/15-minute cadence is more frequent than the requested hourly loop. Central PR [#1170](https://github.com/ContextualWisdomLab/.github/pull/1170) routes OpenCode model execution through the gateway, pending protected integration; Noema/Strix gateway migration remains an explicit external prerequisite, not observed completion evidence. |
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

### Runtime role mapping

`thinker` is the canonical runtime and trace role for planning work. `planner`
is the planning responsibility, not a separate `WorkflowStep.role`: the
generated-plan path selects its planner model through the `thinker` role,
invokes that control-plane planning call, and then emits execution trace rows
with the declared `thinker`, `worker`, `verifier`, or `synthesizer` roles. A
planner call itself is not silently relabeled as a distinct `planner` trace
role. This keeps the documented role vocabulary aligned with
`TaskOrchestrator.ROLE_TAGS`, `WorkflowStep.role`, and the API trace contract.

## 4. Open PR inventory at the source-of-truth snapshot

Checks below are a snapshot, not approval. `queued` and `in_progress` are not
 failures, but they also are not merge evidence. Protected main requires two
 approving reviews, an additional approval for unattributed changes,
 last-push approval, resolved threads, all
required workflows, and a normal merge.

| PR | Exact head at snapshot | State / base | Evidence boundary and next action |
| [#792](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/792) | `236a28b3f73380aaa39aa7b19a2bc475c2cbdf6f` | ready, based on main | Documentation-only release gap closure: adds the canonical SemVer changelog and explicitly keeps `0.1.0` unreleased until protected main, required Checks, independent review, and release artifacts are verified. Normal merge still requires the protected gate. |
| [#790](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/790) | `0071751782ae535721e71785c3037989d2d27b77` | ready, based on main | Latest exact head keeps the gateway auth token outside the provider-key bootstrap gate. Exact-head review-gateway/model-discovery/API/security proof is `55 passed` with Ruff/diff clean; hosted Checks and independent approval remain required. |
| [#788](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/788) | `d670601e61ca181a7b7134c7d0219f310334ff05` | ready, based on main | Review opaque admin-session TTL/revocation, same-origin cookie state changes, and Secure-by-default deployment. Run `32376890077` first exhausted NVIDIA NIM and then emitted an unsupported hardcoded-AWS-token claim at `server.py:1932`; the exact PR tree has no AWS token pattern, and the failed Strix job was rerun through the Actions API. Treat the rerun as pending until a fresh exact-head result is terminal. |
| [#789](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/789) | `930bce1193d557f6dfe4252ef3187efb47dde194` | ready, based on main | Current head removes stale direct-entry calls, duplicate fixture keys, and an unused import from the embedding contract tests, and carries the unique ADR 0024 identity. Focused proof is `131 passed`; exact full proof is `1441 passed in 545.70s`; hosted Checks are freshly queued and protected approval remains required. |
| [#782](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/782) | `1e7ddb96256a9379b3d8d4bb39c70a646f302bed` | ready, based on main | Review owner-bound workflow/access/evaluation reads, split-token admin evidence visibility, migration fail-closed behavior, and exact-head protected Checks before merge. |
| [#780](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/780) | `e4e6b7cf27f061ece9f0e03ce82a248480b31597` | ready, based on main | Parent-integrated current head includes #781 trace-purpose authorization and hardened trace fixtures. Exact proof is `1443 passed in 556.14s`; Ruff, compileall, and diff-check pass. Hosted Checks are freshly queued and protected independent approval remains required. |
| [#775](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/775) | `fb8fb621faa66859e36fa9496d3d6deefd09c18e` | ready, based on main | Promoted after exact-head review: marker regression test passed, Python 3.10 resolver skips Atheris, Linux CPython 3.12 resolves Atheris 3.1.0, and the generated hash lock preserves `python_full_version == 3.12.*`. Hosted Checks are green; protected independent approval remains required. |
| [#784](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/784) | `1d8e882f0449efd525717981b8e9b01b1c309851` | ready, based on main | Current head preserves product release-artifact blockers without double-counting concrete blockers already included in the product count. Exact proof is focused `28 passed`, full `1457 passed in 602.67s`; Ruff, compileall, and diff-check are clean. Hosted Checks are queued on this exact SHA and protected approval remains required. |
| [#785](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/785) | `ec609fa7b526a995346c34434e277eb12f5a0246` | ready, based on main | Issue [#568](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/568) exact-head proof is full suite `1461 passed in 580.97s`, focused judge/failover/passthrough/profile suite `69 passed`, and Ruff/diff clean; independent approval and protected Checks remain required. |
| [#773](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/773) | self-reference — refetch live PR head | ready, based on main | This document is the PR's own changing artifact, so embedding its content SHA would become stale on every refresh commit. Refetch the live PR #773 head before relying on this row; review the dated product/technical gap register and ADR 0023 against the other exact heads. |
| [#772](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/772) | `f72ddc886cc55a3243ebe79f6498c7f942409c83` | ready, based on main | Review cache-key isolation, strict bypass parsing, fail-open backend behavior, malformed cache entries, and routing/cost/stream interactions; exact-head cache/cost/ledger proof is `63 passed`, with full suite `1451 passed`. |
| [#771](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/771) | `e1d417070885d5c0d0f0e62bd7d2e07736e87f01` | ready, based on main | The tool-failure PR is limited to failure classification and safe fallback; exact-head fallback/security/HTTP contract suite is `134 passed` and Ruff/diff checks pass. Owner-bound evidence authorization is tracked separately in [#782](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/782). Hosted Checks are queued; obtain independent approval before protected merge. |
| [#770](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/770) | `386c9a03d1d7076106e4061776e81ffd6dac4d6f` | draft, based on stale main | Reconcile after [#768](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/768). Preserve complete-price evidence, provider-family diversity, corrupt-row handling, and consume the shared ordinary-chat classifier rather than a local detector. |
| [#769](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/769) | `9654c285c54443acf6358193925f4e0e8ae501ce` | ready, based on main | Core repository workflows succeeded on this head; obtain exact-head independent approval and remaining protected contexts. |
| [#768](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/768) | `88fee976ca4222309f625058a6f95f09e66744ec` | ready, based on main | Review the current capability boundary, including ShieldGemma, legacy Completions, direct-run regressions, and exact-head hosted checks. |
| [#765](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/765) | `2ab9b9f011403bcea7ee812c5b5b389ddebe1181` | ready, based on main | Promoted from draft after the parent stack was reconciled. The current head includes the virtual-model embedding-capability gate fix. Exact-head local proof is `1510 passed in 611.33s`; Ruff, compile, and diff checks are clean. Hosted Checks and exact-head independent approval remain required before protected merge. |
| [#764](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/764) | `55814b9520133306777834ead0c7d380c3e1c820` | draft, based on main | Verify 3NF catalog persistence, credential promotion/rollback, last-known-good semantics, exact-set stale withdrawal, and shared capability-classifier adoption after rebase. |
| [#763](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/763) | `385a5b4e8d41dd6decab9f0845538e03fc71b51e` | draft, based on main | Reconcile with [#765](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/765)/[#768](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/768); preserve one-shot local Responses translation, local concurrency coordination, concrete-model stickiness, and adaptive provider failover. |
| [#762](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/762) | `be6b6c792165061e16f7d05a06251e5b8ee47519` | ready, based on main | The exact-head ADR closes the documented purpose, classification, AEAD/KMS, migration, and audit-gate review gaps; merge the design only after current-head independent approval, then implement its acceptance criteria separately. |

PR [#791](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/791) was merged into its stacked base branch on 2026-08-20. PR [#779](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/779) was merged into the #765 parent branch at `a4e9a780a56c08e131367f3b904f5c855b3a1b33`; PR [#778](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/778) was then merged into the same #765 parent branch at `0a3ab0b901d0b39d610f26538243bb5b3c1b3c61`; PR [#781](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/781) was merged into the #780 parent branch at `30476b3365ad9825a6dd2b35ac5ee10ef3c34879`; PRs [#776](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/776), [#783](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/783), and [#787](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/787) were merged into their non-main stack branches with merge commits `3e6c4205e707eee70387bb429866b689de848753`, `637e941fd9237780d2fe90150514b048d1675387`, and `41c0c87ef4c4cf335b71d07b990734944db4b89e`. None is a protected-main release. PR [#774](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/774) was closed unmerged as the stale-base predecessor of [#779](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/779). Its local
or predecessor-head evidence does not transfer. Issue [#745](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/745) is represented by
[#772](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/772) and issue [#567](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/567) by [#771](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/771). A draft or implementation PR is not treated as
completed until the protected-main contract is satisfied.

All links and full commit SHAs in this snapshot reflect the remote state
observed at 2026-08-21 04:45 Asia/Seoul; they are evidence pointers, not
standing approval.

### External central workflow prerequisite

At the refreshed snapshot, ContextualWisdomLab/.github PR [#1170](https://github.com/ContextualWisdomLab/.github/pull/1170) is open at exact head `595899d9b98ff0be6e9b42910907adfa643ad9a5`. It pins the current reviewed contextual-orchestrator gateway head `0071751782ae535721e71785c3037989d2d27b77`, keeps the existing `PR_REVIEW_MERGE_TOKEN`/`OPENCODE_APPROVE_TOKEN` publication boundary, and routes the five provider bootstrap keys only to the loopback inference sidecar. Its full local suite is `1239 passed` with 16 subtests; hosted Checks are pending and the required independent approval is absent.

The scheduler's earlier dry-run decision for PR #787 was `review_dispatch` for its non-main base; #787, #779, and #778 are now merged into the #765 parent stack. The target repository currently exposes no `opencode-review.yml` workflow of its own and the central repository-dispatch queue remains asynchronous. Until #1170 reaches protected main, remaining stacked PR review may remain absent or use the prior central model path; this is an external integration dependency, not evidence that the stacked code is merge-ready.

## 5. Open issue and product-gap queue

| Issue | Customer-visible gap | Planned proof / next PR |
|---:|---|---|
| [#568](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/568) | Operators cannot compare provider-neutral reasoning profiles at equal budget. | PR [#785](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/785) adds versioned role profiles, exact snapshot hashing, provider-capability fail-closed request binding, and equal-budget theta-hat/RMSE ablation; production defaults remain locked until measured evidence is available. |
| [#123](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/123) | A sole collaborator can be unable to satisfy last-push approval. | Add governance evidence/runbook or a protected-rule-compatible process; never bypass approval. |
| [#119](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/119) | Ambiguous or unbounded inbound framing threatens request integrity. | The #776/#783 implementation stack is merged into non-main branches; protected-main integration still requires exact-head hosted evidence and independent approval. |
| [#118](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/118) | Liveness and authenticated readiness are not yet fully separated. | PR [#780](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/780) implements the minimal `/healthz` and authenticated `/readyz` contract; merge only after exact-head Checks and independent approval. |
| [#117](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/117) | Trace access and inference access need separate authority. | The #781 implementation is integrated into #780 at the current parent branch; merge #780 only after exact-head protected evidence confirms the `trace` purpose scope, pre-release audit event, and audit-outage fail-closed behavior. |
| [#116](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/116) | Browser admin sessions need separation from long-lived bearer credentials. | PR [#788](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/788) implements opaque bounded sessions, Secure-by-default cookies, same-origin state-change checks, logout/revocation, and regression evidence. |
| [#103](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/103) | Release readiness must fail closed on stale head, missing review, or missing Checks evidence. | PR [#784](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/784) separates product evidence from release authority and adds exact-head `gh api` collection; merge only after fresh protected evidence. |
| [#102](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/102) | Equivalent endpoints need race-to-first-valid completion without unsafe cancellation. | Add bounded concurrency and provider truth tests. |
| [#95](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/95) | Atheris locking must work on all supported CPython interpreters. | Land portable lock implementation and run the hosted fuzz job. |
| [#86](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/86) | NVIDIA NIM discovery needs live, evidence-grade capability/cost/quality measurement. | Use KV-registered NIM credentials in a controlled benchmark; publish provenance and limits. The issue remains open and no accepted active implementation PR exists. |

GitHub currently returns `404 Not Found` for issue [#777](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/777); its earlier metric-gap
row is therefore removed from the actionable queue rather than treated as a
live work item.

## 6. Prioritized gap register

| Priority | Gap | Current evidence | Definition of done |
|---:|---|---|---|
| P0 | Protected delivery cannot merge green PRs without the required protected approvals. | Live ruleset `18156473` requires two approving reviews, an additional approval for unattributed changes, last-push approval, and resolved threads; several PRs are green but blocked. | Required independent reviewers approve the exact current SHA, all thread and workflow gates resolve, hosted required workflows pass, and normal squash/merge succeeds. |
| P0 | Provider boundary is still being assembled across stacked PRs. | [#768](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/768), [#765](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/765), [#764](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/764), [#770](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/770), and [#763](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/763) are pending integration; #778 and #779 are integrated into #765, including temperature negotiation. Central OpenCode gateway routing is tracked by [.github#1170](https://github.com/ContextualWisdomLab/.github/pull/1170). | One current-main stack has capability isolation, secure JSON, bounded framing, multimodal evidence, KV bootstrap, honest catalog, optional-control negotiation, and failover with no duplicate logic; central review execution must use the same current gateway pin after protected integration. |
| P0 | Operational failure paths are not yet one buyer-verifiable contract. | [#771](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/771) and [#772](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/772) are open. | Exact-head full suite, focused edge tests, security scans, and a buyer-facing failure/rollback trace pass. |
| P1 | PII can remain usable without blanket masking, but authorization/encryption is unfinished. | [ADR 0010](planning/adrs/0010-pii-audit-not-mask.md) explicitly marks both follow-ups not started; [#762](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/762) is documentation. | Purpose-scoped caller/role authorization, field-level encryption at rest, credential-only redaction, and audit tests prove raw PII is only returned to an authorized purpose. |
| P1 | Deep-workflow compute policy lacks provider-neutral measured ablation. | PR [#785](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/785) supplies opt-in profiles, snapshot replay, and synthetic/estimated RMSE; the production gate remains closed pending buyer-held-out measurement. | Equal-budget shallow/deep/role-effort/access-list replay with reproducible quality, verifier, cost, and trace metrics. |
| P1 | Model discovery lacks live NVIDIA NIM evidence. | Issue [#86](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/86) remains open; local catalog is not production telemetry. | KV-backed NIM discovery benchmark records model capability, price provenance, failure class, and quality result without secret leakage. |
| P1 | Release gate and hourly loop need exact operational proof. | Central scheduler workflows own the loop; PR [#784](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/784) adds the exact-head authority evaluator/collector, but protected approval and release evidence remain open. | One scheduler owner, no duplicate workflow, exact-head release gate, version/changelog update, and normal protected release evidence. |
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
