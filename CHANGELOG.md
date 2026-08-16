# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Versioned `reasoning_effort_profile` catalog (issue #568) with fail-closed
  parse, per-role bindings, replayable snapshot hash, and an equal-budget
  true-θ RMSE ablation that emits θ̂ and RMSE(θ̂, θ). Sampling temperature
  is not reasoning effort. Production route/conduct defaults stay locked
  until `production_default_change_allowed` is true.
  Next action: run `python tests/test_reasoning_effort_profile.py` and keep
  live defaults unchanged while the gate is false. Pass
  `role_effort_catalog=default_role_effort_catalog()` to attach the same
  `reasoning_effort_snapshot` on `complete`, `run`, `stream_route`, and
  `batch_route`, and to send that role's `reasoning_effort` and
  `max_tokens` on `ModelClient` chat, stream, and batch. Omit it to keep
  today's payload and request body.

### Fixed

- Reject missing profiles, blank `profile_version`, and fractional seeds.
  Snapshot hashing now fails closed on extra or missing roles. The
  production-default gate returns false on junk reports, omitted or
  unrecognized `measurement_status`, and anything other than an explicit
  `measured` status. Boolean true-θ values fail closed. Access-list scope
  is a real ablation factor, not a duplicate label. `stream_route` writes
  the same snapshot to `--state-db` as `run` and `batch_route`. The
  Hypothesis/Atheris profile target strips `true_theta` before parse so
  the ablation invariants actually run.

### References

- Sakana AI. (2026). *Sakana Fugu Technical Report*.
  https://github.com/SakanaAI/fugu/blob/main/Fugu_technical_report.pdf
- Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025).
  *Trinity: An evolved LLM coordinator* (arXiv:2512.04695).
  https://arxiv.org/abs/2512.04695
- Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025).
  *Learning to orchestrate agents in natural language with the Conductor*
  (arXiv:2512.04388). https://arxiv.org/abs/2512.04388
- Baker, F. B. (2001). *The basics of item response theory* (2nd ed.).
  ERIC Clearinghouse on Assessment and Evaluation.
  https://eric.ed.gov/?id=ED458219
