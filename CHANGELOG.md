# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- SSE-proxy `tools` and `response_format` on `/v1/chat/completions` when
  `stream=true`. Function-tool mocks emit `delta.tool_calls` and finish as
  `tool_calls` (invoice `lookup_balance` binds `INV-9` from the prompt);
  content-only `response_format` streams still match the JSON body; live
  providers are piped verbatim. Next action: send `stream=true` when the
  client reads SSE; include the invoice id in the user text; omit
  `stream_options.include_usage`.

### Fixed

- Fail closed on unknown assistant `tool_calls` entry and `function` keys
  (`unknown_tool_call_fields` / `unknown_tool_call_function_fields`) on both
  the orchestration path and the tools / `response_format` SSE proxy.
  Optional `index` is a non-negative integer or JSON `null`. Next action:
  send only `id`, `type`, `function`, and optional `index` on assistant
  `tool_calls`.
- Fail closed on tools / `response_format` for non-boolean
  `include_orchestration_trace` and unknown `mode` before the JSON or SSE
  proxy. Next action: send a boolean or omit the trace flag; send
  `auto` / `route` / `conduct` or omit `mode`.
- Treat official-SDK JSON `null` on optional `tools[].function.description`,
  `parameters`, and `strict` as omit-real: the keys are popped before
  `proxy_completion` so upstream providers see an omitted field, not a null
  schema. Non-null wrong types still fail closed with named `invalid_tools`.
  Next action: send those fields only when you have a real string, JSON Schema
  object, or boolean; SDK defaults of `null` are safe.
- Fail closed on tools passthrough for `seed`, `stop`, `n>1`, `logprobs`,
  `logit_bias`, and out-of-range penalties — the same named errors as the
  orchestration path. Next action: omit those knobs on tool-calling requests.
- Apply the request `temperature` on streamed route completions instead of
  silently using `0.2`. Next action: send the temperature you want; streaming
  no longer changes the sampling policy.

### References

- OpenAI. (2024). *Create chat completion*. OpenAI API reference.
  https://platform.openai.com/docs/api-reference/chat/create
- Bray, T. (Ed.). (2017). *The JavaScript Object Notation (JSON) data
  interchange format* (RFC 8259). Internet Engineering Task Force.
  https://doi.org/10.17487/RFC8259
- OpenAI. (2024). *Streaming API responses*. OpenAI API documentation.
  https://platform.openai.com/docs/guides/streaming-responses
- WHATWG. (n.d.). *Server-sent events*. HTML Living Standard.
  https://html.spec.whatwg.org/multipage/server-sent-events.html
- OpenAI. (2024). *Function calling*. OpenAI API documentation.
  https://platform.openai.com/docs/guides/function-calling
- Schick, T., Dwivedi-Yu, J., Dessì, R., Raileanu, R., Lomeli, M.,
  Hambro, E., Zettlemoyer, L., Cancedda, N., & Scialom, T. (2023).
  Toolformer: Language models can teach themselves to use tools.
  *Advances in Neural Information Processing Systems, 36*.
  https://arxiv.org/abs/2302.04761
- Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K., &
  Cao, Y. (2023). ReAct: Synergizing reasoning and acting in language
  models. *International Conference on Learning Representations*.
  https://arxiv.org/abs/2210.03629
