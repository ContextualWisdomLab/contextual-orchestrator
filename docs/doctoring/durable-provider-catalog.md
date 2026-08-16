# Durable Provider Catalog Doctoring

## Purpose

This record explains why provider credentials and model catalogs are separate,
how the five configured provider accounts become an orchestration pool, which
failures are tolerated, and which failures stop service. It is the operational
source for incident response, rollback, and audit review.

## Invariants

1. Provider API-key values exist only in the encrypted credential registry.
2. The provider catalog contains credential names, never secret values.
3. `NVIDIA_NIM_API_KEY` and `NVIDIA_NIM_API_KEY_SUB` are independent accounts.
4. Pull-request code never receives production provider or database secrets.
5. A configured PostgreSQL catalog/KV is authoritative; failure cannot silently
   downgrade to process memory.
6. A failed provider refresh cannot disable its last-known-good models.
7. A complete successful refresh may disable models absent from that account's
   new complete listing.
8. Zero usable candidates is a startup/sync failure, not permission to use mocks.
9. Capability and role fit outrank context and cost; price is a bounded tie-break.
10. Native Bytez requests use its Key/input contract; unsupported OpenAI
    passthrough shapes fail closed.

## Bootstrap sequence

The trusted protected-default-branch workflow performs these actions:

1. Require non-empty `CONTEXTUAL_ORCHESTRATOR_KV_DSN`,
   `CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE`, and all five provider keys.
2. Add values to GitHub Actions masking without echoing them.
3. Select `CONTEXTUAL_ORCHESTRATOR_KV_BACKEND=postgres`.
4. Validate the complete fixed inventory before any provider credential write.
5. Upsert credentials through `register_credential()` into pgcrypto storage.
6. Refresh each provider account independently over bounded credentialed HTTPS.
7. Upsert normalized provider/model/capability/modality rows transactionally.
8. Preserve prior rows for failed accounts and classify them `stale_available`.
9. Generate a secret-free agent pool and reject zero candidates.
10. Inspect the safe summary and generated JSON for any exact secret value.

Do not copy a provider key into `--agents`, repository variables, command-line
arguments, artifacts, cache keys, logs, issue comments, or deployment manifests.

## Runtime sequence

Start the gateway with the durable catalog connection:

```bash
python -m contextual_orchestrator --serve \
  --provider-catalog-dsn "$CONTEXTUAL_ORCHESTRATOR_CATALOG_DSN" \
  --admin-token "$CONTEXTUAL_ORCHESTRATOR_ADMIN_TOKEN" \
  --inference-token "$CONTEXTUAL_ORCHESTRATOR_INFERENCE_TOKEN"
```

The DSN connects to the catalog; it is not a provider API key. Startup loads only
enabled account/model rows. Each `ModelAgent` carries a credential name, and the
provider client resolves the current value from the credential registry at the
request boundary. Credential rotation therefore does not require rewriting
model rows.

The existing orchestration engine receives the complete pool. Fast route mode
selects one model. Conduct mode selects role-appropriate Thinker, Worker,
Verifier, and Synthesizer candidates and retains other eligible accounts as
failover. Provider retries remain bounded and circuit breakers prevent a
persistently failing account from being selected continuously.

## Exception matrix

| Failure | Retry | Catalog mutation | Service effect | Required action |
| --- | --- | --- | --- | --- |
| DNS, connect, timeout | Bounded jitter | Failure row only | Stale models continue if present | Check egress/DNS/provider status |
| HTTP 408/409/425/429/5xx | Bounded jitter | Failure row only after exhaustion | Account stale/failed; peers continue | Inspect rate limits and provider SLO |
| HTTP 401/403 | No retry storm | Failure row only | Account stale/failed | Rotate or reauthorize named key |
| Redirect | Reject | Failure row only | Account stale/failed | Correct canonical endpoint; do not follow credential redirects |
| Private/reserved destination | Reject before credential send | Failure row only | Account stale/failed | Treat as SSRF/configuration incident |
| Non-JSON, duplicate/invalid JSON, excessive body | Reject | Failure row only | Account stale/failed | Treat as provider contract/security incident |
| Missing key in required bootstrap | No writes | None | Whole production bootstrap blocked | Configure the exact Actions secret |
| Missing key in optional local bootstrap | No write for account | Failure row on sync | Peers may continue | Seed key before production |
| PostgreSQL unavailable | No memory fallback | None | Sync/startup blocked | Restore authoritative database |
| Empty successful listing | No destructive replacement | Failure row only | Prior models stay; otherwise account failed | Verify provider list entitlement/contract |
| Bytez unsupported output | No repair/guess | Runtime failure only | Orchestrator may use another eligible account | Select supported native model/adapter |
| Bytez tool/Responses passthrough | Reject | None | Request fails closed | Route that contract to an OpenAI-compatible candidate |
| All accounts unavailable, no prior model | Bounded account attempts | Failure evidence where DB works | Gateway does not start | Restore at least one validated provider |

Raw exception messages and response bodies are not public error contracts because
they can contain provider-controlled or sensitive content. Stable reason codes
are the operational interface.

## Rotation procedure

1. Add the new key value to the existing Actions secret name.
2. Manually run **Provider Catalog Sync** on protected `main` in the production
   environment.
3. Confirm the safe summary reports the credential name and at least one model.
4. Confirm no account unexpectedly changed to `failed` or `stale_available`.
5. Send a bounded canary inference through that account.
6. Revoke the old provider key only after the canary succeeds.
7. Confirm the next scheduled refresh and runtime call resolve the new value.

The database upsert replaces the encrypted value under the same credential name;
model rows and consuming services require no secret-bearing change.

## Incident response

### Suspected credential disclosure

- Revoke/rotate the provider key immediately.
- Run trusted bootstrap to replace the encrypted registry value.
- Inspect Actions, application, proxy, database-audit, and provider logs for the
  credential name and access time; do not paste the value into searches or tickets.
- Verify generated agent JSON and workflow summaries remain value-free.
- Treat a provider-side unauthorized model invocation as a security incident.

### Catalog poisoning or malformed listing

- Disable the affected `provider_accounts.enabled_flag` row.
- Preserve the response only in an access-controlled incident store; do not add
  it to public CI logs.
- Confirm other providers still supply role coverage.
- Reproduce with a sanitized fixture and add a failing parser/transport test.
- Re-enable only after exact-head security tests and a clean refresh.

### Database outage

- Do not select memory mode as an automatic recovery mechanism.
- Restore the authoritative PostgreSQL service, network path, and pgcrypto
  passphrase access.
- Validate `provider_credentials`, `provider_accounts`, `provider_models`, and the
  latest `catalog_refresh_runs` before restarting the gateway.
- If emergency local mock service is intentionally required, start it as an
  explicitly separate non-production deployment and label all evidence accordingly.

## Rollback

Code rollback may remove `--provider-catalog-dsn` and return a deployment to an
explicit reviewed agents file, but it must not copy API-key values into that
file or reintroduce runtime environment lookup. Keep the credential registry and
catalog tables during rollback; they are backward-compatible control-plane data
and preserve audit evidence.

A schema rollback is normally unnecessary. If required, first export account,
model, capability, modality, and refresh metadata without secret values. Drop
catalog tables only after all catalog-backed services are stopped. Do not drop
`provider_credentials` as part of a model-catalog rollback.

## Verification commands

```bash
python -m pytest \
  tests/test_provider_catalog.py \
  tests/test_provider_catalog_coverage.py \
  tests/test_provider_catalog_cli.py -q
python -m coverage erase
python -m coverage run --branch -m pytest -q
python -m coverage report --fail-under=100
interrogate --fail-under 100 contextual_orchestrator
python -m compileall -q contextual_orchestrator
python -m pip check
git diff --check
```

The trusted live sync is separate evidence. Pull-request success proves parser,
store, routing, failure, and workflow contracts without proving that any current
provider credential or production database is healthy.

## Evidence interpretation

- `refreshed`: current provider listing committed successfully.
- `stale_available`: current refresh failed, but prior enabled models remain.
- `failed`: refresh failed and that account has no usable prior model.
- `disabled`: governance deliberately excluded the account.
- `candidate_model_count`: enabled account/model pairs, not a quality claim.
- inferred capability: routing hint derived conservatively from metadata/name,
  not a provider guarantee or benchmark result.
- price: stored only when supplied and finite; absent is `NULL`, not zero.

## Research and standards rationale

FrugalGPT and RouteLLM show that model selection can improve the
quality–cost frontier, but only when routing respects task quality rather than
using price alone. Fugu, TRINITY, and Conductor motivate a swappable model pool,
role assignment, selective context, and a route-versus-deep-orchestration split.
The durable catalog supplies that pool while retaining an auditable deterministic
policy until learned routing has a valid evaluation set.

RFC 9110 informs retry and status classification: safe catalog GET operations may
be retried within explicit limits, while authentication failures and ambiguous
contracts fail fast. NIST AI RMF supports traceable inventory, monitoring, and
risk treatment. PostgreSQL pgcrypto provides the existing encryption-at-rest
boundary, while table separation prevents model metadata queries from exposing
secret values.

## References

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large language
models while reducing cost and improving performance*. arXiv.
https://doi.org/10.48550/arXiv.2305.05176

Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC 9110).
Internet Engineering Task Force. https://doi.org/10.17487/RFC9110

*Learning to orchestrate agents in natural language with the Conductor*.
(2025). arXiv. https://arxiv.org/abs/2512.04388

National Institute of Standards and Technology. (2023). *Artificial intelligence
risk management framework (AI RMF 1.0)* (NIST AI 100-1).
https://doi.org/10.6028/NIST.AI.100-1

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E., Kadous,
M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with preference
data*. arXiv. https://doi.org/10.48550/arXiv.2406.18665

PostgreSQL Global Development Group. (2026). *pgcrypto*.
https://www.postgresql.org/docs/current/pgcrypto.html

Sakana AI. (2026). *Fugu technical report*.
https://github.com/SakanaAI/fugu/blob/main/Fugu_technical_report.pdf

*TRINITY: An evolved LLM coordinator*. (2025). arXiv.
https://arxiv.org/abs/2512.04695
