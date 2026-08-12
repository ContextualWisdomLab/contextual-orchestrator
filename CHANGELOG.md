# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- NIM discovery catalog body bound + dry-run call budget uses max_steps;
  offline cost-quality rejects malformed scripted answers and zeros failed-cell usage.

### Added
- Offline NIM capability probe plan + fixture classification (issue #86).
- Offline cost-quality `--use-mock-orchestrator` path: Fugu `route_once` and
  Conductor/TRINITY `conduct` via `mock://` agents (issue #86 paper-path exercise).

### Added
- Offline NIM cost-quality comparison harness (`nim_cost_quality` +
  `nim-cost-quality-offline` CLI) for issue #86 post-discovery: locked task
  manifest scorers, honest unknown actual/hypothetical cost, policy summaries,
  and quality-latency / quality-cost Pareto frontiers without live egress.
- Offline NIM capability inventory + dry-run benchmark plan (issue #86).
- `discover-nim-models` CLI and `nim_discovery` module (issue #86): allowlisted
  NVIDIA HTTPS `/v1/models` only; offline fixture status; unique agent ids on
  slug collision; live tests require `RUN_LIVE_NIM_TESTS=1`.
- Role-differentiated sampling temperatures for paper-role ablation.

### Security
- Semgrep nosemgrep hygiene for audited SQL placeholders / TLS opt-out / urllib.

## [0.1.0] - 2026-07-13

### Added
- Initial OpenAI-compatible orchestration gateway.
