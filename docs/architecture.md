# Architecture Notes

## Equivalent endpoint execution

After model-group selection, endpoints may race only when their normalized
equivalence contracts match completely and `hedge_eligible` is true. Text and
every media capability use the same bounded executor. The first completed
response must pass its modality contract; a first token is never a winner.
Missing usage remains unavailable rather than zero cost, and cancel-or-safe-drain
outcomes enter the existing audit path.

Contract identity, capabilities, and membership are normalized across
`endpoint_equivalence_contract`, `endpoint_equivalence_capability`, and
`endpoint_equivalence_member`. Agent deletion cascades membership; contract
deletion is restricted while referenced. Configuration writes are operator-paced,
so race traffic does not create a hot write partition in these relations.

## Sources Read

APA 7th citations (titles retained for paper-contract search):

- Sakana AI. (2026, June 22). *Sakana Fugu: One model to command them all*. https://sakana.ai/fugu-release/
- Sakana AI. (2026). *Sakana Fugu Technical Report*. https://github.com/SakanaAI/fugu/blob/1397abb416e4b774003a09b689ea120e0da02262/Fugu_technical_report.pdf
- Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025). *Trinity: An evolved LLM coordinator* (arXiv:2512.04695). https://arxiv.org/abs/2512.04695
- Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025). *Learning to orchestrate agents in natural language with the Conductor* (arXiv:2512.04388). https://arxiv.org/abs/2512.04388
- Baker, F. B. (2001). *The basics of item response theory* (2nd ed.). ERIC Clearinghouse on Assessment and Evaluation. https://eric.ed.gov/?id=ED458219

## What The Architecture Is

The public shape is a single model API. The internal shape is a model pool plus
an orchestrator that decides when to answer directly, when to delegate, how
much context each worker receives, when to verify, and how to synthesize the
final answer. The public `contextual-orchestrator` model is the orchestration
candidate; the configured local and remote models are worker candidates in its
pool. The candidate registry retains every discovered model. `disabled` is an
explicit operator/admin quarantine or removal state, not an automatic discovery
result. Capability and recursion constraints are expressed separately from that
state.

The useful split is quality-latency, not separate products:

- Low-latency routing: select one worker for the current query or turn.
- Deep orchestration: create a multi-step workflow when the task needs decomposition, independent attempts, verification, or synthesis.

TRINITY is the inspiration for the role vocabulary, not an implemented method here. Its trained coordinator (a small model's hidden state plus a lightweight head) chooses both the agent and one of exactly three roles (Thinker, Worker, Verifier) on every turn and stops when the Verifier accepts. This repository borrows the role names and contracts only: `conduct` runs a fixed thinker → worker → verifier → synthesizer template with deterministic capability-hint worker choice, so there is no learned per-turn agent/role selection.

Conductor contributes the workflow representation: each step is a natural-language subtask, an assigned worker, and an access list of prior step outputs. This is the key piece for preventing every worker from being dragged into the same transcript while still allowing deliberate collaboration. The representation is implemented (`WorkflowStep.access`), so this part is partial rather than name-only. The paper's workflows come from a 7B model trained with reinforcement learning; here the default is the fixed 4-step template (`OrchestrationPolicy.workflow_planning = "template"`), and the optional `"generated"` mode asks an untrained planner model for a plan. That mode corresponds to the paper's training-free ablation with prompted frontier models (Appendix B.7, Table 11), not to the trained Conductor.

The generated-plan step bound (`OrchestrationPolicy.max_workflow_steps`, default 6) is a product decision recorded in the policy source: the fixed template needs four steps, and six leaves a generated plan one extra worker plus one repair/verify step. It is not the Fugu-Ultra report's "up to 5 steps" training setting (arXiv:2606.21228 S3.2.3), which is not copied into any other layer here, and it is separate from the effort catalog's per-profile `max_workflow_steps`. The planner prompt and the plan parser read the same policy value (`tests/test_paper_contracts.py::test_generated_plan_bound_comes_from_policy`).

The Fugu report combines these ideas into production constraints:

- Fugu is optimized for latency by selecting a worker without expensive coordinator generation.
- Fugu-Ultra is optimized for quality by generating deeper workflows over a broader agent pool.
- The agent pool is swappable, allowing provider preference, model exclusion, and compliance controls.
- Multi-agent tool/function-call workflows need memory discipline: isolate agents inside the current workflow, but keep useful shared memory across turns.

Fidelity note (2026-09-13, Fugu report arXiv:2606.21228 S3 / Fugu-Ultra
Conductor): the paper's Conductor routes a tool loop back to the agent that
emitted the tool call — when the client executes the tool and sends the
results back, the continuation goes to the same worker, not a freshly
selected one. This gateway previously did not do that: a follow-up carrying
`role: "tool"` results was ranked like any new request, so a virtual selector
(`orchestrator/free`, `orchestrator/auto`, `contextual-orchestrator`) could
hand a different provider/model the results for calls it never emitted. This
is now closed by `TaskOrchestrator`'s bounded `tool_loop_memory` map
(`tool_call_id -> emitting agent id`, see `_apply_tool_loop_route` in
`contextual_orchestrator/orchestrator.py`): a follow-up's remembered emitting
agent is moved to the front of the already-filtered candidate order on
`proxy_completion`'s single-agent passthrough, `route_once`, `conduct`'s
worker step, and `_orchestrated_provider_completion`'s structured synthesis
-- covering both of that path's callers (the Responses API and
`response_format`-only chat passthrough) -- but only when it is still
eligible under the request's own constraints (explicit concrete model,
free/ZDR, circuit state); otherwise routing falls back to the normal order.
On the Responses surface a served `function_call` item's `call_id` is
recorded the same way a chat `tool_calls[].id` is, and a follow-up's
`function_call_output` item needs no separate lookup: the existing
input-to-chat conversion already turns it into a `role: "tool"` /
`tool_call_id` message before candidate selection runs. The served
response's `orchestration` extension records `tool_loop_route`
(`"emitting_agent"`/`"fallback"`) and `tool_loop_agent_id` as evidence on
every one of these paths.

## Implementation Mapping

This repository implements the interface and control plane, not the trained
coordinator or its optional recursive self-worker. The public model is therefore
an explicit control-plane candidate, while the worker pool is selected from
configured `ModelAgent` records. The current implementation keeps that public
record out of internal roles with provider exclusions until the runtime has a
bounded, authenticated recursion protocol; it is not administratively disabled.

- `contextual_orchestrator.orchestrator.ModelAgent`: one configured worker model.
- `TaskOrchestrator.route_once`: the low-latency routing path (Fugu).
- `TaskOrchestrator.conduct`: the workflow path: a fixed thinker/worker/verifier/synthesizer template (TRINITY role names, not its learned coordinator) with Conductor-format steps and access lists (template or untrained prompted plan, not the RL-trained Conductor).
- Virtual selectors (`orchestrator/free`, `orchestrator/auto`, `contextual-orchestrator`) keep every inference surface on that control plane: `/v1/chat/completions`, `/v1/responses`, `/v1/embeddings`, `/v1/images/generations`, `/v1/videos`, `/v1/audio/*`, and `/v1/rerank`. Tools, `stream=true`, or a non-text modality do not eject a virtual request into a sticky single-agent pin; a concrete model id remains a debug pin. Chat Completions and media endpoints cannot emit Responses `reasoning_text` events, so paper-role process output stays internal and only the modality result is returned.
- `TaskOrchestrator._invoke`: the shared route/Conduct invocation path. A
  request-time failure of the primary provider call — 5xx, 429, network, a
  413 request-size rejection (a 400 context-window overflow —
  `_is_context_length_exceeded_error` — is classified the same way), or a
  non-retryable 4xx such as 401/403/404
  (this list is illustrative, not exhaustive: any failure the provider
  taxonomy classifies via `classify_provider_transport_failure` falls into
  either bucket) — advances to the next ranked candidate within the same
  cost tier — `orchestrator/free` never fails over into a priced agent, and
  `orchestrator/auto` only fails over inside the primary's own declared
  model group — instead of surfacing an opaque error; exhausting every
  eligible candidate still fails closed with the last classified provider
  error. See [ADR 0001's amendment](adr/0001-tool-execution-fallback-policy.md#amendment-2026-08-30-explicit-provider-transport-classification).
- Context-window candidate filtering: `proxy_completion`'s passthrough loop,
  `route_once`, and `conduct`'s worker step all funnel virtual-selector
  candidate ranking through `TaskOrchestrator._failover_candidates`, which
  optionally skips a candidate whose `ModelAgent.context_window` is a known
  positive int provably smaller than a conservative lower bound on the
  request's prompt tokens (`token_counting.prompt_token_lower_bound`: the
  exact native tokenizer count when one is mapped for the candidate's model,
  otherwise a character-count heuristic documented never to overestimate; see
  planning ADR 0133). A `None` window is never treated as evidence of a
  too-small window, and an explicitly requested concrete model is never
  filtered -- only virtual selection opts in the bound. Filtering every
  remaining candidate raises the same `ProviderRequestTooLargeError` (413)
  the all-providers-413 path uses. A response whose filter excluded at least
  one candidate carries the evidence in its `orchestration` extension:
  `prompt_token_lower_bound`, `prompt_token_bound_source`
  (`"exact"` or `"estimate_lower_bound"`), and `context_window_excluded`.
- Rate-limit-aware admission (2026-09-14): a 429/503 candidate failure records
  a per-agent quota cooldown from `Retry-After` (or a numeric
  `x-ratelimit-reset*` fallback) separately from the health circuit breaker --
  a 429 is quota exhaustion, not a model health failure, and does not trip it.
  A 429 with neither header (RFC 9110 permits omitting it; NIM/OpenRouter
  routinely do) records an *assumed* cooldown -- the administrator-owned
  `rate_limit_unknown_cooldown_seconds` default -- instead of nothing, tagged
  `cooldown_source: "assumed"` (vs `"provider"`) everywhere a cooldown is
  surfaced; a 503 with neither header keeps requiring a real provider-stated
  duration, since it is a possibly-permanent availability signal without a
  429's inherent quota-recovery semantics. `TaskOrchestrator._failover_candidates`
  skips a currently cooled-down candidate for every caller by default, falling
  back to the full list only when every candidate is limited. The
  wait-then-retry/honest-429 decision is one shared method,
  `TaskOrchestrator._await_rate_limit_recovery`: the discriminator is not
  candidate count but whether the caller delegated model selection at all --
  a virtual/gateway-selected model (`GATEWAY_DEFAULT_MODEL`/`AUTO_MODEL`/
  `FREE_MODEL`, or none) waits out the earliest cooldown even with only one
  currently eligible candidate (a single-route free pool wiped to one
  candidate by a 429 is real production evidence, not a hypothetical --
  noema-review run 34772771262 on contextual-orchestrator#1177,
  `ContextualWisdomLab/.github#2148`), while an explicit concrete model id
  keeps its pre-existing immediate classified-error contract unconditionally.
  Waiting is one bounded wait, never a busy-loop, applied when it fits the
  request's administrator-owned
  `model_timeout_seconds` deadline or the `rate_limit_wait_seconds`
  caller-contract default, or raises an honest `429`/`provider_rate_limited`
  with a `Retry-After` header (never a `502` connection-failure
  misclassification) when waiting is impossible. Two callers reach it:
  `proxy_completion`'s own passthrough failover loop, and
  `TaskOrchestrator._invoke_with_rate_limit_recovery`, which wraps `_invoke`
  -- the shared engine `route_once` and every `conduct` step (including the
  worker step) use to reach a candidate -- so the real `orchestrator/free`
  HTTP path is covered by the same admission contract, not a separate one.
  See the 2026-09-14 entries in
  [the gap baseline](product-technical-gap-baseline.md) for the production
  evidence and full scope note.
- `WorkflowStep.access`: Conductor-style visibility control.
- `ModelClient`: OpenAI-compatible HTTP client, with `mock://` for local checks.
- `contextual_orchestrator.server`: small `/v1/chat/completions` HTTP server.
- `contextual_orchestrator.video_jobs.VideoJobRegistry`: provider-affine async
  video resources. New submissions join immutable `video_job_records` with an
  optional first-complete `video_job_usages` row; legacy owner payloads are a
  compatibility read-and-update path — `observe_provider_result` still writes
  the first-complete `video_job_usages` row for a legacy `video_job_owners`
  record that has none. Provider status is observed in provider responses,
  never persisted or inferred.
- Batch routing jobs carry a non-secret authenticated-principal digest from
  submission through status and result retrieval; mismatched owners receive
  the same not-found response before backend access. Results require the
  separate trace purpose in addition to inference authorization.
- Streamed `/v1/responses` emits OpenAI reasoning items: stage summaries on
  `response.reasoning_summary_*`, and TRINITY thinker/worker/verifier plus
  Conductor step outputs on `response.reasoning_text.*`. Fugu `route_once`
  has no separate process stream; its worker answer is `output_text`. The
  synthesizer answer is also `output_text`.
- Streamed `/v1/responses` workflow runs preserve optional provider usage on
  each trace step and record one `stream` cost-ledger row per completed step.
  Missing provider counts remain `unavailable`; the gateway never derives
  billing tokens from the final answer. The final Responses event uses the
  standard `input_tokens`/`output_tokens`/`total_tokens` usage shape only when
  all workflow steps are measured. See [ADR 0040](planning/adrs/0040-streamed-responses-usage-boundary.md).
- `ResponsiveThreadingHTTPServer`: I/O-bound provider waits run in independent
  daemon request threads, the accept queue uses the operating system's native
  `SOMAXCONN`, and fixed-length responses use HTTP/1.1 persistent connections.
  The explicit `max_concurrent_runs` semaphore remains the expensive-work
  admission boundary, returning 503 without waiting when saturated. See the
  [k6 web-concurrency baseline](benchmarks/2026-08-25-web-concurrency-k6.md).
- `contextual_orchestrator.reasoning_effort_profile`: versioned per-role
  compute profiles (issue #568). Psychometric θ̂ and RMSE(θ̂, θ) score
  equal-budget variants of the same Fugu route versus Fugu-Ultra conduct
  split, the same TRINITY roles, and the same Conductor steps/access lists.
  They do not add a fourth dispatcher, a passthrough chain, or a
  name-inferred model family. Sampling temperature is not reasoning effort.
  Production route/conduct defaults stay locked until
  `production_default_change_allowed` is true. A rank constant is not an
  estimate. Buyer next action: run
  `python -m pytest -q tests/test_reasoning_effort_profile.py` and keep live
  defaults unchanged while that gate is false.

Agent-pool administration resolves `agent_pool_id` and `worker_agent_id`
together at the resource boundary. The current persistence model has one
`default` pool, so an unknown pool/worker combination returns not-found before
the worker is read, patched, or removed.

The deliberate simplification is the policy. The paper systems learn routing and topology from rewards; this lab uses a deterministic capability-hint heuristic only for worker/role routing so the repo runs without training data, GPUs, or vendor credentials. It is never an answer-quality, verification, or accept/reject judgment: verifier decisions must use the structured model judge and fail closed (see [ADR 0001](planning/adrs/0001-fail-closed-model-judgment.md)).

Add learned routing only when there is an evaluation set and logs proving the heuristic policy is the bottleneck.
The [NIM cost-quality benchmark](nim_benchmark.md) is that evaluation set's supplier: it discovers the hosted catalog dynamically, probes every modality contract, and compares route/conduct/single-worker policies with paired uncertainty — evidence first, learned policy later.

## SDK omit-real persist

Official OpenAI SDKs serialize omitted optional fields as JSON `null` or as empty/whitespace strings. Returning HTTP 200 while leaving those keys on the proxied body is not omit: providers then reject `tool_calls[].function.arguments: null`, blank Responses `instructions`, and non-string `metadata` values after this gateway already accepted the request. OpenAI `metadata` keys must be non-empty and must not include leading/trailing whitespace (`key == key.strip()`); padded keys return named `invalid_metadata` so attribution joins cannot diverge from strip()-normalized labels. Locked by `tests/test_metadata_key_no_padding_http_honesty.py` on tip ≥ #724 (re-land of #695).

Buyer next action: send the same payload the SDK emits. Expect the upstream echo to match an omitted field (key absent, or `arguments` as `""`), and expect `tools` + nonzero `top_logprobs` to return `invalid_top_logprobs` instead of a silent passthrough.

Locked by `tests/test_tip_reland_sdk_omit_persist_http_honesty.py` on the #668 substrate. Independent of Fugu/TRINITY/Conductor compute allocation: this is the OpenAI wire contract the coordinator sits behind (OpenAI, n.d.-a, n.d.-b).

Compatibility honesty for Structured Outputs and tools: `response_format.json_schema.name` and `tools[].function.name` (also message `name` and `tool_calls[].function.name`) must match `[a-zA-Z0-9_-]{1,64}`. ASCII is required — `str.isalnum()` alone accepts Unicode letters and digits (`café`, `名前`, Arabic-Indic digits) and would forward an illegal name for an opaque provider 400. Illegal names return named `invalid_response_format` / `invalid_tools` / `invalid_message` / `invalid_message_name`. Locked by `tests/test_json_schema_name_charset_http_honesty.py` and `tests/test_tool_function_name_charset_http_honesty.py` on the #686 substrate. Incidental leading/trailing whitespace on those names, on `tool_calls[].id`, and on tool-message `tool_call_id` is stripped and written back before length/charset checks so form/JS SDKs that pad wire strings still bind; blank-after-strip stays omit/reject. Locked by `tests/test_tool_call_id_name_strip_http_honesty.py` on the tip ≥ #717 substrate.

Official Responses `text.format` accepts `type` text / json_object / json_schema (flat schema keys), pops null/blank optionals, rejects `verbosity` and dual-plane `text`+`response_format`. Locked by `tests/test_responses_text_format_http_honesty.py` on the #687 substrate.

### References

OpenAI. (n.d.-a). *Create chat completion*. OpenAI Platform. https://platform.openai.com/docs/api-reference/chat/create

OpenAI. (n.d.-b). *Create a model response*. OpenAI Platform. https://platform.openai.com/docs/api-reference/responses/create

Sakana AI. (2026, June 22). *Sakana Fugu: One model to command them all*. https://sakana.ai/fugu-release/

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025). *Trinity: An evolved LLM coordinator* (arXiv:2512.04695). https://doi.org/10.48550/arXiv.2512.04695

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025). *Learning to orchestrate agents in natural language with the Conductor* (arXiv:2512.04388). https://doi.org/10.48550/arXiv.2512.04388

## Product Planning Interpretation

The product is not a Fugu clone. It is a control-plane prototype for the same public shape: one compatible API with hidden orchestration. The enterprise value comes from exposing the hidden operating evidence:

- pool health and provider exclusion for Fugu-style configurability;
- latency-quality policy for the Fugu versus Fugu-Ultra tradeoff;
- thinker, worker, verifier, and synthesizer roles for TRINITY-style trace review;
- natural-language subtasks and access lists for Conductor-style auditability;
- replayable evaluation runs before any learned coordinator replaces the deterministic policy.

See [product_planning.md](product_planning.md) for the product reboot.


OpenAI o-series `reasoning_effort` (chat/Completions) and Responses `reasoning.effort` accept known levels `none`/`minimal`/`low`/`medium`/`high` (casefold, strip) as default-effort no-ops when this gateway has no effort plane; unknown levels fail closed with named errors. Locked by `tests/test_reasoning_effort_low_medium_high_noop_http_honesty.py` on tip ≥ #738.
