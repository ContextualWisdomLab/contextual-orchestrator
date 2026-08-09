# ADR-0015: Provider egress and response trust

## Status

`active_pr` — PR #96 contains the complete candidate implementation; protected
main retains only the controls explicitly documented there.

## Context and decision drivers

Provider configuration can be attacker-influenced or stale, and the provider
receives both a credential and purpose-bound request content. Scheme and
hostname validation do not prevent DNS rebinding, connection-to-validation
drift, ambient proxy use, credential-forwarding redirects, ambiguous HTTP
framing, or resource exhaustion through JSON, JSONL, and SSE responses. The
boundary must remain provider-neutral and independently usable without assuming
an external egress proxy.

## Considered alternatives

- trust operator-entered provider URLs: insufficient against mistakes,
  compromised configuration, and DNS changes;
- validate URL and DNS, then use the default opener: socket selection, ambient
  proxies, and redirects can escape the validated identity;
- require a central proxy: useful as defense in depth, but it breaks standalone
  authority and does not validate response semantics;
- retain DNS validation through connection establishment and own bounded
  response parsing: selected.

## Decision

Non-mock egress requires HTTPS, an optional explicit host allowlist, and only
globally routable resolved addresses. The accepted transport pins a validated
address through connection establishment while preserving the original
hostname for TLS SNI and certificate verification. It ignores ambient proxy
configuration, rejects redirects, constrains timeouts/retries, and bounds header,
body, chunk, cumulative SSE, output-token, and batch-response resources.

The response boundary rejects conflicting length/transfer framing, invalid or
duplicate JSON keys, non-finite numbers, malformed/truncated UTF-8 and SSE, and
completion without the required terminal state. Errors are bounded and redacted.
None of these active-PR behaviors is described as shipped before protected
merge.

## Consequences

Some provider extensions and enterprise proxy assumptions require a reviewed
adapter instead of silent compatibility. The transport surface is larger, but
credentials, memory, and parser state gain one testable authority.

## Failure and recovery

Private/non-global resolution, pin drift, TLS failure, redirect, proxy attempt,
invalid framing, excessive bytes/tokens, malformed content, or exhausted retry
budget fails closed. Only explicitly classified timeout, throttle, unavailable,
or eligible 5xx failures may retry or fail over. Recovery disables the affected
provider or restores the last accepted transport; it never allows a private
destination or ambient proxy as a shortcut.

## Security, privacy, and governance impact

This boundary addresses SSRF, DNS rebinding, credential exfiltration, redirect
confusion, response smuggling, decompression/resource exhaustion, parser
differentials, and sensitive-error leakage. Provider output remains untrusted
and cannot grant tool, host, review, or credential authority.

## Compatibility and migration

`mock://` remains networkless. Compatible providers must offer direct HTTPS
and the documented response subset. Rollout is adapter-local and can be
reverted without rewriting workflow evidence. Deployment-specific egress
controls add defense in depth but do not replace the library boundary.

## Verification and acceptance

Acceptance includes DNS rebinding and IPv4/IPv6 tests; allowlist and non-global
rejection; TLS hostname/certificate identity; proxy and redirect rejection;
credential revocation; retry, failover, circuit, and cleanup; framing and
cumulative resource bounds; strict JSON/JSONL/SSE/UTF-8; error redaction;
property/fuzz tests; Semgrep/CodeQL; exact-head coverage/docstrings; and
qualifying review.

## Rollback and supersession

Rollback disables affected providers and restores the last protected
implementation while retaining safe global-address validation. Supersession
requires equal or stronger address, connection, TLS, credential, proxy,
redirect, framing, resource, parser, compatibility, and recovery evidence.

## References

Bray (2017), Fielding et al. (2022), Rescorla (2018), and OWASP Foundation
(n.d.). Full APA 7 entries are in [the reference index](../REFERENCES.md).
