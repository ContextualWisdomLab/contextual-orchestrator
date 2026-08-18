# KV credential resolution

Runtime provider secrets (model provider API keys) are resolved from a
**pluggable key/value credential registry**, never from `os.getenv` at request
time. This document describes the `get_credential` seam, the KV backends, the
bootstrap flow, and why the previous `api_key_env` environment pattern is
superseded.

## The `get_credential` seam

`contextual_orchestrator/credentials.py` exposes two functions plus a small
pluggable backend interface:

```python
from contextual_orchestrator import get_credential, register_credential

get_credential("OPENAI_API_KEY")        # -> "sk-..." | None (from the KV)
register_credential("OPENAI_API_KEY", value)   # writes into the KV
```

The orchestrator resolves an agent's provider key through this seam only:

- Remote `ModelAgent` records use `get_credential(agent.credential_name)`.
- Direct `mlx://` workers are intentionally keyless and never receive a
  provider credential.
- Authenticated loopback `local://` gateways may use the separate,
  explicitly named `ModelAgent.local_credential_key`.
- `ModelClient._send()` resolves the transport-specific key before building
  the outgoing request.
- `ModelClient._validate_provider()` requires the credential to be **resolvable**
  before any egress when that transport names a key. A non-mock agent whose
  credential is missing raises `NotConfigured` — it never silently falls back
  to `os.getenv`.

Mock agents (`base_url` starting with `mock://`) early-return before any
credential logic and stay keyless.

### Agent credential naming

`ModelAgent` gained a `credential_key` field (default `"OPENAI_API_KEY"`) that
names the credential to resolve from the KV:

```json
{ "id": "coding_agent", "model": "gpt-5.5",
  "base_url": "https://api.openai.com/v1", "credential_key": "OPENAI_API_KEY" }
```

**Back-compat:** the legacy `api_key_env` field is still accepted. When set, its
string is treated as the **credential name** in the KV — it is *not* read as an
environment variable. `ModelAgent.credential_name` returns `api_key_env` when
present, otherwise `credential_key`.

### Direct MLX versus an authenticated local gateway

These schemes have different credential contracts:

```json
{ "id": "mlx_worker", "model": "mlx-community/gemma-4-e4b-it-4bit",
  "base_url": "mlx://127.0.0.1:18083/v1" }
```

The direct `mlx://` transport is a loopback-only, keyless mlx-lm server. A
`credential_key` or remote `OPENAI_API_KEY` is never forwarded to it. A
`local://` URL instead denotes the contextual-orchestrator loopback gateway;
when that gateway requires bearer authentication, configure only its explicit
local token name:

```json
{ "id": "mlx_gateway", "model": "mlx-community/gemma-4-e4b-it-4bit",
  "base_url": "local://127.0.0.1:18084/v1",
  "local_credential_key": "LOCAL_GATEWAY_TOKEN" }
```

The gateway owns worker template settings, so `chat_template_kwargs` is sent
only to direct `mlx://` workers. Missing local gateway credentials fail closed;
they do not fall back to an OpenAI credential or an unauthenticated request.

## Backends

Backends implement a tiny interface (`get(name)` / `set(name, value)`), selected
at bootstrap by `CONTEXTUAL_ORCHESTRATOR_KV_BACKEND`:

| Selector   | Backend                        | Use                                   |
| ---------- | ------------------------------ | ------------------------------------- |
| `memory`   | `InMemoryCredentialBackend`    | dev/tests — **default**, no Postgres  |
| `postgres` | `PostgresCredentialBackend`    | production — pgcrypto-encrypted registry |

Tests and the app suite run on the in-memory backend, so **no KV or Postgres is
required to run `pytest`**.

### Postgres pgcrypto registry (org reference pattern)

The default production backend mirrors xtrmLLMBatchPython's pgcrypto-encrypted
Postgres credential registry. New DB objects use 2+ word snake_case names:

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE IF NOT EXISTS provider_credentials (
    credential_name text PRIMARY KEY,
    encrypted_value bytea NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
```

Secrets are encrypted at rest with `pgp_sym_encrypt(value, passphrase)` and read
back with `pgp_sym_decrypt(encrypted_value, passphrase)`.

## The single allowed env use: bootstrap transport

Environment variables are permitted in **exactly one place** — as bootstrap
transport to *connect to and unlock the KV itself*, never as the runtime source
of a provider key:

| Variable                                   | Role                                   |
| ------------------------------------------ | -------------------------------------- |
| `CONTEXTUAL_ORCHESTRATOR_KV_BACKEND`       | backend selector (`memory`/`postgres`) |
| `CONTEXTUAL_ORCHESTRATOR_KV_DSN`           | Postgres DSN to reach the registry     |
| `CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE`    | pgcrypto passphrase to unlock secrets  |

These open the KV. They are not provider API keys.

## Bootstrapping a credential

A one-shot CLI subcommand writes a deploy-time secret into the KV:

```bash
# Preferred: pipe the secret over stdin (keeps it out of argv and the app env)
echo "$OPENAI_API_KEY" | python -m contextual_orchestrator \
    register-credential --name OPENAI_API_KEY --value-stdin

# Or use bootstrap transport: read the value from a named env var at bootstrap
python -m contextual_orchestrator \
    register-credential --name OPENAI_API_KEY --from-env OPENAI_API_KEY
```

Run this against the `postgres` backend so the value persists:

```bash
export CONTEXTUAL_ORCHESTRATOR_KV_BACKEND=postgres
export CONTEXTUAL_ORCHESTRATOR_KV_DSN="postgresql://user@host/db"
export CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE="…"
echo "$OPENAI_API_KEY" | python -m contextual_orchestrator \
    register-credential --name OPENAI_API_KEY --value-stdin
```

### CI/deploy injection without runtime `os.getenv`

Inject `secrets.OPENAI_API_KEY` into the **bootstrap job only**, and pipe it to
`register-credential`. The running orchestrator never sees the secret in its
environment:

```yaml
# deploy job (NOT the app test job)
- name: Seed provider credential into the KV
  env:
    CONTEXTUAL_ORCHESTRATOR_KV_BACKEND: postgres
    CONTEXTUAL_ORCHESTRATOR_KV_DSN: ${{ secrets.KV_DSN }}
    CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE: ${{ secrets.KV_PASSPHRASE }}
  run: |
    printf '%s' "${{ secrets.OPENAI_API_KEY }}" \
      | python -m contextual_orchestrator register-credential \
          --name OPENAI_API_KEY --value-stdin
```

The application test workflow must **not** receive `OPENAI_API_KEY`: tests run on
the mock pool and the in-memory backend and stay green without any secret.

## Why this supersedes `api_key_env`

The previous pattern read `os.environ.get(agent.api_key_env)` at request time —
the environment *was* the runtime source of the provider key. Per the org
principle **"No os.getenv, values from KV"**, that source moves to the KV:

- Secrets live encrypted in the registry, resolved via `get_credential`.
- Missing credentials fail loudly (`NotConfigured`) instead of silently using an
  ambient env var.
- Env is demoted to bootstrap transport for connecting to the KV.

`api_key_env` is retained only as a back-compat *credential name* alias.

## Server authentication and Keyverse

Provider credentials and gateway bearer authentication are separate concerns.
The CLI resolves named server tokens from this KV when `--auth-token-key`,
`--admin-token-key`, or `--inference-token-key` is used; it does not read the
legacy `CONTEXTUAL_ORCHESTRATOR_*TOKEN` environment variables at request time.
Explicit token flags remain local-development escape hatches.

For production ecosystem access, construct `SecurityConfig` with a reviewed
`bearer_verifier` that validates Keyverse-issued OIDC tokens. The adapter must
own issuer/audience/signature/expiry/scope validation and key rotation; do not
decode JWTs with a string split or place Keycloak admin credentials in this
repository. Keyverse RP registration, desired-state reconciliation, and
confidential-client secret placement remain deployment-controller operations.

## Multi-provider auto-discovery

Once a provider's credential is registered in the KV, `contextual_orchestrator`
can discover that provider's available models and turn them into agent-pool
candidates automatically — no hand-written `agents.json` entry required.
`contextual_orchestrator/model_discovery.py` covers five providers out of the
box, all resolved through `get_credential` (never fabricated, never read from
`os.getenv`):

| Provider          | KV credential name       | Auth header       |
| ------------------ | ------------------------ | ------------------ |
| OpenAI              | `OPENAI_API_KEY`         | `Bearer <token>`   |
| OpenRouter          | `OPENROUTER_API_KEY`     | `Bearer <token>`   |
| NVIDIA NIM (primary)| `NVIDIA_NIM_API_KEY`     | `Bearer <token>`   |
| NVIDIA NIM (sub)    | `NVIDIA_NIM_API_KEY_SUB` | `Bearer <token>`   |
| Bytez               | `BYTEZ_API_KEY`          | `Key <token>`      |

Bytez's `Key <token>` scheme (rather than `Bearer`) is why `ModelAgent` has an
`auth_scheme` field (default `"Bearer"`) — set it per agent when a provider
doesn't use the OpenAI-compatible default.

Register any subset of the five keys, then discover:

```bash
echo "$OPENROUTER_API_KEY" | python -m contextual_orchestrator \
    register-credential --name OPENROUTER_API_KEY --value-stdin

python -m contextual_orchestrator discover-models --agents-db state/pool.db
```

A provider with nothing registered is silently skipped — registering one key
or all five both work. `discover-models` prints a JSON report
(`discovered_count`, `priced_count`, `providers_with_errors`, and each
`{provider, model, agent_id}` found) and, with `--agents-db`, persists the
discovered agents into the same sqlite agent-pool file `--serve --agents-db`
reads — the same durable-overlay mechanism the admin console's "add agent"
uses (`TaskOrchestrator.sync_discovered_agents`, an idempotent upsert of
`add_agent`/`patch_agent`'s existing persistence path). Discovered agents are
added **disabled**, so a newly found model never starts serving traffic
before an operator opts it in.

Cost-based auto-optimization reuses the existing price-table selector rather
than adding a new one: `model_discovery.refresh_price_book` writes any
provider-reported per-token pricing into `PriceBook`, and
`model_discovery.select_cheapest_discovered_agent` calls
`batch_routing.cheapest_upstream` to pick the lowest-cost candidate among
discovered models for a representative request shape.

## Gateway direction

This credential seam is the durable first step of growing
`contextual-orchestrator` into a LiteLLM-class model gateway: one stable
`get_credential` boundary that a multi-provider key store, rotation, and
per-tenant scoping can grow behind without touching the routing engine. The
Rust/Python hybrid gateway is a later, separately-approved effort and is **not**
started here.
