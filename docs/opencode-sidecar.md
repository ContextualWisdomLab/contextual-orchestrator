# OpenCode / Strix sidecar contract

ContextualWisdomLab no longer uses GitHub Models. OpenCode and Strix should
call **this repo** as one OpenAI-compatible provider.

```
register the 5 secrets → serve on localhost → OpenCode provider
baseURL http://127.0.0.1:8000/v1
model   contextual-orchestrator
```

App unit tests (`.github/workflows/tests.yml`) and the Security workflow stay
**secret-free**. Seeding lives only in `.github/workflows/opencode-sidecar.yml`
(`workflow_dispatch` / `workflow_call`, not `pull_request`).

## Tokens

| Variable | Role |
| --- | --- |
| `CONTEXTUAL_ORCHESTRATOR_TOKEN` | Single local token (`--auth-token`). Enough for OpenCode. |
| `CONTEXTUAL_ORCHESTRATOR_INFERENCE_TOKEN` | Inference-only token when split from `--admin-token`. |
| `CONTEXTUAL_ORCHESTRATOR_ADMIN_TOKEN` | Admin console / `/api/v1/*` when using split tokens. |

Generate a loopback token:

```bash
export CONTEXTUAL_ORCHESTRATOR_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

## Org secrets → KV (bootstrap only)

These GitHub Actions secret *names* are registered into the credential KV.
Runtime still uses `get_credential`, never `os.getenv` at request time.

| Secret | Typical agents |
| --- | --- |
| `NVIDIA_NIM_API_KEY` | NIM primary Nemotron Super 49B / 120B |
| `NVIDIA_NIM_API_KEY_SUB` | NIM secondary (same host, failover key) |
| `OPENAI_API_KEY` | `https://api.openai.com/v1` |
| `OPENROUTER_API_KEY` | `https://openrouter.ai/api/v1` |
| `BYTEZ_API_KEY` | `https://api.bytez.com/models/v2/openai/v1` |

A missing secret **skips that upstream** and keeps the rest serving.

### Same-process CI (in-memory KV)

Memory KV dies when the process exits, so CI must seed inside the serve process:

```bash
python -m contextual_orchestrator --serve \
  --seed-from-env \
  --agents examples/agents.production.json \
  --agents-db "$RUNNER_TEMP/agents.db" \
  --host 127.0.0.1 \
  --port 8000 \
  --auth-token "$CONTEXTUAL_ORCHESTRATOR_TOKEN"
```

Do not pass --allow-public-bind in CI. Bind stays `127.0.0.1`.

### Postgres deploy (KV survives process restart)

```bash
export CONTEXTUAL_ORCHESTRATOR_KV_BACKEND=postgres
export CONTEXTUAL_ORCHESTRATOR_KV_DSN="postgresql://user@host/db"
export CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE="…"

python -m contextual_orchestrator seed-provider-catalog \
  --from-env --skip-missing \
  --agents examples/agents.production.json \
  --agents-db /var/lib/contextual-orchestrator/agents.db \
  --discover-models   # default on; live GET /v1/models wins over the static seed

# or one name at a time
printf '%s' "$OPENAI_API_KEY" | python -m contextual_orchestrator \
  register-credential --name OPENAI_API_KEY --value-stdin
```

## OpenCode provider block

```json
{
  "provider": {
    "contextual-orchestrator": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Contextual Orchestrator",
      "options": {
        "baseURL": "http://127.0.0.1:8000/v1",
        "apiKey": "{env:CONTEXTUAL_ORCHESTRATOR_TOKEN}"
      },
      "models": {
        "contextual-orchestrator": {
          "name": "contextual-orchestrator"
        }
      }
    }
  }
}
```

Strix / any OpenAI SDK uses the same `baseURL` and `model`.

OpenCode can list the composed catalog:

```bash
curl -sS http://127.0.0.1:8000/v1/models \
  -H "authorization: Bearer $CONTEXTUAL_ORCHESTRATOR_TOKEN"
```

The list always includes `contextual-orchestrator` plus surfaced worker model
ids from live discovery (static seed only when a provider list fails).

## Smoke curl

```bash
curl -sS http://127.0.0.1:8000/v1/chat/completions \
  -H "authorization: Bearer $CONTEXTUAL_ORCHESTRATOR_TOKEN" \
  -H "content-type: application/json" \
  -d '{"model":"contextual-orchestrator","messages":[{"role":"user","content":"Write one sentence."}]}'
```

Expect HTTP 200 when at least one of the five secrets is registered. When every
secret is missing the gateway fail-closes (`NotConfigured`) and does **not**
fall back to GitHub Models.

Reusable workflow: `.github/workflows/opencode-sidecar.yml` (`workflow_call`).
The org OpenCode review pipeline in `ContextualWisdomLab/.github` should call
that workflow (or start this server the same way) instead of GitHub Models.
