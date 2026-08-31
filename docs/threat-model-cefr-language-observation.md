# Threat model: CEFR language observations

## Assets and trust boundaries

| Asset | Boundary | Required protection |
|---|---|---|
| Task, rubric, anchor, and evidence references | Caller to gateway | Exact contract validation and bounded opaque identifiers |
| Source audio, transcript, and acoustic evidence | Authorized source service to rater | Reference-only traces; no source copy in gateway output |
| Rater independence | Rater call to rater call | One assignment per prompt; no candidate or peer-rater context |
| Provider credentials | KV registry to existing gateway | No environment lookup or direct provider transport |
| Observation evidence | Gateway to fast-mlsirm | Exact contract adapter, allowlisted fields, no final level/score |

## Threats and controls

- A caller supplies a fake or future contract version. The exact CEFR contract,
  fast-mlsirm version, and gateway contract are checked before egress.
- A model emits a final CEFR level or a score. The strict schema rejects
  unknown fields and the post-parse allowlist has no such field.
- One rater leaks another rater's decision or candidate identity. Prompt
  construction contains one assignment and only opaque references.
- A provider returns duplicate JSON keys, undeclared evidence, or a malformed
  response. Duplicate-key parsing, reference subset checks, and bounded output
  limits fail closed and route to human review.
- A provider timeout or transport failure is mistaken for a low rating. Stable
  failure evidence is returned without an observation or invented score.
- A direct provider fallback bypasses catalog policy. The public operation
  accepts only the existing gateway contract; its concrete adapter uses
  `TaskOrchestrator.client.proxy_send` after gateway-side selection.
- Trace data exposes source text or PII. The module serializes references,
  stable metadata, usage counts, and failure codes only; it never serializes
  provider answer text.

Residual risk remains until the external source authorization, released CEFR
contract, human-review queue, and fast-mlsirm calibration owner provide their
own exact-head evidence. This slice is not a security, validity, fairness, or
CEFR-linkage certification.
