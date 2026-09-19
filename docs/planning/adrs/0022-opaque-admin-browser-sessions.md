# ADR 0022: Opaque admin browser sessions

- Status: Proposed implementation
- Date: 2026-08-20
- Figma file: `vsZMd8WAv42HDRgcZuNcWk` (existing embedded admin source)
- Related issue: #116

## Decision

The embedded admin console establishes a short-lived, bounded, opaque
server-side session after one admin bearer validation. Browser requests carry
only the `HttpOnly; SameSite=Strict; Secure` cookie by default. API clients
continue to use bearer authentication, and a session cookie never authorizes
inference scope.

State-changing requests authenticated by the session also require same-origin
`Origin`/`Host` evidence. Missing, `null`, or mismatched origins fail closed.
The session store has a TTL and a maximum size with deterministic earliest
expiry eviction, preventing unbounded process memory growth.

## Why

Reusing a long-lived bearer as a browser cookie increases replay impact and
couples browser lifetime to API credential lifetime. Blanket PII masking would
also make authorized operator work unusable; this boundary protects the
credential and access purpose instead of altering authorized business data.

## Consequences

The current store is process-local and therefore suitable for a single gateway
process or explicit sticky-session deployment. A multi-process or durable
session backend requires a separate ADR with rotation, revocation replication,
key lifecycle, and failover evidence. HTTPS is required when the secure cookie
default is enabled; local HTTP tests must opt into an insecure cookie explicitly.

## Verification

The security suite covers valid establishment, raw-bearer non-reflection,
admin-only scope, cross-origin rejection, revocation, and clearing. The admin
contract covers the session form, same-origin credential mode, and token field.
Hosted Security, Strix, dependency, and full-suite Checks remain required for
release.

## References (APA 7th)

Barth, A. (2011). *HTTP state management mechanism* (RFC 6265). Internet
Engineering Task Force. https://doi.org/10.17487/RFC6265

National Institute of Standards and Technology. (2022). *Digital identity
guidelines: Authentication and lifecycle management (NIST Special Publication
800-63B)*. https://doi.org/10.6028/NIST.SP.800-63b

OWASP Foundation. (n.d.). *Session management cheat sheet*. Retrieved August
20, 2026, from https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html
