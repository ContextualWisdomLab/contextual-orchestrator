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
    target: "verifier exceptions and wrong scopes return unauthorized"
    measurement_window: "every protected request"
    source: "SecurityConfig authorization tests"
---

# Keyverse authentication boundary and KV credential placement

## Context

The repository originally treated gateway authentication as a static bearer-token comparison and read CLI token defaults from environment variables. The ecosystem identity plane is broader: Keyverse documents contextual-orchestrator as an OIDC relying party, keeps RP registration/client secrets in the IdP DB/KV, and requires deployment-controlled reconciliation and acceptance evidence.

> Keyverse states that ecosystem applications, including contextual-orchestrator, are OpenID Connect relying parties.
>
> Keyverse states that RP client registrations and secrets live in the IdP database/KV, not in an RP environment.
>
> SecurityConfig.bearer_verifier now accepts a deployment-injected verifier and denies when that verifier errors or rejects scope.

## Decision Drivers

* Recognize Keyverse as the production identity boundary instead of pretending a static token is OIDC.
* Keep client secrets and provider credentials in KV/deployment systems.
* Avoid an unsafe hand-written JWT decoder in the stdlib core.
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

SecurityConfig.bearer_verifier(token, scope) is the only production integration point. The adapter must validate issuer, audience, signature, expiry, key rotation, and scope using an approved library or trusted Keyverse/WAF boundary. The core does not decode JWTs, call Keycloak Admin REST, or store RP client secrets. CLI token flags are explicit local escape hatches; named token flags resolve from the KV.

### Consequences

* Good, because the repository now records the Keyverse dependency and has a safe injection boundary.
* Good, because auth adapter failures are denials, not accidental access.
* Good, because runtime provider/auth secrets no longer use the legacy CLI environment defaults.
* Bad, because a complete production OIDC adapter still requires deployment-specific issuer, audience, JWKS, scopes, TLS, and acceptance evidence.
* Bad, because callers using SecurityConfig directly must choose an explicit token or verifier.

### Confirmation

Run the external-verifier security test and inspect readiness_profile()["auth_mode"]. In deployment, record Keyverse RP desired-state digest, convergence receipt, client UUID, controlled authorization-code/PKCE result, refresh/logout result, and rollback reference without recording bearer or client-secret bytes.

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
| CLI had legacy token environment defaults. | Resolve named auth tokens from KV; remove token env defaults from the Python CLI. | Implemented |
| RP registration and client secret placement were absent. | Add a deployment-controller integration using Keyverse preflight/reconcile and approved secret storage; never put secrets in this repo. | Required follow-up |
| JWT validation library/issuer/JWKS contract is deployment-specific. | Select and review one adapter, including rotation, claims, TLS, clock skew, and negative tests before production. | Required follow-up |
| Partial or mixed CLI token modes could trigger an unrelated KV lookup before reporting the configuration error. | Reject single/split mode mixing and incomplete split credentials before resolving any KV entry. | Implemented |
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
* contextual_orchestrator/__main__.py
* contextual_orchestrator/credentials.py
* docs/kv-credentials.md
* Keyverse deployment-controller/RP registration integration (follow-up)

## More Information

* [Keyverse repository](https://github.com/ContextualWisdomLab/keyverse)
* [Keyverse relying-party onboarding](https://github.com/ContextualWisdomLab/keyverse/blob/main/docs/rp-onboarding.md)
* [Keyverse architecture](https://github.com/ContextualWisdomLab/keyverse/blob/main/ARCHITECTURE.md)
