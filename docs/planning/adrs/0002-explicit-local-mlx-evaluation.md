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
informed:
  - "contributors"
affected_components:
  - "contextual_orchestrator/orchestrator.py"
  - "contextual_orchestrator/server.py"
  - "contextual_orchestrator/__main__.py"
  - "examples/agents.mlx.json"
  - "tests/test_local_mlx.py"
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
    target: "authenticated /v1/models returns the configured local model identifiers through contextual-orchestrator"
    measurement_window: "every Codex provider startup and passthrough test run"
    source: "contextual_orchestrator/server.py and tests/test_openai_passthrough.py"
  - metric: "credential separation"
    target: "ChatGPT/OpenAI authentication is selected only by the built-in OpenAI provider; no OpenAI credential is forwarded to mlx-lm"
    measurement_window: "every local server startup and provider configuration review"
    source: "contextual_orchestrator/orchestrator.py, contextual_orchestrator/server.py, local Codex profile configuration"
---

# Explicit local mlx transport and evaluation adapter

## Context

mlx-lm exposes an OpenAI-compatible server, but local reasoning models may return a reasoning-only message when thinking consumes the output budget. The gateway previously treated local HTTP as a remote provider shape, and the evaluation package had no provider-neutral boundary that guaranteed contextual-orchestrator was used for LLM-as-a-Judge.

Codex custom providers use the Responses wire contract, while the installed
mlx-lm server exposes an OpenAI-compatible Chat Completions endpoint. A direct
Codex-to-mlx-lm configuration therefore cannot preserve the Codex request and
streaming contract. The compatibility boundary belongs in
contextual-orchestrator, which is already the authenticated routing and
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

For Codex, the gateway accepts the Responses request, converts supported
message and function-tool items to the local Chat Completions shape, forwards
the configured mlx-lm chat-template arguments, converts the result back to a
Responses object, and emits a valid Responses SSE sequence for streaming. The
gateway also exposes the configured model identifiers at /v1/models. The
OpenAI/ChatGPT login remains a separate built-in Codex provider selected by a
Codex profile; its credential is never sent to the loopback mlx-lm endpoint.

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
* Do not make contextual-orchestrator auto-discover or silently switch between mlx-lm, llama.cpp, vLLM, and LM Studio; each additional runtime requires an explicit agent configuration and compatible contract.
* Do not bind the local Codex bridge to a public interface or make inference unauthenticated.

## Implementation Plan

* `contextual_orchestrator/orchestrator.py`: keep the Responses-to-Chat and Chat-to-Responses conversion at `ModelClient.proxy_send`; validate local `mlx://` endpoints before sending and preserve `chat_template_kwargs`.
* `contextual_orchestrator/server.py`: authenticate `/v1/models` and `/v1/responses`, proxy Responses requests, and frame streamed responses with `response.completed` and `data: [DONE]`.
* `examples/agents.mlx.json`: keep the selected local model and explicit `mlx://127.0.0.1:8080/v1` transport visible in data, not code.
* `tests/test_local_mlx.py`: verify the local Responses request is adapted to the Chat transport and template arguments.
* `tests/test_openai_passthrough.py`: verify the Responses SSE completion contract and model discovery endpoint.
* Local machine configuration: keep the ChatGPT login in Codex's normal auth cache, select the built-in `openai` provider through a profile when needed, and keep the local gateway bearer token in the OS credential store.

## Verification

* `PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_local_mlx.py tests/test_openai_passthrough.py` passes in the repository test environment.
* `GET /healthz` and authenticated `GET /v1/models` succeed on the loopback gateway.
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
| Unbounded local parallelism could exhaust memory. | Cap local_concurrency and preserve sequential default. | Implemented |
| Batch result errors could lose usage/IDs. | Preserve custom IDs and usage per local request. | Implemented |
| LLM-as-a-Judge could bypass the gateway. | Make fast-mlsirm depend on an injected contextual-orchestrator object, not a provider. | Implemented |
| Quality claims could be inferred from latency/step count. | Report structural metrics as structural and use rubric judgments for quality. | Implemented; benchmark ongoing |
| Codex sends Responses requests while mlx-lm accepts Chat Completions. | Convert the supported request/response subset at the authenticated gateway and test the SSE completion sequence. | Implemented |
| Codex model discovery reached the gateway's missing `/v1/models` route. | Expose the configured local model IDs through an authenticated OpenAI-compatible list response. | Implemented |
| Codex's large developer/tool payload exceeded the gateway's default 64 KiB body limit. | Keep the secure default; use an explicit 8 MiB limit only for the loopback, bearer-authenticated local Codex LaunchAgent. | Implemented |
| A local provider could accidentally receive ChatGPT/OpenAI credentials. | Keep built-in OpenAI auth and the local gateway bearer credential in separate Codex/provider boundaries; never attach OpenAI auth to `mlx://`. | Implemented |

## Risks and Mitigations

| risk | likelihood | impact | mitigation | owner |
| --- | --- | --- | --- | --- |
| A malicious config labels a remote endpoint as local. | low | high | Scheme, loopback host, port, credential/query validation and tests. | maintainer |
| Concurrent mlx requests exceed device memory. | medium | high | Default concurrency 1 and bounded user control; measure before raising it. | local-runtime owner |
| A small judge model produces invalid JSON. | medium | medium | Disable thinking, cap prompt/output, strict parse, fail closed. | evaluation owner |
| Responses-to-Chat conversion loses a future Codex item or tool type. | medium | high | Reject unknown request fields, forward only supported function tools, add a focused regression for every newly supported item type, and fail closed on malformed provider output. | gateway owner |
| The local model emits a syntactically valid but operationally unusable tool call. | medium | medium | Keep the model/tool capability explicit in `agents.mlx.json`, use a capable local model for tool-heavy work, and retain exact Codex smoke plus tool-call tests. | local-runtime owner |

## Rollback / Exit Strategy

Remove the explicit local adapter and use the mock path if the local server is unavailable; retain remote HTTPS validation unchanged. Revert concurrency to one and keep the output-content guard. Do not broaden local URL matching as a convenience fix.

## Affected Components

* contextual_orchestrator/orchestrator.py
* contextual_orchestrator/server.py
* contextual_orchestrator/__main__.py
* examples/agents.mlx.json
* tests/test_local_mlx.py
* tests/test_openai_passthrough.py
* fast-mlsirm/python/fast_mlsirm/llm_judge.py
* fast-mlsirm/tests/test_llm_judge.py

## More Information

The public projects are [contextual-orchestrator](https://github.com/ContextualWisdomLab/contextual-orchestrator) and [fast-mlsirm](https://github.com/ContextualWisdomLab/fast-mlsirm). This ADR intentionally does not add a provider SDK, a second orchestration runtime, or a Responses implementation inside mlx-lm.

On 2026-08-12 the Codex compatibility path was implemented in
`ModelClient.proxy_send` and the HTTP server. The local checks covered the
transport adapter, Responses SSE framing, and `/v1/models`; a live Codex smoke
returned the requested sentinel through the loopback gateway. The machine's
ChatGPT login remains available through Codex's built-in `openai` provider
profile, while the local server uses a separate OS-keychain bearer token.
