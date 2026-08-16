# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Chat Completions tools/`response_format` passthrough now fail-closes
  `store`, `modalities`, `prediction`, `reasoning_effort`, `service_tier`,
  and `metadata` with the same named errors as the orchestration path.
  SDK tool-calling bodies can no longer bill a stored, audio, predicted,
  high-reasoning, flex-tier, or untyped-metadata completion.
- `--serve` resolves Bearer tokens from CLI flags, then the KV
  (`gateway_auth_token`, `gateway_admin_token`, `gateway_inference_token`,
  plus historical `CONTEXTUAL_ORCHESTRATOR_*` aliases). Process env is no
  longer the runtime source.

### Operator next action

Seed the gateway token with `register-credential --name gateway_auth_token`
before `--serve`. Do not export `CONTEXTUAL_ORCHESTRATOR_TOKEN` into the
app process and expect it to be read at request time.
