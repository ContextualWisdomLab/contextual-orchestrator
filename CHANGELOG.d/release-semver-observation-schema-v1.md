- Versioned, hash-pinned JSON Schemas (Draft 2020-12) for release SemVer
  evidence, independent rater observations and a receipt envelope now ship
  in the wheel under `contextual_orchestrator/schemas/release_semver/`, with
  a `MANIFEST.json` of SHA-256 digests and an immutability guard test. This
  is a contract only: there is no model call and no version decision.
  contextual-orchestrator collects observations and forwards the
  fast-mlsirm receipt unchanged. No schema can represent `release_version`
  or a model self-reported confidence (ADR 0137; #1083 step 1 of 5;
  aligned with ContextualWisdomLab/.github#2260 ADR-0033).
