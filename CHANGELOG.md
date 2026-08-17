# Changelog

## Unreleased

### Added

- Production agent catalog (`examples/agents.production.json`) for NVIDIA NIM
  (primary + secondary Nemotron Super 49B / 120B), OpenAI, OpenRouter, and
  Bytez. Capability tags cover coding, review, and reasoning so Fugu route vs
  Conductor/TRINITY conduct can pick workers. GitHub Models, Copilot tokens,
  `gpt-5.6-luna`, and `gpt-5.6-terra` are rejected.
- `seed-provider-catalog` CLI and `--seed-from-env` serve flag register the five
  org Actions secrets (`NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_API_KEY_SUB`,
  `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `BYTEZ_API_KEY`) into the KV. A
  missing secret skips that upstream. **Live `GET /v1/models` is the primary
  catalog** after each secret is registered (KV credential, never request-time
  `os.getenv`). The static seed is fallback only when the list is missing,
  401/403/404/429/5xx, empty, or malformed. The gateway exposes
  `GET /v1/models` (`contextual-orchestrator` plus surfaced worker ids).
  (`docs/doctoring/provider-catalog.md`).
- OpenCode/Strix sidecar contract: loopback `http://127.0.0.1:8000/v1`, model
  `contextual-orchestrator` (`.github/workflows/opencode-sidecar.yml`,
  `docs/opencode-sidecar.md`). App tests and Security stay secret-free.

### Changed

- Fast-path routing is a cost-performance choose (quality per unit operator
  cost), not deterministic keyword scoring and not a walk down the seed JSON.
  429 / 5xx / timeout re-runs the same chooser on the remaining healthy pool.
  Missing credentials drop that worker from the candidate set. An empty
  healthy pool fail-closes (no GitHub Models). Deep `conduct` stays
  Conductor-style and still requires a workflow hint.
- Unconfigured remote workers are skipped at select/re-selection time. When every
  provider credential is missing, routing raises `NotConfigured` and does not
  fall back to GitHub Models.
- Malformed upstream chat.completion bodies raise `ProviderResponseError` so
  the gateway failovers or returns a JSON error instead of crashing.
- Live catalog discovery reuses `ModelClient.fetch_provider_json` (the existing
  validated urllib seam) instead of `http.client` or a second `urlopen`.
  `file://` and private/reserved list targets fail closed.
