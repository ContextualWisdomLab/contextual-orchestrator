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
  - "docs/release-semver-observation.md"
related:
  - path: "docs/planning/adrs/0129-canonical-immutable-release.md"
    relation: "release mechanism this contract ships inside; unchanged"
  - path: "docs/cefr-language-observation.md"
    relation: "pattern this slice is modeled on (observations, not decisions)"
success_criteria:
  - metric: "no version authority in contextual-orchestrator"
    target: "no schema in the family can represent release_version or a model self-reported confidence"
    source: "tests/test_release_semver_schema_v1.py"
  - metric: "schema immutability"
    target: "v1 schema bytes are pinned by SHA-256 in MANIFEST.json and in an immutability guard test"
    source: "tests/test_release_semver_schema_v1.py"
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
   observations over one deterministic evidence pack. It never computes,
   chooses or outputs a release version. No schema in this family can
   represent `release_version`. The observation schema has no `confidence`,
   probability or score field, so a model self-report cannot be mistaken
   for authority.
2. **Receipt forwarded unchanged.** The receipt envelope carries the
   fast-mlsirm receipt as an opaque object bound by its `schema_id` and
   SHA-256. `outcome` (`decision` | `no_decision`) is copied from that
   receipt. Any decided version exists only inside the fast-mlsirm
   document, which contextual-orchestrator does not interpret.
3. **Three versioned schemas (JSON Schema Draft 2020-12)** under
   `contextual_orchestrator/schemas/release_semver/v1/`:
   - `evidence.schema.json` (`cwl_release_semver_evidence/v1`): source
     commit, previous tag or `null`, declared `pyproject.toml` version as
     input evidence, `api_surface_inspected`, and bounded `{ref, text}`
     items for changelog fragments, removed/renamed public symbols,
     required-argument promotions, deprecated-alias-only changes, HTTP API
     route changes, persistence-schema changes, commit titles and PR
     titles. The field names follow the #2260 evidence pack, with
     namespaced refs added so observations can cite evidence.
   - `observation.schema.json` (`cwl_release_semver_observation/v1`):
     echoed `evidence_sha256` and `assignment_ref`, `observed_class`
     (`major` | `minor` | `patch` | `abstain`), `evidence_refs`,
     `breaking_change_refs`, and a bounded `reason_code`.
   - `receipt_envelope.schema.json`
     (`cwl_release_semver_receipt_envelope/v1`): schema digests, evidence
     digest, `gateway_contract` fixed to
     `contextual-orchestrator-contract-v1`, `model_pool` fixed to
     `orchestrator/free`, producer identity, observations with the
     gateway-reported served route (audit only), the opaque fast-mlsirm
     receipt, and the copied `outcome`.
4. **Closed and bounded.** Every object sets `additionalProperties: false`.
   Arrays, strings and identifiers have explicit maximums. The per-document
   byte caps (256 KiB evidence, 16 KiB observation, 1 MiB envelope) are
   recorded in each schema's `$comment` for the step 2 consumer to enforce.
5. **Immutability.** `MANIFEST.json` maps each schema `$id` to the SHA-256
   of its exact file bytes. A test pins the v1 digests separately and fails
   if a v1 file is edited or deleted. Any change is a new `v2/` directory
   with new `$id`s. The `$id` values are identifiers, not retrieval
   locations; integrity comes from the manifest digest and from the
   immutable release wheel that ships the files (ADR 0129 / #1229).
6. **Evidence digest.** `evidence_sha256` is the SHA-256 of the RFC 8785
   canonical JSON form of the evidence document. v1 evidence has only
   ASCII member names and no JSON numbers, so this equals
   `json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
   encoded as UTF-8.

## Unresolved owner decisions

None of these is decided here. The schemas neither encode nor imply an
answer, and later steps wait for the owner:

1. **0.x breaking-change rule.** Under 0.x, does a breaking change bump
   minor, or major (plain SemVer arithmetic, as #2260's `apply_bump` does
   today)?
2. **First release with no tags.** The repository has no release tag while
   `pyproject.toml` declares `0.2.0`. #2260's inactive path falls back to
   `previous_version = 0.0.0`. Is the first release decided from `0.0.0`,
   or is the declared `0.2.0` treated as the first-release candidate?
   `previous_tag` is nullable so either answer is representable.
3. **Timeout policy.** ADR-0033 and the organisation require a null default
   model timeout. Is any explicit, audited timeout admissible for release
   observation, or only provider termination and user cancellation?
4. **Rater count and independence.** How many observations are required,
   and how independence is established (distinct served routes, credential
   accounts, provider families, blinding), is expected to follow from the
   fast-mlsirm#2035 estimator. The envelope allows 1 to 32 observations
   only as a bound, not as a required count.

## Planned steps (each waits on the owner and fast-mlsirm#2035)

1. This ADR, the v1 schemas, manifest, packaging and tests.
2. Typed validation of evidence/observation documents and the evidence
   digest, with no transport.
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
- **Schemas inline in Python (as the CEFR slice does).** Rejected for this
  contract: consumers outside this package must verify the exact bytes, so
  standalone files with a digest manifest are more verifiable.

## Traceability and primary references

Preston-Werner, T. (2013). *Semantic Versioning 2.0.0*. https://semver.org/spec/v2.0.0.html

JSON Schema. (2022). *JSON Schema: Draft 2020-12*. https://json-schema.org/draft/2020-12

Rundgren, A., Jordan, B., & Erdtman, S. (2020). *JSON Canonicalization Scheme (JCS)* (RFC 8785). RFC Editor. https://www.rfc-editor.org/rfc/rfc8785

ContextualWisdomLab/.github. (2026). *ADR-0033: Noema decides semantic-version bumps for central releases* (Proposed; PR #2260 at `dccacc77`). https://github.com/ContextualWisdomLab/.github/blob/dccacc77cd7be310d443b126ea98aec19216c816/docs/adr/0033-noema-semver-bump.md
