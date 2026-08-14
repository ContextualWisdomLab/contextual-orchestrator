# Local MLX verifier routing calibration — 2026-08-14

Status: routing evidence; not a claim of unbiased judgment or production IRT
validity.

## Execution contract

Every judge call used the existing path:

`fast-mlsirm.ContextualOrchestratorJudge -> contextual-orchestrator._FastMLSIJudgeAdapter -> TaskOrchestrator -> ModelClient -> mlx-lm`

The initial live probe used `mlx://127.0.0.1:8080/v1`, temperature `0`,
disabled MLX thinking, `max_output_tokens=128`, zero local retries, two
criteria, three ordered categories, and the implicit `binary_threshold` method.
The later dedicated-port follow-ups in this document use
`mlx://127.0.0.1:18083/v1`; the port change is intentional because the 8080
listener was not an exclusive MLX owner. Each result therefore produced a
two-column polytomous row when all four Boolean boundary calls were valid. The
safe and unsafe cases were judged separately; no retry, keyword matching,
positional inference, category synthesis, or silent repair was used. A parse or
monotonicity failure remains a failed comparison.

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

## Local readiness registry guard — 2026-08-14

The gateway readiness path now verifies the local `/v1/models` registry contains
the configured model before sending its bounded one-token completion probe. This
keeps a port-owner/configuration mismatch fail-closed before an expensive judge
run while preserving the existing no-retry and bounded-timeout contract. The
focused local transport suite passed `41` tests; the complete contextual suite
passed `387` tests. Against the dedicated MLX listener on port `18083`, the
registry-plus-completion probe returned `ready` in `5.48 s` with 15 provider
tokens.

## Dedicated-port 3B non-ceiling follow-up — 2026-08-14

The same held-out control design was rerun with
`mlx-community/llama-3.2-3b-instruct-4bit` on the dedicated loopback listener
`mlx://127.0.0.1:18083/v1`. The exact route remained
`ContextualOrchestratorJudge -> _FastMLSIJudgeAdapter -> TaskOrchestrator ->
ModelClient -> mlx-lm`; contextual-orchestrator was at `62100d3` and
fast-mlsirm at `57795b1`. Temperature was `0`, thinking was disabled,
`max_output_tokens=128`, local/server concurrency was `4`, and the implicit
`binary_threshold` method produced two anchored criterion items with three
ordered categories.

Two held-out groups were evaluated: a partial K=`3` answer with the correct
option first and an unsupported K=`7` answer with the correct option last. Each
group included baseline, option-only, shuffled-option, and
distractor-replacement variants. The run produced 8 outcomes (64 Boolean
boundary calls) in `67.454 s`: 5 passed and 3 strict `JudgeFormatError`
failures caused by non-monotone thresholds. Every valid row was saturated at
`[2,2]`; category occupancy was `{evidence_quality: {0:0, 1:0, 2:5},
risk_awareness: {0:0, 1:0, 2:5}}`, and conditional gold exact agreement was
`0/5`. The four partial K=`3` variants over-scored the gold `[1,1]`, while the
unsupported K=`7` option-only variant over-scored the gold `[0,0]`; the other
three K=`7` variants failed closed.

This is model-stratified saturation and reliability evidence, not a causal
positive-option-count estimate. Preserve all five valid rows and all three
failures in the denominator; keep 3B out of the verifier role until it passes
non-ceiling held-out gold calibration with bounded failure rates. No keyword
matching, retry, positional inference, category repair, or silent drop was
used.

## K-stratified report follow-up — 2026-08-14

The updated fast-mlsirm calibration report was exercised against the same
dedicated Gemma 4 e4b listener at `mlx://127.0.0.1:18083/v1`, using contextual
head `b30697d06d1160b6a892fbdd26112316fb53a202` and fast head
`22596ab714e20e9b4d1aa7f50f621deec010f622`. The route remained
`ContextualOrchestratorJudge -> _FastMLSIJudgeAdapter -> TaskOrchestrator ->
ModelClient -> mlx-lm`; temperature was `0`, thinking was disabled,
`max_output_tokens=128`, local/server concurrency was `4`, and the implicit
`binary_threshold` method produced two criterion columns.

Four held-out groups crossed K=`3` and K=`5` for partial `[1,1]` and
unsupported `[0,0]` gold anchors. Baseline, option-only, shuffled-option, and
distractor-replacement variants produced 16 valid outcomes and 64 boundary
calls in `221.505 s`; no provider, parse, IRT, or monotonicity failure occurred.
Conditional gold exact agreement was `7/16` (`43.75%`). Aggregate category
occupancy was evidence-quality `{0:8,1:0,2:8}` and risk-awareness
`{0:7,1:1,2:8}`. All partial rows were over-scored `[2,2]`; unsupported rows
were correctly `[0,0]` except the K=`5` shuffled control, which became
`[0,1]` (`score_delta=+0.25`).

The new report exposed these strata directly: K=`3` and K=`5`, each variant's
status count, mean score, category occupancy, gold agreement, and an explicit
zero unstratified denominator. This is descriptive control evidence, not a
causal positive-K estimate; the K=`5` shuffled shift strengthens the requirement
to balance option position/order and retain non-ceiling human/gold anchors
before verifier promotion or polytomous IRT interpretation. No keyword
matching, retry, positional inference, category repair, or silent drop was
used.

## HTTP gateway smoke and overload boundary — 2026-08-14

The dedicated worker was exposed through a live contextual-orchestrator HTTP
gateway on `127.0.0.1:18084`, authenticated with an explicit local test token,
and configured with `max_concurrent_runs=4`. The gateway agent targeted
`mlx://127.0.0.1:18083/v1` and the Gemma 4 e4b model. A single OpenAI-compatible
`/v1/chat/completions` request returned `200`, answer `OK`, and provider usage
`10/2/12` prompt/completion/total tokens.

At the configured concurrency, four simultaneous HTTP requests completed
successfully with four distinct completion IDs; latency was p50 `1449.28 ms`
and maximum `1459.57 ms`. A fifth simultaneous request was rejected immediately
with structured `503 concurrency_limit_exceeded`. This is the intended bounded
overload behavior: it preserves an explicit failure rather than creating an
unbounded queue or silently dropping a judge item.

The first smoke exposed a response-ID collision because completion IDs used the
current millisecond. The response, buffered-stream, and direct-stream paths now
share a UUID-based ID generator; the focused streaming suite passed `7` tests.
No keyword matching, retry, positional inference, category repair, or silent
drop was introduced.

## Warm gateway throughput recheck — 2026-08-14T09:52Z

The existing dedicated worker (`mlx://127.0.0.1:18083/v1`, Gemma 4 e4b) and
authenticated gateway (`127.0.0.1:18084`, `max_concurrent_runs=4`) were
re-measured with the same short `Reply with exactly OK.` request. Every `200`
response returned a unique completion ID and usage `10/2/12`.

| simultaneous requests | result | wave time | successful p50 | max successful |
| ---: | --- | ---: | ---: | ---: |
| 1 | `1/1` HTTP 200 | `307.89 ms` | `306.94 ms` | `306.94 ms` |
| 2 | `2/2` HTTP 200 | `327.23 ms` | `326.96 ms` | `326.99 ms` |
| 4 | `4/4` HTTP 200 | `579.67 ms` | `576.15 ms` | `579.27 ms` |
| 5 | `4/5` HTTP 200, `1` HTTP 503 `concurrency_limit_exceeded` | `590.70 ms` | `587.53 ms` | `590.12 ms` |

This warm sample supports the existing admission bound of four for this
server/model configuration: the fifth request is rejected explicitly and does
not create queue growth or silent loss. It is throughput evidence only, not a
judge-quality or general hardware-optimality claim; no concurrency default was
changed from this one workload recheck.

## Cross-repository judge-contract regression — 2026-08-14

The live smoke below was executed at contextual-orchestrator `a07c11f` with
fast-mlsirm `3d42c0b`. The redaction-only fast follow-up `a536292`, checked
through the current contextual working tree `a9278d1`, also passed the exact
interpreter preflight with `available=true`, fast version `0.7.0`, and matching
`contextual-orchestrator-contract-v1` package-root exports. Before the
fast export fix, `ContextualOrchestratorJudge` itself could be imported and
called, but the same preflight returned `ImportError` because the package root
did not expose the versioned contract constant. That was an integration defect,
not evidence that the judge was unavailable; the constant is now public and a
fast-mlsirm regression test covers the export.

The repaired route was smoke-tested against the dedicated Gemma 4 e4b listener
with temperature `0`, thinking disabled, `max_output_tokens=128`, two criteria,
three ordered categories, and `cumulative_threshold`. A partial answer returned
valid categories `{evidence_quality: 0, risk_awareness: 0}`, row `[0,0]`, score
`0`, and `accepted=false` in `21.205 s` with `641` provider tokens; an
unsupported answer returned the same row and score in `2.940 s` with `607`
provider tokens. These are descriptive integration observations only: the
semantic cases were not gold-calibrated, and no keyword matching, retry,
positional inference, category repair, or silent drop was used.

## Current exact-head polytomous judge smoke — 2026-08-14

The current linked heads (`contextual-orchestrator` `474b667b576f8a019db51d892db41a605e3a0a85`,
`fast-mlsirm` `a536292cc05bd16287dab16431bc0c3fef74ba81`) were exercised against
the dedicated Gemma 4 e4b listener at `mlx://127.0.0.1:18083/v1`. The exact
route was `ContextualOrchestratorJudge -> _FastMLSIJudgeAdapter ->
TaskOrchestrator -> ModelClient -> mlx-lm`; two criteria, three anchored
categories, and four independent `binary_threshold` calls completed in
`19.354 s` with `2,163` provider tokens. The result was score `1.0`,
`accepted=true`, criterion categories `{evidence_quality: 2, risk_awareness: 2}`,
and the required two-column polytomous IRT row `[2,2]`.

This is current-head integration and contract evidence, not semantic quality
promotion evidence. It confirms that the IRT output remains multi-item and
that the latest redaction-only fast-mlsirm change does not break the real
contextual route. No keyword matching, positional inference, category repair,
retry, scalar synthesis, or silent drop was used; balanced held-out gold and
perturbation calibration remain required.

## Current exact-head K-stratified direct and threshold calibration — 2026-08-14

The current local pair (`contextual-orchestrator` `bc882c0e937bef1312b2e499bfb1fdd1b9076df5`,
`fast-mlsirm` `a536292cc05bd16287dab16431bc0c3fef74ba81`) was exercised against
the dedicated Gemma 4 e4b listener at `mlx://127.0.0.1:18083/v1`. Every call
used `ContextualOrchestratorJudge -> _FastMLSIJudgeAdapter -> TaskOrchestrator
-> ModelClient -> mlx-lm`, two criteria, explicit anchored categories, and no
keyword, positional, retry, category-repair, or silent-drop fallback.

The explicit `direct` calibration sweep completed all 12 outcomes:

| case | K | status | score | accepted | row | latency | total tokens |
| --- | ---: | --- | ---: | --- | --- | ---: | ---: |
| safe | 2 | complete | 1.0 | yes | `[1,1]` | 3.827 s | 701 |
| safe | 3 | complete | 1.0 | yes | `[2,2]` | 3.191 s | 729 |
| safe | 5 | complete | 1.0 | yes | `[4,4]` | 3.632 s | 772 |
| safe | 7 | complete | 1.0 | yes | `[6,6]` | 3.453 s | 801 |
| unsafe | 2/3/5/7 | complete | 0.0 | no | `[0,0]` | 2.377–2.896 s | 670–769 |
| partial | 2 | complete | 0.0 | no | `[0,0]` | 3.717 s | 714 |
| partial | 3 | complete | 0.5 | no | `[1,1]` | 3.361 s | 727 |
| partial | 5 | complete | 0.5 | no | `[2,2]` | 2.862 s | 739 |
| partial | 7 | complete | 0.5 | no | `[3,3]` | 2.967 s | 781 |

This sample does not show monotone positive drift as K grows: safe and unsafe
were invariant, while partial changed once from K=2 to K=3 and then remained
stable. It is category-count sensitivity, not proof of neutrality or of the
user's positive-bias hypothesis.

The production-default `binary_threshold` comparison completed K=`3` for all
three cases and K=`5` for unsafe; safe K=`5` and partial K=`5` failed closed
after all 8 boundary calls parsed but produced non-monotone vectors:

| case | K | status | score/row | calls | latency | total tokens |
| --- | ---: | --- | --- | ---: | ---: | ---: |
| safe | 3 | complete | 1.0 / `[2,2]` | 4 | 5.395 s | 2,142 |
| safe | 5 | failed closed, `non_monotone` | no IRT row | 8 | 8.263 s | 4,384 |
| unsafe | 3 | complete | 0.0 / `[0,0]` | 4 | 4.237 s | 2,049 |
| unsafe | 5 | complete | 0.0 / `[0,0]` | 8 | 7.081 s | 4,163 |
| partial | 3 | complete | 0.0 / `[0,0]` | 4 | 4.145 s | 2,018 |
| partial | 5 | failed closed, `non_monotone` | no IRT row | 8 | 9.140 s | 4,167 |

The two K=`5` failures had `parse_status=passed`, `completed_call_count=8`,
and `failed_call_count=0`; they are semantic ordinal failures, not transport
failures. Keep them in the denominator and do not repair them into an IRT row.
The binary path therefore remains the safer contract boundary but is not yet a
quality or unbiased-IRT claim; larger balanced gold, category occupancy, and
perturbation calibration remain required.

## Current exact-head gateway and integrated Judge recheck — 2026-08-14

The current source pair (`contextual-orchestrator`
`8f922d806336fd41d8fd73585a7c225784249332`, `fast-mlsirm`
`47c5fbdde98b3550fe319d1de238a32cbaec8a1f`) was rechecked against the live
Gemma 4 e4b listener (`mlx://127.0.0.1:18083/v1`, prompt/decode concurrency
4) and authenticated gateway (`127.0.0.1:18084`, maximum concurrent runs 4).

| concurrent width | statuses | wave | p50 successful | unique IDs |
| ---: | --- | ---: | ---: | ---: |
| 1 | `1x200` | 2,170.42 ms | 2,170.42 ms | 1 |
| 2 | `2x200` | 341.35 ms | 341.31 ms | 2 |
| 4 | `4x200` | 591.34 ms | 588.64 ms | 4 |
| 5 | `4x200, 1x503` | 595.39 ms | 592.41 ms | 4 |

The first width-1 request is a cold/warm-up observation; subsequent widths are
not averaged with it. Successful short responses reported 10 prompt, 2
completion, and 12 total tokens. The fifth request remained an explicit
`concurrency_limit_exceeded` overload rather than queue growth or silent loss.

The same exact-head pair then ran one real two-criterion anchored
`binary_threshold` Judge through
`ContextualOrchestratorJudge -> _FastMLSIJudgeAdapter -> TaskOrchestrator ->
ModelClient -> mlx-lm`. Four boundary calls completed in 4.949 s with 1,923
provider tokens, score `1.0`, accepted `true`, categories
`{evidence_completeness: 2, release_safety: 2}`, and IRT row `[2,2]`.
This is route/contract and throughput evidence, not semantic quality or bias
promotion evidence; the K-stratified failures and balanced gold requirements
remain unchanged.

## Direct MLX versus gateway warm comparison — 2026-08-14T10:49:55Z

The dedicated worker and gateway were re-measured with the same short request
(`Reply with exactly OK.`), after one warm-up request per endpoint. The direct
worker used `http://127.0.0.1:18083/v1/chat/completions`; the gateway used the
authenticated `http://127.0.0.1:18084/v1/chat/completions`. Both returned unique
completion IDs for successful responses.

| path | width | statuses | wave | successful p50 | max successful |
| --- | ---: | --- | ---: | ---: | ---: |
| direct MLX | 1 | `1x200` | 202.69 ms | 202.52 ms | 202.52 ms |
| gateway | 1 | `1x200` | 204.12 ms | 203.96 ms | 203.96 ms |
| direct MLX | 2 | `2x200` | 323.97 ms | 323.74 ms | 323.74 ms |
| gateway | 2 | `2x200` | 321.26 ms | 321.01 ms | 321.13 ms |
| direct MLX | 4 | `4x200` | 596.54 ms | 593.77 ms | 596.12 ms |
| gateway | 4 | `4x200` | 562.70 ms | 559.07 ms | 562.18 ms |
| direct MLX | 5 | `5x200` | 899.16 ms | 837.65 ms | 898.60 ms |
| gateway | 5 | `4x200, 1x503` | 564.28 ms | 560.04 ms | 563.75 ms |

At widths one through four, gateway latency was within this small warm-sample
measurement variation of direct MLX; there is no evidence that the gateway
should be bypassed for performance. Direct width five completed by queueing
against the worker's four-request configuration and took substantially longer,
while the gateway preserved the explicit four-request admission bound and
rejected the fifth request. Keep the bound at four for this model/server pair;
increasing it would hide queue latency rather than improve throughput. This is
transport evidence only and does not alter the semantic calibration or IRT
acceptance boundary.

## Current exact-head integrated Judge recheck — 2026-08-14T10:53:08Z

The current source pair (`contextual-orchestrator` `070d9297675ebc45e821808b532fb6af809cbbf2`,
`fast-mlsirm` `8f5d85ae58d462a552831c238fc3967476589934`) was run through the
same dedicated Gemma 4 e4b worker and authenticated gateway. The route remained
`ContextualOrchestratorJudge -> _FastMLSIJudgeAdapter -> TaskOrchestrator ->
ModelClient -> mlx-lm`, with two anchored criteria, three categories, and the
implicit `binary_threshold` method.

All four boundary calls completed in `3.731 s` with `2,015` provider tokens
(`1,860` prompt and `155` completion). The result was score `1.0`,
`accepted=true`, criterion categories
`{evidence_completeness: 2, release_safety: 2}`, trace step count `4`, and
the required multi-item IRT row `[2,2]`. This confirms the current
cross-repository transport and IRT shape after the benchmark/ADR documentation
push; it is not semantic quality, bias, or production IRT promotion evidence.
Balanced non-ceiling gold, perturbation stability, category occupancy, and all
failure denominators remain required.

## Warm direct MLX versus authenticated gateway recheck — 2026-08-14T11:56:58Z

The dedicated Gemma 4 e4b worker and authenticated gateway were re-measured
after one warm-up request per endpoint with the identical short prompt
(`Reply with exactly OK.`), temperature `0`, and `max_tokens=32`. Each width
sent `4 * width` requests; the gateway remained configured with
`max_concurrent_runs=4`.

| path | width | requests/statuses | wave | successful p50 | successful p95 |
| --- | ---: | --- | ---: | ---: | ---: |
| direct MLX | 1 | `4/4 x 200` | 0.837 s | 0.212 s | 0.220 s |
| direct MLX | 2 | `8/8 x 200` | 1.333 s | 0.334 s | 0.348 s |
| direct MLX | 4 | `16/16 x 200` | 2.599 s | 0.672 s | 0.694 s |
| direct MLX | 5 | `20/20 x 200` | 3.535 s | 0.919 s | 0.943 s |
| gateway | 1 | `4/4 x 200` | 0.921 s | 0.233 s | 0.236 s |
| gateway | 2 | `8/8 x 200` | 1.530 s | 0.386 s | 0.392 s |
| gateway | 4 | `16/16 x 200` | 2.560 s | 0.616 s | 0.737 s |
| gateway | 5 | `4/20 x 200`, `16/20 x 503` | 0.806 s | 0.802 s | 0.805 s |

The gateway stays close to direct MLX through width `4` and explicitly rejects
excess admission at width `5`; it does not silently queue, drop, or repair
requests. This is warm transport/admission evidence only. It does not change
the multi-item Judge, semantic calibration, category-occupancy, or IRT
promotion gates, and the rejected requests remain in the overload denominator.
