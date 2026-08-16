# Architecture Notes

## Sources Read

APA 7th citations (titles retained for paper-contract search):

- Sakana AI. (2026, June 22). *Sakana Fugu: One model to command them all*. https://sakana.ai/fugu-release/
- Sakana AI. (2026). *Sakana Fugu Technical Report*. https://github.com/SakanaAI/fugu/blob/main/Fugu_technical_report.pdf
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

TRINITY contributes the compact coordinator idea: a small model representation plus a lightweight head can choose agent and role over multiple turns. Its Thinker, Worker, and Verifier contracts are practical enough to implement directly.

Conductor contributes the workflow representation: each step is a natural-language subtask, an assigned worker, and an access list of prior step outputs. This is the key piece for preventing every worker from being dragged into the same transcript while still allowing deliberate collaboration.

The Fugu report combines these ideas into production constraints:

- Fugu is optimized for latency by selecting a worker without expensive coordinator generation.
- Fugu-Ultra is optimized for quality by generating deeper workflows over a broader agent pool.
- The agent pool is swappable, allowing provider preference, model exclusion, and compliance controls.
- Multi-agent tool/function-call workflows need memory discipline: isolate agents inside the current workflow, but keep useful shared memory across turns.

## Implementation Mapping

This repository implements the interface and control plane, not the trained
coordinator or its optional recursive self-worker. The public model is therefore
an explicit control-plane candidate, while the worker pool is selected from
configured `ModelAgent` records. The current implementation keeps that public
record out of internal roles with provider exclusions until the runtime has a
bounded, authenticated recursion protocol; it is not administratively disabled.

- `contextual_orchestrator.orchestrator.Agent`: one configured worker model.
- `Orchestrator.route_once`: the low-latency routing path.
- `Orchestrator.conduct`: the workflow path with planner, worker, verifier, and synthesizer steps.
- `WorkflowStep.access`: Conductor-style visibility control.
- `ModelClient`: OpenAI-compatible HTTP client, with `mock://` for local checks.
- `contextual_orchestrator.server`: small `/v1/chat/completions` HTTP server.
- `contextual_orchestrator.reasoning_effort_profile`: versioned per-role
  compute profiles (issue #568). Fugu's latency-versus-quality split, TRINITY
  roles, and Conductor steps/access lists become an explicit catalog. Sampling
  temperature is not reasoning effort. Production route/conduct defaults stay
  locked until `production_default_change_allowed` passes a true-θ RMSE gate.
  The ablation emits θ̂ and RMSE(θ̂, θ); a rank constant is not an estimate.
  Buyer next action: run `python tests/test_reasoning_effort_profile.py`
  and keep live defaults unchanged while that gate is false.

The deliberate simplification is the policy. The paper systems learn routing and topology from rewards; this lab uses a deterministic capability-hint heuristic only for worker/role routing so the repo runs without training data, GPUs, or vendor credentials. It is never an answer-quality, verification, or accept/reject judgment: verifier decisions must use the structured model judge and fail closed (see [ADR 0001](planning/adrs/0001-fail-closed-model-judgment.md)).

Add learned routing only when there is an evaluation set and logs proving the heuristic policy is the bottleneck.

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
