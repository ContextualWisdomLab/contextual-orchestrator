# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Fail-closed empty, omitted, null, non-list, and non-object `messages` on
  the tools / `response_format` passthrough path with the same
  `invalid_message` as orchestration. Next action: always send a non-empty
  `messages` array of objects with tool-calling requests.
- Fail-closed `routing.channel=batch` and `latency_tolerant=true` on
  passthrough (no batch job plane). Next action: omit those hints or set
  `channel=sync` on tool-calling requests.
- Fail-closed `seed`, `stop`, `n>1`, `logprobs`, `logit_bias`, out-of-range
  penalties, and unsupported `reasoning_effort` / `service_tier` before
  `proxy_completion`. Next action: omit those knobs on tool-calling
  requests — they are not applied and must not bill a silent drop.
- Streamed route completions apply the request `temperature` instead of
  silently falling back to `0.2`. Next action: send the temperature you
  want on `"stream": true` route calls.
- Treat official-SDK JSON `null` on optional `tools[].function.description`,
  `parameters`, and `strict` as omit-real: the keys are popped before
  `proxy_completion` so upstream providers see an omitted field, not a null
  schema. Non-null wrong types still fail closed with named `invalid_tools`.
  Next action: send those fields only when you have a real string, JSON Schema
  object, or boolean; SDK defaults of `null` are safe.

### References

- OpenAI. (2024). *Create chat completion*. OpenAI API reference.
  https://platform.openai.com/docs/api-reference/chat/create
- Bray, T. (Ed.). (2017). *The JavaScript Object Notation (JSON) data
  interchange format* (RFC 8259). Internet Engineering Task Force.
  https://doi.org/10.17487/RFC8259
