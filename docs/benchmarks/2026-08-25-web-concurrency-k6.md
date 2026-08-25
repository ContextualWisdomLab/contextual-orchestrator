# Web concurrency k6 baseline — 2026-08-25

## Decision

The current synchronous provider transport remains because it already runs in
one daemon request thread per HTTP connection. A slow upstream call therefore
does not occupy the accept loop or another request's thread. The measured
bottleneck was instead the inherited five-connection listen backlog and
HTTP/1.0 connection churn. The gateway now uses the operating system's native
`SOMAXCONN` backlog and HTTP/1.1 persistent connections. No routing weights or
performance heuristics were added.

This is an I/O-concurrency result, not a production capacity promise. The test
uses only synthetic prompts and a deterministic one-second delayed provider;
it contains no provider credential, personal data, or production record.

## End-to-end path exercised

`k6 -> HTTP authentication -> JSON validation -> run-slot admission -> route ->
synthetic delayed ModelClient -> OpenAI-compatible response`, while a separate
arrival-rate scenario calls `/healthz`. The test therefore detects a web server
that stops accepting liveness traffic while provider requests wait.

The invariant-based threshold is `health_latency p(99) < provider delay`. It
does not invent a production latency SLO: a liveness request must complete
before the deliberately blocked provider call, or isolation has failed. All
HTTP requests and response checks must succeed.

## Reproduction

Terminal 1:

```bash
uv run python tests/load/serve_synthetic_delay.py \
  --delay-seconds 1 --max-concurrent-runs 64
```

Terminal 2:

```bash
BASE_URL=http://127.0.0.1:18089 \
  k6 run tests/load/k6_web_concurrency.js --summary-mode=full
```

The checked scenario starts 64 simultaneous delayed inference users, performs
128 authenticated completions in two waves, and sends 20 liveness requests per
second for five seconds. `SecurityConfig.max_concurrent_runs=64` is the explicit
admission limit under test, not an inferred capacity.

## Exact measured result

Host: Apple Silicon macOS; Python 3.13.14; k6 2.2.0; loopback HTTP; synthetic
one-second provider delay. Base was `838b3de1`; the exact tested candidate
source tree was `97ce7ed7` (the later documentation-only commit does not alter
runtime code or the k6 fixture).

| Metric | Base HTTP/1.0 + backlog 5 | Candidate HTTP/1.1 + `SOMAXCONN` | Observation |
|---|---:|---:|---|
| Completed inference checks | 128/128 | 128/128 | 64 simultaneous calls supported |
| Failed HTTP requests | 0/229 | 0/229 | no request loss |
| Inference scenario rate | 16.18 req/s | 25.02 req/s | 54.61% higher measured rate |
| Inference connection-blocked average | 571.73 ms | 1.79 ms | listen/connection bottleneck removed |
| Inference connection-blocked p95 | 3.95 s | 9.16 ms | burst tail materially reduced |
| Liveness p99 during delayed inference | 18.73 ms | 9.90 ms | completes before one-second provider delay |
| Candidate liveness checks | — | 101/101 | web remained responsive |

The throughput percentage is derived directly from the two measured scenario
rates: `(25.021239 / 16.183192 - 1) * 100 = 54.61%`. It is not a weight used by
routing or production configuration.

## Remaining bottlenecks and next measurement

- The stdlib server uses one daemon thread per connection. The admission
  semaphore bounds expensive orchestration work, but a reverse proxy or ASGI
  deployment should be measured before raising the explicit 64-run ceiling.
- Provider service time still sets inference latency: candidate inference p95
  was 1.07 seconds with a one-second synthetic provider.
- TLS termination, cross-host network latency, real provider quotas, multiple
  processes, and sustained soak behavior were outside this loopback run. Add
  those only with a deployment-specific workload and SLO; this benchmark must
  not fabricate them.

## Research and standards basis (APA 7th)

Dean, J., & Barroso, L. A. (2013). The tail at scale. *Communications of the
ACM, 56*(2), 74–80. https://doi.org/10.1145/2408776.2408794

Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP/1.1* (RFC 9112;
STD 99). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc9112

Grafana Labs. (n.d.). *API load testing*. Grafana k6 documentation. Retrieved
August 25, 2026, from
https://grafana.com/docs/k6/latest/testing-guides/api-load-testing/

The RFC makes HTTP/1.1 persistent connections the default and notes that
multiple connections avoid head-of-line blocking at a server-resource cost.
Dean and Barroso establish why tail behavior, rather than only averages,
governs responsive online services. k6's documented arrival-rate executor is
used for the independent liveness stream.
