# Issue #1106: supported review path measurement receipt

Status: **LIVE EVIDENCE UNAVAILABLE; Draft/HOLD**. Checked 2026-09-24 19:10 UTC. This receipt is separate from the [local synthetic fail-closed benchmark](review_gateway_failclosed_benchmark.md). No company content, credential, hosted request, deployment, or load test was used.

## Observed build and selection boundary

- The `.github` default branch was `e6334e229581a918e2f22de18733b76fa65d7e71` at inspection. Its [sidecar script](https://github.com/ContextualWisdomLab/.github/blob/e6334e229581a918e2f22de18733b76fa65d7e71/scripts/ci/contextual_orchestrator_review_sidecar.sh#L17) defaults `ORCHESTRATOR_PIN_SHA` to `767e67fbc6b881a452761f32abb69b9971b9b03b`, clones that CO revision into each runner, and installs its hash-locked dependencies. The variable can be overridden, so the script's default is **not** an observed runner build SHA.
- The sidecar restricts its workflow pool to `free` and its [preflight](https://github.com/ContextualWisdomLab/.github/blob/e6334e229581a918e2f22de18733b76fa65d7e71/scripts/ci/contextual_orchestrator_review_sidecar.sh#L413) calls local `/v1/chat/completions` with `model: orchestrator/free`. The [launcher](https://github.com/ContextualWisdomLab/.github/blob/e6334e229581a918e2f22de18733b76fa65d7e71/scripts/ci/contextual_orchestrator_review_launcher.py#L1244) instantiates `TaskOrchestrator(agents, client=client)` from its discovery/policy/preflight selection; it does not call CO's `build_review_orchestrator`. This is the currently documented supported runner-side request path, not a deployed immutable gateway.
- [Noema](https://github.com/ContextualWisdomLab/.github/blob/e6334e229581a918e2f22de18733b76fa65d7e71/.github/workflows/noema-review.yml#L728) starts the sidecar and sets its API URL to local `/v1/chat/completions`. [Strix](https://github.com/ContextualWisdomLab/.github/blob/e6334e229581a918e2f22de18733b76fa65d7e71/.github/workflows/strix.yml#L782) explicitly chooses `free` and starts the same sidecar.
- CO [PR #1235](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1235) was Draft at `119367ea315adf27cbe37c1efc1011f09f72cdbf`; its Security jobs were skipped. CO had zero GitHub releases. Neither the draft revision nor local synthetic tests identify a deployed runner build or hosted result.

## Bounded comparison contract

For a future authorized runner measurement, capture the workflow run URL/id, checked-out CO SHA from the sidecar log, `.github` workflow SHA, installed lock digest, launcher route (`orchestrator/free`), host class, catalog/admission version, and a sanitized preflight artifact **before** counting a sample. Compare a known baseline SHA and candidate SHA using the same safe synthetic chat request shape, same eligible model selection, max output, runner class, warmup, concurrency, and bounded request count. Hold provider/model availability constant or report that comparability failed. Record per-request end-to-end latency p50/p95, completed requests per second over the same measurement window, and class counts: success, typed 400 `review_model_not_allowed`, typed 503 `allocation_evidence_unavailable`, provider/transport failure, timeout, malformed response, and other HTTP errors. Record total provider attempts and unknown-outcome attempts separately; a transport spy is not wire delivery evidence.

Read-only evidence commands, with no credentials in output:

```sh
gh api graphql -f query='query { repository(owner:"ContextualWisdomLab",name:".github") { defaultBranchRef { target { oid } } } }'
gh run list -R ContextualWisdomLab/.github --workflow noema-review.yml --limit 10 --json databaseId,headSha,conclusion,createdAt,url
gh run list -R ContextualWisdomLab/.github --workflow strix.yml --limit 10 --json databaseId,headSha,conclusion,createdAt,url
gh pr view 1235 -R ContextualWisdomLab/contextual-orchestrator --json headRefOid,isDraft,statusCheckRollup
```

For a controlled before/after run, the operator must supply two exact, authorized runner builds and sanitized per-request timing/status/attempt artifacts from the **same** supported local HTTP endpoint. Use a small fixed sample and one concurrent caller, then compute class counts and latency/throughput from the artifacts. Do not use review content or print credentials. Stop if the source pin, model pool, eligible catalog, runner class, or request shape differs. This receipt does not authorize a workflow dispatch or provider egress.

## Concrete blocker

No exact hosted sidecar build pair, immutable owner release, scoped endpoint credential, or comparable sanitized request-level timing artifacts were available in this inspection. The sidecar's default pin `767e67fb` is older than the Draft owner fix and the runner can override it. A live before/after latency, error, or throughput number for the actual supported path would therefore be fabricated. The only measured A/B numbers remain [local synthetic HTTP evidence](review_gateway_failclosed_benchmark.md), which establishes the admission boundary and says nothing about hosted capacity.
