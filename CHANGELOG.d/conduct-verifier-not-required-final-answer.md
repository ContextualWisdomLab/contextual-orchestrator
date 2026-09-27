# Keep the synthesized answer when the verifier is optional

- Fixed template `conduct` returning the verifier step's review report as the
  final answer when `OrchestrationPolicy.verifier_required` is `False`. The
  synthesizer (final template step) now answers in that case, matching the
  generated-plan branch; `verifier_required` still only decides whether a
  rejected verdict falls back to the worker output.
- Added a regression test covering both accepted and rejected verdicts.
- Corrected the fast-mlsirm boundary so both fixed and generated conduct plans
  judge the final response candidate, with the verifier report passed as
  `reference_answer` (a comparison standard), rather than judging the report
  itself. The conduct judgment uses `task_alignment` and `evidential_support`
  criteria because the old criteria ask about "the verifier output". The
  acceptance threshold stays `0.7` on every path, and direct routes
  (`route_once`, streaming, batch) keep their previous criteria unchanged.
