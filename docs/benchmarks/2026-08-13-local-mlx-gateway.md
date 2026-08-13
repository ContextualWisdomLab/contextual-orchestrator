# Local MLX gateway and fast-mlsirm judge — 2026-08-13

Status: integration evidence, not a quality or bias claim. The run used one
cached local model and one fixed task; broader paired calibration remains
required.

## Execution contract

The measured judge path was:

`fast-mlsirm.ContextualOrchestratorJudge -> contextual-orchestrator._FastMLSIJudgeAdapter -> ModelClient -> mlx-lm`

The MLX server was already listening on `mlx://127.0.0.1:8080/v1` and exposed
`mlx-community/llama-3.2-3b-instruct-4bit`. The run used temperature `0`,
`max_output_tokens=192` for workflow steps, disabled MLX thinking, zero
retries, and two rubric criteria. The fast-mlsirm source checkout ran in its
Python 3.12 environment (`fast-mlsirm 0.7.0`, NumPy 2.5.1); the contextual
source checkout was placed on `PYTHONPATH`. No keyword, lexical, positional,
silent-drop, or malformed-output repair was used.

The contextual-orchestrator project environment alone does not install
fast-mlsirm's NumPy dependency. Running the same command with that environment
therefore failed closed with `fast-mlsirm judge could not be loaded`; this is a
dependency-boundary finding, not a successful judge result. The reproducible
integration command uses fast-mlsirm's declared runtime environment so the
injected judge is actually available.

## Measurements

| path | elapsed | provider usage | result |
| --- | ---: | ---: | --- |
| direct `route` worker | 23.002 s | 50 prompt + 48 completion = 98 | one trace step; route accepted by contract |
| isolated fast-mlsirm judge | 3.977 s | 392 prompt + 59 completion = 451 | strict JSON parsed; `accepted=true`; judge mode `route` |
| four-step `conduct` plus judge | 43.915 s | workflow 2,404 + judge 676 = 3,080 | four trace steps; fast judge parsed; `accepted=false` with evidence-based rationale; judge mode `route` |

After the contract fix, the verification metadata also carries the two
criterion scores and `judge_irt_row` as a dichotomous two-item row. The row is
derived by fast-mlsirm's `to_irt_row`, not by lexical matching or a gateway
threshold heuristic.

The four workflow step latencies were 10.089 s, 10.153 s, 8.697 s, and
10.225 s. The judge used a single bounded route call rather than recursively
starting another conduct workflow. The final rejection is a model-evaluation
result, not a keyword rule; malformed or unavailable judge output would remain
fail-closed.

### Current-server polytomous judge probe

On the same day, a fresh live probe used
`ContextualOrchestratorJudge -> contextual-orchestrator -> mlx-lm` with the
3B Llama model as judge, temperature `0`, disabled thinking, two criteria,
`max_output_tokens=256`, and one strict call at each K. Every call parsed and
produced a two-item row; no keyword, lexical, positional, or silent-drop
fallback was used.

| K | score | accepted | criterion categories (`evidence_quality`, `risk_awareness`) | IRT row | total tokens | seconds |
|---:|---:|:---:|:---:|:---:|---:|---:|
| 2 | `0.5000` | no | `(1, 0)` | `(1, 0)` | 594 | 8.147 |
| 3 | `0.5000` | no | `(2, 0)` | `(2, 0)` | 600 | 3.972 |
| 5 | `0.5000` | no | `(4, 0)` | `(4, 0)` | 606 | 4.220 |
| 7 | `0.6667` | no | `(6, 2)` | `(6, 2)` | 612 | 4.122 |

The criterion-level movement and K=7 score increase are fresh evidence of
category-count sensitivity, not proof of a universal positive-bias law. The
rows pass only the two-dimensional response-shape contract; one person is
insufficient for `validate_irt_experiment_readiness` or any IRT fit. The
result is therefore retained as a calibration observation, with K, method,
trace, usage, parse status, and readiness status kept separate.

## Additional local model and batch-throughput probe

Using the same loopback `mlx-lm` server, temperature `0`, disabled thinking,
one fixed deployment-risk prompt, and `max_tokens=96`, three cached models
returned valid Chat Completions after their load sample. The measured warm
latencies (three sequential requests; the first load sample is excluded) were:

| model | prompt tokens | completion tokens | warm seconds | finish |
| --- | ---: | ---: | ---: | --- |
| `mlx-community/llama-3.2-1b-instruct-4bit` | 65 | 38 | `1.557, 2.120, 1.728` | stop |
| `mlx-community/llama-3.2-3b-instruct-4bit` | 65 | 27 | `2.211, 2.013, 1.820` | stop |
| `mlx-community/gemma-4-e4b-it-4bit` | 37 | 23 | `2.811, 2.267, 2.106` | stop |

This is a transport/performance probe only; it is not a quality ranking. A
separate eight-request 3B local batch through `ModelClient.batch_chat` measured
the explicit concurrency knob:

| `local_concurrency` | elapsed seconds | requests/second | non-empty outputs |
| ---: | ---: | ---: | ---: |
| 1 | `18.547` | `0.431` | `8/8` |
| 2 | `8.140` | `0.983` | `8/8` |
| 4 | `8.108` | `0.987` | `8/8` |

This was an earlier eight-request snapshot. It is retained as historical
evidence, not as a universal tuning result: the later repeated probe below
used different request cardinality and warm-cache state.

### Repeated warm-cache concurrency probe

The follow-up used two trials per concurrency after one warm-up request per
model, temperature `0`, thinking disabled, `max_output_tokens=32`, and unique
short prompts. The 3B run used 16 requests; the 1B and Gemma 4B runs used
eight. Every cell completed with non-empty content for every request.

| model | requests | c=1 median seconds (req/s) | c=2 median seconds (req/s) | c=4 median seconds (req/s) | c=8 median seconds (req/s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `llama-3.2-3b-instruct-4bit` | 16 | `25.585` (`0.625`) | `15.139` (`1.057`) | `10.956` (`1.460`) | `7.928` (`2.018`) |
| `llama-3.2-1b-instruct-4bit` | 8 | `2.825` (`2.832`) | — | `1.631` (`4.906`) | `1.524` (`5.251`) |
| `gemma-4-e4b-it-4bit` | 8 | `7.765` (`1.030`) | — | `5.003` (`1.599`) | `3.654` (`2.189`) |

For this running mlx-lm service, `local_concurrency=8` is the fastest tested
batch setting across all three models. Keep interactive route/conduct paths
sequential and keep the library default at `1`; latency-tolerant batch callers
may start at `--local-concurrency 8` (or the equivalent constructor value),
then re-measure after changing the model, server flags, prompt size, or device
memory pressure. This is still a throughput/transport result, not a quality
ranking.

## IRT boundary

The judge received two criteria, so its result can produce multiple
dichotomous items through `LLMJudgeResult.to_irt_row(item_type="dichotomous")`.
Explicit category-count runs must use the polytomous path and produce one
category item per criterion; a scalar or one-item row is rejected. These
measurements do not claim that the two-item smoke output is sufficient for IRT
estimation. Public fast-mlsirm fitters now enforce the same multi-item boundary,
while low-level diagnostic kernels retain their documented single-item use.

## Interpretation and next gate

The local 3B model is usable through the gateway after adapter-contract and
prompt-schema fixes, but it is latency-heavy for a four-step workflow and
structured-output reliability must remain in the denominator. Next calibration
should repeat balanced held-out cases across model size, category count,
option order, framing, direct versus cumulative-threshold methods, parse
status, and token/latency usage. No single K or this smoke run establishes a
universal positive-bias law.

Related decisions: [ADR-0001](../planning/adrs/0001-fail-closed-model-judgment.md),
[ADR-0002](../planning/adrs/0002-explicit-local-mlx-evaluation.md),
[ADR-0005](../planning/adrs/0005-irt-response-matrix-contract.md), and
[ADR-0006](../planning/adrs/0006-polytomous-llm-judge-bias-calibration.md).
