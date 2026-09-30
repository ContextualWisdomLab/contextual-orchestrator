# Document diff data-URI ReDoS RCA

Status: Proposed until protected integration and exact-head hosted Checks.

## Incident

The Python CodeQL dispatch for
`ContextualWisdomLab/contextual-orchestrator#1221@4dcf9e32b057cde83bca67bfd45975fc6deda458`
reported `py/polynomial-redos` with security severity 7.5 at
`contextual_orchestrator/document_diff_review.py:129`. Central run
`36447487525`, job `109084173022`, preserved SARIF artifact `11026927998`
with digest
`sha256:0145d9b03e8c0064c2a57be79bc3f8168bcd45dc93b488aa4a4b1f81c23898a5`.

## Root cause

The data-URI boundary searched caller-controlled extracted document text with
`data:[^,\s]*,`. Repeated `data:` prefixes let the unanchored expression retry
over overlapping suffixes. The per-object byte ceiling bounded the input, but
did not make polynomial work an acceptable security boundary.

## Repair and invariant

The replacement scans disjoint text segments. It finds a case-insensitive
`data:` prefix, advances once until comma, whitespace, or end, and resumes only
after the terminating whitespace. A comma before whitespace remains a data URI
and is rejected. Broken headers remain ordinary text, and a later valid header
is still found. Binary signatures, long base64 runs, credentials, resident
registration numbers, byte budgets, and provider-call admission are unchanged.

RED imported the absent linear scanner and failed collection. GREEN covers
ordinary and upper-case data URIs, whitespace termination, a later valid URI,
and 1,600 repeated attacker-controlled prefixes with and without a terminal
comma. Hosted CodeQL on the repaired exact head remains the authoritative
acceptance gate; this record does not convert queued, skipped, or stale results
into success.
