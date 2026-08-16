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
  missing secret skips that upstream. Optional `GET /v1/models` discovery
  appends chat models; providers without a list API keep the static seed
  (`docs/doctoring/provider-catalog.md`).
- OpenCode/Strix sidecar contract: loopback `http://127.0.0.1:8000/v1`, model
  `contextual-orchestrator` (`.github/workflows/opencode-sidecar.yml`,
  `docs/opencode-sidecar.md`). App tests and Security stay secret-free.

### Changed

- Unconfigured remote workers are skipped at select/failover time. When every
  provider credential is missing, routing raises `NotConfigured` and does not
  fall back to GitHub Models.
- Malformed upstream chat.completion bodies raise `ProviderResponseError` so
  the gateway failovers or returns a JSON error instead of crashing.
