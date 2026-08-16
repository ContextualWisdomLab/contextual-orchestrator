# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- `/v1/responses` now accepts official `text.format` types `text`,
  `json_object`, and flat `json_schema`. JSON-null or blank `description`
  and JSON-null `strict` are popped before proxy. `text.verbosity` (except
  JSON null / blank, which are omitted) and sending both `text` and
  `response_format` return `invalid_text`. If you see `invalid_text`, send
  one official `text.format` object — do not retry a dual-plane or
  verbosity payload.
- `/v1/responses` now treats JSON `null`, empty, and whitespace `instructions` as
  **omit-real**: the key is removed before provider passthrough so OpenAI SDK
  optional defaults do not become a blank upstream system prompt. Non-string and
  >32000-character values still return `invalid_instructions`. Send a non-empty
  string when you want a system prompt; do not retry a blank payload.

## [0.1.0] - 2026-08-16

### Added

- OpenAI-compatible chat, Responses, embeddings, and batch routing surfaces with
  Fugu / TRINITY / Conductor orchestration, KV credentials, and admin evidence.
