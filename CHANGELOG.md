# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
- Apply request `top_p`, `presence_penalty`, and `frequency_penalty` on
  streamed route completions. `stream_chat` now copies the same
  request-scoped defaults `chat()` already used, so a streamed invoice
  summary at `top_p=0.1` is not billed with the provider nucleus default.
  Next action: send the nucleus and penalty values you want on `stream=true`
  route bodies; they are no longer dropped.
- Fail closed on inbound JSON request framing before the socket read.
  Missing `Content-Length` is `length_required` (411). Signed, non-decimal,
  or duplicate lengths are `invalid_content_length`. Oversized declared
  lengths stay `request_too_large`. Chunked `Transfer-Encoding` is
  `unsupported_transfer_encoding`. Next action: send one unsigned decimal
  `Content-Length` that matches the JSON bytes; do not send `-1` or chunked
  bodies.

### References

- OpenAI. (2024). *Create chat completion*. OpenAI API reference.
  https://platform.openai.com/docs/api-reference/chat/create
- Bray, T. (Ed.). (2017). *The JavaScript Object Notation (JSON) data
  interchange format* (RFC 8259). Internet Engineering Task Force.
  https://doi.org/10.17487/RFC8259
- Holtzman, A., Buys, J., Du, L., Forbes, M., & Choi, Y. (2020). The
  curious case of neural text degeneration. *International Conference on
  Learning Representations*. https://arxiv.org/abs/1904.09751
- Fielding, R. (Ed.), Nottingham, M. (Ed.), & Reschke, J. (Ed.). (2022).
  *HTTP semantics* (RFC 9110). RFC Editor.
  https://doi.org/10.17487/RFC9110
- Fielding, R. (Ed.), Nottingham, M. (Ed.), & Reschke, J. (Ed.). (2022).
  *HTTP/1.1* (RFC 9112). RFC Editor. https://doi.org/10.17487/RFC9112
