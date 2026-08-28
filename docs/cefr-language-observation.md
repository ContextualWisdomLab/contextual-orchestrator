# CEFR language criterion observations

Status: experimental gateway slice. This is an observation boundary, not a
CEFR scoring or certification implementation.

## Contract boundary

`observe_language_response_criteria()` requires both the released
`cwl_cefr_language_assessment/v1` adapter and the current `fast-mlsirm` scoring
contract version. A missing, incompatible, or malformed adapter fails closed
before any provider call. The gateway contract is the existing
`contextual-orchestrator-contract-v1` boundary.

The request carries only opaque references to the task, rubric, criterion,
category anchors, and source evidence. It also carries one assignment per
independent rater, a prompt revision, replay id, and bounded workflow settings.
Source audio, transcripts, acoustic features, candidate identity, and PII are
not copied into the request trace or returned artifact.

## Execution

1. The released contract adapter validates the request envelope.
2. Each rater receives the same declared references and exactly one rater
   assignment. A rater never receives another rater's output or candidate
   identity.
3. `TaskOrchestratorCefrGateway` selects a structured-output-capable,
   auto-discovered agent and sends the request through the existing KV-backed
   gateway. No direct provider transport is available in this module.
4. Chat Completions and Responses `json_object` or strict `json_schema` formats
   are accepted. Duplicate keys, undeclared anchors/evidence, malformed JSON,
   and unsupported shapes are rejected.
5. Only criterion observations and evidence-reference ids are returned. The
   response schema has no CEFR-level, score, placement, certification, or
   psychometric-result field.

High uncertainty, an out-of-distribution signal, a critical criterion,
unsupported evidence, disagreement, malformed output, timeout, provider
failure, or an incomplete panel sets `human_review.required=true` with stable
reason codes. The function never repairs a rating into a score and never
calculates a final level.

## Example

```python
request = CefrLanguageObservationRequest(
    task_ref="assessment/task-revision-1",
    rubric_ref="assessment/rubric-revision-4",
    criterion_ref="writing/coherence",
    category_anchor_refs=("anchor/writing-1", "anchor/writing-2"),
    evidence_reference_ids=("evidence/transcript-7", "evidence/audio-7"),
    rater_assignments=(
        CefrRaterAssignment("assignment/model-a", "llm-family-a", "2026-08"),
        CefrRaterAssignment("assignment/model-b", "llm-family-b", "2026-08"),
    ),
    prompt_revision="prompt/criterion-v1",
    replay_id="replay/assessment-7",
    workflow_settings={"reasoning_effort": "medium"},
)
result = observe_language_response_criteria(request, gateway, contract_adapter)
```

## Claim boundary and follow-up

This slice does not provide the released CEFR contract adapter, human-review
queue persistence, source-evidence authorization service, CEFR standard setting,
many-facet calibration, posterior probabilities, classification recovery, or
overall reporting. Those belong to the learning-interoperability-contracts,
Psychometrics Commons, and fast-mlsirm owners. Until those exact dependencies
are released and validated, this module cannot claim CEFR linkage or placement
authority.

The Council of Europe says that the CEFR Companion Volume broadens and updates
the framework, while its linking manual emphasizes transparent procedures and
supporting evidence rather than a Council of Europe validation endorsement.
The implementation therefore preserves criterion evidence and leaves linking
and interpretation to the assessment owner.

## References

- Council of Europe. (2020). *Common European framework of reference for
  languages: Learning, teaching, assessment—Companion volume*. Council of
  Europe Publishing. https://www.coe.int/en/web/common-european-framework-reference-languages/cefr-companion-volume-and-its-language-versions
- Council of Europe. (2009). *Relating language examinations to the Common
  European Framework of Reference for Languages: Learning, teaching,
  assessment—A manual*. https://www.coe.int/en/web/common-european-framework-reference-languages/relating-examinations-to-the-cefr
- Council of Europe. (2011). *Manual for language test development and
  examining*. https://www.coe.int/en/web/common-european-framework-reference-languages/developing-tests-examining
- American Educational Research Association, American Psychological
  Association, & National Council on Measurement in Education. (2014).
  *Standards for educational and psychological testing*. American Educational
  Research Association. https://www.aera.net/Publications/Books/Standards-for----Educational-Psychological-Testing-2014-Edition

The Council of Europe publications are cited and linked rather than copied
into this repository; no redistribution permission for their PDFs is assumed.
