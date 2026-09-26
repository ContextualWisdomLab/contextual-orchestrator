# Keep the synthesized answer when the verifier is optional

- Fixed template `conduct` returning the verifier step's review report as the
  final answer when `OrchestrationPolicy.verifier_required` is `False`. The
  synthesizer (final template step) now answers in that case, matching the
  generated-plan branch; `verifier_required` still only decides whether a
  rejected verdict falls back to the worker output.
- Added a regression test covering both accepted and rejected verdicts.
