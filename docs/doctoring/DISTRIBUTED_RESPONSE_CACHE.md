# Doctoring: distributed response cache

## Evidence boundary

The implementation is an optional Redis/Dragonfly-compatible response-cache
provider. It does not claim semantic embedding similarity: keys represent the
same normalized request envelope, so a cache hit is exact and reproducible.
The local TTL/LRU path remains the standalone default.

## Source map

| Requirement | Implementation | Verification |
|---|---|---|
| Provider-neutral contract | `ResponseCacheProvider` protocol | import and round-trip tests |
| Redis/Dragonfly compatibility | injected `get`/`set(..., ex=ttl)` client | fake client with bytes and TTL evidence |
| Safe keying | SHA-256 model/mode/message envelope digest | key stability and collision-scope tests |
| Cache outage behavior | read/write exceptions fail open | backend failure tests |
| Explicit bypass | strict `X-Cache-Bypass` parser | valid and ambiguous header tests |

## References — APA 7th

Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP caching* (RFC 9111;
STD 98). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc9111

Redis Ltd. (n.d.). *SET command*. Redis documentation. Retrieved August 20,
2026, from https://redis.io/docs/latest/commands/set/
