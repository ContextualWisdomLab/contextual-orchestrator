# Changelog

All notable changes to `contextual-orchestrator` are documented here. The
project follows Semantic Versioning; a version is released only after the
protected `main` branch, required Checks, independent review, and release
artifacts are verified on the same commit.

## [Unreleased]

## [0.2.0] - 2026-08-25

### Added

- Structured tool failure categories, stable fallback actions, and public
  adapter exceptions.
- Secret-free `tool_fallback_decision` audit events.
- Exact regression coverage for the Strix
  `Tool execute_command not found in agent strix` failure.
- Operator-managed model groups: `ModelAgent.group_name`, measured intra-group
  routing (Beta(1,1) posterior success probability over Jacobson-gain EWMA
  latency), group-alias model resolution, `/api/v1/model_groups` CRUD with
  normalized persistence, Admin editing, and routing-evidence display across
  text, image, video, speech, transcription, embeddings, rerank, and audio.
  (#834, ADR 0026)
- OpenCode Zen provider discovery plus explicit free-tier classification from
  reported zero prices or `-free`/`:free` id suffixes; `discover-models
  --free-only`. (#834)

### Changed

- Agent invocation retries explicitly idempotent transient tool failures with
  bounded exponential backoff within a per-agent budget.
- A shared four-attempt ceiling bounds the configured same-agent retry budget.
- Fail-closed tool decisions have dedicated JSON and SSE error contracts and
  preserve the observed failure kind in secret-free audit evidence.
- Missing or unavailable tools move to the next eligible agent instead of
  terminating the workflow immediately.
- Strix B105 false positives eliminated at the source: KV credential-name
  constants renamed `*_CREDENTIAL_NAME`; readiness label keys renamed
  `readiness_ok/warning/failure`. (#833)

### Security

- Ambiguous non-idempotent outcomes, invalid arguments, permission denial, and
  policy denial fail closed.
- Fallback errors and audit events do not copy provider exception text, tool
  arguments, outputs, or credentials; fail-closed exceptions sever the
  original cause chain so later traceback logging cannot recover them.

## [0.1.0] - Unreleased

This is the current development baseline, not a published release. It
provides the OpenAI-compatible gateway, route/conduct orchestration, workflow
and access evidence, provider credential boundaries, cost and readiness
reporting, and security-focused contract tests.
