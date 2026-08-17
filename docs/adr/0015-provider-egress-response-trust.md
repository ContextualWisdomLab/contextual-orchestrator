# ADR-0015: Provider egress and response trust

## Status

`accepted_architecture`

Protected `main` requires HTTPS for non-mock providers, blocks
loopback/private/reserved destinations, supports an optional host allowlist,
applies timeouts and an output-token cap, and redacts secrets from errors.
DNS pinning through connection establishment, ambient-proxy rejection,
redirect rejection, and a complete inbound/outbound framing contract are
**not** claimed as shipped.

**Date:** 2026-08-17
**Decision owner:** Contextual Orchestrator maintainers

## Context and decision drivers

Provider configuration can be attacker-influenced or stale, and the provider
receives both a credential and purpose-bound request content. Scheme and
hostname validation do not prevent DNS rebinding, connection-to-validation
drift, ambient proxy use, credential-forwarding redirects, ambiguous HTTP
framing, or resource exhaustion (OWASP Foundation, n.d.-b; Fielding et al.,
2022; Rescorla, 2018; Bray, 2017).

The boundary must remain provider-neutral and independently usable without
assuming an external egress proxy. A reverse proxy is defense in depth, not
a substitute for application-owned checks.

## Considered alternatives

- Trust operator-entered provider URLs: insufficient against mistakes,
  compromised configuration, and DNS changes.
- Validate URL and DNS, then use the default opener: socket selection,
  ambient proxies, and redirects can escape the validated identity.
- Require a central proxy: useful as defense in depth, but it breaks
  standalone authority and does not validate response semantics.
- Fail-closed destination policy now, and pin/framing ownership as the
  accepted target: selected.

## Decision

Non-mock egress requires HTTPS, an optional explicit host allowlist, and
rejection of non-globally-routable resolved addresses. The accepted target
additionally pins a validated address through connection establishment while
preserving the original hostname for TLS SNI and certificate verification,
ignores ambient proxy configuration, rejects redirects, and bounds header,
body, chunk, cumulative SSE, output-token, and batch-response resources.

The accepted response boundary rejects conflicting length/transfer framing,
invalid JSON, non-finite numbers, and malformed or truncated UTF-8 and SSE
(Fielding et al., 2022; Bray, 2017; WHATWG, n.d.). Errors are bounded and
redacted.

Until those target controls land on protected `main`, only the implemented
destination and credential checks may be described as shipped.

## Consequences

Some provider extensions and enterprise proxy assumptions require a reviewed
adapter instead of silent compatibility. The transport surface is larger, but
credentials, memory, and parser state gain one testable authority.

## Failure and recovery

Private or non-global resolution, TLS failure, missing credentials, and
caller 4xx fail closed. Only explicitly classified timeout, throttle,
unavailable, or eligible 5xx failures may retry or fail over (Fielding et
al., 2022, §9.2.2). Recovery disables the affected provider or restores the
last accepted transport; it never allows a private destination as a
shortcut.

## Security, privacy, and governance impact

This boundary addresses SSRF, credential exfiltration, and sensitive-error
leakage (OWASP Foundation, 2025; National Institute of Standards and
Technology, 2024a). Provider output remains untrusted and cannot grant tool,
host, review, or credential authority.

## Compatibility and migration

`mock://` remains networkless. Compatible providers must offer direct HTTPS
and the documented response subset. Deployment-specific egress controls add
defense in depth but do not replace the library boundary.

## Verification and acceptance

`tests/test_security_hardening.py` covers the implemented destination and
authentication checks. Pin, proxy, redirect, and framing tests are required
before those controls change status.

## Rollback and supersession

Rollback disables affected providers and restores the last protected
implementation while retaining safe global-address validation. Supersession
requires equal or stronger address, connection, TLS, credential, proxy,
redirect, framing, resource, parser, compatibility, and recovery evidence.

## References

Bray, T. (2017). *The JavaScript Object Notation (JSON) data interchange
format* (RFC 8259). RFC Editor. https://doi.org/10.17487/RFC8259

Fielding, R., Nottingham, M., & Reschke, J. (Eds.). (2022). *HTTP semantics*
(RFC 9110). RFC Editor. https://doi.org/10.17487/RFC9110

Rescorla, E. (2018). *The Transport Layer Security (TLS) protocol version 1.3*
(RFC 8446). RFC Editor. https://doi.org/10.17487/RFC8446

WHATWG. (n.d.). *HTML living standard: Server-sent events*. Retrieved August
17, 2026, from
https://html.spec.whatwg.org/multipage/server-sent-events.html

OWASP Foundation. (n.d.-b). *Server-side request forgery prevention cheat
sheet*. Retrieved August 17, 2026, from
https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html

OWASP Foundation. (2025). *OWASP Top 10 for large language model
applications 2025*. https://owasp.org/www-project-top-10-for-large-language-model-applications/

National Institute of Standards and Technology. (2024a). *Artificial
intelligence risk management framework: Generative artificial intelligence
profile* (NIST AI 600-1). https://doi.org/10.6028/NIST.AI.600-1

See also [docs/REFERENCES.md](../REFERENCES.md).
