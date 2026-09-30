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

PR #1349 is the canonical owner repair. Its fixed-token scan recognizes
case-insensitive `data:`, comma, and whitespace in one pass, preserving the
original `data:[^,\s]*,` language without a header-length cutoff. Binary
signatures, long base64 runs, credentials, resident registration numbers, byte
budgets, and provider-call admission are unchanged.

The #1221 ancestor retains the original CodeQL and SARIF identity above. The
stacked merge replaces its parallel scanner and duplicate regression with
#1349's broader contract: ordinary and mixed-case data URIs, repeated prefixes,
headers beyond the rejected 256-character workaround, whitespace termination,
and deterministic varied-text equivalence against the original language.
Hosted CodeQL on the unchanged merged head remains the authoritative acceptance
gate; this record does not convert queued, skipped, or stale results into
success.
