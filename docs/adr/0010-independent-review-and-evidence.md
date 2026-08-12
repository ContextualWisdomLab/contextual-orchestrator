# ADR-0010: Independent review and evidence authority

## Status

`accepted_architecture`

## Context and decision drivers

Checks, commit statuses, automated reviews, human reviews, unresolved findings,
mergeability, and protected merge answer different questions. Treating any one
as a substitute for the others can ship stale, synthetic, author-only, or
unreviewed work.

## Considered alternatives

- merge when named workflows are green: ignores head identity and approval;
- treat an automated approval/status as independent human approval: conflates
  evidence identities;
- reconstruct repository rules from prose: likely to drift from GitHub;
- bind every evidence item to exact head and retain protected merge as final
  authority: selected.

## Decision

Each candidate records contributor head, live base, checkout identity, job
conclusion, review identity, unresolved threads, and merge authority separately.
Queued, pending, skipped-required, cancelled, absent, failed, predecessor-head,
stale-base, author-only, status-only, synthetic-merge, rate-limited, and
infrastructure-only results are not exact-head success.

Before any merge or auto-merge mutation, GitHub's live aggregate
`reviewDecision` must be `APPROVED` for the unchanged head. A missing decision,
`REVIEW_REQUIRED`, or `CHANGES_REQUESTED` blocks the mutation even when branch
protection currently allows zero approvals. An eligible independent non-author
approval must also be present; the aggregate field is evidence of the combined
repository state, not a substitute reviewer. A completed, successful,
structured same-head Strix report is separately required. Queued, in-progress,
neutral/no-report, cancelled, skipped, absent, or predecessor-head Strix states
block merge.

Zero valid unresolved findings and every required exact-head check are required
in addition to those review and security gates. GitHub's protected operation is
the final merge authority.

## Consequences

Changes may wait when the review control plane is degraded. Safe local work,
tests, documentation, and non-conflicting branches continue without weakening
the gate or fabricating evidence.

## Failure and recovery

Stale or ambiguous evidence blocks merge only. A new head invalidates evidence
according to repository policy and reacquires it. If the aggregate review state
regresses or a required check becomes incomplete after auto-merge is queued,
automation disables that queued mutation and starts exact-head verification
again. Review and Strix outages are retried later; workflows do not rewrite
themselves or reduce required contexts.

## Security, privacy, and governance impact

Reviewer credentials, development-model credentials, and product credentials
are separate. Automation cannot impersonate a human or alter branch protection
to approve its own work.

## Compatibility and migration

Existing CI remains evidence-producing infrastructure. Adoption adds explicit
head/base capture and removes prose that promotes statuses into approvals.

## Verification and acceptance

Acceptance scenarios cover exact contributor head, synthetic merge, new commits,
stale base, missing checks, unresolved threads, author review, automated review,
independent approval, and protected merge refusal.

## Rollback and supersession

The gate may be made stricter without migration. Any relaxation requires a
security ADR, ruleset-owner approval, and equivalent independent-control proof.

## References

NIST SP 800-218 and NIST SP 800-218A. See
[the reference index](../REFERENCES.md).
