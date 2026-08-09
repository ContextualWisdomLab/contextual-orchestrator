# Incident response runbook

**Document state:** `accepted_architecture`
**Scope:** provider, credential, privacy, persistence, cost, batch, evidence, and
release incidents owned or observed by Contextual Orchestrator

This runbook coordinates response. It does not replace a host organization's
on-call, legal, privacy, or certification procedure. Host-owned identity,
tenancy, customer notice, and business-record decisions remain with the host.

## Severity and authority

| Severity | Example | Required authority |
|---|---|---|
| SEV-1 | Confirmed credential or sensitive-payload disclosure; unauthorized provider egress; destructive cross-tenant access. | Incident commander plus security/privacy owner; revoke first. |
| SEV-2 | Provider-wide outage without safe failover; corrupt durable evidence; release artifact/provenance mismatch. | Service owner plus affected dependency/release owner. |
| SEV-3 | Bounded provider degradation; dropped prompt-safe usage export; delayed batch; stale required review evidence. | Service/repository owner. |
| SEV-4 | Non-production documentation or local mock defect with no security/data impact. | Repository maintainer. |

A model, automated reviewer, status, or local readiness endpoint cannot assume
incident-command, legal, privacy, release, or protected-merge authority.

## Universal response

1. **Identify:** record UTC time, reporter, affected interface, deployment,
   exact source/artifact identity, policy snapshot, and observed evidence.
2. **Classify:** distinguish caller/configuration, transient upstream,
   integrity/security, privacy, state, batch, cost/evidence, or release.
3. **Contain:** stop the unsafe path with the narrowest reversible control.
   Revoke a credential before debugging if disclosure is plausible.
4. **Preserve:** retain bounded redacted logs, audit identities, provider
   request IDs, store copies, artifact digests, and timeline. Do not copy raw
   prompts, answers, credentials, or unnecessary PII into tickets.
5. **Eradicate:** perform RCA at the first failed boundary and repair the root
   cause test-first. Do not weaken egress, auth, retention, coverage, review, or
   release gates to restore service.
6. **Recover:** use a reviewed policy/config/artifact/store, execute the
   scenario-specific checks, and observe a stable window.
7. **Reconcile:** identify lost/duplicated workflow, batch, audit, usage, or
   release evidence. Mark an irrecoverable gap instead of estimating success.
8. **Close:** require protected/deployed acceptance proportional to severity,
   document follow-ups/owners/dates, and update canonical docs/ADRs if the
   boundary changed.

## Credential or provider-egress incident

1. Disable affected non-mock agents and revoke the provider credential.
2. Block the host/provider destination at the deployment boundary when safe.
3. Rotate the credential in KV through bootstrap tooling and restart any process
   that could retain the old value.
4. Inspect DNS, selected address, TLS identity, proxy variables, redirect
   behavior, request/response bounds, redacted exceptions, and provider audit.
5. Prove the old credential fails, the new value is read from KV, private or
   mismatched destinations fail before authorization, and a permitted provider
   succeeds.
6. Review whether prompts/PII crossed an unauthorized destination and invoke the
   host privacy/legal process where applicable.

Rollback means disabling the provider or returning to the last accepted
transport. It never means permitting ambient proxies, redirects, private
addresses, or environment-secret fallback.

## Sensitive payload or PII incident

1. Stop the affected trace, persistence, export, benchmark, or provider surface.
2. Preserve the purpose, audience, tenant, provider, residency, retention, and
   authorization decision that applied.
3. Locate every authorized and unauthorized copy without broadening access.
4. Revoke credentials/tokens where needed and delete or quarantine copies under
   the governing retention/legal process.
5. Verify telemetry, cost ledger, readiness packets, and default traces contain
   no raw prompt/answer or credential.
6. Restore only with reviewed purpose/audience minimization, access,
   encryption, provider, retention, deletion, and audit evidence.

Blanket masking is not automatic recovery: it may destroy authorized business
meaning while leaving access and retention defects unresolved.

## Provider outage or malformed-response incident

1. Classify timeout, reset, throttle, unavailable/5xx, permanent 4xx, TLS,
   framing, schema, or resource-bound failure.
2. Confirm bounded retry, failover, and circuit state; prevent retry storms.
3. Disable a malformed or policy-incompatible provider rather than accepting a
   truncated, oversized, duplicate-key, non-finite, or incomplete response.
4. Exercise a realistic request on the recovered candidate and verify attempt,
   serving-agent, validation, usage, and budget evidence.
5. Re-enable gradually under the same policy snapshot.

## Persistence, audit, or cost-ledger incident

1. Stop claiming durability or complete cost/audit evidence.
2. Preserve the failed SQLite/SQL/KV file/database read-only for diagnosis.
3. Determine last known good backup, write, sequence, and correlation identity.
4. Restore a validated compatible backup or initialize an explicitly new store.
5. Reconcile records, workflow IDs, batch jobs, usage export counts, drops, and
   audit gaps. Unknown remains unknown.
6. Run parameter-binding, restart, migration/rollback, retention, backup, and
   recovery tests before restoring the durability claim.

## Batch dependency incident

1. Preserve backend and client job IDs and last observed state.
2. Stop new submissions if ownership, budget, or result identity is uncertain.
3. Keep interactive route available when its dependencies are healthy.
4. Reconcile submitted, running, terminal, partial, duplicate, and unknown jobs.
5. Validate result schema, token/cost attribution, and no cross-job publication
   before reopening submissions.

Coordinator job and idempotency maps are process-local on protected main. After
a restart, do not assume an externally surviving job can be retrieved safely or
replay chat results until workflow/usage identity has been reconciled.

## Review, check, or protected-merge incident

1. Bind every observation to the contributor, synthetic merge, or protected
   commit actually checked out.
2. Treat queued, absent, skipped-required, cancelled, failed, stale,
   predecessor, author-only, status-only, rate-limited, and infrastructure-only
   evidence as nonpassing.
3. Do not synthesize approval, broaden bot authority, reuse another credential,
   dismiss a valid finding, or weaken protection.
4. Block only merge/release and continue non-conflicting repository work.
5. Recover through the legitimate exact-head workflow/reviewer and re-evaluate
   unresolved findings and eligibility before merge.

## Bad release, package, or migration

1. Stop rollout/publication and preserve tag, source SHA, artifact digest, SBOM,
   provenance, builder, dependency lock, and migration state.
2. Yank/deprecate according to registry policy and deploy the last accepted
   artifact where safe.
3. Follow expand/backfill/contract rollback or restore the last compatible
   state backup.
4. Run build/install/import, compatibility, migration/rollback, security,
   reconciliation, and deployed smoke checks.
5. Publish an incident/recovery record without claiming unaffected evidence.

## Required closure evidence

- root-cause and systemic-control cause;
- impacted data/providers/tenants/artifacts and bounded timeline;
- containment and revocation proof;
- RED regression, minimal GREEN repair, full relevant suite;
- exact-head security/fuzz/coverage/docstring/package evidence;
- migration/rollback/reconciliation evidence where state changed;
- zero valid unresolved findings and required independent review;
- protected-main or deployed operational acceptance proportional to impact;
- updated threat model, ADR, operability, traceability, and release evidence.

## Escalation and external evidence

Use the repository's private vulnerability reporting path in the
[security policy](../SECURITY.md).
Production contact rosters, legal/privacy notice deadlines, buyer contacts,
cloud/provider escalation, on-call schedules, and certification-reporting
requirements are deployment-owned inputs and must be completed before a
production readiness claim.
