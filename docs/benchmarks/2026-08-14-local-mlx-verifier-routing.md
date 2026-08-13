# Local MLX verifier routing calibration — 2026-08-14

Status: routing evidence; not a claim of unbiased judgment or production IRT
validity.

## Execution contract

Every judge call used the existing path:

`fast-mlsirm.ContextualOrchestratorJudge -> contextual-orchestrator._FastMLSIJudgeAdapter -> TaskOrchestrator -> ModelClient -> mlx-lm`

The live probe used `mlx://127.0.0.1:8080/v1`, temperature `0`, disabled MLX
thinking, `max_output_tokens=128`, zero local retries, two criteria, three
ordered categories, and the implicit `binary_threshold` method. Each result
therefore produced a two-column polytomous row when all four Boolean boundary
calls were valid. The safe and unsafe cases were judged separately; no retry,
keyword matching, positional inference, category synthesis, or silent repair
was used. A parse or monotonicity failure remains a failed comparison.

## Same-route model comparison

| model | safe result | unsafe result | latency | provider tokens |
| --- | --- | --- | ---:| ---:|
| Llama 3B | passed, score `1.0`, row `[2,2]` | failed closed, `non_monotone`, `4/4` calls parsed | `6.82 s` / `2.56 s` | `1,855` / `1,854` |
| Gemma 4 e4b | passed, score `1.0`, row `[2,2]` | passed, score `0.5`, row `[1,1]` | `7.73 s` / `4.87 s` | `1,836` / `1,828` |
| Gemma 4 31B | failed closed, boundary failure, `1/4` calls completed | passed, score `0.25`, row `[1,0]` | `96.93 s` / `52.38 s` | `481` / `1,871` |
| DeepSeek R1 Qwen 32B | failed closed, boundary failure, `0/4` calls completed | failed closed, boundary failure, `0/4` calls completed | `100.04 s` / `100.06 s` | `0` / `0` |

The e4b candidate is the best current verifier primary for this workload:
both balanced semantic cases returned bounded structured results, while the
larger candidates failed or timed out and the 3B case produced a non-monotone
unsafe comparison. This is a role-eligibility and service-reliability result,
not a quality ranking or proof that e4b is unbiased. The 3B remains an eligible
lower-priority fallback candidate for future calibration, and all four models
remain discoverable for non-verifier roles.

## Routing decision

The local registry excludes Gemma 4 31B, DeepSeek R1 Qwen 32B, and Llama 1B
from the `verifier` role. The 1B exclusion remains based on the earlier
all-boundary structured-output failure. Gemma 4 e4b is now selected as the
verifier primary by the existing priority/exclusion policy; no provider is
removed or silently disabled. Promotion requires a larger balanced held-out
calibration set with gold recall, false-positive/false-negative rates,
category occupancy, option-count/order perturbations, and non-ceiling rows.

This evidence expands the active Goal and ADR acceptance boundary: model
selection must be rechecked after prompt, server, model, timeout, or output
budget changes, and a fast model cannot be promoted solely for throughput.
