# KV credential resolution

Application secrets (model provider keys and API-auth tokens) are resolved from
a **pluggable key/value credential registry**, never from argv or `os.getenv` at
runtime. Secret values enter the application over stdin only. This document
describes the `get_credential` seam, the KV backends, the bootstrap flow, and
why the previous environment pattern is superseded.

## The `get_credential` seam

`contextual_orchestrator/credentials.py` exposes two functions plus a small
pluggable backend interface:

```python
from contextual_orchestrator import get_credential, register_credential

get_credential("OPENAI_API_KEY")        # -> "sk-..." | None (from the KV)
register_credential("OPENAI_API_KEY", value)   # writes into the KV
```

The orchestrator resolves an agent's provider key through this seam only:

- `ModelClient.chat()` calls `get_credential(agent.credential_name)`.
- `ModelClient._send()` reads the key the same way for the outgoing request.
- `ModelClient._validate_provider()` requires the credential to be **resolvable**
  before any egress. A non-mock agent whose credential is missing raises
  `NotConfigured` — it never silently falls back to `os.getenv`.

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
# The only supported value transport: stdin (keeps it out of argv/app env)
echo "$OPENAI_API_KEY" | python -m contextual_orchestrator \
    register-credential --name OPENAI_API_KEY --value-stdin
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

### Ephemeral in-memory bootstrap and API authentication

An in-memory server can receive multiple named secrets as one JSON object on
stdin. Provider and API-auth values are registered before serving; CLI options
contain only their KV names:

```bash
printf '{"OPENAI_API_KEY":"%s","ORCHESTRATOR_AUTH_TOKEN":"%s"}' \
  "$OPENAI_API_KEY" "$CONTEXTUAL_ORCHESTRATOR_TOKEN" \
  | python -m contextual_orchestrator --serve \
      --agents examples/agents.openai.json \
      --auth-token-credential ORCHESTRATOR_AUTH_TOKEN \
      --bootstrap-credentials-stdin
```

Split access uses `--admin-token-credential NAME` together with
`--inference-token-credential NAME`. Both values must already be present in the
KV or be included in the stdin JSON object.

## Why this supersedes `api_key_env`

The previous pattern read `os.environ.get(agent.api_key_env)` at request time —
the environment *was* the runtime source of the provider key. Per the org
principle **"No os.getenv, values from KV"**, that source moves to the KV:

- Secrets live encrypted in the registry, resolved via `get_credential`.
- Missing credentials fail loudly (`NotConfigured`) instead of silently using an
  ambient env var.
- Env is demoted to bootstrap transport for connecting to the KV.

`api_key_env` is retained only as a back-compat *credential name* alias.

## Gateway direction

This credential seam is the durable first step of growing
`contextual-orchestrator` into a LiteLLM-class model gateway: one stable
`get_credential` boundary that a multi-provider key store, rotation, and
per-tenant scoping can grow behind without touching the routing engine. The
Rust/Python hybrid gateway is a later, separately-approved effort and is **not**
started here.
