# Durable registry semantic identifiers

## Decision

The batch-job registry is a reusable orchestration persistence boundary. Its public Python seams therefore name the domain concept rather than expose generic `name` and `key` parameters.

- `ValkeyJsonMapping(..., name, ...)` → `ValkeyJsonMapping(..., registry_name, ...)`
- `JobRegistryFactory.lock(name, key, ...)` → `JobRegistryFactory.lock(registry_name, claim_key, ...)`
- `JobRegistryFactory.mapping(name, ...)` → `JobRegistryFactory.mapping(registry_name, ...)`

The semantic names are authoritative in signatures and new code. The established `name=` and `key=` keyword forms remain accepted only through a bounded compatibility-keyword adapter so external Python callers are not broken by a refactor. Supplying both the semantic and legacy form for the same identifier fails closed with `TypeError`; unknown compatibility keywords are also rejected. No deprecation warning is suppressed: the aliases remain supported until a separately versioned breaking API contract explicitly retires them.

Existing repository callers pass these identities positionally, so the change preserves runtime behavior and stored Valkey keys. The generated key format remains `batch_job_registry:{registry_name}` and claim format remains `batch_job_registry:{registry_name}:claim:{claim_key}`; no persisted registry namespace is rewritten and no migration is required.

## DDD / compatibility boundary

- **Bounded context:** durable batch-job orchestration registry.
- **Domain service:** `JobRegistryFactory`.
- **Repository adapter:** `ValkeyJsonMapping`.
- **Invariant:** registry names identify durable logical maps; claim keys identify one claim within a registry.
- **Invariant:** renaming Python parameters must not alter Valkey hash/lock key bytes or retention semantics.
- **Anti-corruption boundary:** legacy generic keyword names are translated at the call boundary and never become the internal domain vocabulary.

`tests/test_batch_job_registry_naming_contract.py` protects the semantic Python signatures, legacy-keyword compatibility, conflict behavior, and rejection of open-ended kwargs. Existing batch routing, cost routing, video-job, file-registry, retention, fencing, and cancellation suites remain responsible for behavior and persistence compatibility.

## Security and operability

No credential source, network endpoint, persistence TTL, locking algorithm, fencing token, cancellation state, or execution authority changes. This is an API-language clarity repair at the internal reusable boundary.