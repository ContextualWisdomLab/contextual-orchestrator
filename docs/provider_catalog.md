# Provider catalog operator guide

This guide turns the five existing organization provider secrets into the
runtime chat-model pool without placing API-key values in source, generated
agents JSON, or the long-running process environment.

## Required GitHub Actions secrets

Provider credentials:

- `NVIDIA_NIM_API_KEY`
- `NVIDIA_NIM_API_KEY_SUB`
- `BYTEZ_API_KEY`
- `OPENROUTER_API_KEY`
- `OPENAI_API_KEY`

Durable credential/catalog bootstrap:

- `CONTEXTUAL_ORCHESTRATOR_KV_DSN`
- `CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE`

The five provider keys alone cannot create a durable database result. The DSN
and passphrase identify and unlock the existing pgcrypto registry/catalog. If
either is absent, the protected sync fails instead of reporting success against
a process-local registry that disappears before the service can use it.

## First synchronization

After this feature reaches protected `main`:

1. Open **Actions → Provider Catalog Sync → Run workflow**.
2. Select protected `main` and the `production` environment.
3. Wait for **Seed encrypted credentials and refresh model catalog**.
4. Read only the safe summary:
   - `candidate_agent_count` must be greater than zero;
   - intended accounts should be `refreshed`;
   - `stale_available` is serviceable but requires investigation;
   - `failed` means that account has no current or prior usable catalog.
5. Diagnose with credential names and stable error codes, never with values.

The same workflow runs every six hours. Each account refresh is isolated so one
outage cannot erase another account or its own last complete model set.

## Start the gateway from the catalog

```bash
export CONTEXTUAL_ORCHESTRATOR_CATALOG_DSN="$CONTEXTUAL_ORCHESTRATOR_KV_DSN"
python -m contextual_orchestrator --serve \
  --provider-catalog-dsn "$CONTEXTUAL_ORCHESTRATOR_CATALOG_DSN" \
  --admin-token "$CONTEXTUAL_ORCHESTRATOR_ADMIN_TOKEN" \
  --inference-token "$CONTEXTUAL_ORCHESTRATOR_INFERENCE_TOKEN" \
  --host 127.0.0.1 \
  --port 8000
```

`--provider-catalog-dsn` is authoritative. It replaces the seed agents file with
enabled chat/reasoning/coding rows. An unavailable or empty catalog is a startup
error; the process does not silently start `examples/agents.mock.json`.

OpenAI, OpenRouter, and NVIDIA NIM use the inherited hardened
OpenAI-compatible transport. Bytez uses its native adapter. A Bytez request that
needs unsupported Responses/tool passthrough fails closed; select an eligible
provider whose contract supports that API surface.

## Confirm the pool

Use the authenticated admin agent-pool endpoint or console and verify:

- provider names match successfully refreshed accounts;
- NVIDIA primary and secondary have distinct agent ids and credential names;
- generated agent configuration contains no provider value;
- embedding, reranking, image-generation, speech, moderation, video, and
  `unknown` inventory does not appear as chat workers;
- reasoning/coding/vision/audio tags appear only on chat-capable candidates;
- unknown context and price remain absent/null rather than zero;
- disabled accounts disappear from runtime candidates but remain in history.

## Common failures

### `provider credential inventory is incomplete`

Add or repair the exact missing Actions secret, then rerun the protected
workflow. Required bootstrap performs no partial credential write.

### `provider catalog requires a PostgreSQL DSN`

Configure `CONTEXTUAL_ORCHESTRATOR_KV_DSN`. Do not replace the durable production
path with temporary SQLite or memory.

### `catalog_authentication_failed`

Rotate or reauthorize the named provider key. The catalog client does not retry
401/403 in a loop.

### `stale_available`

The current refresh failed, but the prior complete catalog remains. Check
provider status, egress, entitlement, and rate limits. The next schedule retries
within bounded limits.

### `no usable chat-capable provider model exists after catalog refresh`

All enabled accounts lack a current or prior eligible chat model. Restore at
least one provider before starting the gateway. Non-chat inventory is retained
but cannot satisfy chat service.

### Bytez native error

Confirm the selected model is a text-generation/chat candidate. Route OpenAI
Responses, tool calling, multimodal content, or unsupported output contracts to
a compatible provider. Do not add shape guessing or silent repair.

## Rotation without downtime

1. Replace the value under the same Actions secret name.
2. Run Provider Catalog Sync manually.
3. Verify the account refresh and send a bounded canary.
4. Revoke the old key.
5. Confirm the next scheduled refresh and runtime call use the updated registry
   value.

Model rows refer to the stable credential name, so rotation requires no
secret-bearing model or consumer configuration change.

For incident response, rollback, and evidence interpretation, read
[`docs/doctoring/durable-provider-catalog.md`](doctoring/durable-provider-catalog.md).
