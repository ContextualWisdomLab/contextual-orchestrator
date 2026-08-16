# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses semantic versioning.

## [Unreleased]

### Added

- Tools and `response_format` passthrough now stream OpenAI-compatible SSE
  (`chat.completion.chunk`, including `tool_calls` deltas) when `stream=true`.
  The default OpenAI SDK tool-calling body is no longer a 400 `invalid_stream`
  or a silent JSON completion. `stream_options.include_usage=true` still fails
  closed. Grounded in Hickson (2015) and OpenAI (n.d.); see
  `docs/papers/README.md`.

### Buyer next action

- Send a pool `model` and a non-empty `messages` array. Set `stream=true` on
  tool-calling requests to receive streamed `tool_calls`. Omit
  `stream_options.include_usage` until usage-on-stream is implemented.
