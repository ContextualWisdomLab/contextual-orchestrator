# Provider catalog (main-line first slice)

Registering a provider credential under one of the five organization **names**
is enough for the orchestrator to discover that account's catalog and overlay
workers. Values live in the KV (`get_credential` / `register-credential`).
Env is bootstrap transport only. See [kv-credentials.md](kv-credentials.md).

## Credential names

- `NVIDIA_NIM_API_KEY` — `https://integrate.api.nvidia.com/v1/models`
- `NVIDIA_NIM_API_KEY_SUB` — same origin, independent account (quota/revocation isolated)
- `BYTEZ_API_KEY` — native `https://api.bytez.com/models/v2` with `Authorization: Key` (not OpenAI `/v1/models`)
- `OPENROUTER_API_KEY` — `https://openrouter.ai/api/v1/models`
- `OPENAI_API_KEY` — `https://api.openai.com/v1/models`

## Refresh

```bash
echo "$OPENAI_API_KEY" | python -m contextual_orchestrator \
  register-credential --name OPENAI_API_KEY --value-stdin

python -m contextual_orchestrator refresh-provider-catalog --agents examples/agents.mock.json
```

Or at serve time: `--refresh-provider-catalog`. Admin:
`POST /api/v1/provider_catalogs/refresh` and `GET /api/v1/provider_catalogs/latest`.

Failures (timeout, 429, 5xx, malformed, empty, revoked key, missing catalog)
are isolated per account, recorded in audit, and **do not invent models**.
Last-known-good rows stay. A second refresh inside 60s is throttled unless
`force` is set.

This slice does **not** copy the PR #96 DNS-pinned egress stack. Catalog HTTP
reuses `ModelClient._validate_provider` (https, host allowlist env, private-address
block). Quality/Pareto selection is [issue #86](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/86) and is a follow-up.

## Selection after overlay

Capability-first (existing role/domain tags), then known operator/catalog price.
Unpriced ≠ free. A free **channel** with a known list/original price (catalog
list field, published $/1M, or finite OpenRouter `pricing`, including a
same-document paid sibling for `:free` variants) is compared at that list
price — it is not ranked as cost 0.0. Explicit $0 with no list price may
compete as 0. Missing or non-finite catalog prices stay unpriced; no list
price is invented. Aligns with open PR #575. Do not use `cheapest_upstream` —
it treats unknown price as 0.0.
