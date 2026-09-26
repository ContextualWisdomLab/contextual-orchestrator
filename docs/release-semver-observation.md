# Release SemVer observation schemas (v1)

Status: contract only. There is no transport code and no version decision
in this repository yet. Decision record:
[ADR 0137](planning/adrs/0137-release-semver-observation-schema.md).

## What this is

A versioned, hash-pinned set of JSON Schemas (Draft 2020-12) for a future
release SemVer path that fits
[ContextualWisdomLab/.github#2260](https://github.com/ContextualWisdomLab/.github/pull/2260)
and its ADR-0033:

| File | Contract | Role |
|---|---|---|
| `contextual_orchestrator/schemas/release_semver/v1/evidence.schema.json` | #2260 evidence pack (strict subset) | #2260's member names (`previous_version`, string lists, `api_surface_inspected`), closed and size-bounded |
| `contextual_orchestrator/schemas/release_semver/v1/observation.schema.json` | `cwl_release_semver_observation/v1` | One independent rater's class, cited items and enumerated reason (no confidence, no free text) |
| `contextual_orchestrator/schemas/release_semver/v1/receipt_envelope.schema.json` | `cwl_release_semver_receipt_envelope/v1` | Observations plus the unchanged fast-mlsirm receipt |
| `contextual_orchestrator/schemas/release_semver/MANIFEST.json` | — | `$id` → SHA-256 of exact file bytes |

## What contextual-orchestrator does and does not do

- It **collects observations** and **forwards the fast-mlsirm calibrated
  receipt unchanged**. The receipt `document` is the only decision
  authority; the envelope has no `outcome`, decision or version field of
  its own.
- It **never produces or interprets a release version or decision**. No
  field in these schemas carries one. The opaque receipt `document` may
  contain fast-mlsirm's decision; the client neither writes nor reads it.
- It never selects a provider, model or group. The envelope fixes
  `model_pool` and every observation's `served_route.route` to
  `orchestrator/free`. The served agent, model and provider come from the
  gateway's route report and are recorded for audit only.
- A gateway or transport failure is not an observation and is never
  recorded as `abstain`; the client fails closed.
- Automatic selection stays disabled in `.github#2260` until
  [fast-mlsirm#2035](https://github.com/ContextualWisdomLab/fast-mlsirm/issues/2035)
  and an immutable contextual-orchestrator release containing this
  contract (and its later client) both exist.

## Evidence pack

Every pack the v1 schema accepts is also accepted by #2260's code at
`dccacc77`; v1 is a strict subset. #2260's own evidence fixtures
(`tests/fixtures/noema_semver/evidence_*.json`, copied byte for byte under
`tests/fixtures/github_2260_noema_semver/`) validate unchanged.

- As in #2260, a pack that is not marked `api_surface_inspected: true` must
  carry at least one removed, renamed or required-argument finding.
- v1 is stricter than #2260 in some ways: the pack is closed, all nine
  members are required, `previous_version` must be canonical, every item
  must be a string, and sizes are capped. ADR 0137 lists every input #2260
  accepts and v1 rejects as an owner decision.
- `previous_version` is the only previous version the raters see. #2260
  never parses the pack value: it accepts any non-empty value and fills
  only a falsy one, and its workflow always passes a git-derived
  `--previous-version` that overrides the pack. In v1 the producer writes
  that same value into the pack, in canonical `X.Y.Z` form, and step 2
  rejects a mismatch.
- Strings must be I-JSON (no unpaired surrogates such as `"\ud800"`). The
  schema cannot express this, so step 2 checks it before computing digests.
- Items may contain newlines, tabs and other characters. An item is blank,
  and rejected, exactly when Python's `str.strip()` would empty it.
- Identifiers that are not part of #2260's pack (the evidence source commit
  and the digests) live in the envelope.

## Citations

Observations cite pack items in either of two forms:

- **Index ref:** `#/<list>/<index>`, an RFC 6901 JSON Pointer fragment into
  the pack, for example `#/changelog_fragments/0`. Any item can be cited
  this way, however long or multi-line it is.
- **Text ref:** a #2260 prefix plus the item with surrounding whitespace
  stripped, exactly as #2260's `detected_breaking_refs` builds it. The
  prefixes are `changelog:`, `api:removed:`, `api:renamed:`,
  `api:required-arg:` and `api:deprecated-alias:`, plus `commit:` and `pr:`
  for commit and PR titles. Internal newlines and tabs are kept, so every
  ref #2260 generates is accepted.

A `minor` or `patch` observation may not cite an item from #2260's three
detector lists. Step 2 performs the checks a schema cannot, such as pack
membership, digest equality and breaking markers in changelog text (see
ADR 0137, "Step 2 validator cross-checks").

## Verifying the schemas

The schemas and `MANIFEST.json` ship in the wheel under
`contextual_orchestrator/schemas/release_semver/`. A consumer should:

1. install the exact released wheel (verified release asset or hash-pinned);
2. compute the SHA-256 of each schema file and compare it with
   `MANIFEST.json` and with the digest it pinned when adopting v1;
3. resolve `$ref` (the envelope refers to the observation schema by `$id`)
   through a **local registry** built from those packaged files. `$id`
   values are identifiers, not download locations: never fetch them over the
   network, and disable any remote-retrieval fallback in the validator. With
   Python `jsonschema`, pass an explicit `referencing.Registry` whose
   `retrieve` refuses unknown URIs;
4. reject documents over the byte cap in each schema's `$comment` (evidence
   4 MiB, observation 64 KiB, envelope 4 MiB).

v1 files are immutable. A change is published as `v2/` with new `$id`s.
`.gitattributes` disables end-of-line conversion for the schemas and their
fixtures, so the digests hold on `core.autocrlf` clones and Windows builds.
Patterns avoid `\s`, `\d` and `\w` and guard against Python's
`$`-before-final-newline behaviour, so ECMA-262 and Python validators
agree.

## Digests

`evidence_sha256` and `fast_mlsirm_receipt.sha256` are SHA-256 digests of
the RFC 8785 canonical JSON form of the evidence pack and receipt document.
For number-free JSON with ASCII member names (every v1 evidence pack) this
equals
`json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
encoded as UTF-8. A receipt document may contain JSON numbers, so its digest
needs a full RFC 8785 implementation. Repeated-digit digests and commit ids
(for example all zeros) are rejected. That check only catches placeholders;
integrity comes from step 2 recomputing the digests.

## Open owner questions

These are unresolved; see ADR 0137:

- the 0.x breaking-change rule;
- the first release with no tags versus the declared `0.2.0`;
- the timeout policy versus the null default;
- rater count and independence;
- the inputs #2260 accepts and v1 rejects;
- the Co-ordinator defaults (size caps, multi-line citation,
  `recorded_unavailable` coverage).
