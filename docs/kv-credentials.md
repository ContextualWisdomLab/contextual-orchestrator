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

### Browser operator session (admin console)

The `/admin` HTML shell is public so operators can open the console. Data and
mutation endpoints stay admin-scoped. Establish a same-origin session once:

1. Open **Integrations → Operator session** and submit the admin bearer token, or
2. `POST /admin/session` with `{"token":"..."}` (or `Authorization: Bearer …`).

The response sets the HttpOnly cookie `contextual_orchestrator_session`
(`SameSite=Strict`, default `Max-Age` 12 hours). The cookie value is an
**opaque server-side session id**, never the admin bearer itself — so the
long-lived secret is not replayed on every browser request and cannot be used
as `Authorization: Bearer` if stolen from cookie storage. `DELETE /admin/session`
revokes the id and clears the cookie. Subsequent browser calls use
`credentials: "same-origin"` and never keep the raw admin secret in JavaScript.
Reverse proxies may instead inject `Authorization` on every request; both
mechanisms are accepted.

### Registering a credential from the admin frontend

`POST /admin/api/credentials` (admin scope) lets the `/admin` console — or any
authenticated operator tool — write a named secret into the KV without a shell
session, so an operator never has to hand the raw value to a deploy script:

```bash
# Secret value comes from stdin (or a protected file) so it never lands in argv or shell history.
# Prefer the same-origin admin session cookie (POST /admin/session once in the browser)
# or a reverse proxy that injects Authorization for authenticated operators.
printf '%s' "$LITELLM_API_KEY" | jq -Rn --arg name LITELLM_API_KEY \
  '{name: $name, value: input}' \
  | curl -X POST http://127.0.0.1:8000/admin/api/credentials \
      -H "authorization: Bearer $ADMIN_TOKEN" \
      -H "content-type: application/json" \
      --data-binary @-
# -> {"registered": "LITELLM_API_KEY"}
```

`name` must be `UPPER_SNAKE_CASE` (1-64 characters); `value` must be a
non-empty string. The response never echoes `value`, and no `GET` endpoint
returns it — this is a write-only seam into the same registry `get_credential`
reads. This is the whole scope of the frontend/Keyverse boundary described
below: the gateway writes secrets into the KV it already owns, it does not
implement OIDC identity itself (see "Server authentication and Keyverse").

To wire that credential to a live agent, give the agent's `credential_key`
the same name, e.g. an OpenAI-compatible gateway (LiteLLM proxy or similar)
reached through the org's LLM gateway:

```json
{ "id": "gateway_agent", "model": "your-gateway-model-name",
  "base_url": "https://your-litellm-compatible-gateway/v1",
  "credential_key": "LITELLM_API_KEY", "tags": ["reasoning", "coding"] }
```

`base_url` is deployment data (agent pools are data, not code — see
`examples/agents.openai.json`); this repo does not hardcode or guess it.
Pair this with `--price-per-million` (see `docs/architecture.md`) so live
routing actually prefers the cheapest equally-capable agent once real prices
are known.

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
