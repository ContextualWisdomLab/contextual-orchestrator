# Durable registry semantic identifiers

## Decision

The batch-job registry is a reusable orchestration persistence boundary. Its public Python seams therefore name the domain concept rather than expose generic `name` and `key` parameters.

- `ValkeyJsonMapping(..., name, ...)` → `ValkeyJsonMapping(..., registry_name, ...)`
- `JobRegistryFactory.lock(name, key, ...)` → `JobRegistryFactory.lock(registry_name, claim_key, ...)`
- `JobRegistryFactory.mapping(name, ...)` → `JobRegistryFactory.mapping(registry_name, ...)`

The semantic names are authoritative in signatures and new code. The established `name=` and `key=` keyword forms remain accepted only through a bounded compatibility-keyword adapter so external Python callers are not broken by a refactor. Supplying both the semantic and legacy form for the same identifier fails closed with `TypeError`; unknown compatibility keywords are also rejected. No deprecation warning is suppressed: the aliases remain supported until a separately versioned breaking API contract explicitly retires them.

The runtime adapter must technically accept omission of `registry_name`/`claim_key` long enough to translate a legacy keyword inside the function body. That implementation detail is not the public semantic contract. `contextual_orchestrator.registry_signature_contract` installs explicit Python `__signature__` metadata so `inspect.signature` and signature-driven tooling see `registry_name` and `claim_key` as required non-null `str` parameters. The compatibility-only `name=`/`key=` aliases therefore remain executable without advertising the new authoritative identifiers as optional.

Existing repository callers pass these identities positionally, so the change preserves runtime behavior and stored Valkey keys. The generated key format remains `batch_job_registry:{registry_name}` and claim format remains `batch_job_registry:{registry_name}:claim:{claim_key}`; no persisted registry namespace is rewritten and no migration is required.

## DDD / compatibility boundary

- **Bounded context:** durable batch-job orchestration registry.
- **Domain service:** `JobRegistryFactory`.
- **Repository adapter:** `ValkeyJsonMapping`.
- **Invariant:** registry names identify durable logical maps; claim keys identify one claim within a registry.
- **Invariant:** semantic registry and claim identifiers are required in the authoritative public introspection contract even while legacy keyword aliases remain executable at the compatibility boundary.
- **Invariant:** renaming Python parameters must not alter Valkey hash/lock key bytes or retention semantics.
- **Anti-corruption boundary:** legacy generic keyword names are translated at the call boundary and never become the internal domain vocabulary.

`tests/test_batch_job_registry_naming_contract.py` protects the semantic Python signatures, required/non-null introspection contract, legacy-keyword compatibility, conflict behavior, and rejection of open-ended kwargs. Existing batch routing, cost routing, video-job, file-registry, retention, fencing, and cancellation suites remain responsible for behavior and persistence compatibility.

## Failed-Check RCA — 2026-09-02

PR #997 exact head `5b3f75e665aafb219407aae7ea79ef16163ce0a7` failed Tests run `33507271631`, job `99854209500` after checkout, Python/uv setup, and dependency installation all succeeded. The full suite reached 3,308 passed / 2 skipped before three deterministic failures in `tests/test_orchestrated_responses_stream.py`:

- `test_virtual_models_stream_openai_reasoning_summaries[orchestrator/free]` expected the old four-phase conduct summaries but the runtime emitted the single route summary;
- `test_http_virtual_responses_preserves_message_array_and_sampling_controls` assumed the conduct-only leading instruction offset;
- `test_stream_failure_emits_terminal_responses_event` injected failure into `conduct`, while `orchestrator/free` auto mode now calls `stream_route`.

The registry PR changes only this registry boundary and its dedicated tests; none of its five changed paths owned the failing Responses-stream behavior. Cross-repository/source-history inspection found the exact three-test repair already merged to protected `main` as PR #1005 / merge `8839081659df587b19642be17b9114f9dee8b666`. PR #1005 had bisected the root cause to `9173923b` intentionally pinning `orchestrator/free` auto mode to route while leaving three predecessor tests on conduct-era expectations. This is stale-base/predecessor test evidence, not a registry product defect, provider/network failure, permission problem, or reason to weaken the test gate.

The repair therefore preserves the upstream causal fix instead of duplicating or suppressing tests: current protected `main@8839081659df587b19642be17b9114f9dee8b666` was merged into the PR branch with a non-force two-parent commit `d2ca9e23de306feadb67ae0662b2f99db6d609ac`. The merge tree keeps all five registry-PR paths and takes the already-reviewed Responses-stream test repair from protected main. Fresh exact-head Checks must be terminal-success before this PR is considered verified; predecessor failures, queued jobs, and skipped jobs are not passing evidence.

## Security and operability

No credential source, network endpoint, persistence TTL, locking algorithm, fencing token, cancellation state, or execution authority changes. This is an API-language clarity repair at the internal reusable boundary. The failed-Check repair above changes no runtime route policy and weakens no security, review, coverage, or test gate.
