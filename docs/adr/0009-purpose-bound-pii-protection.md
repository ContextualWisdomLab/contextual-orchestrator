# ADR-0009: Purpose-bound PII protection

## Status

`accepted_architecture`

## Context and decision drivers

Authorized business tasks may require names, account details, or other personal
data. Blanket masking can destroy the task's meaning, while copying full payloads
into traces, analytics, caches, or broad operator views creates avoidable risk.
Protection must follow purpose, audience, authority, and lifecycle.

## Considered alternatives

- mask every recognized identifier before orchestration: reduces utility and
  can corrupt required facts;
- retain complete payloads everywhere for debugging: operationally convenient
  but violates minimization;
- rely only on provider policy: delegates responsibilities the host still owns;
- preserve minimum authorized payload on the execution path and minimize every
  derived projection: selected.

## Decision

The integrating host establishes purpose, legal basis, tenant/user authority,
provider eligibility, and subject-rights handling. The orchestrator passes only
the minimum authorized content to selected providers and roles. Telemetry and
cost records exclude raw prompts/answers; traces, persistence, caches, previews,
and operator views have distinct audience controls, retention, and redaction.
Masking is a projection control, not authorization or encryption.

## Consequences

Deployments need data classification and audience policy rather than one global
redaction switch. Correctly authorized workflows preserve business meaning,
while broad evidence surfaces contain less sensitive data.

## Failure and recovery

Unknown purpose, authority, provider eligibility, or trace audience fails closed
for the affected exposure. An exposure incident triggers provider containment,
credential review, deletion/retention procedures, evidence preservation, impact
assessment, and host-owned notification obligations.

## Security, privacy, and governance impact

This decision applies minimization, least authority, separation of telemetry
from content, and lifecycle controls. It does not claim that the repository
alone satisfies a jurisdiction, DPA, or certification.

## Compatibility and migration

Existing request semantics remain. Integrations add purpose/tenant authority at
their boundary and must partition or disable caches and persistence until those
keys participate in authorization.

## Verification and acceptance

PII-bearing fixtures verify preservation on the authorized model path,
exclusion from prompt-safe telemetry, audience-limited traces, cache isolation,
retention/deletion behavior, redacted failures, and provider restrictions.

## Rollback and supersession

Rollback means narrowing or disabling the affected projection, never restoring
unbounded copying. Supersession requires a privacy threat model, data-flow map,
compatibility plan, and deployment-specific legal review.

## References

NIST AI RMF 1.0, NIST AI 600-1, ISO/IEC 27001:2022, and ISO/IEC 42001:2023.
See [the reference index](../REFERENCES.md).
