# Operability and recovery

**Document state:** `accepted_architecture`

## Operating modes

| Mode | Dependencies | Durability |
|---|---|---|
| Offline/mock | Python process and mock agent data | In-memory unless state paths are supplied. |
| Standalone provider | HTTPS model provider and credential backend | Optional SQLite state/agent files and optional SQL ledger. |
| CWL modular | Host ingress/identity plus optional KV, `pg-llm-batch`, and viewer | Each component retains its declared ownership. |

## Startup checks

- validate agent IDs and at least one enabled agent;
- validate bind address and explicit public-bind intent;
- validate token configuration and separation where required;
- validate configured CA bundle, state paths, KV selector, and adapter imports;
- seed provider credentials before non-mock traffic;
- report liveness separately from provider, store, batch, and review readiness.

`GET /healthz` proves only that the process can answer. It does not prove model
credentials, provider reachability, database recovery, or release readiness.

## Runtime signals

- requests, rejections, active concurrency, and latency by route/conduct mode;
- selected/served agent, failover origin, transient retry, and circuit state;
- workflow step count, access exposure, verifier outcome, and trace completeness;
- provider-reported versus estimated token use and unpriced model counts;
- budget remaining/exceeded state;
- batch submitted/running/completed/failed lifecycle;
- usage export queue, stored count, failures, drops, and flush state;
- optional store availability and last successful durable write;
- exact source revision and policy/config version in operational evidence.
- execution-path label (`plain_sync`, `passthrough`, `route_stream`, or batch),
  whether workflow/usage/state evidence was recorded, and why any item is absent;
- active cost authority, price source/freshness, unknown-price count, and
  workflow-spend versus ledger reconciliation;
- adapter mode (`configured`, `memory_fallback`, or `heuristic_fallback`) and
  process-local batch/idempotency state age.

Raw prompts, answers, credentials, and unnecessary PII are not general metrics.

## Initial SLI/SLO entry criteria

Production objectives require a real deployment baseline. Repository mocks do
not establish a production SLO. Before setting targets, collect:

- successful compatible requests divided by admitted requests;
- P50/P95/P99 latency by route/conduct/provider;
- provider failover success and retry amplification;
- trace-complete conducted-run rate;
- provider-exclusion violations (target zero);
- credential or secret exposure incidents (target zero);
- durable-state write/recovery success;
- usage export completeness and lag;
- batch completion and age by terminal state.

## Current protected-main limitations

- Raw passthrough and route streaming bypass coordinator ledger recording;
  route streaming also bypasses durable workflow state, and failed streams may
  leave no retained run.
- Workflow-derived spend/budget and the independent ledger are not synchronized.
  Missing ledger price becomes zero; budget admission is pre-run and non-atomic.
- Coordinator batch/job/idempotency maps are process-local. Restart loses local
  lookup and chat result replay can duplicate usage.
- Config-store and token-counter construction may silently use memory/heuristic
  fallbacks. Availability does not prove the configured durable/precise mode.
- `/healthz` remains process liveness only. Static OpenAPI and runtime route
  scopes are not yet generated from one registry.
- Clearfolio is a browser deep link only; this service does not own an upload or
  conversion integration.

## Incident classification

| Class | Example | Immediate action |
|---|---|---|
| Caller/configuration | Invalid body, mode, token, missing credential, permanent 4xx. | Reject without retry; correct caller/config. |
| Transient upstream | Timeout, reset, 429, eligible 5xx. | Bounded retry/failover; observe circuit. |
| Integrity/security | Private destination, TLS/ref/hash mismatch, malformed trusted evidence. | Fail closed; do not retry as transient. |
| State | SQLite/SQL/KV unavailable or corrupt. | Stop claiming durability; isolate store and restore/replace explicitly. |
| Batch dependency | External submit/poll/retrieve unavailable. | Preserve job identity/state; keep interactive path independent. |
| Evidence/control plane | Required check/review absent, stale, or infrastructure-only. | Block only merge/release; continue safe repository work. |

## Recovery runbooks

### Provider outage

1. Confirm failure class and affected agents/providers.
2. Observe bounded retry/failover and circuit state.
3. Exclude a provider only through reviewed operator policy.
4. Verify a realistic request on the recovered path.
5. Preserve the incident trace without credentials or unnecessary payloads.

### Credential compromise

1. Revoke at the provider and disable affected agents.
2. Rotate the KV value through bootstrap tooling.
3. Confirm old credentials fail and new credentials work.
4. Review trace/log/artifact exposure and retention.
5. Reopen the incident if any stale process can retain the old value.

### SQLite state failure

1. Stop treating current history as durable.
2. Preserve the failed file read-only for diagnosis.
3. Restore a validated backup or initialize an explicitly new store.
4. Reconcile workflow/evaluation/audit/analytics completeness.
5. Run restart tests before returning durability to service.

### Cost export degradation

1. Inspect queue/drop/store-failure telemetry without logging payloads.
2. Repair the external store or adapter.
3. Flush within a bounded time and reconcile stored counts.
4. Mark irrecoverable gaps rather than estimating missing records.

### Bad release or migration

1. Stop rollout and preserve exact artifact/provenance identity.
2. Follow the affected ADR's rollback or expand/backfill/contract boundary.
3. Restore a compatible state/schema version.
4. Execute package, migration, smoke, security, and data reconciliation tests.
5. Close only with protected-main/deployed evidence, not the repair PR alone.

## Change and release operations

- one writer per repository branch;
- exact target ref/blob rechecked before every write;
- no force push, destructive rebase, self-modifying repair workflow, or gate
  weakening;
- stateful changes include forward migration, rollback, backup, and recovery;
- releases originate only from protected main after all acceptance evidence;
- version, changelog, artifacts, SBOM, provenance, and published package identity
  agree.

## External evidence still required

Repository controls do not supply production capacity tests, hosted penetration
tests, incident-call evidence, legal/DPA acceptance, buyer signatures, or SOC 2
and CSAP certification. Those remain explicit external inputs.
