# Review gateway explicit-model fail-close request-path receipt

Local synthetic measurement on 2026-09-24 UTC for #1106 and draft PR #1235.
The runtime repair is `76f3367a1877b456bed624ff1fa811e3b54cda13`
against predecessor `9504495c6c616a15c314c7a38218a73b143aa5e1`.
The current PR head at measurement was
`2ac14caf6e1c221619b18dcb94330b0e4e98abc9`; its later change only
declares the already-returned 400 envelope in OpenAPI.

The same synthetic prompt and fixed credential name were sent through the
direct `proxy_completion` path and the real `/v1/chat/completions` HTTP path.
The provider was a loopback HTTP server returning a fixed response after a
10 ms delay. No external provider, real credential, company data, or research
content was used. Each process ran on the same macOS 26.5.1 arm64 host with
Python 3.12.13 and 10 reported CPUs. Each scenario used 20 warmup calls,
then five rounds of 40 measured calls at concurrency four. The whole sequence
was run twice in baseline → repaired order. Provider sends exclude warmup.

| Path / revision | Measured outcomes (n=400) | Provider sends | p50 / p95 latency, ms across the two runs | Mean throughput, req/s across the two runs |
| --- | --- | ---: | --- | --- |
| Direct, predecessor `9504495c` | 400 × `200:ok` | 400 | 18.708–19.516 / 201.982–234.967 | 64.60–67.40 |
| Direct, repair `76f3367a` | 400 × `400:review_model_not_allowed` | 0 | 0.004–0.005 / 0.008–0.022 | 51,531–82,332 |
| HTTP, predecessor `9504495c` | 400 × `200:ok` | 800 | 107.468–109.722 / 235.684–254.233 | 31.59–33.14 |
| HTTP, repair `76f3367a` | 400 × `400:review_model_not_allowed` | 0 | 2.451–4.340 / 3.795–6.671 | 892.19–1,529.46 |
| HTTP free control, predecessor | 400 × `503:allocation_evidence_unavailable` | 0 | 2.402–6.114 / 4.878–13.988 | 591.18–1,476.81 |
| HTTP free control, repair | 400 × `503:allocation_evidence_unavailable` | 0 | 3.299–3.386 / 6.790–7.497 | 1,009.94–1,081.51 |

The listed throughput values are the means of each run's five 40-call rounds.
The per-round measurements and exact runner settings are in
[`evidence/review_gateway_failclosed_20260924.json`](evidence/review_gateway_failclosed_20260924.json).
The two-run ranges are descriptive observations, not confidence intervals.
Their within-run ranges were 29.09–34.05 req/s for predecessor HTTP
explicit requests and 852.72–1,586.18 req/s for repaired HTTP explicit
requests. The unchanged free-control path ranged from 393.75 to 1,759.54
req/s across runs. That spread, plus a current-head `2ac14caf` HTTP explicit
check (200 × 400, zero sends, 4.321 ms p50, 7.591 ms p95, 848.61 req/s),
shows substantial local scheduling noise. The explicit-model paths also
return different outcomes before and after repair, so their latency and
throughput cannot be interpreted as serving-capacity improvement. The
defensible result is the observed change from provider sends to typed
pre-send rejection. No hosted runtime or production latency was measured.

Reproduction uses the same script and project-local interpreter for both
checkouts. Execute each benchmark command twice, saving each JSON stdout;
stderr contains only local request-failure logs. The script checks exact
error codes and provider-send boundaries before printing a result.

```sh
SOURCE=$(git rev-parse --show-toplevel)
PY="$SOURCE/.venv/bin/python"
SCRIPT="$SOURCE/scripts/bench_review_gateway_failclosed.py"
git worktree add --detach /tmp/co-1106-bench-before 9504495c6c616a15c314c7a38218a73b143aa5e1
git worktree add --detach /tmp/co-1106-bench-after 76f3367a1877b456bed624ff1fa811e3b54cda13
```

From `/tmp/co-1106-bench-before`:

```sh
"$PY" "$SCRIPT" --requests-per-round 40 --rounds 5 --warmup 20 --concurrency 4 --provider-delay-ms 10 --expected-explicit-status 200
```

From `/tmp/co-1106-bench-after`:

```sh
"$PY" "$SCRIPT" --requests-per-round 40 --rounds 5 --warmup 20 --concurrency 4 --provider-delay-ms 10 --expected-explicit-status 400
```

The direct and HTTP rejection paths are also covered by
`tests/test_review_gateway_admission_contract_1106.py`. This local receipt
does not satisfy protected-head checks, independent review, calibrated
allocation evidence, immutable release, or consumer workflow acceptance.
