# ADR 0002: Optional distributed response cache

- Status: Proposed
- Date: 2026-08-20
- Decision owners: ContextualWisdomLab

## Decision

Keep the existing in-process TTL/LRU cache for standalone deployments and add a
small provider contract for Redis/Dragonfly-compatible clients. The provider is
dependency-free: the application injects an already configured client and a
positive TTL from its KV/configuration layer. Runtime code does not read an
environment variable or create a second connection pool.

Requests are keyed by a SHA-256 digest of the normalized model, orchestration
mode, ordered message envelope, sampling parameters, and an optional
authenticated partition. Prompts, responses, and bearer material do not appear
in the remote key. HTTP callers always derive the partition from the already
authenticated bearer; direct library callers must provide a non-secret
partition when responses must be isolated. Cache reads and writes fail open
because the cache is an optimization, not the source of truth. `X-Cache-Bypass:
true` (or `1`) bypasses the cache for a request; ambiguous header values are
rejected.

The provider is opt-in and mutually exclusive with the local `cache_ttl` option.
No cache is used for streamed route responses, and cache configuration does not
change provider routing, credentials, or cost-ledger attribution.

## Consequences

- Multiple gateway workers can reuse deterministic responses without a runtime
  Redis dependency in the leaf package.
- A cache hit records zero provider tokens and zero provider cost under a
  dedicated `cache` request channel; it is not silently rebilled as inference.
- A cache outage increases provider traffic but does not make valid requests fail.
- Operators must choose a TTL appropriate to response freshness and their data
  retention policy; cache contents are not an authoritative record.

## Standards traceability

The request-key and bypass behavior follows the distinction between a cacheable
response and an authoritative application result in HTTP caching semantics. The
provider itself uses the Redis-compatible `GET`/`SET EX` contract and remains
behind an explicit application boundary.

## References — APA 7th

Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP caching* (RFC 9111;
STD 98). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc9111

Redis Ltd. (n.d.). *SET command*. Redis documentation. Retrieved August 20,
2026, from https://redis.io/docs/latest/commands/set/
