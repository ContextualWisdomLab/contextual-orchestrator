# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- SSE-proxy `tools` and `response_format` on `/v1/chat/completions` when
  `stream=true`. Concatenated mock content matches the non-stream JSON body;
  live providers are piped verbatim so `delta.tool_calls` survive. Next
  action: send `stream=true` when the client reads SSE; omit
  `stream_options.include_usage`.

### Fixed

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
