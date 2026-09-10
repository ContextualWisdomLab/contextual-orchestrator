# PR #1049 passthrough failure evidence

Relocated on 2026-09-10 from the PR's cumulative baseline and changelog to
preserve current main's records without changing any production or test blob.
The dated observations and earlier validation below are historical evidence,
not a fresh integrated-head, release, or deployment claim. The complete source
history remains on PR #1049, including head
`e2641c16a82816e15f12013efad7fe50e94a3333`.

## Changelog fragment — Unreleased

- Passthrough attempt receipts no longer infer public provider labels from
  endpoint hostnames. Ambiguous timeout/connection failures now report the
  neutral `transport` phase and remain sticky even for `orchestrator/free`,
  preventing duplicate completion and unreported upstream usage. Generic
  HTTP 500/502/504 and non-standard 529 responses are sticky as well: an HTTP
  retry classification alone does not prove that a non-idempotent completion
  request was never applied.

## 2026-09-04 Autonomous Commercialization Loop: issue #1045 root-cause fix for orchestrator/free passthrough 502 evidence

Observation time: 2026-09-04 Asia/Seoul.

GitHub authentication was re-verified first with `gh api user`. The primary
checkout was dirty, so work continued in a clean linked worktree at
`.worktrees/commercial-loop-20260904-issue1045`. Open PR heads and prior
`commercial-loop-*` worktrees were re-fetched before editing. No existing
open PR head covered this exact contract: PR [#1046](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1046)
was only queued behind hosted checks for an unrelated EgressWeave SSRF change,
while the active `orchestrator/free` queue items [#1028](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1028)
and [#993](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/993)
were preserved as distinct in-flight contracts. The highest-leverage
independent unit was therefore issue
[#1045](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/1045):
typed attempt evidence and bounded failover for long `orchestrator/free`
tool-loop transport failures.

### Root cause confirmed on current `main`

The live Noema review incidents in issue `#1045` reproduced the single-agent
tool-loop path, not `route_once()`. `/v1/chat/completions` tool-bearing
requests call `proxy_completion(..., single_agent=True)`, which performs
virtual-model passthrough failover inside `TaskOrchestrator.proxy_completion`.

Current-head RCA:

- raw HTTP passthrough failures were already classified and could participate
  in bounded failover, but raw provider transport exceptions such as
  `TimeoutError`, `urllib.error.URLError`, `ConnectionError`, and wrapped DNS
  failures were not classified inside the multi-candidate passthrough loop;
- `classify_provider_failure()` already mapped those raw exceptions to bounded
  typed 502 surfaces, but `proxy_completion()` only invoked the classifier for
  `HTTPError` and already-classified `ProviderUpstreamError` instances;
- raw transport failures had no request-scoped attempt receipt explaining why
  the gateway stopped. They remain non-replayable because a timeout or generic
  connection failure does not prove that the provider rejected the request
  before accepting work or usage.

### Local fix completed

The worktree change makes one surgical contract extension:

- `proxy_completion()` now classifies every caught passthrough provider
  exception before deciding whether failover is permitted;
- `orchestrator/free` virtual passthrough advances only after evidence that
  proves non-acceptance, such as an RFC-defined request rejection or temporary
  pre-request DNS failure. RFC 9110 section 9.2.2 does not authorize automatic
  replay of a non-idempotent request from retryability alone. Generic
  500/502/504 responses and the non-standard 529 therefore remain sticky,
  alongside raw timeout and generic transport failures, to prevent duplicate
  completion and unreported usage;
- sticky failures now record the distinct failover decision
  `sticky_candidate_failure` instead of incorrectly reusing
  `eligible_candidates_exhausted`, while explicit concrete-model requests
  remain single-provider sticky.

The public error detail remains bounded and secret-safe: no credentials, raw
provider bodies, prompt text, or inferred endpoint hostnames are emitted.
Unclassified connection/timeout outcomes use lifecycle phase `transport`;
only explicit TLS failures use `connecting`.

### Exact local verification

The 2026-09-08 current-head review repair added three explicit acceptance
boundaries: no replay after an ambiguous transport outcome, no inferred
endpoint hostname in public attempt evidence, and no invented `connecting`
phase for an outcome whose lifecycle stage is unknown. The revised tests first
failed as expected (`3 failed, 61 passed`) and then passed after the minimal
owner fix.

- Added focused regressions proving ambiguous raw/classified transport errors
  remain sticky in both the in-process free-model loop and real
  `/v1/chat/completions` HTTP path. A follow-up RED contract found that HTTP
  500 still replayed; the repair also keeps 502, 504, and 529 sticky while
  retaining bounded failover for explicit rejection and temporary pre-request
  DNS evidence.
- `.venv/bin/python -m pytest tests/test_passthrough_provider_failover.py tests/test_openai_passthrough.py -q`
  -> `98 passed in 10.64s`
- `.venv/bin/python -m pytest tests/test_provider_error_taxonomy.py tests/test_passthrough_provider_failover.py tests/test_openai_passthrough.py -q`
  -> `119 passed in 11.61s`
- `uvx ruff check --select E4,E7,E9,F contextual_orchestrator/orchestrator.py tests/test_passthrough_provider_failover.py tests/test_openai_passthrough.py`
  and `git diff --check` -> success.

### Branch-local quality note

- `uv run ruff check contextual_orchestrator/orchestrator.py tests/test_passthrough_provider_failover.py tests/test_openai_passthrough.py`
  could not run in this worktree because the pinned environment does not
  currently expose a `ruff` executable (`No such file or directory`).

Hosted exact-head checks, protected merge, and the unchanged LifeOS/Noema
consumer canary remain future steps because this invocation stopped at one
completed local root-cause work unit, per the hourly-loop boundary.
