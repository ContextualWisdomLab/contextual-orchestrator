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
| Safe keying | SHA-256 model/mode/message/parameter/partition envelope digest | key stability and partition-isolation tests |
| Cache outage behavior | read/write exceptions fail open | backend failure tests |
| Explicit bypass | strict `X-Cache-Bypass` parser | valid and ambiguous header tests |
| Cost honesty | cache hits use zero tokens and zero cost on the `cache` channel | ledger replay test |

HTTP cache partitions are derived from the authenticated bearer digest and are
never returned or persisted as raw credentials. Direct library callers choose a
non-secret `cache_partition` when identical prompts must remain isolated.

## Effort-catalog attribution repair (2026-09-06)

### Observed failure and decision

At RED `80fe7d5f75973b40986cac895369613ac51803d5`, the same request after a
worker-effort change from medium to high returns the old medium answer from
both cache-provider paths. The saved record then recomputes its snapshot from
the new catalog, falsely attributing that answer to the high setting. A warm
cache also returns an answer after a required catalog role is removed.
Four deterministic unit cases reproduce these failures without external calls.

Source `29712e06` adds the existing validated catalog hash to request parameters
in `TaskOrchestrator._cache_key`, the common local/shared key boundary. It
rethrows `EffortProfileError` before the existing serialization-failure fallback
in `complete`. `run` deep-copies the completed result's existing snapshot and
does not fabricate one when the result has none. Follow-up `92858f33` retains
the existing error import and removes the redundant addition.

| Situation | Required behavior and evidence |
|---|---|
| Catalog content changes between requests | New key, one new worker execution; local TTL and injected shared-provider paths are tested. |
| New mapping has equal catalog content | Same key and cache hit; object identity is not the cache identity. |
| Required role removed after a warm-cache request | Raise the configuration error before cache reuse or another worker call. |
| Settings change after completion but before persistence | Preserve the completed result's original snapshot. |
| Caller later mutates the completion snapshot | Saved record remains unchanged because the copy is detached. |
| No catalog configured | Keep the existing key envelope and absence of effort metadata. |

A global cache flush was rejected because it would not define identity across
shared-cache clients. Hashing the object identity was rejected because in-place
changes would remain invisible and equal mappings would miss. A new cache layer
or estimator is unnecessary: canonical validation/hashing and `copy.deepcopy`
already exist. Provider/cache outages retain their existing fail-open behavior;
invalid configuration is a different boundary. No dependency was added.

### Exact local verification

All four new cases fail at `80fe7d5f` (exit 1, 0.23 seconds) and pass at
`29712e06` (exit 0, 0.26 seconds). On clean final source
`92858f33f52902460b9cc4d003e02a5aff21d28c`, the following command passes
**148 tests in 15.25 seconds**:

```sh
.venv/bin/pytest -q tests/test_distributed_cache_truth_and_isolation.py \
  tests/test_distributed_response_cache.py tests/test_response_cache.py \
  tests/test_reasoning_effort_profile.py tests/test_psychometric_routing.py \
  tests/test_psychometric_benchmark_boundaries.py tests/test_persistence.py \
  tests/test_workflow_run_object_authorization.py
```

The evidence directory is `/tmp/co-1067-effort-cache.u3eBJA`:
`red-pytest.log`, `green-{pytest.log,junit.xml}`,
`final-focused-{pytest.log,junit.xml}`, and `coverage-{pytest.log,data}` /
`coverage.json`. The coverage run uses the first three files above with
`python -m coverage run --branch -m pytest -q` (27 passed in 0.53 seconds).
It covers eight/eight statements and two/two branches of `_cache_key`, the new
configuration-error rethrow, and both new snapshot-preservation branches.
Other completion/persistence branches are outside that complete-coverage claim.

`uv tool run --offline ruff check --isolated --select E4,E7,E9,F` passes on
both changed Python files using an already cached tool. The initial default
Ruff selection exposed the redundant import, which was removed. The final
default selection still reports 31 findings already present in the RED
orchestrator source, with identical code/message counts; it is not a full-lint
success. Neither dependencies nor lint configuration were changed.

### Limits of the sequential repair

These are unit fixtures of declared settings, not evidence that a provider
honors effort, an IRT construct is invariant, or routing quality improves.
Snapshot hashing adds validation work to opted-in cached requests; no latency
improvement is claimed. No-catalog requests avoid that additional validation.
At `92858f33`, this patch did not provide a stable effort revision during an
in-flight request, and cache-disabled/bypass execution kept its earlier
validation timing. The later proposed
[request-revision repair](reasoning-effort-profile.md#request-revision-contract-proposed)
addresses that catalog-specific gap, including streaming, retry, and early
validation. Neither repair freezes the agent pool and policy or proves that
an upstream provider honors the declared controls.
Hosted checks, independent review, protected delivery, and immutable release
remain required before consumers adopt this unmerged change.

## References — APA 7th

Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP caching* (RFC 9111;
STD 98). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc9111

Redis Ltd. (n.d.). *SET command*. Redis documentation. Retrieved August 20,
2026, from https://redis.io/docs/latest/commands/set/
