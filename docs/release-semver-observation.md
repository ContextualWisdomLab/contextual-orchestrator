# Release SemVer observation schemas (v1)

Status: contract only. There is no transport code and no version decision
in this repository yet. Decision record:
[ADR 0137](planning/adrs/0137-release-semver-observation-schema.md).

## What this is

A versioned, hash-pinned set of JSON Schemas (Draft 2020-12) for a future
release SemVer path that fits
[ContextualWisdomLab/.github#2260](https://github.com/ContextualWisdomLab/.github/pull/2260)
and its ADR-0033:

| File | Contract id | Role |
|---|---|---|
| `contextual_orchestrator/schemas/release_semver/v1/evidence.schema.json` | `cwl_release_semver_evidence/v1` | Bounded evidence pack at one exact source commit |
| `contextual_orchestrator/schemas/release_semver/v1/observation.schema.json` | `cwl_release_semver_observation/v1` | One independent rater's observation (no confidence field) |
| `contextual_orchestrator/schemas/release_semver/v1/receipt_envelope.schema.json` | `cwl_release_semver_receipt_envelope/v1` | Observations plus the unchanged fast-mlsirm receipt |
| `contextual_orchestrator/schemas/release_semver/MANIFEST.json` | — | `$id` → SHA-256 of exact file bytes |

## What contextual-orchestrator does and does not do

- It **collects observations** and **forwards the fast-mlsirm calibrated
  receipt unchanged**. `outcome` is copied from that receipt.
- It **never outputs `release_version`**. No schema here can represent one.
- It never selects a provider, model or group. The envelope fixes
  `model_pool` to `orchestrator/free` and records the gateway-reported
  served route for audit only.
- Automatic selection stays disabled in `.github#2260` until
  [fast-mlsirm#2035](https://github.com/ContextualWisdomLab/fast-mlsirm/issues/2035)
  and an immutable contextual-orchestrator release containing this
  contract (and its later client) both exist.

## Verifying the schemas

The schemas and `MANIFEST.json` ship in the wheel under
`contextual_orchestrator/schemas/release_semver/`. A consumer should:

1. install the exact released wheel (verified release asset or hash-pinned);
2. compute the SHA-256 of each schema file and compare it with
   `MANIFEST.json` and with the digest it pinned when adopting v1;
3. reject documents over the byte cap in each schema's `$comment`.

v1 files are immutable. A change is published as `v2/` with new `$id`s.

## Evidence digest

`evidence_sha256` is the SHA-256 of the RFC 8785 canonical JSON form of
the evidence document. For v1 (ASCII member names, no numbers) this equals
`json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
encoded as UTF-8.

## Open owner questions

The 0.x breaking-change rule, the first release with no tags versus the
declared `0.2.0`, the timeout policy versus the null default, and rater
count and independence are unresolved. See ADR 0137.
