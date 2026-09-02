# Dynamic item-generation invocation boundary

`cwl_dynamic_item_generation_invocation/v1` records one complete item-generation
execution without granting the provider, model, prompt, or generator any scoring
or governance authority.

## Context

A dynamic evaluation may begin without a fixed item set. The owning product
supplies a versioned evaluation blueprint and asks a human, model, or algorithmic
generator to resolve a concrete item. The item used by an evaluation must then be
frozen by exact content identity before any rater observation is interpreted.

The generator call and the resulting reference decision are different facts.
Conflating them would allow a provider output to become a gold answer, approved
anchor, adjudication result, or validated item merely because generation
succeeded.

## Decision

The orchestrator owns only provider-neutral execution evidence:

- one exact generator configuration identity;
- one blueprint revision reference;
- bounded source-snapshot and retrieval-context references;
- every attempted execution reference, including failed and fallback attempts;
- optional seed provenance;
- a terminal `generated`, `abstained`, or `failed` state;
- for `generated`, exact item/content references and a complete lowercase
  SHA-256 content digest;
- for `abstained` or `failed`, an explicit reason reference and no manufactured
  content.

The Anti-Corruption Layer rejects unknown fields and structurally rejects score,
latent-trait, gold/golden, anchor, approval, reference-status, adjudication,
validation, pass/fail, certification, employment-decision, deterministic, and
regeneration-verified fields.

## Seed and reproducibility

A recorded seed is provenance only. The invocation contract does not state that
the same provider/model/prompt/seed will reproduce the same content. Provider
serving revisions, routing, retrieval evidence, tokenizer/decoding behavior,
safety layers, and model updates may change independently.

The downstream `fast_mlsirm_dynamic_evaluation_item/v1` contract distinguishes
`inputs_recorded` from independently `verified` regeneration. This orchestrator
contract emits neither status; it only records the source execution evidence.

## Failure denominator

`failed` and `abstained` are first-class terminal observations. They retain their
attempt and reason references and cannot contain generated-item or content
identity. A workflow must not discard them when calculating generation success,
review load, coverage, or provider reliability.

## DDD ownership

- contextual-orchestrator owns provider/model execution, fallback, structured
  output translation, and this source-text-free invocation evidence.
- fast-mlsirm owns the reusable dynamic-item/reference/linking Published Language
  and production psychometric arithmetic.
- Psychometrics Commons owns hosted blueprint/run lifecycle, panel assignment,
  adjudication, persistence, authorization, and result publication.
- LineageWeave owns product-specific rubric, source-evidence, and lineage
  projection for its own bounded context.
- TEPP owns temporal/event semantics and later drift/invariance monitoring.

This module does not create a score, reference answer, validation result,
adjudication resolution, anchor-promotion decision, release, or product policy.
It stores no provider credential or raw item/source/prompt/response content.
Opaque references and hashes are provenance, not authorization or signatures.

## Verification

The RED contract was committed before the production module existed. The final
isolated verification harness executes 23 focused tests and reaches 100%
statement and branch coverage over `dynamic_item_generation.py`, including raw
JSON duplicate-member/depth handling, reference and allocation bounds, terminal
state coupling, authority-field rejection, fallback-attempt retention, mutable
input copying, and direct-construction invariant replay.

Repository-hosted exact-head CI, security, package, and independent review remain
authoritative before integration. Upstream/downstream consumption must pin an
immutable released version and digest rather than this mutable PR head.
