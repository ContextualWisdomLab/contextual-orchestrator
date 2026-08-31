# NIM model discovery + cost-quality benchmark

The optional benchmark harness (`contextual_orchestrator/nim_benchmark.py`)
addresses issue #86: generate reproducible evidence about how the repository's
routing policies behave on a **real, dynamically discovered** model pool.
NVIDIA NIM is an evaluation provider, not a runtime dependency. Importing the
normal `contextual_orchestrator` package does not import or mutate the optional
benchmark module.

The detailed engineering and evidence record is
[`docs/doctoring/nim-benchmark-evidence-grade.md`](doctoring/nim-benchmark-evidence-grade.md).

## Run it

```bash
# Deterministic dry run: validates manifests, scorers, budgets, evidence
# sufficiency, and artifact schemas against an in-process provider. It performs
# no network calls and never receives NVIDIA_NIM_API_KEY.
python -m contextual_orchestrator nim-benchmark --dry-run \
  --pricing-scenario examples/nim_pricing_scenario.json \
  --output-dir benchmark_artifacts

# Live CI run: the workflow injects NVIDIA_NIM_API_KEY only into the live step.
# The process bootstraps it into the credential registry and runtime access
# resolves the credential by name.
python -m contextual_orchestrator nim-benchmark \
  --max-total-requests 2000 \
  --max-output-tokens 264 \
  --git-sha "$GITHUB_SHA" \
  --workflow-run-id "$GITHUB_RUN_ID"
```

The provider secret is never accepted through argv, printed, or serialized.
Artifact writing fails closed if the resolved secret appears in any output.

`--max-output-tokens` is the per-provider-call output cap. The equal
cell-wide prompt-plus-completion budget is five times that cap by default
(`1,320` tokens), which leaves the fixed five-call conduct workflow enough room
for its prompts while keeping the same cell budget for every policy.

## Provider-egress security boundary

Catalog discovery, probes, and live policy evaluation use validation-time
address pinning:

- every provider URL must use HTTPS;
- each request resolves its hostname exactly once;
- every answer must be globally routable, so RFC 6598 shared space, private,
  loopback, link-local, multicast, reserved, unspecified, and IPv6 unique-local
  addresses are rejected;
- the socket dials only an address from that exact DNS answer;
- HTTP authority, TLS SNI, and certificate hostname verification retain the
  original hostname;
- environment proxy settings are not consulted;
- redirects are rejected rather than followed; and
- address fallback is limited to the same validation result; and
- every provider response is read through an 8 MiB hard cap before it can be
  materialized in memory.

This closes the DNS time-of-check/time-of-use gap created by validating a
hostname and then letting a generic URL opener resolve it again.

## Dynamic catalog and all-modality probes

The live inventory comes from the OpenAI-compatible `GET /v1/models`; no
hard-coded list is treated as authoritative. The parser deduplicates and sorts
usable identifiers while retaining invalid-entry and duplicate evidence. Zero
usable models fails the run closed.

Every discovered model receives a row for each contract:

| Probe | Endpoint or request contract |
| --- | --- |
| `chat_completion` | `POST /chat/completions` |
| `text_completion` | `POST /completions` |
| `response_generation` | `POST /responses` |
| `text_embedding` | `POST /embeddings` |
| `image_understanding` | chat with a tiny PNG `image_url` part |
| `video_understanding` | chat with a validated one-frame MP4 `video_url` part |
| `audio_understanding` | chat with a tiny WAV `input_audio` part |
| `audio_transcription` | `POST /audio/transcriptions` |
| `audio_speech` | `POST /audio/speech` |

After catalog discovery and before the first capability request, the harness
constructs the complete request plan: one discovery request, every sorted
`(model_id, capability_name)` probe, and the conservative evaluation reserve for
the maximum eligible worker pool. If the configured cap is even one request
short, the run fails closed before capability egress and reports the required
and configured counts. Partial model-major prefixes cannot produce routing
evidence. Once preflight passes, all fixed cells execute under bounded
concurrency; thread scheduling can change completion order but not coverage.

The monthly schedule runs on the first day of each month and uses a hard ceiling
of 2,000 requests. This places the next scheduled run inside the current
reviewed evidence window; stale access-cost evidence still fails closed. On the
127-model catalog scale observed on 2026-08-05, the current thirty-task, seven-worker
configuration requires 1,924 requests: one catalog request, 1,143 capability
probes, and a 780-request worst-case evaluation reserve. The reserve includes
the full equal-call envelope for route-once cells, the five-call conduct
envelope, and real-time judge calls on direct and cheapest-worker cells. Catalog growth
beyond the ceiling causes a zero-partial-egress preflight failure rather than
silent truncation.

The embedded video fixture is a deterministic, decodable 16 × 16, one-frame
H.264 MP4. Its bytes are verified against SHA-256
`777dda43b5a15162b68a39aa486d5c70c9994d7fe761742fd00d4e13508983c0`, and its
container structure, video handler, AVC sample entry, dimensions, sample count,
and media data are validated before use.

Probe outcomes are `supported`, `unsupported`, `rate_limited`, `timeout`,
`unavailable`, `failed`, `malformed_response`, or `skipped`. HTTP 401 fails the
whole run closed. Model-level classes are derived from observations rather than
model names or marketing metadata.

## Fair comparison contract

Every policy × task cell receives the same:

- locked task and scorer version;
- total prompt-plus-completion token allowance configured by
  `--max-output-tokens`;
- five-call maximum envelope;
- timeout policy; and
- five-step workflow-depth ceiling.

Provider retries and orchestration tool retries are disabled inside the benchmark
cell so the declared request budget bounds actual egress and the measured call
envelope remains comparable across policies.

The token allowance is cell-wide, not per call. Prompt tokens are charged before
a request, the output cap is reduced to the remaining allowance, and valid
provider-reported usage replaces the latest estimate. A deep `conduct` path
cannot receive five times a direct arm's total token budget merely because it
uses more calls.

Compared policies are:

1. one direct baseline per chat-eligible worker;
2. deterministic `route_once`;
3. bounded `conduct_bounded`; and
4. a cheapest eligible worker only when an explicit reviewed pricing scenario
   supports that comparison.

Each cell records configured and observed budgets, score and scorer version,
outcome and reason, latency, depth, usage source, model/role/step assignments,
actual and hypothetical cost fields, and a response SHA-256.

## Cost honesty and evidence validity

Actual endpoint access and hypothetical paid cost remain separate evidence
classes.

As reviewed on 2026-08-05, NVIDIA's current General FAQ states that NVIDIA
Developer Program members have free access to hosted NIM API endpoints for
prototyping. The report records that exact source, review date, validity horizon,
program context, production distinction, and uncertainty. A live run fails
closed after 2026-09-04 until the official source is reviewed again. Production
support and licensing are not inferred from prototype access and require
NVIDIA AI Enterprise under the reviewed documentation.

Hypothetical paid cost is computed only from an explicit pricing scenario.
Omitting a scenario is valid and leaves cost `"unknown"`. A live scenario must
be marked `reviewed` and contain an HTTPS source, reviewer, review date, validity
horizon, rate basis, uncertainty, and explicit input/output rates. Unreviewed,
future, incomplete, or expired scenarios fail before provider egress. The
included example is intentionally `example_unreviewed`; it exists only to test
dry-run schemas and must never be presented as real model pricing.

## Evidence sufficiency and uncertainty

The bundled thirty-task manifest is an evidence-floor fixture with two exploratory
tasks kept outside the decision set. It proves integration behavior but does not
authorize production routing. A report reaches
`evidence_review_required` only when it contains at least 30 paired locked tasks
and at least 90% successful comparison cells. Otherwise it reports
`insufficient_evidence` and explains the shortfall.

These thresholds are explicit conservative governance floors, not universal
statistical guarantees. Every report keeps `routing_recommendation` null even
when the floor is met; a human review remains required.

- Seeded paired bootstrap intervals preserve task pairing.
- Pareto frontiers cover quality versus latency and quality versus reviewed
  hypothetical cost.
- Unknown-cost policies are excluded from the cost frontier and named.
- The manifest rejects expected-answer leakage according to each task's scorer.
- Only locked tasks enter reported comparisons; exploratory tasks remain outside
  the decision evidence.

## Fail-closed contract

A run aborts without artifacts when live provenance is absent, the credential is
missing, endpoint validation fails, discovery is incomplete, authentication is
rejected, a request/call/token budget is exhausted, cost evidence is invalid or
expired, a provider response exceeds 8 MiB, report validation fails, or output
would contain the provider secret.

## Provenance and artifacts

Each run writes:

- `benchmark_report.json`;
- `benchmark_cells.csv`; and
- `benchmark_summary.md`.

Provenance records the exact Git SHA and workflow run, catalog/manifest/pricing
hashes, benchmark parameters, capability failures and skips, equal-budget
configuration and observations, access-cost evidence and validity, evidence
sufficiency, uncertainty, and Pareto results. Dry-run artifacts are deterministic
so schema and evidence regressions are reviewable as diffs.

## Workflow

`.github/workflows/nim-benchmark.yml` uses separate dry and live jobs. The dry
job has no NVIDIA secret. Only the live benchmark step receives
`NVIDIA_NIM_API_KEY`. Both paths use immutable action revisions, hard request and
execution bounds, single-flight concurrency, and retained artifacts. The
workflow cannot merge, release, approve its own changes, or rewrite production
routing.

The normal Tests workflow separately proves 100% production statement and
branch coverage, 100% public docstrings, wheel build/install/import behavior,
optional-import isolation, and absence of temporary repair/export mechanisms.

## Method grounding

HELM supports standardized multi-metric evaluation and explicit reporting of
coverage gaps. FrugalGPT, RouteLLM, and Hybrid LLM motivate measuring routing
cost-quality trade-offs. NIST AI 600-1 supports documented, risk-aware testing,
evaluation, verification, and validation. These sources shape the measurement
and governance design; they do not substitute for exact-head evidence from the
models, tasks, and policies actually under review.
