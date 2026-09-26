---
id: "0137"
title: "Versioned release SemVer observation schemas: observations only, fast-mlsirm receipt forwarded unchanged"
status: proposed
proposed_date: "2026-09-26"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/schemas/release_semver/"
  - "pyproject.toml ([tool.setuptools.package-data])"
  - ".gitattributes"
  - "docs/release-semver-observation.md"
related:
  - path: "docs/planning/adrs/0129-canonical-immutable-release.md"
    relation: "release mechanism this contract ships inside; unchanged"
  - path: "docs/cefr-language-observation.md"
    relation: "pattern this slice is modeled on (observations, not decisions)"
success_criteria:
  - metric: "no version authority in contextual-orchestrator"
    target: "no schema field carries a release version, decision, outcome or model self-reported confidence; the fast-mlsirm receipt document is the only decision authority"
    source: "tests/test_release_semver_schema_v1.py"
  - metric: "owner evidence-pack conformance"
    target: "the .github#2260 evidence fixtures at dccacc77 validate unchanged against the v1 evidence schema"
    source: "tests/test_release_semver_schema_v1.py; tests/fixtures/github_2260_noema_semver/"
  - metric: "schema immutability"
    target: "v1 schema bytes are pinned by SHA-256 in MANIFEST.json and in an immutability guard test, and are LF-only with end-of-line conversion disabled"
    source: "tests/test_release_semver_schema_v1.py; .gitattributes"
  - metric: "consumer verifiability"
    target: "the schemas and MANIFEST.json ship inside the released wheel"
    source: "pyproject.toml package-data; local wheel build"
---

# ADR 0137: Versioned release SemVer observation schemas

## Status

Proposed (2026-09-26). Step 1 of 5 for
[#1083](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/1083)'s
"immutable client/schema" prerequisite. This step adds JSON Schemas, a
digest manifest, fixtures and tests only. It adds no transport code and no
version-deciding code.

Numbering: 0135 is used on several open branches
(`0135-whole-request-partitioning.md`, `0135-opencode-go-provider-discovery.md`)
and 0136 by open PR #1220 (`0136-document-diff-review-envelope.md`), so this
record takes 0137.

## Context

[ContextualWisdomLab/.github#2260](https://github.com/ContextualWisdomLab/.github/pull/2260)
centralises the release-tag and publish-package workflows. Its
[ADR-0033](https://github.com/ContextualWisdomLab/.github/blob/dccacc77cd7be310d443b126ea98aec19216c816/docs/adr/0033-noema-semver-bump.md)
(Proposed) keeps automatic Noema SemVer selection **fail-closed**:
`decide_version_with_noema` defaults to `false`, and `true` fails until

1. [fast-mlsirm#2035](https://github.com/ContextualWisdomLab/fast-mlsirm/issues/2035)
   releases a calibrated release-decision receipt (explicit statistical
   model, per-class calibration and uncertainty, an explicit `no_decision`
   outcome, immutable identities, and no model self-report or arbitrary
   threshold as authority); and
2. contextual-orchestrator releases an immutable client/schema that carries
   that receipt through `orchestrator/free` using only the gateway token,
   with no provider/model override, no paid fallback, and a null default
   model timeout.

The #2260 adoption boundary also says no consumer may copy
contextual-orchestrator or fast-mlsirm source, call a raw model endpoint,
select a provider/model/group, or add a paid fallback. #2260's production
module deliberately has no model-response verdict parser.

A repo-local "ask a model for `{bump, confidence}` and pick a version" step
in contextual-orchestrator would contradict both documents. The existing
CEFR slice ([`docs/cefr-language-observation.md`](../../cefr-language-observation.md))
already shows the shape that fits: independent raters produce bounded
*observations*, and fast-mlsirm owns the calibrated decision.

## Decision

1. **Observations only.** contextual-orchestrator collects independent rater
   observations over one evidence pack. It never produces or interprets a
   release version or decision, and no field in this schema family carries
   one. The fast-mlsirm receipt `document` is opaque and may contain
   fast-mlsirm's decision; the client neither writes nor reads it. The
   observation has no `confidence`, probability, score or free-text field,
   so a model self-report cannot be mistaken for authority.
2. **Receipt forwarded unchanged; one authority.** The envelope carries the
   fast-mlsirm receipt as `{schema_id, sha256, document}`, where `sha256` is
   the RFC 8785 canonical-JSON digest of `document`. The envelope has **no
   `outcome` field of its own**. A copied outcome would be a second source
   of the decision that could contradict the receipt, so `document` is the
   only decision authority.
3. **Evidence pack = the #2260 pack.** `evidence.schema.json` accepts the
   pack that #2260's reusable `release-tag.yml` hands to
   `noema_semver_bump.py` at `dccacc77`: `previous_version`,
   `changelog_fragments`, `removed_public_symbols`, `renamed_public_symbols`,
   `required_arg_promotions`, `deprecated_alias_only`, `commit_titles`,
   `pr_titles` (arrays of plain strings) and `api_surface_inspected`. #2260's
   rule is mirrored: unless `api_surface_inspected` is `true`, at least one
   removed/renamed/required-arg finding is required. The pack carries no
   identifiers of ours. The evidence source commit, schema digests and
   evidence digest live in the envelope. #2260's own evidence fixtures are
   copied byte-for-byte (Git blob ids recorded in `PROVENANCE.json`) and
   must validate unchanged.
4. **Observation (`cwl_release_semver_observation/v1`).**
   - It holds the echoed `evidence_sha256` and `assignment_ref`, plus
     `observed_class` (`major` | `minor` | `patch` | `abstain`, using #2260's
     bump-class labels), `evidence_refs`, `breaking_change_refs` and
     `reason_code`.
   - **Citation refs** are `<prefix><item text>`. #2260 defines the prefixes
     `changelog:`, `api:removed:`, `api:renamed:`, `api:required-arg:`
     (`detected_breaking_refs`) and `api:deprecated-alias:` (recorded
     fixtures). v1 adds `commit:` and `pr:`.
   - **`reason_code` is a closed enum** tied to #2260's detectors and
     partitioned by class:

     | Class | Allowed reasons |
     |---|---|
     | `major` | `removed_public_symbol`, `renamed_public_symbol`, `required_arg_promotion`, `other_breaking_change` |
     | `minor` | `deprecated_alias_only`, `feature_addition` |
     | `patch` | `fix_only`, `docs_or_internal_only` |
     | `abstain` | `insufficient_evidence`, `conflicting_evidence` |

     `other_breaking_change` covers breaking changes that #2260 records only
     as changelog/commit text (for example an HTTP route removal).
   - **Detector reasons must cite the matching ref.** `removed_public_symbol`
     needs an `api:removed:` breaking ref, `renamed_public_symbol` an
     `api:renamed:` ref, `required_arg_promotion` an `api:required-arg:`
     ref, and `deprecated_alias_only` an `api:deprecated-alias:` evidence ref.
   - **Breaking refs follow the class.** `major` needs at least one breaking
     ref. `minor` and `patch` must have none. `abstain` may cite breaking
     refs when the evidence conflicts. Every class except `abstain` needs at
     least one evidence ref.
5. **Envelope (`cwl_release_semver_receipt_envelope/v1`).**
   - It holds the schema digests, the evidence digest,
     `evidence_source_commit`, `gateway_contract`
     (`contextual-orchestrator-contract-v1`), `model_pool` fixed to
     `orchestrator/free`, and producer identity.
   - Each observation carries a `served_route` whose `route` is fixed to
     `orchestrator/free`; the served agent, model and provider are audit-only.
   - It carries the opaque receipt. Identical observation entries are
     rejected.
6. **Closed, bounded, non-degenerate.**
   - Every object schema sets `additionalProperties: false`.
   - Arrays, strings and identifiers have explicit maximums. The
     per-document byte caps (256 KiB evidence, 16 KiB observation, 1 MiB
     envelope) are recorded in each schema's `$comment` for the step 2
     consumer to enforce.
   - Repeated-digit SHA-256 values and commit ids (all zeros, all `f`, and
     so on) are rejected with a portable `not`/`enum` rather than a
     lookahead regex.
7. **Immutability and byte stability.**
   - `MANIFEST.json` maps each schema `$id` to the SHA-256 of its exact file
     bytes.
   - A test pins the v1 digests separately and fails if a v1 file is edited
     or deleted. Any change is a new `v2/` directory with new `$id`s.
   - `.gitattributes` sets `-text` on the schema directory and the schema
     test fixtures, and a test asserts the files contain no CR bytes, so the
     digests survive `core.autocrlf` clones and Windows-built wheels.
8. **Local `$ref` resolution only.** The `$id` values are identifiers, not
   retrieval locations. Consumers must resolve `$ref` (the envelope refers
   to the observation schema by `$id`) through a local registry built from
   the packaged files, with any remote-retrieval fallback disabled. Each
   schema's `$comment` says so. Integrity comes from the manifest digest and
   from the immutable release wheel that ships the files (ADR 0129 / #1229).
9. **Digests.** `evidence_sha256` is the SHA-256 of the RFC 8785 canonical
   JSON form of the evidence pack. v1 packs have only ASCII member names and
   no JSON numbers, so this equals
   `json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
   encoded as UTF-8. Receipt documents may contain numbers and need a full
   RFC 8785 implementation.

## Differences from #2260's workflow tolerance (owner decisions)

v1 accepts #2260's fixtures unchanged, but it is stricter than the inline
validation in #2260's `release-tag.yml`. Each difference below is proposed,
not decided. The owner may accept it, or ask for a v1 change before release:

1. **Closed pack.** #2260 ignores unknown keys; v1 rejects them.
   Reason: unknown keys would reach raters without a contract.
2. **All nine members required.** #2260 fills a missing `previous_version`
   and tolerates omitted lists, and an omitted `api_surface_inspected` when a
   finding exists. v1 requires all nine members, with explicit empty lists;
   both #2260 fixtures already carry them. Reason: an omitted list is
   ambiguous between "none found" and "not collected".
3. **Canonical `previous_version`.** #2260's `parse_core_semver` tolerates
   surrounding whitespace and a leading `v`. v1 requires the canonical
   `X.Y.Z` that #2260's workflow itself emits.
4. **Non-blank items in every list.** #2260 enforces non-blank strings only
   for the three API-finding lists. v1 enforces them for all lists and caps
   sizes (2000 characters per item, 256 items per list, 512 commit titles).
5. **`commit:` and `pr:` refs** are v1 additions; #2260 defines no prefix
   for commit or PR titles. An item containing a control character, such
   as a newline, cannot be cited by text.
6. **The reason-code set and its class mapping** are ours, tied to #2260's
   detectors. Changing them after release needs v2.

## Unresolved owner decisions

None of these is decided here. The schemas neither encode nor imply an
answer, and later steps wait for the owner:

1. **0.x breaking-change rule.** Under 0.x, does a breaking change bump
   minor, or major (plain SemVer arithmetic, as #2260's `apply_bump` does
   today)? `observed_class` records the SemVer change class (`major` = a
   backward-incompatible public API change); the mapping to a bump is not
   part of this contract.
2. **First release with no tags.** The repository has no release tag while
   `pyproject.toml` declares `0.2.0`. #2260 fills `previous_version` with
   `0.0.0` when no tag exists. Is the first release decided from `0.0.0`,
   or is the declared `0.2.0` treated as the first-release candidate?
3. **Timeout policy.** ADR-0033 and the organisation require a null default
   model timeout. Is any explicit, audited timeout admissible for release
   observation, or only provider termination and user cancellation?
4. **Rater count and independence.** How many observations are required,
   and how independence is established (distinct served routes, credential
   accounts, provider families, blinding), is expected to follow from the
   fast-mlsirm#2035 estimator. The envelope allows 1 to 32 observations
   only as a bound, not as a required count.
5. **The six differences listed above.**

## Planned steps (each waits on the owner and fast-mlsirm#2035)

1. This ADR, the v1 schemas, manifest, packaging and tests.
2. Typed validation of evidence/observation documents, citation membership
   and the evidence digest, with no transport.
3. An `observe` client that sends a strict `json_schema` request to the
   provisioned `orchestrator/free` sidecar using only the gateway token
   file. No provider/model selection is exposed.
4. `verify-envelope`, once fast-mlsirm publishes its receipt schema
   identity.
5. Ship in an immutable contextual-orchestrator release; `.github` then
   pins it (owner's lane).

## Consequences

- contextual-orchestrator gains a stable, hash-pinned contract that
  `.github` and fast-mlsirm can review before any code depends on it.
- Nothing changes at runtime. `release.yml`, `release_checks_gate.sh` and
  the human version-bump path are untouched.
- A released v1 file can never be edited; mistakes are fixed with v2.

## Alternatives considered

- **Repo-local verdict parser with a confidence threshold.** Rejected: it
  contradicts #2260 and fast-mlsirm#2035 (model self-report as authority,
  arbitrary threshold).
- **Copying fast-mlsirm's outcome into the envelope.** Rejected: it creates
  a second, possibly contradictory decision source.
- **`{ref, text}` evidence items with our own identifiers inside the pack.**
  Rejected: #2260 is the owner's design and uses plain strings; our
  identifiers belong in the envelope.
- **Schemas inline in Python (as the CEFR slice does).** Rejected for this
  contract: consumers outside this package must verify the exact bytes, so
  standalone files with a digest manifest are more verifiable.

## Traceability and primary references

Preston-Werner, T. (2013). *Semantic Versioning 2.0.0*. https://semver.org/spec/v2.0.0.html

JSON Schema. (2022). *JSON Schema: Draft 2020-12*. https://json-schema.org/draft/2020-12

Rundgren, A., Jordan, B., & Erdtman, S. (2020). *JSON Canonicalization Scheme (JCS)* (RFC 8785). RFC Editor. https://www.rfc-editor.org/rfc/rfc8785

ContextualWisdomLab/.github. (2026). *ADR-0033: Noema decides semantic-version bumps for central releases* (Proposed; PR #2260 at `dccacc77`). https://github.com/ContextualWisdomLab/.github/blob/dccacc77cd7be310d443b126ea98aec19216c816/docs/adr/0033-noema-semver-bump.md
