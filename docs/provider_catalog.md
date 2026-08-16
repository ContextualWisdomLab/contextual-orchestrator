# Provider catalog operator guide

Use this guide to turn the five existing organization provider secrets into the
runtime model pool without placing API-key values in source, agent JSON, or the
long-running process environment.

## Required Actions secrets

Provider credentials:

- `NVIDIA_NIM_API_KEY`
- `NVIDIA_NIM_API_KEY_SUB`
- `BYTEZ_API_KEY`
- `OPENROUTER_API_KEY`
- `OPENAI_API_KEY`

Durable registry/catalog bootstrap:

- `CONTEXTUAL_ORCHESTRATOR_KV_DSN`
- `CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE`

The provider keys already named above are not sufficient by themselves to create
a durable database result. The DSN and passphrase tell the trusted job where the
pgcrypto registry/catalog lives and how to decrypt credentials later. When either
is absent, the workflow fails instead of reporting success against temporary
memory.

## First synchronization

After the feature reaches protected `main`:

1. Open **Actions → Provider Catalog Sync → Run workflow**.
2. Select protected `main` and the `production` environment.
3. Wait for **Seed credentials and refresh durable catalog** to finish.
4. Read only the safe summary:
   - `candidate_agent_count` must be greater than zero;
   - each intended account should be `refreshed`;
   - `stale_available` is serviceable but requires provider investigation;
   - `failed` means that account has no usable discovered model.
5. Do not copy a provider key into an issue when diagnosing a failure. Use the
   credential name and stable error code.

The same workflow runs every six hours. Each provider refresh is isolated, so one
outage does not erase other accounts or its own last-known-good models.

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

`--provider-catalog-dsn` is authoritative. It disables the seed agents file and
loads enabled database models. Startup fails when the database is unavailable or
contains no enabled candidate; it does not silently start `examples/agents.mock.json`.

OpenAI, OpenRouter, and NVIDIA NIM models use the hardened OpenAI-compatible
transport. Bytez models use the native Bytez adapter. A Bytez request that needs
an unsupported Responses/tool passthrough fails closed rather than returning a
fabricated OpenAI object; another eligible provider should be selected for that
contract.

## Confirm the pool

Use the authenticated admin agent-pool endpoint or console and verify:

- provider names include the accounts refreshed successfully;
- NVIDIA primary and secondary entries have different agent ids and credential
  names;
- no agent JSON contains a provider key value;
- reasoning, coding, vision, audio, and embedding models carry only capabilities
  supported or conservatively inferred from catalog metadata;
- unknown context and price fields remain absent/null rather than zero;
- disabled accounts are absent from runtime candidates but remain in catalog
  history.

## Respond to common failures

### `provider credential inventory is incomplete`

Add or repair the exact missing Actions secret, then rerun the protected workflow.
The required bootstrap performs no partial credential write.

### `provider catalog requires a PostgreSQL DSN`

Configure `CONTEXTUAL_ORCHESTRATOR_KV_DSN`. Do not replace it with a temporary
SQLite or memory path in production.

### `catalog_authentication_failed`

Rotate or reauthorize the named provider credential. The catalog client does not
retry 401/403 repeatedly.

### `stale_available`

The current refresh failed, but the last complete catalog remains enabled. Check
provider status, egress, entitlement, and rate limits. The next scheduled job
will retry within bounded limits.

### `no usable provider model exists after catalog refresh`

All enabled accounts lack both a current and prior candidate. Restore at least
one provider or the database before starting the gateway. Do not bypass this by
starting an unlabeled mock deployment.

### Bytez response/passthrough failure

Confirm the selected model supports ordinary native chat input. Route OpenAI
Responses, tool calling, or structured passthrough to a provider whose contract
supports it. Do not add response-shape guessing.

## Rotation without downtime

1. Replace the value under the existing Actions secret name.
2. Run Provider Catalog Sync manually.
3. Verify the affected account refreshes and a canary succeeds.
4. Revoke the old key.
5. Confirm the next runtime request resolves the updated registry value.

The model catalog refers to the stable credential name, so no model-row or
consumer configuration change is needed during rotation.

For incident handling, rollback, and evidence interpretation, read
[`docs/doctoring/durable-provider-catalog.md`](doctoring/durable-provider-catalog.md).
