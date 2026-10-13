- Versioned, hash-pinned JSON Schemas (Draft 2020-12) for release SemVer
  evidence, independent rater observations and a receipt envelope now ship
  in the wheel under `contextual_orchestrator/schemas/release_semver/`, with
  a `MANIFEST.json` of SHA-256 digests, an immutability guard test and
  `.gitattributes` rules that keep the pinned bytes free of end-of-line
  conversion. The evidence schema accepts a strict subset of what
  ContextualWisdomLab/.github#2260 accepts, including #2260's evidence
  fixtures unchanged, and observations can cite any pack item by index or by
  the text refs #2260 generates. This is a contract only: there is no model
  call and no version decision. contextual-orchestrator collects enumerated
  observations over the `orchestrator/free` route and forwards the
  fast-mlsirm receipt unchanged; it never produces or interprets a release
  decision, and the envelope has no outcome field of its own (ADR 0137;
  #1083 step 1 of 5; aligned with .github#2260 ADR-0033).
