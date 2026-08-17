# ADR-0010: Independent review and evidence authority

## Status

`accepted_architecture`

**Date:** 2026-08-17
**Decision owner:** Contextual Orchestrator maintainers
**Scope:** Repository merge and release evidence. This ADR does not change
the separate OpenCode review pipeline, which stays on GitHub Models.

## Context and decision drivers

Checks, commit statuses, automated reviews, human reviews, unresolved
findings, mergeability, and protected merge answer different questions.
Treating any one as a substitute for the others can ship stale, synthetic,
author-only, or unreviewed work (National Institute of Standards and
Technology, 2022, 2024b).

NIST SP 800-218 asks for separate, repeatable verification and
review—not a single green badge. Commercial readiness endpoints in this
repository are process-local evidence, not merge authority.

## Considered alternatives

- Merge when named workflows are green: ignores head identity and approval.
- Treat an automated approval or status as independent human approval:
  conflates evidence identities.
- Reconstruct repository rules from prose: likely to drift from GitHub.
- Bind every evidence item to an exact head and retain protected merge as
  final authority: selected.

## Decision

Each candidate records contributor head, live base, checkout identity, job
conclusion, review identity, unresolved threads, and merge authority
separately. Queued, pending, skipped-required, cancelled, absent, failed,
predecessor-head, stale-base, author-only, status-only, synthetic-merge,
rate-limited, and infrastructure-only results are not exact-head success.

GitHub's protected operation is the final merge authority. Reviewer
credentials, development-model credentials, and product credentials stay
separate. Automation cannot impersonate a human or alter branch protection to
approve its own work.

The OpenCode review pipeline is separate and stays on GitHub Models. This
ADR does not relocate it.

## Consequences

Changes may wait when the review control plane is degraded. Safe local work,
tests, documentation, and non-conflicting branches continue without weakening
the gate or fabricating evidence.

## Failure and recovery

Stale or ambiguous evidence blocks merge only. A new head invalidates
evidence according to repository policy and reacquires it. Review outages are
retried later; workflows do not rewrite themselves or reduce required
contexts.

## Security, privacy, and governance impact

Independent review is a control, not a product feature. Logs and review
artifacts exclude secrets and unnecessary PII.

## Compatibility and migration

Existing CI remains evidence-producing infrastructure. Adoption adds explicit
head/base capture and removes prose that promotes statuses into approvals.

## Verification and acceptance

Acceptance scenarios cover exact contributor head, synthetic merge, new
commits, stale base, missing checks, unresolved threads, author review,
automated review, independent approval, and protected merge refusal.

## Rollback and supersession

The gate may be made stricter without migration. Any relaxation requires a
security ADR, ruleset-owner approval, and equivalent independent-control
proof. Do not weaken, `continue-on-error`, or disable the Security workflow.

## References

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1* (NIST SP 800-218).
https://doi.org/10.6028/NIST.SP.800-218

National Institute of Standards and Technology. (2024b). *Secure software
development practices for generative AI and dual-use foundation models: An
SSDF community profile* (NIST SP 800-218A).
https://doi.org/10.6028/NIST.SP.800-218A

See also [docs/REFERENCES.md](../REFERENCES.md).
