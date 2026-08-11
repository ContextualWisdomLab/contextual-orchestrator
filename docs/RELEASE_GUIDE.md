# Release, migration, and rollback guide

**Document state:** `accepted_architecture`

This is the canonical operator sequence for preparing, publishing, deploying,
and accepting a Contextual Orchestrator release. It complements ADR-0011,
the test strategy, operability guide, and incident runbook. It does not claim
that an active pull request, synthetic merge, workflow status, or local build
has shipped.

## Authority and release identity

A releasable identity begins at one exact source commit already integrated into
protected `main`. The release owner records one immutable tuple:

- repository and exact source commit;
- version and signed or otherwise repository-authorized tag;
- source archive and package artifact digest;
- dependency-lock digest and build-environment identity;
- CycloneDX SBOM digest and provenance statement identity;
- migration identifier and compatible rollback target, when state changes;
- exact check, security, review, and protected-main operational evidence.

The protected commit, tag, package metadata, changelog, artifact contents, and
published version must agree. Synthetic merge commits and contributor heads may
provide scoped evidence, but neither has publication authority.

## Admission checklist

Before building a candidate, refetch rather than remember:

1. protected-main tip, release target commit, tag absence, and version metadata;
2. branch protection, rulesets, required checks, security gates, and release
   environment policy;
3. exact-head Tests, Security, Fuzz, package, 100% production statement/branch,
   and 100% public-docstring results;
4. formal reviews, zero valid unresolved findings, and an eligible independent non-author approval
   on the unchanged integrated identity;
5. lockfiles, action pins, vulnerability results, license inventory, CycloneDX
   SBOM, and source-to-artifact provenance inputs;
6. compatibility, migration, backup, restore, rollback, and realistic smoke
   evidence for every affected runtime mode; and
7. external inputs that are truly required, without presenting a missing buyer
   signature, hosted penetration test, SLO, SOC 2, or CSAP certification as
   repository success.

Queued, pending, skipped-required, cancelled, failed, absent, stale-head,
predecessor-head, author-only, status-only, synthetic-merge-only, rate-limited,
or infrastructure-only evidence blocks only the affected gate. It is never
promoted to exact-head acceptance.

## Build and provenance procedure

1. Create an isolated clean build from the exact source commit. Do not reuse an
   editable development environment or an artifact from a predecessor head.
2. Install from the reviewed lock and build with the repository-declared
   runtime. Record toolchain and dependency-lock digests.
3. Build the source and wheel artifacts, then install each into a fresh
   environment and verify import, CLI help, health, and bounded mock request
   paths without materializing a live model credential.
4. Repeat the build in a second clean environment and compare normalized
   contents and digests. Explain any platform-defined nondeterminism; an
   unexplained mismatch is not reproducible evidence.
5. Generate the CycloneDX SBOM and provenance statement from the candidate,
   then bind both to the exact source commit and artifact digest.
6. Secret-scan and malware/dependency-scan the source and artifacts. Preserve
   redacted results under the repository's evidence-retention policy.
7. Produce a release manifest containing the identity tuple and links to the
   exact jobs. Run IDs belong in the dated manifest, not timeless architecture.

No build step receives `NVIDIA_NIM_API_KEY` unless a separately admitted,
bounded live-model acceptance cell actually calls a provider. Review-agent
credentials remain independent, and `COPILOT_GITHUB_TOKEN` is not a model-test
credential.

## Migration and rollback procedure

For any state, schema, credential-backend, or external-contract change:

1. inventory physical persisted objects separately from in-memory,
   external/host-owned, conceptual, and planned entities;
2. back up the exact affected state and prove restore before mutation;
3. use expand/backfill/contract: add compatible readers/writers, backfill with
   bounded reconciliation evidence, then contract only after the rollback
   window closes;
4. run upgrade, mixed-version compatibility, restart, replay/idempotency,
   reconciliation, and downgrade or restore tests;
5. define the last compatible application and schema/artifact pair, maximum
   rollback window, data-loss boundary, and correction owner; and
6. stop the rollout if rollback cannot preserve required authorization,
   credential, audit, budget, cost, batch, or workflow evidence.

The generic SQLite `records` object and `docs/database_design.sql` target are
not interchangeable. A migration must name the physical source and target and
must not invent persistence for an in-memory or host-owned entity.

## Publication and deployment procedure

1. Recheck the protected ref and every release input immediately before the
   irreversible publication boundary. A changed source, rule, review, artifact,
   migration, or target freezes the candidate and requires regenerated proof.
2. Create the repository-authorized tag from the admitted protected commit.
3. Publish only artifacts whose digests appear in the release manifest. Do not
   rebuild between approval and publication.
4. Verify registry/package metadata and download the published artifact into a
   clean environment for install/import/smoke validation.
5. Roll out progressively where deployment exists. Keep the last compatible
   artifact and schema available until operational acceptance completes.
6. Record deployment target, configuration/policy digest, start/end time,
   operator identity, result, and rollback decision without secrets or
   unnecessary PII.

A repository release is not a production deployment, buyer acceptance, or
certification. Each external authority records its own evidence and status.

## Protected-main operational acceptance

After publication or deployment, verify against the exact protected-main and
artifact identities:

- package download, install, import, CLI, and `/healthz` behavior;
- representative mock and permitted provider-neutral request paths;
- credential bootstrap-to-KV behavior without secret retention or logging;
- provider DNS pinning, redirect/proxy rejection, response bounds, failover,
  and circuit recovery where the deployed mode uses those boundaries;
- state restart, audit/evidence persistence, cost attribution, budget behavior,
  and batch lifecycle for enabled backends;
- required telemetry, artifact/SBOM/provenance retrieval, and incident links;
- migration reconciliation and the continued feasibility of rollback.

`/healthz` alone is liveness, not release acceptance. Close the release only
when the dated manifest records each applicable observation or an explicitly
owned external gap.

## Abort and recovery conditions

Abort publication or rollout on any identity mismatch, new valid finding,
missing required approval/check, vulnerability, secret exposure, corrupt or
partial artifact, failed restore/migration, unexplained reproducibility drift,
provider trust-boundary regression, or operational smoke failure.

Preserve the failed source, tag, artifact digest, SBOM, provenance, migration,
and redacted logs. Stop further rollout, restore the last compatible
artifact/state pair, reconcile writes and evidence, and follow the incident
runbook. Recovery creates a new candidate from a new exact protected identity;
it never edits or republishes an already approved artifact under the same
version.

## Related authority

- [ADR-0011: Release coverage and provenance](adr/0011-release-coverage-and-provenance.md)
- [Test strategy](TEST_STRATEGY.md)
- [Operability](OPERABILITY.md)
- [Incident runbook](INCIDENT_RUNBOOK.md)
- [Threat model](THREAT_MODEL.md)
- [Traceability](TRACEABILITY.md)
