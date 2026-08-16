# Changelog

All notable changes to Contextual Orchestrator are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Pop JSON-null `tool.function` `description` / `parameters` / `strict` in
  place before provider proxy so SDK optional defaults match omit
  (`#638` unique tip).
- Pop JSON-null or blank `response_format.json_schema.description` and
  JSON-null `strict`; fail closed on unknown inner keys and non-string
  descriptions so structured-output passthrough cannot smuggle or forward
  null optionals.
- Pop empty or whitespace-only `tool.function.description` before proxy
  so SDK blank defaults match omit.
- Accept official Responses `text.format` (flat `type` / `name` / `schema`)
  instead of rejecting every non-empty `text` with `invalid_text`. Pop
  JSON-null or blank `description` and JSON-null `strict` before proxy.

### Documentation

- Compatibility honesty next-action notes in `docs/rest_api_design.md`.
- APA 7th citations for OpenAI Chat Completions, Structured Outputs, and
  IETF JSON Schema 2020-12 in `docs/papers/README.md`.
