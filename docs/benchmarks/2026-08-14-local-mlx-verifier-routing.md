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

The exact interpreter used for these runs also passed
`python -m contextual_orchestrator check-fast-mlsirm`, which verified the
fast-mlsirm import, required judge symbols, and
`contextual-orchestrator-contract-v1`. The contextual-orchestrator-only
environment intentionally fails this preflight with `missing_module: numpy`;
that is an integration-environment failure, not a judge result.

A post-preflight warm smoke on the same e4b endpoint completed the four
Boolean boundary calls in `55.31 s`, returned categories
`{evidence_quality: 2, risk_signal: 2}`, score `1.0`, and row `[2,2]` with
`1,921` provider tokens. This is a successful gateway/contract run, but its
latency is high enough that it remains reliability evidence rather than a
promotion or quality claim; cold/warm distributions and held-out calibration
are still required.

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

## Runtime reliability follow-up

The MLX process reported healthy `/health` and `/v1/models` responses while
real completion requests were timing out. Before the graceful restart, the
server had accumulated hundreds of request threads and macOS swap usage was
near capacity; this is a completion-path exhaustion signal, not proof that the
model or TLS stack is broken. After restart, direct e4b and Llama 3B
completions returned `OK`.

The first full e4b judge run after a model switch still failed closed on the
safe case (`2/4` boundary calls completed within a 30-second request budget),
while the following unsafe case completed with polytomous row `[0,1]`. With
e4b warm and a 60-second request budget, the same safe case completed through
the full `fast-mlsirm -> contextual-orchestrator -> mlx-lm` path in `35.86 s`,
returned categories `{evidence_quality: 2, risk_signal: 2}`, and produced row
`[2,2]`. This separates cold-load/request-budget reliability from semantic
judgment evidence; it does not justify retries, keyword matching, or silent
repair.

The gateway now bounds local requests per normalized loopback endpoint,
serializes requests that would switch the loaded model, preserves configured
same-model concurrency, and fails waiters when the request deadline expires.
Regression coverage includes a competing two-model endpoint and the full
contextual suite remains green (`384 passed`). Promotion still requires
separate cold/warm latency distributions, bounded completion success rates,
category occupancy, and balanced semantic calibration before changing the
verifier role.

## Balanced K=3/K=7 edge-position follow-up — 2026-08-14

To test option-count and correct-position effects beyond the earlier K=`3`/K=`5`
smoke, the exact route
`fast-mlsirm.ContextualOrchestratorJudge -> _FastMLSIJudgeAdapter -> TaskOrchestrator -> ModelClient -> mlx-lm`
was run with contextual-orchestrator `d3480cc` and fast-mlsirm `dbbd41d`. The
Gemma 4 e4b worker used temperature `0`, disabled thinking, `max_output_tokens=128`,
zero retries, `local_concurrency=1`, two criteria, three ordered categories, and
implicit `binary_threshold`. Four held-out case groups crossed K=`3` and K=`7`
with the correct option at the first and last position; each group included
baseline, option-only, shuffled-option, and distractor-replacement variants.

The run produced 16 paired outcomes (64 Boolean boundary calls) in `1,044.7 s`:
11 passed and 5 strict `JudgeFormatError` failures. The 11 valid rows all matched
the supplied gold `[2,2]` (`11/11`) and all observed categories were the maximum
category `2` for both criteria; the five failures remained in the denominator.
Only one case group had a complete baseline/control comparison, with score deltas
`0.0`. This is ceiling-saturated, incomplete calibration evidence: it neither
supports nor rejects a positive option-count bias, and it is not sufficient for
IRT interpretation or verifier promotion. No keyword matching, retry, positional
inference, category repair, or silent drop was used.

## Dedicated-port non-ceiling follow-up — 2026-08-14

The first rerun correctly failed closed before model evaluation because the
temporary script used `http://127.0.0.1` instead of the explicit local-provider
scheme `mlx://127.0.0.1`. A subsequent readiness probe also showed the original
8080 endpoint was unsafe for this machine: an unrelated wildcard listener and
the MLX server shared the port, so `/health` could return 200 while a chat
completion returned zero bytes and timed out. Port 18080 was already occupied
by a Colima SSH forward. The MLX server was therefore restarted on dedicated
loopback port 18083 with prompt/decode concurrency 4; `ModelClient.probe()`
returned `ready` in `2.54 s` with 15 reported tokens.

Using contextual-orchestrator `63451a0` and fast-mlsirm `3c2fecf`, the exact
route `ContextualOrchestratorJudge -> _FastMLSIJudgeAdapter -> TaskOrchestrator ->
ModelClient -> mlx-lm` evaluated four held-out groups: partial and unsupported
answers at K=`3` and K=`7`, with correct options at the first/last positions and
baseline, option-only, shuffled, and distractor-replacement variants. The
Gemma 4 e4b run used two anchored criteria, category_count=`3`, implicit
`binary_threshold`, gateway/server concurrency 4, and completed 16 outcomes
(128 boundary calls) in `202.781 s`: 15 passed and one strict non-monotone
`JudgeFormatError`.

The 15 valid rows had conditional gold exact agreement `5/15` (`33.3%`).
Evidence-quality occupancy was `{0: 5, 1: 5, 2: 5}`; risk-awareness occupancy
was `{0: 7, 1: 0, 2: 8}`. Partial baseline rows were repeatedly over-scored as
`[2,2]`; option-only controls reduced evidence quality to `1` and raised
unsupported-answer evidence quality from `0` to `1` in both K strata. These
are semantic/control-sensitivity observations, not causal evidence of a
positive K law or IRT readiness. The non-monotone failure and every control
outcome remain in the denominator; no keyword matching, retry, repair,
positional inference, or silent drop was used.
