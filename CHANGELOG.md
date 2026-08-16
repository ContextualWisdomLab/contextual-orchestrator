# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added

- Structured tool failure categories, stable fallback actions, and public adapter exceptions.
- Secret-free `tool_fallback_decision` audit events.
- Exact regression coverage for the Strix `Tool execute_command not found in agent strix` failure.
- Hourly PR maintenance dispatcher that requests one bounded, exact-target review-repair opportunity from the protected central `.github` control plane.

### Changed

- Agent invocation now retries explicitly idempotent transient tool failures with bounded exponential backoff within a per-agent budget capped by the shared `MAX_TOOL_RETRY_ATTEMPTS` policy.
- Fail-closed tool decisions now have dedicated JSON and SSE error contracts, and preserve the observed failure kind in secret-free audit evidence.
- Missing or unavailable tools move to the next eligible agent instead of terminating the workflow immediately.

### Security

- Ambiguous non-idempotent outcomes, invalid arguments, permission denial, and policy denial fail closed.
- Fallback errors and audit events do not copy provider exception text, tool arguments, outputs, or credentials.
- The hourly caller remains read-only and model-secret-free while preserving exact-head checks, independent approval, and the existing reviewer credential scheme.
- Provider TLS selection rejects non-boolean values, and the production `--serve` path rejects the development-only certificate-verification opt-out.
