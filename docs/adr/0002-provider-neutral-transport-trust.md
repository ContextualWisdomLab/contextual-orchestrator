# ADR-0002: Provider-neutral interface and transport trust

## Status

`implemented_on_protected_main` for the OpenAI-compatible HTTPS contract,
credential-name binding, loopback/private-address block, optional host
allowlist, timeouts, and output-token cap.

Stricter DNS pinning, ambient-proxy rejection, redirect rejection, and
bounded response-framing ownership remain incomplete on protected `main` and
must not be described as shipped. Related work lives in other pull requests;
this ADR records the protected-main decision only.

**Date:** 2026-08-17
**Decision owner:** Contextual Orchestrator maintainers

## Context and decision drivers

The gateway must swap OpenAI-compatible providers without a provider SDK
lock-in while preventing stored SSRF, credential forwarding, ambiguous
responses, and unbounded resource use (OWASP Foundation, n.d.-b; Fielding et
al., 2022; Rescorla, 2018). Validation that is disconnected from socket
selection does not stop DNS rebinding.

The public shape is a vendor-subset HTTP API, not a standards-body
certification. OpenAPI 3.1 is the contract format for review (OpenAPI
Initiative, 2021). JSON request bodies follow RFC 8259 (Bray, 2017). Bearer
authentication follows RFC 6750 (Jones & Hardt, 2012). Streaming uses
server-sent events (WHATWG, n.d.).

## Considered alternatives

- Provider SDK per vendor: richer features, but fragmented authority and a
  larger dependency surface. Rejected under the Ponytail gate until raw
  OpenAI-compatible HTTP is insufficient.
- Validate the URL once, then use a default opener: vulnerable to resolver
  and redirect/proxy changes.
- Trusted internal proxy only: useful as defense in depth, but not a
  standalone security guarantee.
- Compatible HTTP contract with fail-closed destination checks: selected for
  protected `main`.

## Decision

Model configuration contains a compatible base URL and a KV credential name.
Non-mock production egress is `https://`, optionally allowlisted, bounded, and
credentialed only at the final request boundary. The runtime blocks loopback,
private, link-local, multicast, and reserved provider addresses before sending
a key.

`mock://` agents remain networkless for offline tests. Missing credentials
raise `NotConfigured` rather than falling back to an environment variable.

## Consequences

Providers remain swappable. Some enterprise proxies require an explicit,
reviewed adapter rather than ambient behavior. Strict parsing may reject
provider extensions outside the documented subset.

## Failure and recovery

Private or non-global destinations, missing credentials, TLS failure, and
caller 4xx errors fail closed. Transient timeouts, 429, and 5xx enter jittered
retry, then capability-matched failover and a per-agent circuit breaker
(Fielding et al., 2022, §9.2.2: automatic replay is appropriate when request
semantics are idempotent).

## Security, privacy, and governance impact

The design limits credential exfiltration and internal-network reach (OWASP
Foundation, n.d.-b; National Institute of Standards and Technology, 2022).
Provider content remains untrusted and cannot grant tool, review, or host
authority (OWASP Foundation, 2025).

## Compatibility and migration

Mock providers remain networkless. Compatible providers that rely on
redirects, proxies, nonstandard JSON, or private destinations need an explicit
deployment contract rather than silent compatibility.

## Verification and acceptance

`tests/test_security_hardening.py` and related server tests cover
authentication, body validation, private-address rejection, and redacted
errors. Stronger pin/proxy/framing tests are required before those controls
may be marked implemented.

## Rollback and supersession

Do not roll back by weakening destination validation. Disable a faulty
provider or revert to the last accepted implementation. A replacement requires
equivalent security tests and an explicit authority map.

## References

Bray, T. (2017). *The JavaScript Object Notation (JSON) data interchange
format* (RFC 8259). RFC Editor. https://doi.org/10.17487/RFC8259

Fielding, R., Nottingham, M., & Reschke, J. (Eds.). (2022). *HTTP semantics*
(RFC 9110). RFC Editor. https://doi.org/10.17487/RFC9110

Jones, M., & Hardt, D. (2012). *The OAuth 2.0 authorization framework: Bearer
token usage* (RFC 6750). RFC Editor. https://doi.org/10.17487/RFC6750

OpenAPI Initiative. (2021, February 15). *OpenAPI Specification, Version
3.1.0*. https://spec.openapis.org/oas/v3.1.0.html

OWASP Foundation. (n.d.-b). *Server-side request forgery prevention cheat
sheet*. Retrieved August 17, 2026, from
https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html

OWASP Foundation. (2025). *OWASP Top 10 for large language model
applications 2025*. https://owasp.org/www-project-top-10-for-large-language-model-applications/

Rescorla, E. (2018). *The Transport Layer Security (TLS) protocol version 1.3*
(RFC 8446). RFC Editor. https://doi.org/10.17487/RFC8446

WHATWG. (n.d.). *HTML living standard: Server-sent events*. Retrieved August
17, 2026, from
https://html.spec.whatwg.org/multipage/server-sent-events.html

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1* (NIST SP 800-218).
https://doi.org/10.6028/NIST.SP.800-218

See also [docs/REFERENCES.md](../REFERENCES.md).
