# ADR-0009: Purpose-bound PII protection

## Status

`accepted_architecture`

Secret and PII redaction on traces and errors is present on protected `main`.
Host-owned purpose, legal basis, tenant authority, and subject-rights
handling are not claimed as a complete privacy program.

**Date:** 2026-08-17
**Decision owner:** Contextual Orchestrator maintainers

## Context and decision drivers

Authorized business tasks may require names, account details, or other
personal data. Blanket masking can destroy the task's meaning, while copying
full payloads into traces, analytics, caches, or broad operator views creates
avoidable risk (NIST AI RMF 1.0; NIST AI 600-1; ISO/IEC 27001:2022;
ISO/IEC 42001:2023).

Nielsen et al. (2026) access lists are one technical minimization control:
workers see only listed prior outputs. They are not a substitute for
purpose-bound authorization.

## Considered alternatives

- Mask every recognized identifier before orchestration: reduces utility and
  can corrupt required facts.
- Retain complete payloads everywhere for debugging: operationally convenient
  but violates minimization.
- Rely only on provider policy: delegates responsibilities the host still
  owns.
- Preserve the minimum authorized payload on the execution path and minimize
  every derived projection: selected.

## Decision

The integrating host establishes purpose, legal basis, tenant/user authority,
provider eligibility, and subject-rights handling. The orchestrator passes
only the minimum authorized content to selected providers and roles.
Telemetry and cost records exclude raw prompts and answers. Traces,
persistence, caches, previews, and operator views have distinct audience
controls, retention, and redaction. Masking is a projection control, not
authorization or encryption.

Full orchestration traces are not returned by default. Trusted callers may
request them; inference authority is not automatically trace authority.

## Consequences

Deployments need data classification and audience policy rather than one
global redaction switch. Correctly authorized workflows preserve business
meaning, while broad evidence surfaces contain less sensitive data.

## Failure and recovery

Unknown purpose, authority, provider eligibility, or trace audience fails
closed for the affected exposure. An exposure incident triggers provider
containment, credential review, deletion/retention procedures, evidence
preservation, impact assessment, and host-owned notification obligations.

## Security, privacy, and governance impact

This decision applies minimization, least authority, separation of telemetry
from content, and lifecycle controls. It does not claim that the repository
alone satisfies a jurisdiction, DPA, or certification.

## Compatibility and migration

Existing request semantics remain. Integrations add purpose and tenant
authority at their boundary and must partition or disable caches and
persistence until those keys participate in authorization.

## Verification and acceptance

PII-bearing fixtures verify preservation on the authorized model path,
exclusion from prompt-safe telemetry, audience-limited traces, and redacted
failures.

## Rollback and supersession

Rollback means narrowing or disabling the affected projection, never
restoring unbounded copying. Supersession requires a privacy threat model,
data-flow map, compatibility plan, and deployment-specific legal review.

## References

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2026).
*Learning to orchestrate agents in natural language with the Conductor*
(arXiv:2512.04388, Version 5) [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2512.04388

National Institute of Standards and Technology. (2023). *Artificial
intelligence risk management framework (AI RMF 1.0)* (NIST AI 100-1).
https://doi.org/10.6028/NIST.AI.100-1

National Institute of Standards and Technology. (2024a). *Artificial
intelligence risk management framework: Generative artificial intelligence
profile* (NIST AI 600-1). https://doi.org/10.6028/NIST.AI.600-1

International Organization for Standardization. (2022). *Information
security, cybersecurity and privacy protection — Information security
management systems — Requirements* (ISO/IEC 27001:2022).
https://www.iso.org/standard/27001

International Organization for Standardization. (2023b). *Information
technology — Artificial intelligence — Management system* (ISO/IEC
42001:2023). https://www.iso.org/standard/81230.html

See also [docs/REFERENCES.md](../REFERENCES.md).
