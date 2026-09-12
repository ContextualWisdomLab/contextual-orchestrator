# KPI stack integration checkpoint — 2026-09-12

Status: Proposed; no main adoption, deployment or KPI improvement claimed.

## Ownership and retained history

The numeric acceptance contract belongs to commit
`dccd37e032f74251e3c02e38046dab68c0049787` in PR #1107: observed
delivered-correct fraction improves by at least one percentage point with its
95% difference interval above zero; decision p95 is at most 20 ms and improves
by at least 10%, with the 95% ratio interval below one. The same commit owns
the linked runbook, denominator, holdout and power requirements. These are
targets, not measurements. PR #1103 head `4776a970` is its ancestor.

Main `012beaacd0631f8cd3391c77744eeb626269b5de` did not contain that ancestry.
The receipt/workflow/batch PR merge commits on the retained research branch
also do not prove main adoption. No deletion from main has been established.

Ordinary merge `52fd0da99224f0889e8b012667a93940f6a324ee` joins research head
`e30652556320f8c72578443385dd31fad1139ff7` and current main without force or
discarding predecessor delta. Conflicts were confined to AGENTS.md and the
orchestrator/server modules. Both guidance sections were retained. Runtime
resolution preserves current tool suppression, stream candidate failover,
expanded race results, and validated capacity acquisition while adding
request-owned per-attempt measurement. The independent recovery branch at
`726ae2949b026fbcf8567655aaa29cf1c18534ab` remains intact as reconciliation
evidence, not a second production implementation.

## Verification and concrete remaining defect

Both merged modules parse; whitespace checks pass. Independent read-only
conflict review found no actionable issue within receipt/admission scope.
Focused execution of decision receipt, workflow link, batch lineage, true
streaming and tool-execution fallback suites returned **1 failed, 195 passed
in 13.05s** at merge revision 52fd0da9. The failure is
`test_http_evidence_embedding_cold_and_warm_keep_task_interval`: the second
request has no durable acknowledgement timestamp. Its cause is still under
investigation; do not weaken the assertion or infer that an embedding-cache
hit means a response-cache hit.

The source integration used the existing immutable project test environment
with the separately installed native receipt namespace appended read-only.
It is not installed-core acceptance. Local log:
`/tmp/co-kpi-stack-focused-52fd0da9.log`.

## Next acceptance

Resolve the missing acknowledgement from actual stored evidence, re-run the
focused suite and full checks, then verify an isolated core/native install.
Retain both #1103 and #1107 until protected review/checks and lineage-preserving
merge are verified. The archived bounded outcome exporter still requires
integration; constants or manually seeded observations are not its successor.
