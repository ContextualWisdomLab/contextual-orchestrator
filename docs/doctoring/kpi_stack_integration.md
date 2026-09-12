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

## Verification and resolved test synchronization defect

Both merged modules parse; whitespace checks pass. Independent read-only
conflict review found no actionable issue within receipt/admission scope.
Focused execution of decision receipt, workflow link, batch lineage, true
streaming and tool-execution fallback suites returned **1 failed, 195 passed
in 13.05s** at merge revision 52fd0da9. The failure is
`test_http_evidence_embedding_cold_and_warm_keep_task_interval`: the second
request has no durable acknowledgement timestamp at the instant sampled.
The synchronization cause and repair are recorded below; an embedding-cache
hit does not mean a response-cache hit.

The source integration used the existing immutable project test environment
with the separately installed native receipt namespace appended read-only.
It is not installed-core acceptance. Local log:
`/tmp/co-kpi-stack-focused-52fd0da9.log`.

## Next acceptance

The failure was independently reproduced by delaying the second final receipt
write. The concurrent export correctly reported acknowledgement unobserved;
the completed database subsequently contained both acknowledged receipts and
both workflows marked cache bypass. HTTP response consumption and listener
shutdown do not join daemon request handlers. Commit `36af4a56` therefore
changes only the test: signal after the original `DecisionMeasurement.close`
returns, then await that event before exporting. All original acknowledgement
assertions remain. The five-suite run then passed **196 tests in 11.50s**.
No runtime acknowledgement is invented or moved ahead of delivery, and this
test-only synchronization does not impose a provider/model timeout.

At exact head `81ad64cf77a49f7bc2a57f4851a5c3259387ce5d`, the full source
suite terminated successfully: **3,688 passed, 2 skipped in 261.42s**.
The terminal receipt is session `90461`, log `/tmp/co-kpi-stack-full.log`.
It used the same read-only native namespace arrangement described above;
neither installed-core acceptance nor hosted checks are implied.

Next verify an isolated core/native install.
Retain both #1103 and #1107 until protected review/checks and lineage-preserving
merge are verified. The archived bounded outcome exporter still requires
integration; constants or manually seeded observations are not its successor.
