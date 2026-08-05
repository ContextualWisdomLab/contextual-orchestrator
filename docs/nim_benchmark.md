# NIM model discovery + cost-quality benchmark

The optional benchmark harness (`contextual_orchestrator/nim_benchmark.py`)
answers the buyer-visible gap in issue #86: prove, with reproducible evidence,
what the repository's routing policies buy on a **real, dynamically discovered**
model pool. NVIDIA NIM is an evaluation provider, never a runtime dependency.
The production gateway remains provider-neutral and standard-library-only.

## Run it

```bash
# Deterministic dry run: validate manifests, pricing, scorers, budgets, and
# output schemas against an in-process synthetic provider with zero egress.
python -m contextual_orchestrator nim-benchmark --dry-run \
  --pricing-scenario examples/nim_pricing_scenario.json \
  --output-dir benchmark_artifacts

# Live CI run: the job secret is bootstrap transport into the KV; runtime
# access resolves NVIDIA_NIM_API_KEY only through get_credential.
python -m contextual_orchestrator nim-benchmark \
  --max-total-requests 300 \
  --max-output-tokens 256 \
  --git-sha "$GITHUB_SHA" \
  --workflow-run-id "$GITHUB_RUN_ID"
```

The provider secret is never accepted through argv, printed, or serialized.
The artifact writer refuses to write a file containing the resolved value.

## Workflow credential boundary

The GitHub Actions workflow uses separate top-level jobs for dry and live runs.
`dry_run_benchmark` is available only for an explicitly selected manual dry run,
contains no `secrets` expression, and executes the in-process synthetic provider.
`live_benchmark` runs only for the conservative monthly schedule or an explicit
manual live selection and owns the workflow's sole provider-secret binding.

This separation enforces least privilege before Python starts. Dry-run safety no
longer depends on an application branch correctly ignoring a credential that the
job did not need. A static repository test fails if the dry-run job receives any
secret expression, if the jobs are recombined, or if more than one provider-secret
binding appears in the workflow. The threat model, rollback boundary, executable
contract, and APA 7 references are recorded in
`docs/doctoring/nim-benchmark-workflow-secret-isolation.md`.

## Provider-egress security boundary

Catalog discovery, capability probes, and live policy evaluation share the
runtime provider transport reviewed in security PR #76:

- every endpoint must use HTTPS;
- every validation-time DNS answer must be globally routable, including an
  explicit rejection of RFC 6598 shared address space and all private,
  loopback, link-local, multicast, and reserved ranges;
- the socket connects directly to one address from the validated answer;
- HTTP authority, TLS SNI, and certificate verification retain the original
  provider hostname;
- environment proxy resolution is bypassed;
- redirects are not followed, so a bearer credential cannot be forwarded to a
  destination outside the validated origin; and
- fallback is limited to addresses in the same validation-time answer.

This closes the DNS time-of-check/time-of-use gap that exists when software
validates a hostname and then lets a generic URL opener resolve it again.

## Dynamic catalog and all-modality probes

Models come from the OpenAI-compatible `GET /v1/models`; no model inventory is
hard-coded. The parsed catalog is deduplicated, sorted by model identifier, and
retains machine-readable `duplicate_model_ids` and `invalid_entries` evidence.
Zero usable models fails the run closed.

Every discovered model is probed under bounded concurrency and one shared hard
request budget for these contracts:

| Probe | Endpoint or request contract |
| --- | --- |
| `chat_completion` | `POST /chat/completions` |
| `text_completion` | `POST /completions` |
| `response_generation` | `POST /responses` |
| `text_embedding` | `POST /embeddings` |
| `image_understanding` | chat with a tiny PNG `image_url` part |
| `video_understanding` | chat with a tiny MP4 `video_url` part |
| `audio_understanding` | chat with a tiny WAV `input_audio` part |
| `audio_transcription` | `POST /audio/transcriptions` |
| `audio_speech` | `POST /audio/speech` |

Per-probe outcomes are `supported`, `unsupported`, `rate_limited`, `timeout`,
`unavailable`, `failed`, `malformed_response`, or `skipped`. Every skipped
probe carries a machine-readable reason. HTTP 401 fails the whole run closed.
Model-level classifications are derived from these observations rather than
inferred from names or marketing metadata.

## Fair comparison contract

Every comparable policy × task cell receives the same:

- locked task manifest and scorer versions;
- request timeout;
- total prompt-plus-completion token allowance, configured by
  `--max-output-tokens`;
- declared maximum-call envelope of five calls; and
- workflow-depth ceiling of five steps.

The total allowance is cell-wide, not per call. Before each provider call the
client subtracts estimated prompt tokens and lowers the call's output cap to
the remaining allowance. Provider-reported usage replaces the estimate where
available. A cell stops or fails when either its call or total-token allowance
is exhausted; `conduct` therefore cannot obtain five times the budget of a
single-call arm.

Compared policies are:

1. one direct baseline for each eligible worker;
2. deterministic low-latency `route_once`;
3. bounded deep `conduct_bounded`;
4. the cheapest eligible worker under an explicit reviewed pricing scenario.

Every cell records configured and observed call/token budgets, remaining token
allowance, score and scorer version, outcome and reason, latency, workflow
depth, provider-reported or estimated token usage, model/role/step assignment,
actual and hypothetical cost fields, and a SHA-256 of the answer.

## Cost honesty and evidence validity

Actual and hypothetical cost never mix.

`actual_cost_usd` is currently `0.0` only in the reviewed context of NVIDIA
Developer Program API Catalog hosted endpoints used for prototyping, research,
and testing. The report records a versioned evidence object containing:

- the official NVIDIA documentation source identity;
- review date and validity horizon;
- program and access scope;
- the distinction that production support and licensing require NVIDIA AI
  Enterprise; and
- uncertainty that hosted-endpoint terms may change.

Live runs fail closed after the evidence validity date until the authoritative
source is reviewed again. This prevents a historical free-access assertion
from silently becoming a permanent price claim.

Hypothetical paid cost is computed only from an explicit versioned pricing
scenario. The included example is marked `example_unreviewed`; any unpriced
model makes the whole affected value `"unknown"`. The benchmark never invents
model prices or converts free hosted access into a production pricing claim.

## Statistics and leakage controls

- Paired task-level bootstrap comparisons report seeded percentile 95%
  confidence intervals rather than means alone.
- Pareto frontiers cover quality versus latency and quality versus reviewed
  hypothetical cost; unknown-cost policies are excluded and listed.
- The manifest validator rejects a task when its own scorer would award the
  prompt a point, preventing expected-answer leakage.
- Only the locked split enters reported comparisons; exploratory tasks remain
  tuning-only.

## Fail-closed contract

A run aborts without artifacts when the live KV credential is missing; endpoint
validation fails; catalog discovery is incomplete; authentication is rejected;
the request, call, or token budget is exhausted; live Git/workflow provenance
is missing; actual-cost evidence is expired or incomplete; report validation
fails; or an artifact would expose the provider secret.

## Provenance and artifacts

Each run writes schema-validated `benchmark_report.json`,
`benchmark_cells.csv`, and `benchmark_summary.md`. Provenance records the exact
Git SHA, workflow run identifier, catalog/manifest/pricing hashes, all benchmark
parameters, capability failures and skips, configured versus observed budgets,
cost-evidence identity and validity, uncertainty, and Pareto results. Dry-run
artifacts are deterministic so schema and evidence regressions appear as diffs.

## Workflow

`.github/workflows/nim-benchmark.yml` supports a credential-free manual dry-run
job, an explicitly selected manual live job, and a conservative scheduled live
run. The jobs retain explicit hard request caps, single-flight concurrency,
timeouts, immutable action pins, and retained evidence artifacts. The workflow
never merges, releases, changes routing policy, or rewrites production
configuration.

## Method grounding

Multi-metric, uncertainty-carrying reporting follows HELM (Liang et al., 2022;
arXiv:2211.09110). The cost/quality routing frame follows FrugalGPT, RouteLLM,
and Hybrid LLM, listed in `docs/papers/README.md`. These sources ground the
measurement design; they do not substitute for exact-head benchmark evidence.
