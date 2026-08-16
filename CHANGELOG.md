# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Versioned `reasoning_effort_profile` catalog (issue #568) with fail-closed
  parse, per-role bindings, replayable snapshot hash, and an equal-budget
  true-θ RMSE ablation. Sampling temperature is not reasoning effort.
  Production route/conduct defaults stay locked until
  `production_default_change_allowed` is true.
  Next action: run `python tests/test_reasoning_effort_profile.py` and keep
  live defaults unchanged while the gate is false.

### References

- Sakana AI. (2026). *Sakana Fugu Technical Report*.
  https://github.com/SakanaAI/fugu/blob/main/Fugu_technical_report.pdf
- Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025).
  *Trinity: An evolved LLM coordinator* (arXiv:2512.04695).
  https://arxiv.org/abs/2512.04695
- Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025).
  *Learning to orchestrate agents in natural language with the Conductor*
  (arXiv:2512.04388). https://arxiv.org/abs/2512.04388
