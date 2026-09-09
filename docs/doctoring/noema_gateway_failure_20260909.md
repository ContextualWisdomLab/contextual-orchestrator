# Noema gateway failure: evidence provenance

Status: investigation; no runtime repair or KPI improvement claimed.

## Verified source

- Consumer PR: contextual-orchestrator #1103, head
  `4776a970ed8bdef3406684aef84952740b476d88`.
- Workflow run: `34195571142`; first Noema job: `101967720557`.
- The job reports HTTP 502 after 926.0 seconds at
  `2026-09-08T07:43:21Z`, with `provider_connection_error` in the sidecar.
- Matching artifact: `10045693660`, created `2026-09-08T07:43:22Z`, digest
  `sha256:d3e1ca380217c7e8f5c4ae80e862b6f9333deb9e64e9368a8f02bb11270a3ff9`.
- Run artifacts also contain the same name, `noema-sidecar-evidence`, under
  IDs `10046985455` and `10048993704`, created at 08:21:36Z and 09:16:08Z.
  Name-only download selected later evidence; use artifact ID when attributing
  a failure to a specific attempt.

## Observations and limits

The matching sidecar records repeated approximately 90-second `TimeoutError`
outcomes for `deepseek-ai/deepseek-v4-flash-0731`. It records `circuit_opened`
at 07:39:13.828 and another attempt for the same agent at 07:39:13.911.
It also records other model attempts and circuit resets. These logs do not
contain sufficient request correlation to establish whether adjacent attempts
belong to the same request or whether an already-admitted call crossed the
circuit transition. A circuit bypass is therefore a hypothesis, not a finding.

The job bootstrap explicitly reports gateway source revision
`414f22973658c4ddc3d4320fcf7acd9b4e8ba991` at 07:20:03Z. This differs from
the reviewed PR head. At that source revision, `orchestrator.py:1696` declares
the transport constructor default `timeout: int = 90`; line 2256 selects
`self.timeout` when the request timeout argument is `None`. This is a concrete
candidate explanation for the observed durations, but the caller construction
and any bootstrap overrides still need verification. The bootstrap also reports
five of five provider secrets present; this run does not support a missing-key
diagnosis.

Next investigation: resolve the sidecar constructor and effective timeout
configuration, then trace admission, probes, retries, and fallback in
the deployed source revision. Reproduce any confirmed violation before changing the canonical
gateway. The 926-second failure duration is not routing-decision p95 or buyer
accuracy evidence. Preserve the failed request in the operational denominator.

## Existing repair ownership

PR [#1053](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1053)
already owns removal of the implicit model timeout. On inspection its head is
`76c047585f54fcbe940fe168412f51627d3f79dd`, base `main`, and it remains Draft.
Its description contains older head and test claims; those claims must not be
transferred to the current revision. Continue that PR's implementation and
review rather than creating a duplicate timeout fix. Its documented remaining
scope includes model-specific administrator policy propagation, protected
merge, release, consumer adoption, and runtime recovery.

The three failed compatibility jobs returned by #1053's check rollup
(`101701439950`, `101701439874`, `101701439897`, run `34098501126`)
all end with `DISPATCH_OUTCOME=success`, `VERDICT_STATE=pending` and an
explicit failure awaiting an authenticated terminal verdict. Their log tails
do not report a source vulnerability. This evidence identifies a verdict
delivery investigation at the central workflow owner; it does not establish
that a scan succeeded, or authorize bypassing these checks.

Reading the complete Python step narrows this further: its successful step
only GETs the live PR and commit statuses, validates the head, and writes
`verdict=pending`. It contains no dispatch POST. Consequently
`DISPATCH_OUTCOME=success` is step completion, not a dispatch receipt. The
terminal message "CodeQL scan dispatched" overstates the evidence. The
central dispatch-run listing for 2026-09-07 10:40–11:10Z returned 13 runs,
none for #1053; this bounded search is not proof that no dispatch ever existed.
Investigate the separate dispatch trigger and correct the misleading message
at the central workflow owner.

Central owner inventory identifies open `.github` PR #2044 at
`3720dd853fe399fd453e093a90944b2b0e78a8e6` for versioned head envelopes,
#2040 at `6706c231ab06a3c91c43fdb5b989cfcd79fff593` for target-app wake
credentials, and #2051 at `a34dc5af8363a86531d70e51983ad336b9f57096` for
sibling-shard rerun races. These are candidate repair lanes, not established
causes of #1053. Match dispatch receipts and wake-job logs before adopting one.
An open owner PR does not provide a released consumer contract.

The paginated commit-status endpoint for #1053 head `76c04758` returned no
`codeql-dispatch/*` contexts on inspection. The Python required-job log queries
those contexts, but does not print a dispatch-run identifier. Thus the required
job's successful status-read step cannot locate or prove completion of the scan.
Follow-up must locate the dispatch using repository, PR, language, and full
head SHA; it must not fabricate a status to satisfy the consumer.

The separate coordinator job `101717808225` ran later, at 12:33:14Z, and
POSTed the full #1053 payload. This locates central run `34122498232`, whose
title includes repository, PR #1053, and full head `76c04758`. Validation
succeeded; all three language jobs failed. Python job `101756437515` reports
HTTP 403 `Resource not accessible by integration` while publishing the
dispatch status with both `target-app-token` and `github-token`, then fails
closed without waking the required job. This establishes a concrete status
publication permission failure. It does not prove scanner success or that
either credential is absent. Inspect app permission and installation scope at
the canonical owner before changing the publisher or repeating the scan.

Current metadata from `GET /orgs/ContextualWisdomLab/installations` shows
`opencode-agent` installation `141441800` covers all repositories but grants
only `statuses: read` and `actions: read`. `GET /apps/opencode-agent` reports
the same registered permissions and owner `anomalyco`. Thus repository
selection expansion cannot supply the missing write permissions, and there
is no evidence of a pending write-permission upgrade to accept. The external
app owner must change the registration, or the central workflow must adopt
an explicitly governed publisher identity with the required permissions and
matching verdict authentication. Do not substitute an unrelated installed
app merely because it has write access. This metadata is current evidence,
not a historical grant snapshot for the failed execution.

Sources: [job log](https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/runs/34195571142/job/101967720557),
[matching artifact](https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/runs/34195571142/artifacts/10045693660).
