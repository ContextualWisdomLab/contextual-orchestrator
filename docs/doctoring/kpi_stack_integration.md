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

## Request-level cache aggregation repair — 2026-09-12

At published `eeefaca9378e4f70d03aec263fd26be1dccf92a3`, a cache hit
immediately terminated the native request receipt. Repeated cache hits and
selection followed by cache reuse raised an exception; cache followed by
selection silently omitted the first-selection duration. A later failed or
cancelled item could also retain the earlier cache classification. One HTTP
batch contains multiple items but owns one admission clock.

RED `c4e8343c` reproduced six failures in 0.55s. Runtime repair `0ddb5f1b`
records cache observation without changing native state. At request close,
only an accepted receipt with cache observation and no explicit failure becomes
`cache_hit`. Selection, durable acknowledgement and write-failure terminals keep
their existing meaning. The native state machine is unchanged; catching its
exception alone would leave silent timing loss unresolved.

Frozen `4bc96045037d04fa7477a1532c75f99f0d7e9898` adds real HTTP local-batch
tests for repeated cache, both mixed orders and cache followed by failure,
plus explicit context cleanup and successor-request isolation. Related suites
passed **82 tests in 3.33s**. Full source regression passed **3,699 tests,
2 skipped in 144.99s**, terminal session `86318`, log
`/tmp/co-kpi-full-cache-0ddb5f1b.log` (the filename names the runtime commit;
the tested head is the frozen revision above).

Source reproduction uses the root project `.venv/bin/python`, appends the
read-only native namespace at
`/tmp/co-export-native-acceptance-20260912/lib/python3.14/site-packages/contextual_orchestrator`
to the imported package path, then runs `pytest.main(["tests", "-q"])`.
Do not interpret that source/native arrangement as an installed core test.

Separate installed acceptance used a `git archive` of the frozen revision at
`/tmp/co-cache-wheel-4bc96045.C4cqDg`, Python 3.14.6, all 46 hash-locked
requirements, pytest 9.1.1 and the unchanged native wheel. Core wheel SHA-256:
`3e278e07adf168140b23cde0a3f99be38201dea8ae0abfdc89fcdff2af88514b`.
Native wheel SHA-256:
`8dfee5d228a28733136e25c6006f77006bcba095863a667e0f2a3e71ca8c7c04`.
With `python -I`, working directory `/tmp`, importlib test mode and asserted
core/native `site-packages` origins, `test_decision_cache_aggregation.py`,
`test_decision_receipts.py`, `test_cost_review_server.py` and
`test_workflow_request_link.py` passed **82 tests in 8.93s** (session `18167`).
This verifies measurement correctness, not customer accuracy or latency gains.

## Central review handoff remains an owner gap

The coordinating owner task supplied protected-main evidence at
`.github@fb17ef556f94f673234aa557254ae52779e9a7b0`:
[`noema_review_handoff.py`, lines 191–210](https://github.com/ContextualWisdomLab/.github/blob/fb17ef556f94f673234aa557254ae52779e9a7b0/scripts/ci/noema_review_handoff.py#L191-L210)
sends `repository_dispatch` to the target repository. The
[OpenCode handoff, lines 7707–7736](https://github.com/ContextualWisdomLab/.github/blob/fb17ef556f94f673234aa557254ae52779e9a7b0/.github/workflows/opencode-review-dispatch.yml#L7707-L7736)
sets that repository as its destination. The inspected CO `eeefaca` tree has
no `noema-review.yml` receiver. A 204 event-acceptance response is not a Noema
run or independent review. Keep receiver repair in the `.github` owner;
do not copy a workflow into this consumer to claim review coverage.

At `eeefaca`, Security run `34688379677` completed tests, fuzzing, supply-chain
and CodeQL successfully. That evidence predates the cache repair and does not
approve or validate its new head. Fresh hosted checks, independent review,
protected merge, release and observed KPI acceptance remain separate gates.

Bounded visual receipt: revision `36ade588`, English, 1265 × 712. The actual
browser preview's cache-repair, installed-verification and final owner-gap
sections were directly opened as three overlapping screenshots. Long hashes
and paths wrapped without horizontal clipping; headings and paragraphs did
not overlap. A stale preview-only revision badge was corrected and its top
view recaptured at `http://127.0.0.1:18771/`. Images remain in task tool output.
This does not cover mobile, other locales, Figma or product interaction states.
