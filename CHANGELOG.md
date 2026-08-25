# Changelog

All notable changes to `contextual-orchestrator` are documented here. The
project follows Semantic Versioning; a version is released only after the
protected `main` branch, required Checks, independent review, and release
artifacts are verified on the same commit.

## [Unreleased]

### Added

- Operator-managed model groups: `ModelAgent.group_name`, measured intra-group
  routing (Beta(1,1) posterior success probability over Jacobson-gain EWMA
  latency), group-alias model resolution, `/api/v1/model_groups` CRUD with
  agent-pool persistence, and admin routing-evidence display. (#834, ADR 0026)
- OpenCode Zen provider discovery plus explicit free-tier classification from
  reported zero prices or `-free`/`:free` id suffixes; `discover-models
  --free-only`. (#834)

### Changed

- Strix B105 false positives eliminated at the source: KV credential-name
  constants renamed `*_CREDENTIAL_NAME`; readiness label keys renamed
  `readiness_ok/warning/failure`. (#833)

## [0.1.0] - Unreleased

This is the current development baseline, not a published release. It
provides the OpenAI-compatible gateway, route/conduct orchestration, workflow
and access evidence, provider credential boundaries, cost and readiness
reporting, and security-focused contract tests.
