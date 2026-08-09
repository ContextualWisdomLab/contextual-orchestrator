# ADR-0002: Provider-neutral interface and transport trust

## Status

`accepted_architecture` — the provider-neutral HTTPS/global-address boundary is
`implemented_on_protected_main`; DNS pinning, proxy/redirect rejection, and the
strict response boundary are `active_pr` in #96.

## Context and decision drivers

The gateway must swap OpenAI-compatible providers without provider SDK lock-in
while preventing stored SSRF, credential forwarding, ambiguous responses, and
unbounded resource use. Validation that is disconnected from socket selection
does not stop DNS rebinding.

## Considered alternatives

- provider SDK per vendor: richer features, but fragmented authority and
  dependency surface;
- validate URL once, then use a default opener: vulnerable to resolver and
  redirect/proxy changes;
- trusted internal proxy only: useful deployment option but not a standalone
  security guarantee;
- compatible HTTP contract with end-to-end pinned trust: selected architecture.

## Decision

Model configuration contains a compatible base URL and credential name.
Production egress is HTTPS, globally routable, optionally allowlisted, bounded,
and credentialed only at the final request boundary. The accepted transport
retains validation-time addresses through connection establishment, preserves
host/TLS authority, disables ambient proxies and redirects, bounds cumulative
response bytes, and strictly validates JSON/JSONL/SSE framing. Until #96 merges,
only protected-main controls may be claimed shipped.

## Consequences

Providers remain swappable. Some enterprise proxies require an explicit,
reviewed adapter rather than ambient behavior. Strict parsing may reject
provider extensions outside the documented subset.

## Failure and recovery

Private/non-global destinations, missing credentials, TLS failure, redirects,
ambiguous framing, oversized bodies, malformed JSON/SSE, and non-finite values
fail closed. Transient network/provider errors alone enter bounded retry/failover.

## Security, privacy, and governance impact

The design limits credential exfiltration and internal-network reach. Provider
content remains untrusted and cannot grant tool, review, or host authority.

## Compatibility and migration

Mock providers remain networkless. Compatible providers that rely on redirects,
proxies, nonstandard JSON, or private destinations need an explicit deployment
contract rather than silent compatibility.

## Verification and acceptance

Tests cover global-address policy, DNS rebinding, IPv4/IPv6, TLS SNI and
certificate identity, redirect/proxy leakage, credential revocation, retries,
cleanup, body/framing bounds, strict JSON/JSONL/SSE, and redacted errors.

## Rollback and supersession

Do not roll back by weakening validation. Disable a faulty provider or revert to
the last accepted pinned implementation. A replacement requires equivalent
security tests and an explicit authority map.

## References

Bray (2017), Fielding et al. (2022), Rescorla (2018), OWASP Foundation (n.d.).
See [the reference index](../REFERENCES.md).
