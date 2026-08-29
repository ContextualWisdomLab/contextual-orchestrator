---
id: "0039"
title: "Extract a domain-neutral rater observation bounded context"
status: proposed
proposed_date: "2026-08-29"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/rater_observation.py"
  - "contextual_orchestrator/cefr_language_observation.py"
related:
  - path: "docs/planning/adrs/0038-cefr-language-observation-gateway.md"
    relation: "narrows-to-compatibility-profile"
  - path: "https://github.com/ContextualWisdomLab/fast-mlsirm"
    relation: "published-language-owner"
success_criteria:
  - metric: "ubiquitous language"
    target: "generic observation code contains no CEFR level or descriptor concepts"
    source: "tests/test_rater_observation.py"
  - metric: "decision leakage"
    target: "score, trait, placement, pass/fail, certification, and employment decisions are structurally rejected"
    source: "tests/test_rater_observation.py"
  - metric: "aggregate integrity"
    target: "one invocation has exactly one rater configuration and at most one observation per criterion"
    source: "tests/test_rater_observation.py"
---

# Extract a domain-neutral rater observation bounded context

## Context

The existing CEFR gateway already implements several domain-neutral safety
properties: independently blinded calls, evidence references, abstention,
structured output, bounded provider metadata, and a prohibition on final
scoring. Its code and public types nevertheless use CEFR-specific ubiquitous
language. That makes a language-learning profile look like the owner of a
capability needed by writing assessment, interview evaluation, portfolio
review, performance observation, peer review, and other domains.

A CEFR contract also carries external standards, rights, linking, and claim
semantics that do not belong in a generic model-rater gateway. Reusing it as the
core would couple every assessment product to a language-specific upstream
contract and would allow level-oriented concepts to leak into observation
creation.

## Decision

Create a `Rater Observation` bounded context with `RaterInvocation` as its
aggregate root. The aggregate contains exactly one reusable rater
configuration, one task revision, one rubric revision, one response-evidence
reference, and one or more criterion observations. A criterion is either:

- `observed`, with one ordered category anchor and one or more evidence
  references; or
- `abstained`, with no manufactured category or evidence and an explicit
  reason.

The configuration identity is the product of rater family, provider or
employing authority, exact implementation revision, exact instruction
revision, exact response-schema revision, workflow mode, and modality channel.
Repeated executions are separate invocations under the same configuration;
they are not represented as independent raters.

`fast-mlsirm` owns and releases the published observation language. This
repository implements an Anti-Corruption Layer that translates untrusted
provider output to that language. Unknown fields fail closed. The following
concepts are rejected rather than stored: score, final score, latent trait,
level, placement, pass/fail, certification, and employment decision.

ADR 0038 and `cefr_language_observation.py` remain temporarily as a compatibility
profile for existing consumers. New domain code must import
`rater_observation.py`. A future CEFR profile may translate to and from the
released generic contract without changing the core aggregate.

## Context map

```text
Measurement Context Registry
        | immutable references
        v
Rater Observation (this repository)
        | Published Language
        v
Measurement Calibration (fast-mlsirm)
        | numerical artifacts
        v
Assessment Operations (psychometrics-commons)
        | publication events
        v
Temporal Monitoring (TEPP)
```

This repository does not persist panels, adjudication cases, participant
responses, numerical parameters, score snapshots, or temporal monitoring
artifacts.

## Consequences

### Positive

- CEFR becomes one optional domain profile rather than the architecture center.
- Human, model, and algorithmic raters share one identity and invocation model.
- Provider payloads and domain labels cannot cross the boundary accidentally.
- Failure and abstention remain observable denominator states.
- Downstream numerical and product contexts retain their own authority.

### Costs

- The compatibility CEFR module must eventually delegate to the generic
  aggregate or be removed after its consumers migrate.
- Contract release order must be coordinated with `fast-mlsirm`.
- Domain profiles need explicit Anti-Corruption Layers rather than importing
  internal Python types.

## Rejected alternatives

### Keep CEFR as the generic core

Rejected because CEFR rights, linking, descriptor, and level semantics are not
shared by other assessment domains.

### Create a new shared-framework repository

Rejected because no independent product, lifecycle, or release authority is
present. A released published-language artifact from the numerical owner gives
sufficient decoupling without a jointly changed shared kernel.

### Let provider schemas define the domain model

Rejected because provider fields, decoding options, and API surfaces are
infrastructure concerns and cannot be the product's ubiquitous language.

## Verification

- exact positive and negative aggregate tests;
- unknown-field and decision-leakage tests;
- repeated-reference and bounded-resource tests;
- immutable snapshot tests against hostile mutable caller input;
- compatibility tests for any CEFR adapter added later;
- current-head coverage and docstring gates.

## References

Evans, E. (2003). *Domain-driven design: Tackling complexity in the heart of
software*. Addison-Wesley.

Vernon, V. (2013). *Implementing domain-driven design*. Addison-Wesley.
