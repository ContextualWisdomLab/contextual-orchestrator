# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added

- Structured tool failure categories, stable fallback actions, and public adapter exceptions.
- Secret-free `tool_fallback_decision` audit events.
- Exact regression coverage for the Strix `Tool execute_command not found in agent strix` failure.

### Changed

- Agent invocation now retries explicitly idempotent transient tool failures within a bounded per-agent budget.
- Missing or unavailable tools move to the next eligible agent instead of terminating the workflow immediately.

### Security

- Ambiguous non-idempotent outcomes, invalid arguments, permission denial, and policy denial fail closed.
- Fallback errors and audit events do not copy provider exception text, tool arguments, outputs, or credentials.
