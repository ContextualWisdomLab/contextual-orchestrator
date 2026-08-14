---
id: "0002"
title: "Explicit local mlx transport and evaluation adapter"
status: accepted
proposed_date: "2026-08-10"
accepted_date: "2026-08-11"
deciders:
  - "repository maintainer"
consulted:
  - "mlx-lm runtime"
  - "fast-mlsirm evaluation adapter"
  - "Sakana Fugu Technical Report"
  - "TRINITY: An Evolved LLM Coordinator"
  - "Learning to Orchestrate Agents in Natural Language with the Conductor"
informed:
  - "contributors"
affected_components:
  - "contextual_orchestrator/orchestrator.py"
  - "contextual_orchestrator/server.py"
  - "contextual_orchestrator/__main__.py"
  - "contextual_orchestrator/batch_routing.py"
  - "contextual_orchestrator/cost_router.py"
  - "examples/agents.mlx.json"
  - "examples/agents.local.json"
  - "tests/test_local_mlx.py"
  - "tests/test_batch_routing.py"
  - "tests/test_cost_router.py"
  - "tests/test_openai_passthrough.py"
effort: M
supersedes: null
superseded-by: null
related:
  - path: "docs/planning/adrs/0001-fail-closed-model-judgment.md"
    relation: informational
  - path: "docs/planning/adrs/0003-keyverse-authentication-boundary.md"
    relation: informational
asr_triggers:
  - kind: performance
    evidence: "The local 3B mlx-lm model is available and orchestration multiplies provider calls."
    note: "Temperature, token cap, template behavior, and bounded local concurrency are explicit controls."
  - kind: security
    evidence: "A local endpoint must never receive a remote provider credential."
    note: "Only explicit loopback mlx/local URLs are keyless and translated to HTTP after validation."
  - kind: maintainability
    evidence: "Codex uses the Responses wire contract while mlx-lm exposes Chat Completions."
    note: "Keep protocol conversion, SSE framing, and model discovery at the orchestrator boundary with focused regression tests."
success_criteria:
  - metric: "local provider safety"
    target: "loopback-only mlx/local URL, no Authorization header, remote HTTP rejected"
    measurement_window: "every local transport test run"
    source: "tests/test_local_mlx.py"
  - metric: "judge integration"
    target: "fast-mlsirm judge reaches an injected contextual-orchestrator only"
    measurement_window: "every LLM-as-a-Judge run"
    source: "fast-mlsirm/tests/test_llm_judge.py"
  - metric: "Codex Responses compatibility"
    target: "authenticated /v1/responses requests are adapted to local Chat Completions and return response.completed plus [DONE] when streamed"
    measurement_window: "every passthrough regression run and local Codex smoke"
    source: "contextual_orchestrator/orchestrator.py, contextual_orchestrator/server.py, tests/test_openai_passthrough.py"
  - metric: "local model discovery"
    target: "authenticated /v1/models returns contextual-orchestrator plus every configured worker candidate with governance status"
    measurement_window: "every Codex provider startup and passthrough test run"
    source: "contextual_orchestrator/server.py and tests/test_openai_passthrough.py"
  - metric: "credential separation"
    target: "ChatGPT/OpenAI authentication is selected only by the built-in OpenAI provider; no OpenAI credential is forwarded to mlx-lm"
    measurement_window: "every local server startup and provider configuration review"
    source: "contextual_orchestrator/orchestrator.py, contextual_orchestrator/server.py, local Codex profile configuration"
---

# Explicit local mlx transport and evaluation adapter

## Context

The Fugu technical report describes an orchestrator model that behaves as one
model to callers while selecting, delegating to, verifying with, and
synthesizing work from a swappable worker pool. It also permits the
orchestrator to be selected as a worker for recursive topologies. TRINITY
defines role contracts for thinker, worker, and verifier; Conductor defines
natural-language subtasks, worker identifiers, and access lists.

This repository is a stdlib control-plane implementation of that public shape,
not a trained Fugu/Trinity/Conductor coordinator. Its `contextual-orchestrator`
model is therefore the public orchestration candidate, while `ModelAgent`
records are worker candidates. Every discovered record remains in the registry;
`disabled` is reserved for an explicit operator/admin quarantine or a persisted
removal tombstone, not for an automatic capability or availability judgment.

mlx-lm exposes an OpenAI-compatible server, but local reasoning models may
return a reasoning-only message when thinking consumes the output budget. The
previous transport wording also treated local HTTP as a remote provider shape,
and the evaluation package had no provider-neutral boundary that guaranteed
contextual-orchestrator was used for LLM-as-a-Judge.

Codex custom providers use the Responses wire contract, while the installed
mlx-lm server exposes an OpenAI-compatible Chat Completions endpoint. A direct
Codex-to-mlx-lm configuration therefore cannot preserve the Codex request and
streaming contract. The compatibility boundary belongs in
contextual-orchestrator, which is the authenticated public control-plane and
provider-egress boundary.

> ModelClient accepts an explicit mlx:// or local:// loopback URL and maps it to HTTP only after validation. Direct mlx:// is keyless; authenticated local:// uses only an explicitly named local KV credential.
>
> Direct mlx:// requests can forward chat_template_kwargs, including {"enable_thinking": false}; the local:// gateway owns worker template settings and rejects unsupported template fields. Both report an actionable error when content is absent.
>
> ContextualOrchestratorJudge calls an injected contextual-orchestrator adapter and, when supported, sends a strict JSON Schema request through the gateway; it parses bounded rubric JSON without provider credentials.

## Decision Drivers

* Maximize useful local model output on the available Apple Silicon runtime.
* Keep local tests offline and free of provider SDK dependencies.
* Prevent credentials from being sent to loopback or arbitrary HTTP endpoints.
* Measure quality and latency separately instead of labeling structure as quality.
* Allow the existing ChatGPT Codex login to remain available without sending its credentials to a local model.

## Considered Options

* Treat all OpenAI-compatible endpoints identically.
* Add a direct mlx-specific provider dependency to both repositories.
* Make mlx-lm implement the Codex Responses API or fork its server transport.
* Treat contextual-orchestrator as only a thin gateway and omit it from the model candidate surface.
* Keep the core stdlib-only and add explicit loopback transport controls plus an injected evaluation adapter.

## Decision Outcome

Chosen option: "Explicit loopback local transport plus provider-neutral adapter".

| Driver | Generic HTTP | Direct mlx dependency | Explicit loopback + injected adapter |
| --- | --- | --- | --- |
| Local safety | ambiguous | provider-specific | scheme/host/credential checks |
| Runtime footprint | small | larger | stdlib core, installed mlx executable |
| Judge composition | not enforced | couples packages | contextual-orchestrator boundary is testable |
| Performance controls | implicit | provider-specific | temperature/cap/template/concurrency knobs |

The core accepts only mlx:// or local:// with loopback hosts and a valid port. Direct mlx:// traffic is keyless; authenticated local:// gateway traffic may use only an explicitly named local KV credential, never the remote provider credential. Local batch requests use a bounded thread pool; interactive paths remain sequential by default. fast-mlsirm receives an injected contextual-orchestrator adapter, strict criteria, bounded JSON parsing, and usage/trace metadata.

For Codex, the public control plane accepts the Responses request, converts supported
message and function-tool items to the local Chat Completions shape, forwards
the configured direct mlx-lm chat-template arguments, converts the result back to a
Responses object, and emits a valid Responses SSE sequence for streaming. The
control plane exposes `contextual-orchestrator` followed by every configured
worker candidate at /v1/models, including explicit governance status. Discovery
does not set `disabled`: that field is reserved for operator/admin quarantine or
persisted removal tombstones. Recursive self-selection is constrained by
provider exclusions in the current untrained implementation, rather than by
disabled state.
The OpenAI/ChatGPT login remains a separate built-in Codex provider selected by
a Codex profile; its credential is never sent to the loopback mlx-lm endpoint.

### Consequences

* Good, because the existing mlx_lm.server can be benchmarked without adding a runtime dependency.
* Good, because local reasoning behavior is controlled by explicit template kwargs rather than silent content loss.
* Good, because fast-mlsirm cannot accidentally call a provider outside contextual-orchestrator.
* Good, because Codex can use the same authenticated gateway without changing mlx-lm or leaking ChatGPT credentials to it.
* Bad, because local conduct remains several sequential model calls and can be slow.
* Bad, because the adapter does not manufacture a ground truth; a rubric model is still a model.
* Bad, because the Responses-to-Chat conversion supports only the provider-neutral message/function subset; unsupported Codex namespaces and standalone web search are not forwarded to mlx-lm.
* Bad, because a small local model may not reliably follow the full Codex tool protocol even when the transport is valid.

## Non-goals

* Do not modify or fork mlx-lm to add a Responses endpoint.
* Do not forward ChatGPT/OpenAI auth material to any `mlx://` or loopback provider.
* Do not silently switch runtimes based only on process presence. Discovery may produce an explicit candidate registry; availability and model capability are runtime/provider facts, while `disabled` remains an explicit operator/admin governance action.
* Do not enable recursive contextual-orchestrator self-selection until recursion depth, authentication, and failure termination are explicit.
* Do not bind the local Codex bridge to a public interface or make inference unauthenticated.

## Implementation Plan

* `contextual_orchestrator/orchestrator.py`: keep the Responses-to-Chat and Chat-to-Responses conversion at `ModelClient.proxy_send`; validate loopback endpoints before sending, resolve only the explicit local gateway credential for `local://`, and preserve `chat_template_kwargs` only for direct `mlx://` workers.
* `contextual_orchestrator/batch_routing.py` and `contextual_orchestrator/cost_router.py`: reuse the bounded `ModelClient.local_concurrency` value for the default in-process batch backend; keep the standalone default at one, preserve request ordering, and propagate runner errors without fallback.
* `contextual_orchestrator/__main__.py`: keep the secure HTTP run-slot default at eight, but expose a separate bounded `--max-concurrent-runs` option so an operator can align the gateway admission limit with a measured local batch setting without changing the library default.
* `contextual_orchestrator/server.py`: authenticate `/v1/models` and `/v1/responses`, proxy Responses requests, and frame streamed responses with `response.completed` and `data: [DONE]`.
* `examples/agents.mlx.json`: keep the minimal selected MLX worker example visible in data, not code.
* `examples/agents.local.json`: keep the explicit candidate registry: public contextual-orchestrator and every discovered MLX, llama.cpp, and LM Studio candidate. Do not pre-disable entries as a discovery side effect.
* `tests/test_local_mlx.py`: verify direct MLX template arguments, authenticated local gateway credential separation, and fail-closed missing credentials.
* `tests/test_model_judge.py`: verify structured fast-mlsirm completion requests remain on the contextual gateway adapter.
* `tests/test_openai_passthrough.py`: verify the Responses SSE completion contract and model discovery endpoint.
* Local machine configuration: keep the ChatGPT login in Codex's normal auth cache, select the built-in `openai` provider through a profile when needed, and keep the local gateway bearer token in the OS credential store.

## Verification

* `PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_local_mlx.py tests/test_openai_passthrough.py` passes in the repository test environment.
* `GET /healthz` and authenticated `GET /v1/models` succeed on the loopback control plane; model discovery includes the public orchestrator and the complete configured candidate registry.
* Authenticated streamed `POST /v1/responses` contains `response.completed` and `data: [DONE]` and reaches the configured mlx-lm model.
* A Codex local-provider smoke returns the requested exact sentinel response through contextual-orchestrator.
* Required exact-head CI, independent approval, zero unresolved threads, and final merge refetch are governed by ADR-0004; local verification cannot substitute for those gates.

### Confirmation

Run the local transport and passthrough tests, the real mlx route/conduct/judge benchmark, and the Codex smoke through `/v1/responses`. Confirm traces include provider usage, streamed responses terminate with `response.completed` and `[DONE]`, model discovery returns the configured model, and the judge is disabled-thinking or has enough output budget.

## Pros and Cons of the Options

### Treat all endpoints identically

* Good, because the API surface is smaller.
* Bad, because it hides local security and template semantics.
* Bad, because reasoning-only responses become opaque provider failures.

### Add direct mlx dependencies

* Good, because provider-specific behavior could be wrapped deeply.
* Bad, because both repositories would become harder to install and test.
* Bad, because the installed mlx_lm.server already supplies the required transport.

### Explicit loopback transport and injected adapter (chosen)

* Good, because it reuses the existing OpenAI-compatible surface and stdlib.
* Good, because the trust boundary is visible in configuration and tests.
* Bad, because an external deployment still owns model lifecycle and OIDC integration.

### Direct Codex-to-mlx-lm transport (rejected)

* Good, because it has one fewer process.
* Bad, because the current Codex provider contract is Responses-only while mlx-lm serves Chat Completions.
* Bad, because it would require weakening Codex streaming/tool semantics or maintaining a second transport implementation in mlx-lm.

## Problem Register and Remediation Directions

| Finding | Direction | State |
| --- | --- | --- |
| Reasoning-only mlx responses hid the real failure. | Forward template kwargs and emit an actionable content error. | Implemented |
| Local URLs could be confused with remote egress. | Require explicit loopback scheme/host and strip credentials/query data. | Implemented |
| Unbounded local parallelism could exhaust memory, while non-integer values could be silently truncated into a different concurrency. | Accept only an exact positive built-in integer in `1..64` at the client and CLI boundaries; preserve sequential default and keep the measured batch tuning value explicit. | Implemented in current head; exact-head CI/review follow-up required |
| An earlier eight-request 3B snapshot favored `local_concurrency=2` and incorrectly suggested that `4` was the throughput ceiling for the service. | Treat that result as historical; preserve the sequential interactive/default path, and require repeated warm-cache measurements across request cardinality and model size before changing a tuning recommendation. | Superseded by the repeated probe below; no quality claim |
| The repeated 2026-08-13 loopback probe measured `local_concurrency=8` as fastest for the current mlx-lm service: 16-request 3B median `7.928 s` (`2.018 req/s`), eight-request 1B median `1.524 s` (`5.251 req/s`), and eight-request Gemma 4B median `3.654 s` (`2.189 req/s`); all tested requests returned non-empty content. | Recommend explicit `local_concurrency=8` for latency-tolerant local batches on this server, while retaining library/interactive default `1`; re-measure after model, server-flag, prompt-size, or memory changes and never infer quality from throughput. | Observed and recorded in `docs/benchmarks/2026-08-13-local-mlx-gateway.md`; current tuning evidence |
| A current warm-cache saturation probe on the same 3B service measured c=16 at `6.827 req/s` for 16 requests and `6.246 req/s` for 32 requests, while c=24 and c=32 fell to `4.849` and `5.132 req/s`; every response remained non-empty. | Keep the general multi-model c=8 observation as the conservative cross-model baseline, but recommend explicit c=16 for this measured 3B batch profile only; retain default/interactive c=1 and require re-measurement after model, prompt, server, or memory changes. | Observed and recorded in `docs/benchmarks/2026-08-13-local-mlx-gateway.md`; current 3B tuning evidence |
| The generic `CostRoutingCoordinator` defaulted to a sequential `LocalBatchBackend` even when its `ModelClient` had an explicit local concurrency, so latency-tolerant local batches did not use the measured throughput path. | Pass the existing bounded `ModelClient.local_concurrency` into the default in-process backend, preserve standalone/default concurrency `1`, keep result ordering and runner-error propagation without fallback, and cover the handoff plus a two-request barrier regression. | Implemented in current local head; targeted/full suites and an 8-request live coordinator-to-MLX smoke passed; exact-head CI/review follow-up required |
| The new concurrent coordinator batch path can exercise `TaskOrchestrator`'s shared circuit-breaker state from multiple worker threads; an unlocked failure counter could lose increments and delay provider isolation. | Protect circuit-breaker read/reset/failure/success transitions with one lock and cover concurrent failure recording; keep the lock narrow so provider I/O remains outside it. | Implemented in current local head; concurrent circuit regression added; exact-head CI/review follow-up required |
| The current 32-request 3B saturation probe completed through c=48 only after a throughput collapse and timed out at c=64, while `/v1/models` remained healthy. | Treat c=64 as an observed provider saturation failure rather than a transport or LibreSSL defect; retain the explicit bound for controlled experiments, document the failed point, and use measured c=8/c=16 profiles instead of raising the default or hiding provider timeouts. | Observed 2026-08-13; benchmark evidence and adaptive tuning remain required |
| A live fast-mlsirm cumulative-threshold call returned a valid two-item polytomous row `(4,0)` but assigned `risk_awareness=0` to an answer that explicitly included rollback rehearsal, while `evidence_quality=4`; strict parsing and transport therefore did not guarantee semantic item accuracy. | Keep the complete result and provider/trace metadata in the calibration denominator; add balanced held-out cases and human/gold anchors for item-level recall and severity, and never repair the miss with keywords, category position, or silent coercion. | Observed 2026-08-13; semantic calibration required |
| The 2026-08-14 same-route 3B direct K-way probe scored an unsafe answer `0.0`, `0.5`, `0.8333` and a partial answer `0.0`, `1.0`, `0.0` at K=`2,5,7`; explicit binary thresholds scored both safe and unsafe probes `0.0` at K=`5,7`, with a safe semantic false negative. | Keep the gateway transport neutral while making fast-mlsirm's omitted polytomous method resolve to bounded binary thresholds; retain direct K-way only for explicit calibration, record calls/tokens/latency and semantic misses, and require held-out human/gold recall before IRT use. Never keyword-match or repair. | Implemented in fast-mlsirm `608cfbd`; calibration and exact-head review/check remain required |
| The actual integrated `_FastMLSIJudgeAdapter` smoke with fast-mlsirm `9d18f53` and contextual-orchestrator `a0a354a` selected the binary default at K=5: unsafe output was a valid rejected `(0,0)` result in 8 calls/`2,379` tokens/`3.73 s`, while safe output failed monotonicity after 8 calls/`3.23 s`. | Preserve the gateway's provider-neutral role and record both valid and failed integrated results; use the default only as a fail-closed measurement guard, not a quality claim, and require semantic gold/recall calibration before IRT interpretation. | Observed 2026-08-14; integrated contract verified, calibration remains required |
| The integrated safe-case failure previously exposed only `criterion thresholds must be monotone`, losing per-boundary status and provider accounting. fast-mlsirm `d1eca0c2fed89991e647802f0b27a91f0f6fe2bd` now reports bounded failure evidence: `semantic_status=non_monotone`, `parse_status=passed`, `8/8` completed calls, `8` trace steps, and `2,639` tokens. | Preserve structured failure evidence in the calibration denominator and distinguish complete-but-invalid semantics from transport or parse failure; never coerce the comparison into an IRT row or repair it lexically/positionally. | Observed 2026-08-14; integrated evidence capture implemented, semantic calibration remains required |
| A fresh 16-request 3B route recheck completed `16/16` at c=`1,4,8,16`; throughput was `1.959`, `6.136`, `6.315`, and `5.797 req/s` respectively, with c=8 fastest for this exact workload. | Retain library/interactive default c=1, use explicit c=8 as the current latency-tolerant batch starting point, and re-measure after model, prompt, output budget, server, or memory changes; never infer judge quality from throughput. | Observed 2026-08-14; benchmark recorded, tuning remains workload-specific |
| An anchored K=5 judge comparison through the real MLX route found Gemma 4 e4b strict `(4,4)`/score `1.0` in `3,031` tokens and `11.96 s`, while Llama 3B repeatedly produced a safe `(0,0)` semantic false negative and Llama 1B failed JSON on all eight boundaries. | Keep model choice evidence-based and separate quality, parse reliability, latency, and token cost; treat Gemma 4 e4b as a candidate only, retain Llama failures in the denominator, and require held-out gold/perturbation calibration before changing verifier priorities or IRT claims. | Observed 2026-08-14; fast-mlsirm `dd44a95`, calibration remains required |
| The current exact-head anchored Gemma 4 e4b rerun completed and parsed all eight boundaries but produced `false,false,true,true` for evidence quality and `false,true,true,true` for risk signal, so the ordinal judge failed closed as non-monotone despite complete traces, anchors, and `3,625` provider tokens. | Preserve the complete semantic failure and its trace/usage in the calibration denominator; do not promote the model or repair threshold order with keywords, positions, retries, or coercion. Require balanced held-out gold recall, perturbation stability, and category occupancy before any verifier-priority change. | Observed 2026-08-14; current exact-head integrated evidence, calibration remains required |
| The mlx-lm process remained liveness-ready (`/health` and `/v1/models` returned 200) while all chat completions returned no bytes and timed out; the loopback process had accumulated closed/CLOSE_WAIT connections. | Keep provider readiness separate from process liveness, bound request timeouts/concurrency, record all failed boundaries, and let the single-port supervisor restart the stuck process after an explicit health/readiness diagnosis. Never classify this as a LibreSSL certificate failure or disable TLS verification. | Observed 2026-08-14; explicit process restart restored a direct HTTP 200 completion, lifecycle hardening remains required |
| fast-mlsirm binary-threshold calibration issued independent boundary calls serially even when the injected contextual-orchestrator client had a bounded `local_concurrency` setting. | Reuse only that existing gateway bound for binary boundary calls, keep generic injected orchestrators sequential, preserve deterministic request order and complete trace/usage, and retain fail-closed monotonicity validation; do not add direct provider transport. | Implemented in fast-mlsirm `61e6be9`; targeted/full evidence and live MLX probe recorded |
| The contextual `_FastMLSIJudgeAdapter` did not expose its existing gateway client, so fast-mlsirm's bounded binary concurrency capability was not discoverable on the actual integrated judge path. | Expose the existing client capability from the adapter without adding a provider path, add an integration regression, and keep the fast-mlsirm fallback sequential for generic injected transports. | Fixed locally; exact integrated-path test and review/check follow-up required |
| The HTTP gateway admitted only eight simultaneous orchestration runs even when a measured local MLX batch used `local_concurrency=16`, so the optimized batch setting could be hidden behind the server semaphore; direct `SecurityConfig` callers could also bypass the intended bound. | Preserve the secure default of eight, enforce the same `1..64` bound at the server API and CLI, expose an explicit bounded `--max-concurrent-runs` setting, and require operators to tune it separately with the local batch setting; never raise the default automatically or treat throughput as quality. | Implemented locally; API/CLI regressions and exact-head review/check follow-up required |
| Batch result errors could lose usage/IDs. | Preserve custom IDs and usage per local request. | Implemented |
| LLM-as-a-Judge could bypass the gateway. | Make fast-mlsirm depend on an injected contextual-orchestrator object, not a provider. | Implemented |
| The contextual-orchestrator base environment does not install fast-mlsirm's declared NumPy dependency, so an in-process source checkout can fail to import the judge even though both repositories are present. | Keep the core standalone, but make the integration runner install/use fast-mlsirm's declared environment, run an import preflight, and fail closed rather than silently changing the judge implementation. | Observed 2026-08-13; benchmark command and fail-closed path recorded; packaging/preflight automation remains required |
| Quality claims could be inferred from latency/step count. | Report structural metrics as structural and use rubric judgments for quality. | Implemented; benchmark ongoing |
| Codex sends Responses requests while mlx-lm accepts Chat Completions. | Convert the supported request/response subset at the authenticated gateway and test the SSE completion sequence. | Implemented |
| The Responses adapter treated any non-list input as a message payload, so a malformed object could be silently converted into an empty user message instead of being rejected at the trust boundary. | Accept only the supported string-or-list input contract, reject other JSON types, and cover message, developer, tool-result, function-call, ignored-item, tool-choice, reasoning, metadata, and malformed-input paths. | Fixed in current local head; exact-head CI/review follow-up required |
| A negative remote retry count was accepted and made the retry loop silently skip the provider call. | Validate `max_retries` at client construction with the same non-negative contract as local retries, and cover negative and boolean values before any request can start. | Fixed in current local head; exact-head CI/review follow-up required |
| Codex model discovery reached the gateway's missing `/v1/models` route. | Expose contextual-orchestrator plus the complete configured worker candidate registry through an authenticated OpenAI-compatible list response. | Implemented |
| Codex's large developer/tool payload exceeded the gateway's default 64 KiB body limit. | Keep the secure default; use an explicit 8 MiB limit only for the loopback, bearer-authenticated local Codex LaunchAgent. | Implemented |
| A local provider could accidentally receive ChatGPT/OpenAI credentials. | Keep built-in OpenAI auth and the local gateway bearer credential in separate Codex/provider boundaries; never attach OpenAI auth to `mlx://`. | Implemented |
| The public orchestrator was incorrectly described as a proxy and omitted from the candidate surface. | Treat contextual-orchestrator as the public model-like control plane; retain all discovered worker candidates in an explicit registry, reserve `disabled` for operator/admin governance, and constrain recursive self-selection until a bounded future protocol exists. | Implemented |
| Expanding the registry could silently change the meaning of the existing unauthenticated `/healthz` `agent_count` field from active workers to all candidates. | Preserve `agent_count` as the enabled worker count for compatibility, add explicit `candidate_count` for the full registry, and expose `enabled_agent_count` as a redundant named metric with a regression containing one disabled candidate. | Implemented |
| A live local run showed the mlx-lm `prompt-concurrency=1` queue continuing to process abandoned large prompts after the client timed out; the server logged `BrokenPipe` and was restarted, while a default same-agent retry would add another expensive queued request. | Keep remote retry policy unchanged, but default explicit `mlx://`/loopback local requests to zero same-agent retries; require an explicit local retry opt-in, bound prompt/output budgets, expose provider readiness separately from process liveness, and ensure the supervisor owns one process per port with stale-request cleanup. | Local retry isolation implemented; readiness, prompt-budget, and lifecycle evidence required |
| The local retry opt-in was applied to the loop bound but the stop condition still compared attempts with the remote `max_retries` field, silently capping an explicit local retry budget whenever it exceeded the remote default. | Compute one provider-specific retry limit and use it for both iteration and termination in normal and raw passthrough transports; retain zero local retries by default and regression-test an explicit local budget above the remote budget. | Fixed locally; exact-head CI/review follow-up required |
| An explicit unknown model ID silently fell back to a different worker, and duplicate IDs could report or select a disabled record before an enabled record. | Reject unknown/non-string explicit model IDs, resolve duplicate IDs to an enabled candidate when one exists, and aggregate `/v1/models` status across all records so discovery and execution agree. | Implemented with passthrough and model-list regressions |
| `/v1/models` returned governance-enabled candidates as `active` even when only one MLX model was loaded; a caller could mistake registry membership for provider readiness. | Preserve `status` as governance state for compatibility, add `readiness: "unprobed"` to model entries and `provider_readiness: "unprobed"` to liveness, never perform a blocking synchronous provider probe in discovery, and add a bounded readiness/refresh contract before claiming serving availability. | Explicit boundary implemented; readiness probe/refresh remains required |
| Liveness endpoints could not distinguish a responsive mlx-lm process from a chat path that was timing out, so operators had no safe way to refresh serving readiness; concurrent admin refreshes could also multiply a stuck local queue. | Keep `/healthz` and `/v1/models` non-blocking and `unprobed`; add an admin-authenticated `provider_readiness_report(refresh=true)` that performs one `max_tokens=1` chat probe per enabled worker with a 0.1–30 second bound, no retries, redacted bounded errors, and one narrow process-local lock around the refresh sequence. | Implemented and exercised against live Gemma 4 e4b on 2026-08-14; exact-head CI/review follow-up required |
| Three anchored K=5 Gemma 4 e4b calibration reruns after fast-mlsirm `17e19ec90643a8dfcc464cd7dde0b63949539a32` prompt hardening produced complete/failed-closed counts `2/6`, `5/6`, and `4/6`, with complete-row cell accuracy `25.0%`, `40.0%`, and `37.5%`; partial/unsupported answers were still over-scored and unsafe/irrelevant cases could remain non-monotone. | Treat the prompt change as ordinal-contract hardening only; preserve all semantic failures and over-scores, do not promote Gemma or infer positive-K bias removal, and require larger held-out human/gold recall, randomized order/framing perturbations, and category occupancy before IRT use. | Observed 2026-08-14 through contextual head `c2bb2b2f85b3eae1c0c0138dff7f4a39cd744cd0`; calibration remains open |
| The fast branch ref and GitHub PR #816 pull ref temporarily diverged after the calibration push (`17e19ec` versus predecessor `7605c154`), leaving no checks on the new commit until a normal subsequent named-branch push reconciled exact head `2cd12090f6f4ef8188da15fc6a5704a6ad7063c7`. | Treat branch refs, pull refs, checks, reviews, and rulesets as separate exact-head evidence; record the drift, do not force-push/cancel predecessor runs, and bind all future review/check claims to the reconciled fast head and the linked contextual head. | Resolved by normal push on 2026-08-14; governance follow-up remains required |
| fast-mlsirm PR #816 then advanced from `2cd12090f6f4ef8188da15fc6a5704a6ad7063c7` to `ebd76b4664147c18a3e1cfcc3d689e916a2fff08` after a real failure-evidence gap was found: parsed non-monotone Boolean boundaries were not retained in bounded evidence. | Keep only the validated `meets_threshold` Boolean per ordered boundary, never retain full model output or repair the ordinal result, and invalidate predecessor review/check evidence after the normal push; require fresh exact-head review/check evidence for the linked judge implementation. | Implemented in fast-mlsirm `ebd76b4`; focused `62 passed`, full Python `3654 passed`; exact-head review/check follow-up required |
| GitHub HTTPS from this macOS host failed with `LibreSSL SSL_connect: SSL_ERROR_SYSCALL` on the VPN `utun12` route, while the same endpoints returned HTTP 200 over `en0`; this is a path/MTU/firewall failure signal, not evidence of a bad repository, certificate, or Keyverse credential. | Diagnose the route and interface before changing credentials or TLS verification; retain certificate verification, do not set a global proxy or `GIT_SSL_NO_VERIFY`, and use only a temporary interface-bound relay when an authorized remote operation must proceed. Record the exact interface, endpoint, and cleanup state, then re-run remote checks after the network path recovers. | Observed 2026-08-12; temporary relay used for pushes/checks and must not become repository configuration |
| A later live check showed `curl 8.7.1` using SecureTransport/LibreSSL 3.3.6 returned HTTP 200 to GitHub, while the active Passepartout WireGuard route used `utun10`; therefore the historical `SSL_ERROR_SYSCALL` is not a reproducible LibreSSL installation/certificate defect. | Keep TLS verification enabled and compare VPN-on/off route, DNS, destination IP, socket reset, NAT/egress, endpoint, and MTU evidence. Do not set `GIT_SSL_NO_VERIFY`, replace certificates, or alter repository credentials; treat the error as a VPN path/endpoint failure until a controlled no-VPN reproduction proves otherwise. | Confirmed 2026-08-13; current LibreSSL transport healthy, VPN-path investigation retained |
| The provider host allowlist was read from `CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS` at request time, which made runtime policy depend on mutable environment state outside the KV/config boundary. | Bind non-secret provider policy through `ModelClient(allowed_provider_hosts=...)` and the explicit `--allowed-provider-host` CLI option; retain environment variables only for bootstrap transport and prove request-time env changes do not alter policy. | Implemented in current local head; exact-head CI/review follow-up required |
| The classic branch-protection endpoint returned 404 even though GitHub's branch-rules endpoint exposed organization/repository pull-request and required-workflow rules; querying only classic protection would under-report the effective merge policy. | Query `/rules/branches/main` and PR aggregate state together, record approval/last-push/thread/check requirements, and keep merge fail-closed when the exact head is pending, `REVIEW_REQUIRED`, or lacks an independent approval. | Observed 2026-08-12; ruleset-aware verification required before every merge |
| A repeated live Gemma 4 e4b batch sweep through `ModelClient.batch_chat` used eight requests per run with server `prompt-concurrency=1`/`decode-concurrency=1`; two repetitions measured c=`1,2,4,8` at mean throughputs `2.095`, `2.083`, `2.092`, and `2.088` req/s respectively, with no errors and 248 provider tokens per run. | Keep client `local_concurrency=1` as the default for this single-queue server, do not raise it from a single warm-up result, and tune/re-measure server queue concurrency independently after model, prompt, token-budget, or server changes. Treat the result as throughput evidence, never judge-quality evidence. | Observed 2026-08-14; benchmark recorded, workload-specific retuning remains required |
| The current integrated anchored smoke used Gemma 4 e4b through `ContextualOrchestratorJudge -> _FastMLSIJudgeAdapter -> TaskOrchestrator -> ModelClient -> mlx-lm` with two criteria, K=`3`, c=`1`, and four boundary calls; it completed in `4.404 s`, used `1,797` provider tokens, and produced the two-column polytomous row `[2,2]`. A one-criterion attempt was rejected by the IRT projection contract. | Keep fast-mlsirm Judge traffic inside the contextual adapter, require multiple criteria for IRT output, and never synthesize a scalar second item; retain this as integration/contract evidence rather than semantic quality or promotion evidence. | Verified 2026-08-14; live semantic calibration remains required |
| After fast-mlsirm was synchronized with protected `main` at source merge `bbf5d0e1d1185d4a51fae24fa95c3c18a3ea2f23`, the same two-criterion Gemma 4 e4b integrated smoke completed four Boolean calls through the contextual adapter in `6.023 s`, used `1,872` provider tokens, retained `binary_threshold`, and produced `release_monitoring=2`, `rollback_safety=2`, and row `[2,2]`. | Treat this as post-main integration and contract evidence only. Retain the latency/token delta rather than averaging it into the earlier result; repeat paired runs before any performance claim, and continue to reject scalar output, keyword matching, positional repair, and silent synthesis. | Verified 2026-08-14; semantic calibration and exact-head remote review remain required |
| The first live integration attempt used contextual-orchestrator's own environment with the fast-mlsirm source on `PYTHONPATH`; fast-mlsirm's declared NumPy dependency was absent, so import failed closed even though both source trees were present. | Keep the standalone gateway dependency-light and keep missing/broken fast-mlsirm fail-closed, but add `python -m contextual_orchestrator check-fast-mlsirm` as a same-interpreter preflight that reports the missing transitive module, package version, required judge symbols, and exact contextual contract marker. Require this preflight before any live judge or IRT benchmark. | Implemented locally 2026-08-14; exact-head CI/review follow-up required |
| A fresh same-route model comparison used the real anchored binary-threshold judge with two criteria and baseline/option-only controls. Llama 1B failed both cases (`0/2` passed; all four boundary calls per case completed but strict parsing failed), while Llama 3B and Gemma 4 e4b each passed both cases with polytomous rows `[2,2]`, gold agreement `2/2`, and no provider failures. | Keep the 1B candidate available for fast non-verifier work but exclude it from the `verifier` role in the local registry; allow stronger eligible local agents to handle judge calls through the same gateway. Treat 3B/Gemma as candidates only, retain saturation and gold/perturbation evidence, and never use keyword or silent-repair fallback. | Observed 2026-08-14 through contextual-orchestrator `1614c7f40e5629c07dcfaa97d62b048a7bb459bf`; verifier exclusion implemented in the local registry, broader calibration remains required |
| A fresh same-route two-case comparison at K=`3` found Gemma 4 e4b passed both structured boundary comparisons (`[2,2]` safe, `[1,1]` unsafe) in `7.73 s`/`4.87 s`; Llama 3B passed the safe case but failed the unsafe case as non-monotone; Gemma 4 31B failed the safe boundary after `96.93 s`; DeepSeek R1 Qwen 32B completed no boundary in either `100 s` case. | Keep all models discoverable for non-verifier work, but exclude 31B and DeepSeek from `verifier` alongside the previously excluded 1B; select e4b as the current verifier primary and retain 3B as a lower-priority candidate. Treat this as workload-specific reliability evidence only, preserve every failure in the calibration denominator, and require larger balanced gold/perturbation calibration before promotion or IRT claims. | Observed 2026-08-14 through the contextual-orchestrator adapter; routing exclusions implemented, calibration remains required |

| A local `mlx://127.0.0.1:8080/v1` endpoint shared the machine with an unrelated wildcard listener; `/health` remained HTTP 200 while chat completions returned zero bytes and timed out. Candidate port 18080 was also occupied by a Colima SSH forward. | Treat one-process-per-port ownership as part of local serving readiness: reserve a dedicated loopback port, verify the actual MLX model registry and one bounded completion before calibration, and let the local supervisor report a port-owner/configuration mismatch without terminating unrelated processes. Keep the explicit `mlx://` scheme, bounded concurrency, zero default local retries, and TLS verification rules. | Observed 2026-08-14; dedicated MLX port 18083 restored `ModelClient.probe()` readiness, lifecycle hardening remains required |
| `ModelClient.probe()` previously exercised only a completion after endpoint validation, so an incompatible local listener could produce an opaque timeout even when `/health` was 200. | For explicit local providers, verify `/v1/models` contains the configured model before the one-token completion probe; retain bounded timeouts, zero default local retries, and fail-closed error reporting. | Implemented 2026-08-14; focused `41 passed`, full `387 passed`, live registry-plus-completion probe ready on dedicated port 18083 |
| A warm authenticated gateway recheck at 09:52 UTC measured `1/1`, `2/2`, and `4/4` successful short completions at wave times `307.89 ms`, `327.23 ms`, and `579.67 ms`; a fifth simultaneous request was explicitly rejected as `503 concurrency_limit_exceeded`, and all successful completion IDs were unique. | Keep the measured `max_concurrent_runs=4` admission bound for this server/model configuration, preserve explicit overload failure and UUID IDs, and re-measure after model, prompt, token, server, or device changes. Do not promote one short workload to a global concurrency default or a quality claim. | Observed 2026-08-14; no new code change justified by this sample |
| The current exact-head integrated judge smoke used contextual-orchestrator `474b667b576f8a019db51d892db41a605e3a0a85` and fast-mlsirm `a536292cc05bd16287dab16431bc0c3fef74ba81` with Gemma 4 e4b, two criteria, K=`3`, and four `binary_threshold` calls; it completed in `19.354 s`, used `2,163` provider tokens, and produced the required two-column polytomous row `[2,2]`. | Retain this as current-head route/contract evidence only. Keep multiple criteria mandatory, preserve the model/category result and measured cost, and require balanced held-out gold, perturbation stability, and category occupancy before semantic or IRT claims. Continue to reject keyword matching, positional inference, category repair, scalar synthesis, and silent drop. | Verified 2026-08-14; no new code change justified, semantic calibration and protected PR gates remain required |
| The gateway classified DNS/connection/timeout failures as transient but did not classify `ssl.SSLEOFError` or `ssl.SSLSyscallError`, so a VPN-path `SSL_ERROR_SYSCALL` could fail without the existing bounded retry policy; certificate verification errors are a different trust-boundary failure. | Treat TLS socket EOF/SYSCALL errors as transient network failures, keep `SSLCertVerificationError` non-transient, retain certificate verification, and cover both branches. Never use `GIT_SSL_NO_VERIFY`, a global proxy, or certificate replacement as a retry fix. | Fixed in contextual-orchestrator `1b22ff0`; targeted `14 passed`, full `388 passed`, exact-head CI/review follow-up required |

| The current exact-head MLX/gateway recheck used context `8f922d806336fd41d8fd73585a7c225784249332` and fast `47c5fbdde98b3550fe319d1de238a32cbaec8a1f`: width 1 had a 2,170.42 ms cold/warm-up response, width 2 had 341.35 ms wave latency, width 4 had 591.34 ms, and width 5 produced `4x200` plus bounded `1x503`; all successful response IDs were unique. A real two-criterion binary-threshold Judge completed through the contextual adapter in 4.949 s with 1,923 tokens and row `[2,2]`. | Keep the first request separate as warm-up evidence, retain gateway concurrency 4 as the measured plateau for this listener, preserve the explicit overload denominator, and treat the Judge result as route/contract evidence only. Do not infer semantic quality, unbiasedness, or IRT readiness from throughput or one safe case; rerun balanced gold and perturbation strata after model/server changes. | Verified 2026-08-14; Goal/ADR expanded, semantic calibration and protected PR gates remain open |
| A fresh warm comparison of the same worker versus the authenticated gateway found near-equivalent p50 latency at widths 1/2/4 (direct `202.52/323.74/593.77 ms`; gateway `203.96/321.01/559.07 ms`). Direct width 5 completed only by queueing to `899.16 ms`, while the gateway preserved its four-run admission bound and returned `4x200` plus bounded `1x503` in `564.28 ms`. | Keep the gateway in the performance path and retain `max_concurrent_runs=4` for this worker/server pair; increasing the bound would hide provider queue latency rather than improve throughput. Re-measure after model, prompt, output-budget, server, or device changes, and never infer judge quality from this transport result. | Verified 2026-08-14; no code change justified, benchmark recorded |
| The latest source pair `070d929`/`8f5d85a` completed a real two-criterion, three-category binary-threshold Judge through the contextual adapter in `3.731 s` with `2,015` provider tokens and IRT row `[2,2]`. | Retain the same-interpreter contract and multi-item IRT projection, but treat this as route/shape evidence only; require balanced non-ceiling gold, perturbation stability, category occupancy, and preserved provider/parse/semantic failure denominators before any verifier or IRT promotion. | Verified 2026-08-14; semantic calibration and protected PR gates remain open |

| A fresh warm comparison at current source heads `e9935d763d267bf20abb0bec069070c94a838369`/`b4121d2e2071a02b1f497b7228b0ecde061fbb45` used direct MLX and the authenticated gateway at widths `1,2,4,5`; direct returned `5/5` HTTP 200 by queueing width 5, while the gateway returned `4/5` HTTP 200 plus an explicit `concurrency_limit_exceeded` HTTP 503. Three two-criterion K=`3` Judge probes through the required contextual route preserved binary/direct/cumulative boundaries; cumulative safe output failed closed on non-monotonicity. | Keep `max_concurrent_runs=4` and explicit overload failure for this worker; do not convert direct queueing into hidden gateway work or raise the bound from this sample. Preserve every semantic/format failure, keep binary as the implicit production method and direct/cumulative calibration-only, and require balanced human/gold, occupancy, perturbation, and failure-rate evidence. | Verified 2026-08-15; no code change justified, semantic calibration and protected exact-head gates remain open |

| An authenticated `local://` gateway request initially returned `401` because the client treated every loopback URL as keyless and discarded the gateway bearer credential; the direct `mlx://` worker must remain keyless. | Add `ModelAgent.local_credential_key` as a separate KV name used only by `local://`, fail closed when it is missing, and never reuse `credential_key`/`OPENAI_API_KEY` for either local transport. | Fixed in current local head; focused local/KV tests and live authenticated Judge route passed, exact-head CI/review follow-up required |
| The same gateway rejected `chat_template_kwargs` with HTTP `400 unknown_fields`, although direct mlx-lm accepts the provider-specific template option. | Forward template kwargs only to direct `mlx://` workers; configure template behavior at the mlx-lm worker behind `local://`, and cover the distinction in transport tests. | Fixed in current local head; focused tests and live gateway smoke passed, exact-head CI/review follow-up required |
| Free-form Gemma Judge calls completed but emitted prose/Markdown for the strict rubric, so all four binary boundary parses failed closed despite healthy transport. | Let fast-mlsirm request the exact JSON Schema through the existing contextual adapter's gateway proxy when available, keep the old injected `.complete()` fallback for generic test transports, and preserve all parse failures in calibration denominators. | Implemented in current local heads; focused contextual `73 passed` and fast Judge `48 passed`, live structured route passed, semantic calibration remains open |
| A Gemma 4 e4b Judge request with caller `max_output_tokens=64` returned HTTP `200` but emitted fenced/truncated JSON (`finish_reason=length`) through both the authenticated gateway and direct MLX worker; `response_format` was advisory rather than a grammar guarantee. At `max_output_tokens=256`, direct K=`2,4,6` calibration parsed `12/12`, but option shuffling produced `[0,0]` at K=`2` and `[4,3]` at K=`6` versus `[4,4]` baselines; cumulative parsed only `6/12` and failed closed for the other six. | Keep the gateway's strict structured transport and fail-closed parser; do not treat HTTP success or a schema request as semantic validity. Use a measured output budget of at least `256` for this workload without silently overriding caller configuration, retain every format/semantic failure, and keep direct/cumulative calibration-only until balanced gold, occupancy, option-count/order replication, and human review support an IRT/verifier decision. | Verified 2026-08-15; transport/budget and bias-calibration evidence recorded, semantic calibration and protected Merge remain open |
| The linked fast-mlsirm exact-head Strix run `31836188815`/job `94882896174` returned a terminal success and `Vulnerabilities 0`, but its unbound artifact `9233137440` contained a report identifying symlink arbitrary-file-read paths in the Judge/IRT package's bounded JSON, CSV, NPY/NPZ, and params readers. The report digest was `81b718964554fb447e313a9e8f3679d0e57b1618d7ffa3d0780efdfdb45f1025`; no structured repository/head/run/job/report binding was present. | Treat the linked security result as a real source finding and a non-clean dependency gate. Require fast-mlsirm to pin reads to `O_NOFOLLOW`/regular descriptors, preserve NpzFile ownership safely, add symlink regressions, and rerun with structured exact-head evidence before contextual-orchestrator or fast-mlsirm Merge. Never route around a linked security finding or treat an unbound zero-finding line as clean. | Observed 2026-08-15; fast source fix in progress, linked exact-head security/review/Merge remain open |

## Risks and Mitigations

| risk | likelihood | impact | mitigation | owner |
| --- | --- | --- | --- | --- |
| A malicious config labels a remote endpoint as local. | low | high | Scheme, loopback host, port, credential/query validation and tests. | maintainer |
| Concurrent mlx requests exceed device memory. | medium | high | Default concurrency 1 and bounded user control; measure before raising it. | local-runtime owner |
| A small judge model produces invalid JSON. | medium | medium | Disable thinking, cap prompt/output, strict parse, fail closed. | evaluation owner |
| Responses-to-Chat conversion loses a future Codex item or tool type. | medium | high | Reject unknown request fields, forward only supported function tools, add a focused regression for every newly supported item type, and fail closed on malformed provider output. | control-plane owner |
| The local model emits a syntactically valid but operationally unusable tool call. | medium | medium | Keep the model/tool capability explicit in `agents.mlx.json`, use a capable local model for tool-heavy work, and retain exact Codex smoke plus tool-call tests. | local-runtime owner |
| A discovered candidate is installed but not a usable chat worker. | medium | high | Keep it in the registry without silently changing governance state; provider capability checks and failover determine whether a request can use it, while an operator may explicitly quarantine it. | local-runtime owner |
| Recursive self-selection can loop or re-enter the same authenticated server indefinitely. | medium | high | Keep the contextual-orchestrator self-worker candidate out of internal roles with provider exclusions until recursion depth, internal auth, and termination behavior have focused tests. | control-plane owner |

## Security evidence follow-up

The subsequent exact-head Strix runs were terminal success but still lacked trusted provenance. Fast head 1d05d785a3e5c4e0eecc96b807e3a88786cb8b1d produced run 31839153059, job 94892122092, artifact 9233769170, report SHA-256 05e3e48c1ebc475bdd62759970375268067872748947b3db35e6d4c2c2bfb2fc, and run.json SHA-256 10f4e33bc9dbe752444ba05063bbd9a02c9a58b07838e699d7ee5dcfad5aa768, but no evidence-binding.json. Contextual head 64b6d56a31f17721019d47d0f82945c722e1eb10 produced run 31839154460, job 94892129029, artifact 9234044840, report SHA-256 4f036e7f21c14920ce7fd95575e9e9228d35f88291cd5fdddac62bce3ab01a29, and run.json SHA-256 97b7d9218f86016ceb8b57d8c484cd50c21aad4314ac4f3560c7a2063df2bb43, also without evidence-binding.json. Keep both results as non-clean provider/content evidence until a trusted binding is published.

The current contextual head `e0413fe16ddd7b47f736bfc5e3ea91921736af0d` likewise produced terminal Strix run `31840661126`, job `94896593729`, artifact `9234622284`, report SHA-256 `06193ebbf64e8ed47011d8a01f471c8dee5c1b426c9ed8e15ab3940191d6111f`, and run.json SHA-256 `90e757b30e01a98a324332f9eb5fce933bb90725a441f3aef2f269783153428e`, with no `evidence-binding.json`. The zero-finding report is therefore not a trusted exact-head security pass. A later OpenCode review claimed a coverage-evidence failure for this same head but referenced Actions run `31844382551`, which is not retrievable from the current run API; the current check-run API instead records coverage job `94899211701` as successful. When review evidence and current check evidence disagree or the referenced run is unavailable, discard the stale decision and require a fresh exact-head review; do not silently convert either snapshot into approval.

## Rollback / Exit Strategy

The linked fast-mlsirm security finding is fixed in exact head
`8195434de6eb166a44dbda1f8bd4f2ca5086240a`; its focused IO/security suite
passed `305` tests and its full suite passed `3726` tests with 2 warnings.
Keep this as a non-clean dependency until fresh exact-head Strix evidence is
structured and independently reviewed.

Remove the explicit local adapter and use the mock path if the local server is unavailable; retain remote HTTPS validation unchanged. Revert concurrency to one and keep the output-content guard. Do not broaden local URL matching as a convenience fix.

## Affected Components

* contextual_orchestrator/orchestrator.py
* contextual_orchestrator/server.py
* contextual_orchestrator/__main__.py
* examples/agents.mlx.json
* examples/agents.local.json
* tests/test_local_mlx.py
* tests/test_openai_passthrough.py
* fast-mlsirm/python/fast_mlsirm/llm_judge.py
* fast-mlsirm/tests/test_llm_judge.py

## More Information

The public projects are [contextual-orchestrator](https://github.com/ContextualWisdomLab/contextual-orchestrator) and [fast-mlsirm](https://github.com/ContextualWisdomLab/fast-mlsirm). This ADR intentionally does not add a provider SDK, a second orchestration runtime, or a Responses implementation inside mlx-lm.

On 2026-08-12 the Codex compatibility path was implemented in
`ModelClient.proxy_send` and the HTTP server. The local checks covered the
transport adapter, Responses SSE framing, and `/v1/models`; a live Codex smoke
returned the requested sentinel through the loopback control plane. The machine's
ChatGPT login remains available through Codex's built-in `openai` provider
profile, while the local server uses a separate OS-keychain bearer token.

The Fugu report was then re-read on 2026-08-12. Its distinction between the
single model-like orchestrator and the swappable worker pool, plus its optional
recursive orchestrator-as-worker topology, is the reason this ADR keeps a full
candidate registry while constraining recursive self-selection in the current
untrained stdlib implementation. `disabled` remains an operator decision, not a
discovery decision.
