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

### Live cumulative-threshold semantic spot-check — 2026-08-13

A fresh two-criterion call used the same strict gateway path with
`category_count=5` and `category_method="cumulative_threshold"`. The answer
explicitly described canary rollout, monitoring, independent review, and
rollback rehearsal. The response parsed successfully and produced the valid
two-item polytomous row `(4, 0)`, with score `0.5), one trace step, and
`625` total provider tokens; the judge assigned
`evidence_quality=4` and `risk_awareness=0`.

This is a semantic calibration miss, not a parser or transport failure:
structured output can be valid while an item-level judgment under-recognizes
evidence present in the answer. No keyword, lexical, positional, or
silent-drop repair is allowed. The result must remain in the calibration
denominator and be addressed with balanced held-out cases and human/gold
anchors before any quality or IRT interpretation.

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

For the three-model comparison, `local_concurrency=8` is the fastest tested
cross-model setting. Keep interactive route/conduct paths sequential and keep
the library default at `1`; latency-tolerant batch callers should still
measure the target model before selecting a larger value.

### Current 3B saturation probe

A follow-up warm-cache probe on the same running service used the 3B model,
temperature `0`, disabled thinking, and short unique prompts. All requests
returned non-empty content. The 16-request trial compared concurrency through
`16`; the 32-request trial tested the higher settings after the c=16 result
was fastest.

| requests | max output tokens | `local_concurrency` | elapsed seconds | requests/second | non-empty |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 16 | 24 | 1 | `4.847` | `3.301` | `16/16` |
| 16 | 24 | 2 | `5.467` | `2.927` | `16/16` |
| 16 | 24 | 4 | `3.373` | `4.744` | `16/16` |
| 16 | 24 | 8 | `2.757` | `5.804` | `16/16` |
| 16 | 24 | 16 | `2.344` | `6.827` | `16/16` |
| 32 | 16 | 16 | `5.123` | `6.246` | `32/32` |
| 32 | 16 | 24 | `6.599` | `4.849` | `32/32` |
| 32 | 16 | 32 | `6.235` | `5.132` | `32/32` |

For this specific 3B workload, `local_concurrency=16` is the best measured
setting; raising it to `24` or `32` reduced throughput. This is a bounded
transport result, not a universal hardware optimum or a quality ranking.
Use `--local-concurrency 16` only for latency-tolerant 3B batches after a
warm-cache check, and re-measure after changing the model, server flags,
prompt/output budgets, or device memory pressure.

### 32-request saturation boundary

The same warm service was probed again with 32 requests, the 3B model,
temperature `0`, disabled thinking, unique short prompts, and
`max_output_tokens=16`. All completed settings returned non-empty content;
`c=64` did not complete within the client timeout (`TimeoutError: [Errno 60]`)
even though the loopback `/v1/models` health request remained HTTP 200 after
the probe.

| `local_concurrency` | elapsed seconds | requests/second | non-empty |
| ---: | ---: | ---: | ---: |
| 1 | `18.117` | `1.766` | `32/32` |
| 4 | `11.359` | `2.817` | `32/32` |
| 8 | `9.966` | `3.211` | `32/32` |
| 16 | `10.301` | `3.106` | `32/32` |
| 24 | `11.375` | `2.813` | `32/32` |
| 32 | `10.231` | `3.128` | `32/32` |
| 48 | `14.530` | `2.202` | `32/32` |
| 64 | timeout | — | not applicable |

This boundary is provider saturation, not a LibreSSL failure: the requests
used loopback `lo0`, and the health endpoint stayed available. For this
short-output workload, `c=8` was the fastest stable setting; `c=48` already
collapsed and `c=64` is not an acceptable default. Failed saturation points
remain recorded rather than being hidden, and callers must re-measure after
changing model, prompt, output budget, server flags, or memory pressure.

### Cost-routing integration smoke

After the default batch-backend fix, an eight-request run through
`CostRoutingCoordinator.submit_batch()` and `retrieve_batch()` used the same
3B loopback service, `local_concurrency=8`, temperature `0`, disabled thinking,
and `max_output_tokens=16`. It completed in `4.371 s` (`1.830 req/s`), returned
`8/8` non-empty answers, and retained the submitted custom-ID order. This is
integration evidence for the concurrency handoff and result contract, not a
new cross-workload tuning recommendation.

A repeated warm-cache smoke after the circuit-breaker lock fix completed in
`2.267 s` (`3.529 req/s`) with the same `8/8` non-empty, ordered result
contract. The difference from the first smoke is retained as warm-cache and
provider scheduling variance, not as a quality or universal throughput claim.

### 2026-08-14 paired category-method probe

To test the category-count concern against more than one semantic direction, a
fresh two-case probe used the same
`fast-mlsirm.ContextualOrchestratorJudge -> contextual-orchestrator -> mlx-lm`
path, the 3B Llama judge, temperature `0`, disabled thinking, two criteria, and
K in `{2, 5, 7}`. The cases were a release plan with canary monitoring,
independent review, load testing, and rollback rehearsal, and an unsafe plan
that explicitly omitted review and rollback rehearsal. Every valid output was
converted to a two-item polytomous row; malformed and non-monotone outputs were
not repaired.

| case | method | K=2 | K=5 | K=7 |
|---|---|---:|---:|---:|
| safe release | direct score / categories | `0.5 / (1,0)` | `1.0 / (4,4)` | `1.0 / (6,6)` |
| unsafe release | direct score / categories | `0.0 / (0,0)` | `0.0 / (0,0)` | `0.3333 / (2,2)` |
| safe release | cumulative | parse failure | `0.0 / (0,0)` | monotonicity failure |
| unsafe release | cumulative | parse failure | `0.0 / (0,0)` | parse failure |

Direct K-way output therefore moved materially with K for both semantic cases;
this is evidence of category-count sensitivity and a positive drift in this
sample, not a universal law. Cumulative output was not a reliable mitigation
in this run because four of six calls failed strict parsing or monotonicity.

An opt-in `binary_threshold` follow-up asked one Boolean boundary question per
criterion. The safe case failed monotonicity at K=5 and K=7; the unsafe case
parsed at score `0.0`, using 8 calls/`2,606` tokens at K=5 and 12
calls/`3,940` tokens at K=7. This makes the decomposition a useful
fail-closed calibration probe, not a production default or proof of unbiased
judgment. Its call count, latency, usage, semantic recall, and human/gold
agreement must be measured before any default change.

### Binary-threshold bounded concurrency follow-up — 2026-08-14

The fast-mlsirm follow-up at exact commit `61e6be9` now reuses the injected
contextual-orchestrator `client.local_concurrency` for independent binary
boundary calls. It does not add a provider client or fallback transport;
generic injected orchestrators remain sequential, the request order in the
evidence record is deterministic, and all returned boundaries are still
validated for monotonicity before a result is produced. A bounded live probe
used the same 3B loopback path with `local_concurrency=8`:

| case | K | result | elapsed | provider usage |
|---|---:|---|---:|---:|
| safe release | 5 | failed closed: non-monotone thresholds | `3.004 s` | not retained as a valid result |
| safe release | 7 | failed closed: non-monotone thresholds | `7.839 s` | not retained as a valid result |
| unsafe release | 5 | score `0.0`, categories `(0,0)` | `5.756 s` | `8` calls, `2,422` tokens |
| unsafe release | 7 | score `0.0`, categories `(0,0)` | `7.719 s` | `12` calls, `3,620` tokens |

The lower serial time observed in a prior run is not treated as a causal
speedup because provider queue/cache state differed. The controlled contract
evidence is bounded concurrency, stable ordering, preserved trace/usage, and
fail-closed semantics; quality and bias remain unproven. The exact-source fast
tests passed `58`, and the rebuilt full suite passed `3630` with one skip and
two existing warnings.

### Direct K-way default regression probe — 2026-08-14

A second concise semantic probe used the same 3B loopback model, two criteria,
temperature `0`, disabled thinking, and the same
`fast-mlsirm.ContextualOrchestratorJudge -> contextual-orchestrator -> mlx-lm`
route. Every direct response parsed, but the score changed with K even when
the answer and rubric were fixed:

| case | K=2 | K=5 | K=7 |
|---|---:|---:|---:|
| safe evidence | `1.0000` | `1.0000` | `1.0000` |
| unsafe recommendation | `0.0000` | `0.5000` | `0.8333` |
| partial evidence | `0.0000` | `1.0000` | `0.0000` |

The unsafe answer therefore became accepted at K=7 under the `0.7`
threshold, while the partial answer became accepted only at K=5. This is
direct evidence that implicit K-way selection is unsafe for an IRT item
producer; it is not a universal proof of monotone positive bias.

The same safe and unsafe answers were then evaluated with explicit binary
thresholds at K=5 and K=7, using contextual-orchestrator local concurrency
`4`. Both cases returned score `0.0` at both K values. The safe result is a
semantic false negative, so binary decomposition is a fail-closed calibration
guard, not a claim of unbiased or high-recall judgment.

| case | K | elapsed | provider usage |
|---|---:|---:|---:|
| safe | 5 | `4.12 s` | `8` calls, `2,380` tokens |
| safe | 7 | `5.38 s` | `12` calls, `3,617` tokens |
| unsafe | 5 | `3.57 s` | `8` calls, `2,379` tokens |
| unsafe | 7 | `6.23 s` | `12` calls, `3,647` tokens |

The fast adapter now defaults to `category_method="binary_threshold"` when
`category_count` is supplied without an explicit method. Direct K-way output
remains available only as an explicit calibration method; no keyword,
positional, silent-drop, or malformed-output repair was added.

### Actual adapter default smoke — 2026-08-14

The default-selection result was then verified on the real integrated path,
not only with an injected fake transport. Exact fast-mlsirm source was
`9d18f53`, contextual-orchestrator was `a0a354a`, the local 3B Llama worker was
used through `_FastMLSIJudgeAdapter`, and `category_count=5` was supplied with
no `category_method`. The gateway client used `local_concurrency=4`.

| case | result | calls | tokens | seconds |
|---|---|---:|---:|---:|
| unsafe recommendation | score `0.0`, categories `(0,0)`, rejected | 8 | `2,379` | `3.73` |
| safe evidence | failed closed: non-monotone thresholds | 8 | not a valid result | `3.23` |

The unsafe result proves the production adapter selected binary thresholds and
retained the contextual trace. The safe result is a semantic/calibration
failure, not a transport success; it remains in the denominator and is not
coerced into a category. This is integrated contract evidence only, not a
claim of high recall, unbiasedness, or sufficient IRT sample size.

### Structured failure evidence follow-up — 2026-08-14

The same integrated safe-case failure was rerun after fast-mlsirm
`d1eca0c2fed89991e647802f0b27a91f0f6fe2bd` added bounded failure evidence to
`JudgeFormatError`. Through the real `_FastMLSIJudgeAdapter` and the same
contextual-orchestrator MLX route, the failure now records
`semantic_status=non_monotone`, `parse_status=passed`, `8/8` completed calls,
`8` trace steps, `2,639` provider tokens, and `2.88 s` elapsed time. The
evidence is retained as a failed calibration comparison; it is not converted
to an IRT category and is not a semantic-quality score.

### Anchored judge model comparison — 2026-08-14

Using fast-mlsirm `dd44a95`, the same two-criterion K=5 anchored rubric was
executed through `_FastMLSIJudgeAdapter` and contextual-orchestrator's MLX
route. The results separate model capability from transport:

| model | result | usage | elapsed |
|---|---|---:|---:|
| Gemma 4 e4b | strict `(4,4)`, score `1.0`, accepted | `3,031` tokens | `11.96 s` |
| Llama 3B | repeated safe false negative `(0,0)` and anchored non-monotone output | `2,497`–`3,119` tokens | `3.23`–`5.54 s` |
| Llama 1B | malformed JSON on all eight boundaries; failed closed | `4,764` tokens | `8.04 s` |

Gemma 4 e4b is a measured candidate for quality/latency follow-up, not a
production conclusion. The Llama results remain in the denominator, and no
model is promoted to IRT use without balanced held-out gold recall, parse
success, category occupancy, and perturbation checks.

The integrated path was then checked separately after an audit found that the
contextual `_FastMLSIJudgeAdapter` did not expose the gateway client capability
used by the fast judge. With contextual commit `d82e592` and exact fast judge
code from `61e6be9`, a two-criterion K=3 smoke made four boundary calls through
the adapter, reached peak concurrency `2` for `client.local_concurrency=2`,
and returned score `0.5`. This was a fake-provider integration contract smoke,
not a quality or MLX throughput claim; the original direct-injection evidence
must not be reused as evidence for the integrated path.

### HTTP admission alignment follow-up — 2026-08-14

The gateway's secure default `max_concurrent_runs=8` is an independent
admission limit. A live loopback smoke used the same 3B MLX model, temperature
`0`, disabled thinking, `max_output_tokens=32`, and 16 simultaneous route
requests. With `local_concurrency=16`, changing only the gateway admission
setting produced:

| `max_concurrent_runs` | HTTP 200 | HTTP 503 | elapsed | interpretation |
|---:|---:|---:|---:|---|
| `8` | `8` | `8` | `0.717 s` | secure default rejects excess simultaneous runs |
| `16` | `16` | `0` | `2.245 s` | explicit operator setting admits the measured batch width |

The result verifies admission behavior, not a throughput or quality ranking;
the accepted requests necessarily changed provider queue pressure. The secure
default remains `8`, and operators must explicitly set
`--max-concurrent-runs` alongside a measured `--local-concurrency` value.

### Current route throughput recheck — 2026-08-14

A fresh warm-cache route probe used the same 3B Llama worker, temperature `0`,
thinking disabled, `max_output_tokens=32`, and 16 concurrent route requests.
Every response was non-empty and the run used the real contextual-orchestrator
`TaskOrchestrator.route_once` path.

| `local_concurrency` | successes | elapsed | requests/s |
|---:|---:|---:|---:|
| 1 | 16/16 | `8.166 s` | `1.959` |
| 4 | 16/16 | `2.608 s` | `6.136` |
| 8 | 16/16 | `2.534 s` | `6.315` |
| 16 | 16/16 | `2.760 s` | `5.797` |

Under this exact workload, `local_concurrency=8` was the fastest measured
setting; this supersedes neither the earlier model/prompt-specific c=16 probe
nor the secure HTTP admission default. It is throughput evidence only, not a
quality or semantic-judge result.

### Current exact-head anchored rerun and provider-readiness incident — 2026-08-14

The current fast-mlsirm source at `26b9ccc590a65cebf23537ce00f292f4d5f9e6f7`
and contextual-orchestrator source at
`18d8c3b63eba471f439dd50f36f0f1e395d202d7` were exercised through the real
`ContextualOrchestratorJudge -> _FastMLSIJudgeAdapter -> TaskOrchestrator ->
ModelClient -> mlx-lm` path. The candidate was Gemma 4 e4b, with two criteria,
K=5 complete category anchors, temperature 0, disabled thinking, client
`local_concurrency=4`, and an explicit server `prompt-concurrency=1` /
`decode-concurrency=1`.

The first attempt failed closed at the provider boundary: `/health` and
`/v1/models` returned HTTP 200, but every `/v1/chat/completions` request
returned no bytes before a 15–20 second timeout. The eight judge boundaries
therefore recorded `0/8` completed calls, zero usage, and about 60.7 seconds
elapsed. The loopback mlx-lm process had accumulated many closed/CLOSE_WAIT
connections; it was restarted with the explicit Gemma 4 e4b model and bounded
server concurrency. A direct post-restart completion returned HTTP 200 in
0.316 seconds. This is provider-readiness evidence, not a LibreSSL or TLS
verification failure.

The post-restart anchored rerun completed and parsed all eight Boolean calls in
14.118 seconds with `3,625` provider tokens and eight trace steps, but failed
the ordinal semantic gate: the evidence-quality boundaries were
`false,false,true,true` and the risk-signal boundaries were
`false,true,true,true`. Because a higher threshold became true after a lower
threshold was false, the result was rejected as `semantic_status=non_monotone`;
no category row, acceptance decision, or IRT observation was produced. Anchor
presence was true, but anchor binding and strict JSON parsing do not guarantee
semantic threshold consistency. Retain this complete failure in the
calibration denominator and do not promote Gemma 4 e4b, change verifier
priority, or repair the row without balanced held-out gold and perturbation
evidence.

### Explicit provider readiness refresh — 2026-08-14

The new `TaskOrchestrator.provider_readiness_report(refresh=True)` path was
exercised against the live `mlx-lm` service through `ModelClient`, using
`mlx-community/gemma-4-e4b-it-4bit`, `temperature=0`, disabled thinking, a
three-second probe bound, and zero local retries. `/health` returned `{"status":
"ok"}` and the explicit one-token chat probe returned `ready` in `718.03 ms`
with `15` provider tokens (`14` prompt, `1` completion). The authenticated
`GET /api/v1/provider_readiness/latest?refresh=true` contract then returned
HTTP `200`, `status=ready`, and the same worker-specific usage shape (`250.55
ms` on the warm second probe).

This is serving-readiness evidence only: it proves a bounded chat completion
can pass now, not that the model is semantically calibrated or suitable for
LLM-as-a-Judge. The refresh is explicit, sequential per worker, and
non-retrying so the liveness endpoint cannot hide or multiply a stuck MLX
queue.

### Anchored K=5 calibration after ordinal prompt hardening — 2026-08-14

The linked fast-mlsirm implementation was advanced to
`17e19ec90643a8dfcc464cd7dde0b63949539a32` and exercised through the exact
`ContextualOrchestratorJudge -> _FastMLSIJudgeAdapter -> TaskOrchestrator ->
ModelClient -> mlx-lm` path. The prompt was changed to state that each Boolean
call asks whether the answer meets *at least* the requested category (not
exactly that category), that stronger evidence remains true at lower
boundaries, and that criterion/task relevance is required. Generic intent,
unrelated detail, admissions that a control is missing, and rubric repetition
are not evidence.

On a balanced six-case set with two criteria, K=5, complete per-criterion
anchors, temperature 0, disabled thinking, `local_concurrency=4`, and no local
retries, three complete reruns produced the following calibration-only
evidence:

| prompt version | complete comparisons | failed closed | cell accuracy among complete rows | exact-case accuracy | provider tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| pre-hardening | `2/6` | `4/6` | `25.0%` | `0.0%` | `20,274` |
| minimum-boundary clarification | `5/6` | `1/6` | `40.0%` | `16.7%` | `22,925` |
| relevance clarification repeat | `4/6` | `2/6` | `37.5%` | `16.7%` | `25,528` |

The first two token totals are sums of the per-case usage records retained in
the detailed run output. The third run used `25,528` provider tokens over
`77.907 s`. Complete rows still over-scored partial or
unsupported evidence (`partial_plan` and `evidence_without_safety`), while
non-monotone outputs for unsafe/irrelevant cases were rejected. The prompt
change therefore improves the ordinal contract's protection but does not
establish bias removal, model quality, or IRT readiness. Preserve all failed
comparisons and semantic over-scores in the denominator; require a larger
held-out human/gold set, prompt/order perturbations, and category occupancy
before any model promotion.

The fast PR branch subsequently reconciled its GitHub pull ref at exact head
`2cd12090f6f4ef8188da15fc6a5704a6ad7063c7` (a documentation-only follow-up
recording the temporary branch/pull-ref drift). A later fast-mlsirm follow-up
advanced the linked PR to `ebd76b4664147c18a3e1cfcc3d689e916a2fff08`; it records
the validated `meets_threshold` Boolean in bounded non-monotone failure
evidence without retaining full model output. That push invalidates all
predecessor review/check evidence; the calibration implementation remains the
`17e19ec` ancestor, and the new exact head requires fresh review and checks.

### Repeated local batch concurrency sweep — 2026-08-14

The live `mlx-lm` worker was measured through contextual-orchestrator's
`ModelClient.batch_chat` path with Gemma 4 e4b, eight identical short requests,
temperature `0`, `max_output_tokens=32`, disabled thinking, and zero local or
remote retries. The server was configured with `prompt-concurrency=1` and
`decode-concurrency=1`. Each client-concurrency setting was repeated twice; all
16 requests per setting completed and each run used 248 provider tokens.

| client `local_concurrency` | mean throughput (req/s) | throughput stdev | mean elapsed (s) |
| ---: | ---: | ---: | ---: |
| 1 | `2.095` | `0.019` | `3.819` |
| 2 | `2.083` | `0.028` | `3.840` |
| 4 | `2.092` | `0.017` | `3.824` |
| 8 | `2.088` | `0.025` | `3.832` |

The differences are within this small-run variance and show no benefit from
raising client concurrency while the worker's prompt/decode concurrency is
one. Keep the safe client default at `1`; tune the server-side queue separately
and repeat this workload after changing model, prompt budget, or server
concurrency. This is throughput evidence only, not judge-quality evidence.

### Integrated two-item anchored smoke (pre-main-sync snapshot) — 2026-08-14

The pre-main-sync local source trees were exercised through the complete
`ContextualOrchestratorJudge -> _FastMLSIJudgeAdapter -> TaskOrchestrator ->
ModelClient -> mlx-lm` path with Gemma 4 e4b, temperature `0`, disabled
thinking, `max_output_tokens=192`, zero retries, `local_concurrency=1`, K=`3`,
and two complete anchored criteria. Four Boolean boundary calls completed in
`4.404 s` and used `1,797` provider tokens. The parsed categories were
`release_monitoring=2` and `rollback_safety=2`, producing the required
two-column polytomous IRT row `[2, 2]`.

A separate one-criterion attempt was rejected at the IRT projection boundary
with `IRT output requires multiple criterion items; a scalar judge result is
invalid`. No scalar padding, keyword matching, positional repair, or silent
item synthesis was used. This is an integration and contract smoke, not proof
of semantic quality or model promotion.

### Post-protected-main integrated two-item smoke — 2026-08-14

After fast-mlsirm was synchronized with protected `main` (source merge
`bbf5d0e1d1185d4a51fae24fa95c3c18a3ea2f23`; subsequent head
`c5727de` contains documentation only), the same complete
`ContextualOrchestratorJudge -> _FastMLSIJudgeAdapter -> TaskOrchestrator ->
ModelClient -> mlx-lm` path was rerun with Gemma 4 e4b, temperature `0`,
disabled thinking, `max_output_tokens=192`, zero retries,
`local_concurrency=1`, K=`3`, and two complete anchored criteria. Four
Boolean boundary calls completed in `6.023 s` and used `1,872` provider
tokens. The parsed categories remained `release_monitoring=2` and
`rollback_safety=2`, with `category_method="binary_threshold"`, producing
the required two-column polytomous row `[2, 2]` and score `1.0`.

This confirms post-main synchronization integration and contract preservation,
not semantic accuracy, bias removal, IRT sufficiency, or model promotion. The
latency/token difference from the pre-sync snapshot is retained rather than
normalized away; future performance comparison must use repeated runs under
the same server and prompt configuration.

### Paired option-count and framing controls — 2026-08-14

The new fast-mlsirm calibration controls at exact head
`5a072705c840ea70d87a73bf737d5b193ef428cb` were exercised through the same
`ContextualOrchestratorJudge -> _FastMLSIJudgeAdapter -> TaskOrchestrator ->
ModelClient -> mlx-lm` route with Gemma 4 e4b, temperature `0`, disabled
thinking, `max_output_tokens=192`, zero retries, `local_concurrency=1`, K=`3`,
two complete anchored criteria, and caller-declared `held_out` status. Each
case ran baseline, option-only/no-question, shuffled-option, and
distractor-replacement variants. Every successful result produced the
required two-column polytomous row; no keyword matching, repair, retry, or
positional category inference was used.

| option count | variants | status | gold exact agreement | score range | paired score deltas | elapsed | provider tokens |
| ---: | ---: | --- | ---: | ---: | --- | ---: | ---: |
| 3 | 4 | `4 passed` | `4/4` | `1.0..1.0` | all `0.0` | `20.442 s` | `7,868` |
| 5 | 4 | `4 passed` | `4/4` | `1.0..1.0` | all `0.0` | `20.277 s` | `8,110` |

This small held-out smoke did not show a positive option-count shift, but it
does not estimate or disprove a general LLM option-count effect. The report
retained contamination status, per-variant categories, IRT rows, trace-step
counts, and usage while excluding raw model output. Replication must expand
persons/items, correct-option positions, option counts, models, framing, and
human/gold anchors before any bias or IRT-readiness claim.

### Model-size reliability comparison — 2026-08-14

Using the same held-out three-option case, K=`3`, two anchored criteria,
temperature `0`, disabled thinking, `local_concurrency=1`, and the four paired
variants, the real contextual-orchestrator route produced these exploratory
results:

| model | passed variants | gold exact agreement | paired score deltas | elapsed | provider tokens |
| --- | ---: | ---: | --- | ---: | ---: |
| Llama 1B | `0/4` | not scored | not scored | `25.334 s` | first summary omitted usage; follow-up retained `2,302`–`2,681` tokens/variant |
| Llama 3B | `4/4` | `4/4` | all `0.0` | `24.139 s` | `7,960` |
| Gemma 4 e4b | `4/4` | `4/4` | all `0.0` | `39.731 s` | `7,860` |

The 1B follow-up retained four complete boundary-failure records: all four
provider calls completed, JSON parsing failed on three or four boundaries per
variant, and the report preserved `2,302`–`2,681` provider tokens per variant
without retaining raw output. This is structured-output reliability evidence,
not a claim that the larger models are unbiased. Model promotion requires
more persons/items, balanced correct-option positions and counts, framing and
contamination controls, and human/gold recall.

### Direct-versus-binary paired calibration follow-up — 2026-08-14

The current local `mlx-lm` process was configured for Gemma 4 e4b. Using the
real `fast-mlsirm.ContextualOrchestratorJudge -> contextual-orchestrator ->
mlx-lm` route, temperature `0`, disabled thinking, `max_output_tokens=192`,
zero retries, `local_concurrency=1`, K=`3`, two complete category anchors, and
caller-declared `held_out` status, the same four paired MCQ variants were run
with the explicit `direct` method and with the default method (which resolves
to independent `binary_threshold` calls).

| method | passed | judge failures | gold exact agreement | rows among passed | elapsed |
| --- | ---: | ---: | ---: | --- | ---: |
| explicit `direct` | `2/4` | `2` | `1/2` | baseline `(2,1)`, replacement `(2,2)` | `12.204 s` |
| default `binary_threshold` | `4/4` | `0` | `4/4` | all `(2,2)` | `17.096 s` |

The direct run's option-only and shuffled variants failed closed at the judge
format boundary; they were retained in the denominator. The binary result is
one anchored case, not evidence of universal accuracy or bias removal, but it
supports retaining binary thresholds as the implicit production polytomous
method and keeping direct K-way selection explicit calibration-only. No
keyword matching, positional inference, retry, repair, or silent drop was
used.

The same default binary case was then repeated with the gateway's bounded
local concurrency capability. The server remained configured with prompt and
decode concurrency `1`; all four variants stayed at gold `4/4` with rows
`(2,2)`.

| gateway `local_concurrency` | elapsed | status | gold exact agreement |
| ---: | ---: | --- | ---: |
| `1` | `17.096 s` | `4 passed` | `4/4` |
| `4` | `14.843 s` | `4 passed` | `4/4` |
| `8` | `14.816 s` | `4 passed` | `4/4` |

Concurrency `4` is the smallest tested setting at the observed plateau;
raising it to `8` added no meaningful throughput. Keep the library default at
`1` for interactive or single-queue workloads, and let latency-tolerant batch
callers retune within the gateway bound after changing model, server queue, or
prompt budget. This is a workload-specific throughput result, not a quality
claim.

### Zotero/OA literature audit and linked judge head — 2026-08-14

The local Zotero Desktop reports version `9.0.6` and exposes read-only Local
API reads. Jones--Loe item `CWY355RP` records `Open access` rights and has no
child attachment; Iannario item `MYPNHHWJ` records `Creative Commons
Attribution 4.0 International` rights and also has no child attachment. The
local Connector API successfully created the Cao et al. citation as item
`393S5NXZ`, but its all-rights-reserved record did not authorize copying the
PDF. Item PATCH and `/api/local/authorize` were unavailable, so no local file
upload was attempted.

OpenAlex/Unpaywall/Crossref metadata support Jones--Loe CC BY gold OA and
Iannario CC BY 4.0. The official SAGE download returned anti-bot `403` and the
official De Gruyter download returned a WAF `202` with zero bytes. Those
responses, crawler text, archived bytes without independently verified
provenance, reconstructed PDFs, and unauthorized mirrors are not counted as
original OA attachments. This keeps the PDF requirement open without
misrepresenting retrieval failure as a licensing failure.

The linked fast-mlsirm literature/calibration documentation is at exact head
`e6c457d36f483b7580e56e5825528c70506dd780`. Its evidence remains a bounded
calibration input, not an unbiasedness or IRT-readiness claim.

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
