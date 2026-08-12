---
id: "0003"
title: "Keyverse authentication boundary and KV credential placement"
status: accepted
proposed_date: "2026-08-11"
accepted_date: "2026-08-11"
deciders:
  - "repository maintainer"
consulted:
  - "Keyverse deployment boundary"
  - "contextual-orchestrator security surface"
informed:
  - "contributors"
affected_components:
  - "contextual_orchestrator/server.py"
  - "contextual_orchestrator/orchestrator.py"
  - "contextual_orchestrator/cost_router.py"
  - "contextual_orchestrator/batch_routing.py"
  - "contextual_orchestrator/__main__.py"
  - "contextual_orchestrator/credentials.py"
  - "docs/kv-credentials.md"
effort: L
supersedes: null
superseded-by: null
related:
  - path: "docs/planning/adrs/0004-pr-review-merge-loop.md"
    relation: informational
  - path: "docs/kv-credentials.md"
    relation: informational
asr_triggers:
  - kind: security
    evidence: "The gateway is an ecosystem relying party and bearer tokens authorize admin/inference scopes."
    note: "Authentication must fail closed and secrets must remain in approved KV/deployment boundaries."
  - kind: maintainability
    evidence: "OIDC discovery, JWKS rotation, claims, and client registration are deployment concerns."
    note: "The stdlib gateway exposes an adapter seam instead of embedding an unsafe protocol implementation."
success_criteria:
  - metric: "auth secret runtime source"
    target: "CLI auth secrets come from explicit local flags or named KV entries, never legacy token env defaults"
    measurement_window: "every server startup and auth regression run"
    source: "contextual_orchestrator/__main__.py and test suite"
  - metric: "external verifier failure handling"
    target: "verifier exceptions, boolean-only decisions, and wrong scopes return unauthorized"
    measurement_window: "every protected request"
    source: "SecurityConfig authorization tests"
---

# Keyverse authentication boundary and KV credential placement

## Context

The repository originally treated gateway authentication as a static bearer-token comparison and read CLI token defaults from environment variables. The ecosystem identity plane is broader: Keyverse documents contextual-orchestrator as an OIDC relying party, keeps RP registration/client secrets in the IdP DB/KV, and requires deployment-controlled reconciliation and acceptance evidence. The first verifier seam also returned only a boolean, so it could authorize a scope but could not carry the verified subject or tenant claims into resource authorization.

> Keyverse states that ecosystem applications, including contextual-orchestrator, are OpenID Connect relying parties.
>
> Keyverse states that RP client registrations and secrets live in the IdP database/KV, not in an RP environment.
>
> SecurityConfig.bearer_verifier now accepts a deployment-injected verifier returning a verified identity and denies when it errors, returns only a boolean, or lacks the requested scope.

## Decision Drivers

* Recognize Keyverse as the production identity boundary instead of pretending a static token is OIDC.
* Keep client secrets and provider credentials in KV/deployment systems.
* Avoid an unsafe hand-written JWT decoder in the stdlib core.
* Preserve verified subject/org/workspace context for downstream ABAC and resource ownership.
* Preserve offline/local tests and explicit local-development authentication.

## Considered Options

* Keep static bearer comparison as the only production authentication.
* Embed Keycloak admin calls and a custom JWT/JWKS implementation in this repository.
* Keep static local auth for development and inject a reviewed Keyverse/OIDC bearer verifier at the deployment boundary.

## Decision Outcome

Chosen option: "Deployment-injected Keyverse/OIDC verifier with KV-backed token naming".

| Driver | Static token only | Embedded identity implementation | External verifier boundary |
| --- | --- | --- | --- |
| Keyverse compatibility | none | coupled/private | explicit OIDC RP seam |
| Secret safety | weak env temptation | high blast radius | KV/deployment ownership |
| Local operability | simple | heavy | simple explicit token or mock |
| Protocol correctness | incomplete | hard to maintain | owned by reviewed auth adapter |

SecurityConfig.bearer_verifier(token, scope) is the only production integration point. The adapter must validate issuer, audience, signature, expiry, key rotation, and scope using an approved library or trusted Keyverse/WAF boundary, then return `VerifiedIdentity(subject, org, workspace, scopes, roles)`. The core does not decode JWTs, call Keycloak Admin REST, or store RP client secrets. CLI token flags are explicit local escape hatches; named token flags resolve from the KV.

The HTTP boundary applies exact `org` and `workspace` ABAC to optional request `metadata`, defaults newly created resources to the verified tenant, persists a secret-free owner context on workflow/evaluation/batch resources, and hides resources whose owner context is missing or mismatched. A boolean-only verifier is rejected because scope RBAC without an identity context cannot safely establish tenant authorization.

### Consequences

* Good, because the repository now records the Keyverse dependency and has a safe injection boundary.
* Good, because auth adapter failures are denials, not accidental access.
* Good, because scope RBAC and exact org/workspace ABAC are enforced at the request and resource boundaries.
* Good, because runtime provider/auth secrets no longer use the legacy CLI environment defaults.
* Bad, because a complete production OIDC adapter still requires deployment-specific issuer, audience, JWKS, scopes, TLS, and acceptance evidence.
* Bad, because resources created outside the HTTP boundary or by older state databases have no tenant owner and remain unavailable to tenant-scoped HTTP callers until migrated or recreated.

### Confirmation

Run the external-verifier, boolean-rejection, cross-tenant, workflow-owner, and batch-owner security tests and inspect readiness_profile()["auth_mode"]. In deployment, record Keyverse RP desired-state digest, convergence receipt, client UUID, controlled authorization-code/PKCE result, refresh/logout result, and rollback reference without recording bearer or client-secret bytes.

## Pros and Cons of the Options

### Static token only

* Good, because it works offline.
* Bad, because it is not OIDC and does not express issuer/audience/claims.
* Bad, because legacy environment defaults encourage secret leakage and rotation drift.

### Embed identity implementation

* Good, because the service owns more of the flow.
* Bad, because custom cryptography/protocol code is a high-risk expansion.
* Bad, because it would cross Keyverse's deployment-controller trust boundary.

### External verifier boundary (chosen)

* Good, because Keyverse/OIDC correctness stays with a reviewed identity component.
* Good, because the gateway remains stdlib/local-test friendly.
* Bad, because production wiring is an explicit deployment task and cannot be simulated by a unit test alone.

## Problem Register and Remediation Directions

| Finding | Direction | State |
| --- | --- | --- |
| Keyverse dependency was not visible in the gateway docs/architecture. | Record it here and in KV/auth docs; require deployment acceptance evidence. | Implemented |
| Static auth was mistaken for ecosystem identity. | Expose bearer_verifier; label static tokens local-only. | Implemented |
| The verifier returned only a boolean, losing verified subject/org/workspace claims before resource authorization. | Require `VerifiedIdentity` with non-blank subject, org, workspace, and requested scope; reject boolean-only results and verifier failures. | Implemented |
| Scope RBAC existed without tenant/resource ABAC. | Compare exact request `metadata.org`/`metadata.workspace` to verified Keyverse claims; persist owner context for workflow, evaluation, and batch resources; hide mismatched or ownerless reads. | Implemented |
| Older or direct in-process resources have no owner context. | Migrate/recreate them before tenant-scoped production exposure; do not infer ownership from resource IDs or caller-supplied aliases. | Required follow-up |
| CLI had legacy token environment defaults. | Resolve named auth tokens from KV; remove token env defaults from the Python CLI. | Implemented |
| RP registration and client secret placement were absent. | Add a deployment-controller integration using Keyverse preflight/reconcile and approved secret storage; never put secrets in this repo. | Required follow-up |
| JWT validation library/issuer/JWKS contract is deployment-specific. | Select and review one adapter, including rotation, claims, TLS, clock skew, and negative tests before production. | Required follow-up |
| Partial or mixed CLI token modes could trigger an unrelated KV lookup before reporting the configuration error. | Treat explicit `--admin-token-key`/`--inference-token-key` as split-mode selectors and reject mixing/incompleteness before resolving any KV entry. | Implemented |
| Container startup passed `CONTEXTUAL_ORCHESTRATOR_TOKEN` as secret argv/env material, bypassing the KV boundary. | Pass `--auth-token-key CONTEXTUAL_ORCHESTRATOR_TOKEN`; let the Keyverse/KV deployment adapter resolve the value at runtime. | Implemented |
| Public API may be reachable without the identity edge. | Keep auth mandatory; deny when no static token or external verifier is configured. | Implemented |

## Risks and Mitigations

| risk | likelihood | impact | mitigation | owner |
| --- | --- | --- | --- | --- |
| Deployment injects a verifier that only decodes JWTs. | medium | critical | Require signature/issuer/audience/expiry/scope tests and code review; no decode-only adapter accepted. | security owner |
| Keyverse is unavailable during startup. | medium | high | Fail closed, keep liveness separate, and use explicit readiness/rollback evidence. | deployment owner |
| Local developers put a token in process arguments. | medium | medium | Document only for local use; prefer KV-backed names and external verifier in deployed environments. | maintainer |

## Rollback / Exit Strategy

For local rollback, use an explicit static token with the same mandatory auth gate. For production rollback, remove the external verifier only as part of a controlled deployment rollback; never silently downgrade a public deployment to unauthenticated or environment-default auth.

## Affected Components

* contextual_orchestrator/server.py
* contextual_orchestrator/orchestrator.py
* contextual_orchestrator/cost_router.py
* contextual_orchestrator/batch_routing.py
* contextual_orchestrator/__main__.py
* contextual_orchestrator/credentials.py
* docs/kv-credentials.md
* Keyverse deployment-controller/RP registration integration (follow-up)

## More Information

* [Keyverse repository](https://github.com/ContextualWisdomLab/keyverse)
* [Keyverse relying-party onboarding](https://github.com/ContextualWisdomLab/keyverse/blob/main/docs/rp-onboarding.md)
* [Keyverse architecture](https://github.com/ContextualWisdomLab/keyverse/blob/main/ARCHITECTURE.md)
