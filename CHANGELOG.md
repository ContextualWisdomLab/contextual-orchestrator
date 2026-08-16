# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Chat `tools` / `response_format` passthrough now requires a pool-served
  `model` and rejects `stream=true` with named `invalid_model` /
  `invalid_stream` before the single-agent early-return. Buyers no longer
  get a silent worker when `model` is omitted, or a JSON 200 when they
  asked for SSE. See OpenAI. (n.d.). *Chat Completions API*.
  https://platform.openai.com/docs/api-reference/chat/create
