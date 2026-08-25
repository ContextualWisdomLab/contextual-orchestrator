# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added

- Citation-backed `docs/adr` set: APA 7th references on the tool-execution fallback policy, plus accepted control-plane, cost-aware sync-versus-batch, and MSA-leaf composition ADRs, indexed from `docs/adr/README.md`.
- Structured tool failure categories, stable fallback actions, and public adapter exceptions.
- Secret-free `tool_fallback_decision` audit events.
- Exact regression coverage for the Strix `Tool execute_command not found in agent strix` failure.

### Changed

- Agent invocation now retries explicitly idempotent transient tool failures with bounded exponential backoff within a per-agent budget.
- A shared four-attempt ceiling now bounds the configured same-agent tool retry budget.
- Fail-closed tool decisions now have dedicated JSON and SSE error contracts, and preserve the observed failure kind in secret-free audit evidence.
- Missing or unavailable tools move to the next eligible agent instead of terminating the workflow immediately.

### Security

- Ambiguous non-idempotent outcomes, invalid arguments, permission denial, and policy denial fail closed.
- Fallback errors and audit events do not copy provider exception text, tool arguments, outputs, or credentials; fail-closed exceptions also sever the original cause chain so later traceback logging cannot recover them.
