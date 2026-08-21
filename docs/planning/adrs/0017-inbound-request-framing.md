---
status: proposed
date: 2026-08-20
decision-makers:
  - contextual-orchestrator maintainers
---

# ADR 0017: Fail-closed inbound request framing

## Context

The HTTP handler previously converted one `Content-Length` value and delegated
all other framing behavior to `BufferedReader.read`. Missing, negative,
duplicate, transfer-coded, truncated, and slow request bodies therefore did not
share one bounded policy. This is an inbound trust-boundary defect, separate
from provider-response framing.

## Decision

Accept only one ASCII decimal `Content-Length` within the configured body limit.
Reject missing length, duplicate length lines, `Transfer-Encoding`, malformed
or signed values, and `Transfer-Encoding` plus `Content-Length` before reading
body bytes. Read exactly the declared number of bytes with a bounded socket
deadline. On any framing failure, return a stable generic error and close the
connection so unread bytes cannot be interpreted as another request.

The server does not implement chunked decoding in this change. A future bounded
decoder requires a separate design and socket-level evidence.

## Consequences

- Every current JSON body endpoint inherits one parser/reader policy.
- Clients must send a fixed-length JSON request; the API returns `411`, `413`,
  `408`, or `400` with `invalid_request_framing`/named framing codes as
  appropriate.
- The body deadline and byte limit are visible in the secret-free readiness
  profile.
- Socket-level, truncation, timeout, duplicate, transfer-coding, and boundary
  tests become merge evidence.

## Standards

Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP/1.1* (RFC 9112).
RFC Editor. https://www.rfc-editor.org/rfc/rfc9112.html

## Customer next action

Send JSON requests with exactly one fixed decimal `Content-Length`; retry a
framing error only after correcting the request, not by replaying the same
ambiguous bytes.
