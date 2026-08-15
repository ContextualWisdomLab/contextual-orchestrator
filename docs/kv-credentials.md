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

## Allowed environment use: bootstrap transport and one-shot config seeding

Environment variables are permitted only during process bootstrap. They may
select, connect to, and unlock the KV, or seed the non-secret provider host
allowlist exactly once. They are never the request-time source of a provider
key or mutable request-time policy:

| Variable | Bootstrap role |
| -------- | -------------- |
| `CONTEXTUAL_ORCHESTRATOR_KV_BACKEND` | Select the `memory` or `postgres` credential backend. |
| `CONTEXTUAL_ORCHESTRATOR_KV_DSN` | Connect to the Postgres registry. |
| `CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE` | Unlock encrypted provider credentials. |
| `CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS` | Seed `provider/allowed_hosts` once when that KV key is initially absent. |

The first three values select or open the KV. The provider-host value is a
one-shot bootstrap input copied into the runtime config store. After store
installation and first seeding, the KV value is authoritative and later
environment mutations have no effect. None of these values is a provider API
key.

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

## Gateway direction

This credential seam is the durable first step of growing
`contextual-orchestrator` into a LiteLLM-class model gateway: one stable
`get_credential` boundary that a multi-provider key store, rotation, and
per-tenant scoping can grow behind without touching the routing engine. The
Rust/Python hybrid gateway is a later, separately-approved effort and is **not**
started here.

## Non-secret runtime config (provider host allowlist)

Operator tunables that are not secrets also resolve from the KV config store
(`get_runtime_config_store` / `get_config_value`), never from `os.getenv` at
request time.

| Category | Key | Purpose |
| -------- | --- | ------- |
| `provider` | `allowed_hosts` | Comma-separated or list of HTTPS provider hostnames allowed for egress. Empty = no extra filter (public-IP checks still apply). |

Bootstrap: if `provider/allowed_hosts` is unset, the first read may seed the store
from `CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS`. After seeding, only the
store is authoritative; live environment mutations do not change request-time
policy.

```python
from contextual_orchestrator.kv_config import set_config_value

set_config_value(
    "provider",
    "allowed_hosts",
    "api.openai.com,integrate.api.nvidia.com",
)
```
