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
