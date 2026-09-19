---
id: "0038"
title: "Keep CEFR language raters at an evidence-only gateway boundary"
status: proposed
proposed_date: "2026-08-28"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/cefr_language_observation.py"
related:
  - path: "https://github.com/ContextualWisdomLab/learning-interoperability-contracts/pull/5"
    relation: requires
  - path: "https://github.com/ContextualWisdomLab/fast-mlsirm/issues/1484"
    relation: downstream-numerical-owner
success_criteria:
  - metric: "rater independence"
    target: "each prompt contains one assignment and no peer-rater or candidate identity"
    source: "tests/test_cefr_language_observation.py"
  - metric: "claim boundary"
    target: "returned artifacts contain criterion observations and evidence references but no final level or score"
    source: "tests/test_cefr_language_observation.py"
---

# Keep CEFR language raters at an evidence-only gateway boundary

## Context

CEFR language assessment needs criterion-level writing and speaking evidence,
but the gateway is not the CEFR contract owner or numerical psychometric owner.
The external `cwl_cefr_language_assessment/v1` contract and the corresponding
fast-mlsirm CEFR work are not yet released. A gateway-local schema would drift
from those owners and could accidentally turn an LLM label into a placement
decision.

## Decision

Add a provider-neutral observation operation that accepts opaque contract
references and a caller-supplied exact contract adapter. It must verify the
CEFR, fast-mlsirm, and contextual-orchestrator contract versions before any
provider request. It uses the existing KV-backed and auto-discovered
`TaskOrchestrator` path for structured Chat Completions or Responses calls.

Each rater call is independently blinded. The operation retains only stable
model/provider/version metadata, prompt/workflow revisions, sanitized usage,
parse/verifier state, bounded failure codes, criterion observations, and
evidence-reference ids. Disagreement, uncertainty, malformed evidence, and
provider failure route to human review. No final CEFR level, score, placement,
certification, or psychometric result is emitted.

## Consequences

This is safe to ship before the external contracts are released because the
operation cannot run without their adapter. It provides a reusable gateway
seam and deterministic replay identity, but it does not provide source evidence
authorization, human-review persistence, standard setting, calibration,
classification recovery, or CEFR linkage. Those remain explicit follow-up
boundaries.

## References

See `docs/cefr-language-observation.md` for the APA 7th Council of Europe and
AERA/APA/NCME references and the rationale for linking rather than vendoring
copyrighted standards PDFs.
