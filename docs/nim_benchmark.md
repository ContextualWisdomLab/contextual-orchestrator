# NIM model discovery + cost-quality benchmark

The optional benchmark harness (`contextual_orchestrator/nim_benchmark.py`)
answers the buyer-visible gap in issue #86: prove, with reproducible evidence,
what the repo's routing policies buy on a **real, dynamically discovered**
model pool — NVIDIA NIM as the *evaluation provider*, never a runtime
dependency. The production gateway stays provider-neutral and stdlib-only;
the harness reuses the same stdlib HTTP and KV seams.

## Run it

```bash
# Deterministic dry run — validates manifests, pricing, scorers, budgets, and
# output schemas against an in-process synthetic provider. Zero network egress.
python -m contextual_orchestrator nim-benchmark --dry-run \
  --pricing-scenario examples/nim_pricing_scenario.json \
  --output-dir benchmark_artifacts

# Live run (CI): the workflow seeds NVIDIA_NIM_API_KEY from the job env into
# the KV (bootstrap transport), then everything resolves via get_credential.
python -m contextual_orchestrator nim-benchmark \
  --max-total-requests 300 --git-sha "$GITHUB_SHA" --workflow-run-id "$GITHUB_RUN_ID"
```

The secret is **never** accepted via argv, printed, or serialized; the artifact
writer refuses to write any file containing the resolved credential value.

## Dynamic catalog + all-modality capability probes

- Models come from the OpenAI-compatible `GET /v1/models` — no hard-coded
  inventory. The parsed catalog is deduplicated, **sorted by model id** (immune
  to provider response-order drift), and keeps machine-readable
  `duplicate_model_ids` / `invalid_entries` hygiene lists.
- Every discovered model is probed, under bounded concurrency
  (`--probe-concurrency`) and one shared hard request budget
  (`--max-total-requests`), for **every contract NIM can host**:

  | probe | endpoint |
  | --- | --- |
  | `chat_completion` | `POST /chat/completions` |
  | `text_completion` | `POST /completions` |
  | `response_generation` | `POST /responses` |
  | `text_embedding` | `POST /embeddings` |
  | `image_understanding` | chat with an `image_url` part (tiny PNG data URI) |
  | `video_understanding` | chat with a `video_url` part (tiny MP4 stub) |
  | `audio_understanding` | chat with an omni-style `input_audio` part (tiny WAV) |
  | `audio_transcription` | `POST /audio/transcriptions` (multipart WAV) |
  | `audio_speech` | `POST /audio/speech` (binary success contract) |

- Per-probe outcomes: `supported`, `unsupported`, `rate_limited`, `timeout`,
  `unavailable`, `failed`, `malformed_response`, or `skipped` — a skipped probe
  always carries a machine-readable reason (e.g. `request_budget_exhausted`).
  HTTP 401 anywhere fails the whole run closed (`BenchmarkAuthError`).
- Model-level classification is derived, never separately probed:
  `omni_capable` (chat + image + audio understanding), `vision_chat_capable`,
  `chat_capable`, `embedding_only`, `completion_only`, `responses_only`,
  `audio_only`, `unsupported_for_contract`, `rate_limited`, `unavailable`,
  `failed`, `skipped`. Media probes use tiny synthetic assets; only HTTP 200
  counts as support, so a model that rejects the stub is honestly classified
  unsupported for that contract.

## Fair comparison contract

All compared systems share the same task set (the **locked** manifest split),
scorers, timeout, output-token budget, and the five-step workflow-depth cap
(Conductor/TRINITY bound). Compared systems:

1. per-worker **direct** baselines (no orchestration) — also the source of the
   **best single worker in hindsight** reference (post-hoc argmax; no extra calls);
2. deterministic low-latency **`route_once`**;
3. bounded deep **`conduct`** (template plan, ≤ 5 steps, observed call counts
   recorded per cell — nothing assumes every task needs all workers);
4. **cheapest-eligible-worker** under the explicit pricing scenario (skipped
   with a machine-readable reason when no scenario prices any worker).

Every policy × task cell records: scorer name+version and score,
success/failure/timeout, end-to-end latency (provider latency is recorded as
`null` — not observable through the OpenAI-compatible body — never fabricated),
call count and workflow depth, prompt/completion/total tokens with an honest
`token_usage_source` (`reported` vs `estimated`), `actual_cost_usd` (0 while
the hosted catalog is free to the caller), `hypothetical_cost_usd`, the exact
model/role/step assignment, and a SHA-256 of the raw answer (never the raw
prompt or any secret).

### Cost honesty

`actual_cost_usd` and `hypothetical_cost_usd` never mix. Hypothetical cost is
computed **only** from an explicit versioned pricing scenario
(`examples/nim_pricing_scenario.json` is a schema demo marked
`example_unreviewed`); any model the scenario does not price makes the whole
cell `"unknown"`. No rate is ever invented.

### Statistics

- Paired task-level **bootstrap** comparisons (percentile 95% CI, seeded,
  2000 resamples) between the headline policies — uncertainty is reported,
  never just means.
- **Pareto frontiers** for quality-vs-latency and quality-vs-hypothetical-cost
  (policies with unknown cost are excluded *and listed*).

### Leakage prevention

The manifest validator rejects any task whose registered scorer would award
the prompt text itself a point — expected answers and rubrics never reach
model prompts. The `exploratory` split is for tuning only and never enters the
locked evaluation.

## Fail-closed contract

A run aborts (exit 1, no artifacts) when: the KV credential is missing for a
non-dry run; catalog discovery is incomplete (non-JSON, wrong shape, zero
usable models, HTTP/network failure); the planned evaluation exceeds the
remaining request budget (pre-flight) or the budget is exhausted mid-run; live
provenance (`--git-sha`, `--workflow-run-id`) is absent; the report fails
schema validation; or an artifact would contain the provider secret.

## Provenance + artifacts

`benchmark_report.json` (schema-validated), `benchmark_cells.csv`, and
`benchmark_summary.md` are written per run and uploaded by the workflow with
90-day retention. Provenance records: run mode, git SHA, workflow run id,
catalog-snapshot SHA-256, task-manifest SHA-256, pricing-scenario SHA-256, and
every benchmark parameter (including the seed and the depth cap). Dry-run
artifacts are byte-for-byte deterministic (fixed clock, zeroed probe timers,
seeded statistics) so schema regressions show up as diffs.

## Workflow

`.github/workflows/nim-benchmark.yml`: manual dispatch (defaults to dry run;
live runs are an explicit opt-in with an explicit budget) plus a conservative
monthly scheduled live run (300-request hard cap). Single-flight concurrency
(`group: nim-benchmark`, no cancellation), 60-minute job timeout, pinned
actions, secret exposed only as env to the run step. The benchmark never
merges, releases, or rewrites production configuration; a reviewed follow-up
PR may update recommended routing policy only when the evidence crosses an
explicit decision threshold.

## Method grounding

Honest, multi-metric, uncertainty-carrying reporting follows HELM (Liang et
al., arXiv:2211.09110 — see `docs/papers/README.md`); the cost/quality routing
frame follows FrugalGPT (2305.05176), RouteLLM (2406.18665), and Hybrid LLM
(2404.14618), already vendored in `docs/papers/`. This benchmark exists to
supply the evaluation set + logs that `docs/architecture.md` requires **before**
any learned policy replaces the deterministic heuristic.
