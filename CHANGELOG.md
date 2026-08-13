# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- OpenAI Completions and chat Completions **request-scoped sampling passthrough** via
  `ModelClient` defaults (`temperature`, `top_p`, `max_tokens`, `presence_penalty`,
  `frequency_penalty`) restored after each request (PR band #298–#306).
- Cost-ledger attribution parity for Completions and chat: `user`→`account`, request
  `model`→`model_name` (explicit attribution wins on rollup flatten), default
  `service` of `completions_api` / `chat_completions_api` (#299–#304).
- Fail-closed honesty for unapplied OpenAI fields on Completions and chat
  (`echo=true`, `best_of>1`, non-empty `suffix`, `n>1`, integer `logprobs`, `stop`,
  `logit_bias`, `seed` where not wired) (#288–#297, #307–#309 band).

### Changed
- `UsageRecord.as_dict` prefers pinned `attribution.model_name` for cost rollups when
  set, else the served model id (#302).

### Docs
- Sampling/attribution honesty doctoring note with APA 7th citations under
  `docs/doctoring/openai-sampling-attribution.md`.


### Added
- Role-differentiated sampling temperatures for paper-role ablation.
- Optional `model_group` on agents (create/patch/admin payload): peers in the same group race for first valid
  completion to remove replica tail latency (issue #102).
- Coordinated disclosure doctoring (`docs/doctoring/security-disclosure-lifecycle.md`)
  and root `ARCHITECTURE.md` pointer (PR path).
- Fail-closed commercial release authorization evidence (`product_evidence_status`
  vs `release_authorization`; issue #103).
- Price-aware live routing via `--price-per-million` and admin KV credential
  registration with HttpOnly operator session (PR #111 path).

### Security
- Audited Semgrep suppressions for fixed SQL placeholders, intentional TLS
  opt-out, and validated provider urllib egress.
- Provider egress pinning and Atheris interpreter lock work tracked on security
  PRs (see #96).

## [0.1.0] - 2026-07-13

### Added
- Initial OpenAI-compatible orchestration gateway with route/conduct paths,
  mock agents, admin console, and commercial evidence surfaces.
