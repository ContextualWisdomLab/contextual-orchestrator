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

> ModelClient accepts an explicit mlx:// or local:// loopback URL and maps it to HTTP only after validation.
>
> Local requests can forward chat_template_kwargs, including {"enable_thinking": false}, and report an actionable error when content is absent.
>
> ContextualOrchestratorJudge calls an injected .complete(messages, mode=...) object and parses bounded rubric JSON without provider credentials.

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

The core accepts only mlx:// or local:// with loopback hosts and a valid port for keyless local traffic. Local batch requests use a bounded thread pool; interactive paths remain sequential by default. fast-mlsirm receives an injected contextual-orchestrator adapter, strict criteria, bounded JSON parsing, and usage/trace metadata.

For Codex, the public control plane accepts the Responses request, converts supported
message and function-tool items to the local Chat Completions shape, forwards
the configured mlx-lm chat-template arguments, converts the result back to a
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

* `contextual_orchestrator/orchestrator.py`: keep the Responses-to-Chat and Chat-to-Responses conversion at `ModelClient.proxy_send`; validate local `mlx://` endpoints before sending and preserve `chat_template_kwargs`.
* `contextual_orchestrator/batch_routing.py` and `contextual_orchestrator/cost_router.py`: reuse the bounded `ModelClient.local_concurrency` value for the default in-process batch backend; keep the standalone default at one, preserve request ordering, and propagate runner errors without fallback.
* `contextual_orchestrator/__main__.py`: keep the secure HTTP run-slot default at eight, but expose a separate bounded `--max-concurrent-runs` option so an operator can align the gateway admission limit with a measured local batch setting without changing the library default.
* `contextual_orchestrator/server.py`: authenticate `/v1/models` and `/v1/responses`, proxy Responses requests, and frame streamed responses with `response.completed` and `data: [DONE]`.
* `examples/agents.mlx.json`: keep the minimal selected MLX worker example visible in data, not code.
* `examples/agents.local.json`: keep the explicit candidate registry: public contextual-orchestrator and every discovered MLX, llama.cpp, and LM Studio candidate. Do not pre-disable entries as a discovery side effect.
* `tests/test_local_mlx.py`: verify the local Responses request is adapted to the Chat transport and template arguments.
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
| GitHub HTTPS from this macOS host failed with `LibreSSL SSL_connect: SSL_ERROR_SYSCALL` on the VPN `utun12` route, while the same endpoints returned HTTP 200 over `en0`; this is a path/MTU/firewall failure signal, not evidence of a bad repository, certificate, or Keyverse credential. | Diagnose the route and interface before changing credentials or TLS verification; retain certificate verification, do not set a global proxy or `GIT_SSL_NO_VERIFY`, and use only a temporary interface-bound relay when an authorized remote operation must proceed. Record the exact interface, endpoint, and cleanup state, then re-run remote checks after the network path recovers. | Observed 2026-08-12; temporary relay used for pushes/checks and must not become repository configuration |
| A later live check showed `curl 8.7.1` using SecureTransport/LibreSSL 3.3.6 returned HTTP 200 to GitHub, while the active Passepartout WireGuard route used `utun10`; therefore the historical `SSL_ERROR_SYSCALL` is not a reproducible LibreSSL installation/certificate defect. | Keep TLS verification enabled and compare VPN-on/off route, DNS, destination IP, socket reset, NAT/egress, endpoint, and MTU evidence. Do not set `GIT_SSL_NO_VERIFY`, replace certificates, or alter repository credentials; treat the error as a VPN path/endpoint failure until a controlled no-VPN reproduction proves otherwise. | Confirmed 2026-08-13; current LibreSSL transport healthy, VPN-path investigation retained |
| The provider host allowlist was read from `CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS` at request time, which made runtime policy depend on mutable environment state outside the KV/config boundary. | Bind non-secret provider policy through `ModelClient(allowed_provider_hosts=...)` and the explicit `--allowed-provider-host` CLI option; retain environment variables only for bootstrap transport and prove request-time env changes do not alter policy. | Implemented in current local head; exact-head CI/review follow-up required |
| The classic branch-protection endpoint returned 404 even though GitHub's branch-rules endpoint exposed organization/repository pull-request and required-workflow rules; querying only classic protection would under-report the effective merge policy. | Query `/rules/branches/main` and PR aggregate state together, record approval/last-push/thread/check requirements, and keep merge fail-closed when the exact head is pending, `REVIEW_REQUIRED`, or lacks an independent approval. | Observed 2026-08-12; ruleset-aware verification required before every merge |

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

## Rollback / Exit Strategy

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
