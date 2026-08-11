# Threat model

**Document state:** `accepted_architecture`<br>
**Scope:** standalone runtime, optional adapters, and CWL composition boundary

## Assets

- provider credentials and KV bootstrap material;
- authorized prompts, PII-bearing business content, model outputs, and traces;
- policy, agent-pool, provider-exclusion, budget, and price configuration;
- workflow, access-list, audit, analytics, benchmark, and release evidence;
- state, credential, cost-ledger, and external batch stores;
- reviewer, check, status, merge, and release authority.

## Trust zones

1. Untrusted caller and payload.
2. Authenticated inference caller.
3. Privileged operator/admin.
4. Orchestration process and its memory.
5. Credential and state stores.
6. External model provider and network.
7. Optional batch/viewer/CWL dependencies.
8. GitHub CI, automated reviewers, human reviewers, and protected merge.

## Threats and controls

| Threat | Abuse path | Current control | Residual gap/status |
|---|---|---|---|
| Authentication bypass | Public bind or shared token exposes admin or inference. | Bearer checks, split admin/inference tokens, explicit public-bind flag, request bounds. | Production identity, rotation, tenant RBAC, and gateway policy are host-owned/`planned`. |
| SSRF and DNS rebinding | Provider base URL resolves to internal or changed destination. | Protected main rejects non-HTTPS/non-global addresses and supports allowlists. | Full DNS pinning, proxy/redirect rejection, and strict transport lifetime are `active_pr` #96. |
| Credential exfiltration | Secret leaks into model context, redirects, logs, errors, traces, or artifacts. | KV lookup, no ambient runtime fallback, redaction, prompt-safe ledger. | Rotation and audience-bound secret distribution require deployment evidence. |
| Malicious provider response | Oversized, malformed, duplicate-key, non-finite, or deceptive response exhausts or contaminates runtime. | Provider URL validation, a socket timeout, a request-side `max_tokens` hint, and expected-shape validation seams. | There is no enforced provider-response byte cap or cumulative SSE cap; strict bounded framing/JSON/SSE is `active_pr` #96. |
| Prompt injection across agents | One model output instructs later roles or steals hidden context. | Access lists limit visibility; roles and subtasks are explicit. | Content remains untrusted; tool authority and sanitization belong to each integrating tool/host. |
| Excessive context disclosure | Generated workflow exposes unrelated prior outputs. | Plan validation, explicit step access tuple, trace inspection. | Tenant/purpose authorization is host-owned; role-effort control is `active_pr` #99. |
| Denial of wallet/service | Large prompts, deep workflows, retries, concurrency, provider output, or batch fan-out exhaust resources. | Request-body, workflow-step, retry, rate, concurrency, cache, and workflow-budget controls; provider calls carry an output-token hint. | Hard upstream response bounds, distributed quotas, and provider-level reservation are incomplete. |
| Cost falsification | Estimated tokens or missing price appears as measured spend/free routing. | Spend analytics qualifies unknown price, but the separate ledger defaults missing price to zero and its SQL price table is dormant. | Unify cost authority, make unknown non-zero/non-free, and reconcile budget/ledger before cost-routing claims. |
| Persistence disclosure | SQLite JSON payload or backup exposes raw prompts/outputs. | Persistence is opt-in; SQL parameters prevent injection; normalized encrypted target is documented. | Generic state encryption, retention pruning, tenancy, and backup controls are not complete. |
| PII loss through blanket masking | Required business identifiers are destroyed or become unusable. | Payload path may retain authorized data; broad telemetry omits prompt/output. | Audience- and purpose-specific field policy needs host integration; masking alone is rejected. |
| PII overexposure | Full traces or persisted payloads reach a broader audience than the inference request. | Trace is not exposed by default; admin/inference tokens can be split; redaction/minimization. | Protected main has no dedicated trace scope: an inference caller can opt into a chat trace. Fine-grained tenant/purpose RBAC and subject-rights workflow are host-owned. |
| SQL/config injection | Attacker-controlled kind/key/payload alters schema or query. | Bound SQL parameters and naming validation. | Generic JSON payload schema evolution needs migration controls. |
| Cache data crossover | Cached response is reused for a different caller or policy. | Exact request/mode key, disabled by default, bounded TTL/LRU, deep copies. | Multi-tenant cache partitioning is not implemented; hosts should keep cache disabled absent an authority key. |
| External batch confused deputy | Caller submits/retrieves another job or replays results for duplicate accounting. | Injected backend contract, request validation, local standalone backend. | Tenant ownership is adapter/host-owned; coordinator handles and idempotency are process-local and lost on restart. |
| Evidence-path bypass | Passthrough or route streaming returns an answer without the workflow, ledger, budget, or durable record expected by operators. | Mode-specific analytics/traces and explicit documentation. | Protected main still bypasses coordinator usage for passthrough/streaming and state persistence for route streaming. |
| Silent adapter downgrade | Config or token-count adapter failure falls back to memory/heuristic behavior without sufficient operator authority. | Standalone fallback preserves availability. | Degraded mode must be surfaced and excluded from durable/precise evidence claims. |
| Supply-chain compromise | Mutable action/package or generated artifact executes attacker code. | Immutable action pins, hash locks, CodeQL, dependency audit, SBOM, central scanners. | External runner and provider integrity require operational evidence. |
| Evidence/reviewer spoofing | Status or model comment is treated as independent approval or exact-head success. | Explicit evidence taxonomy and branch governance. | Live rulesets and eligible human capacity remain external governance dependencies. |
| Stale-base merge | Check/review applies to predecessor head or synthetic merge. | Exact contributor-head workflows and live-base reconciliation policy. | Central control-plane reliability must be proven on protected main. |

## Misuse cases

### Authorized PII request

An authenticated host sends a customer email requiring names and account data.
The orchestrator may pass the minimum necessary content to an approved model
under the host's purpose policy. Usage telemetry receives identifiers and token
counts, not the message body. Protected main does not enforce a separate trace
permission: an inference-scoped chat caller may opt into orchestration trace
output, while admin authority can retrieve persisted workflow records. The host
must therefore restrict those tokens/endpoints to the same authorized purpose;
dedicated tenant/purpose trace RBAC remains planned.

### Hostile provider configuration

An operator attempts to configure a provider at loopback, a private network, or
an allowlist-excluded host. Execution fails before sending a credential. The
active #96 transport strengthens this by retaining validation-time address pins
through connection establishment.

### Compromised worker output

A worker emits instructions to reveal another step's context. The verifier and
synthesizer receive only their declared access-list inputs. They must treat
worker text as untrusted data; no tool or credential authority follows from the
text.

## Security acceptance

- realistic auth, SSRF, redirect, response-bound, malformed JSON/SSE, secret
  leakage, PII, SQL, cache, concurrency, retry, batch, and evidence tests;
- 100% owned production statement and branch coverage without excluding real
  behavior;
- current exact-head CodeQL, dependency, supply-chain, fuzz, and required
  organization scans;
- zero valid unresolved findings and qualifying independent approval;
- deployment-specific penetration, access, retention, backup, and incident
  evidence before production claims.

The repository is designed toward NIST AI RMF, NIST SSDF, ISO/IEC 27001,
ISO/IEC 23894, ISO/IEC 42001, CSAP, and SOC 2 evidence needs. It does not claim
certification or attestation. See `REFERENCES.md`.
