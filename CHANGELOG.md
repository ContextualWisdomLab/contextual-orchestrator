# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Optional `model_group` on agents: peers in the same group race for first valid
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
