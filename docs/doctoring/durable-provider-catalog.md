# Durable Provider Catalog Doctoring

## Operational invariants

1. Provider values exist only in the encrypted credential registry.
2. Catalog rows contain credential names, never provider-secret values.
3. `NVIDIA_NIM_API_KEY` and `NVIDIA_NIM_API_KEY_SUB` remain independent accounts.
4. Pull-request code receives no production provider or database secrets.
5. Configured PostgreSQL authority never silently downgrades to process memory.
6. Failed refreshes preserve each account's last complete usable catalog.
7. Complete successful refreshes may disable models absent from the new listing.
8. Only chat/reasoning/coding models enter the chat orchestration pool.
9. Zero eligible candidates blocks sync/startup; it never selects bundled mocks.
10. Provider capability fit outranks context and known price.
11. Native Bytez uses its Key/input contract; unsupported passthrough fails closed.
12. Public errors and summaries contain stable codes and names, not raw responses.

## Trusted bootstrap sequence

The protected-default-branch synchronization performs these actions:

1. Require non-empty `CONTEXTUAL_ORCHESTRATOR_KV_DSN`,
   `CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE`, and all five provider keys.
2. Add each value to GitHub Actions masking without echoing it.
3. Select `CONTEXTUAL_ORCHESTRATOR_KV_BACKEND=postgres`.
4. Validate the complete fixed provider generation before writing one credential.
5. Upsert values through `register_credential()` into pgcrypto storage.
6. Refresh provider accounts independently over bounded credentialed HTTPS.
7. Normalize accounts, models, capabilities, modalities, and refresh evidence.
8. Preserve prior rows for failed accounts and classify them `stale_available`.
9. Export only eligible chat agents and reject an empty pool.
10. Compare generated evidence against the exact five secret values.

Do not copy a provider value into source, agents JSON, repository variables,
command arguments, artifacts, cache keys, logs, issue comments, or deployment
manifests.

## Runtime sequence

Start the gateway with catalog authority:

```bash
python -m contextual_orchestrator --serve \
  --provider-catalog-dsn "$CONTEXTUAL_ORCHESTRATOR_CATALOG_DSN" \
  --admin-token "$CONTEXTUAL_ORCHESTRATOR_ADMIN_TOKEN" \
  --inference-token "$CONTEXTUAL_ORCHESTRATOR_INFERENCE_TOKEN"
```

The DSN is database bootstrap transport, not a provider credential. Startup loads
only enabled, serving-capable rows. Each `ModelAgent` stores a credential name;
the provider client resolves its current registry value at the request boundary.
Credential rotation therefore does not rewrite model rows.

The ordinary orchestration engine receives the eligible pool. Route mode selects
one model. Conduct mode assigns role-capable Thinker, Worker, Verifier, and
Synthesizer steps and keeps other candidates available for failover. Existing
retries and per-agent circuit breakers remain in force.

## Exception matrix

| Failure | Retry | Catalog mutation | Service effect | Operator action |
| --- | --- | --- | --- | --- |
| DNS, connect, timeout | Bounded jitter | Failure row only | Prior models continue when present | Check egress, DNS, provider SLO |
| HTTP 408/409/425/429/5xx | Bounded jitter and capped `Retry-After` | Failure row after exhaustion | Account stale/failed; peers continue | Inspect rate and provider status |
| HTTP 401/403 | No retry storm | Failure row only | Account stale/failed | Rotate or reauthorize named key |
| Redirect | Reject | Failure row only | Account stale/failed | Correct canonical endpoint |
| Private/reserved destination | Reject before credential send | Failure row only | Account stale/failed | Treat as SSRF/config incident |
| Invalid media, UTF-8, JSON, duplicate/non-finite object, excessive body | Reject | Failure row only | Account stale/failed | Treat as provider contract/security incident |
| Required key missing | No provider writes | None | Whole production bootstrap blocked | Configure exact Actions secret |
| PostgreSQL unavailable | No memory fallback | None | Sync/startup blocked | Restore authoritative DB |
| Empty listing | No destructive replacement | Failure row only | Prior models stay; otherwise failed | Verify entitlement/contract |
| Non-chat inventory only | Persist inventory | Successful metadata rows | Chat startup blocked | Enable a validated chat model |
| Bytez unsupported message/output/passthrough | No repair or guessing | Runtime failure only | Other eligible provider may serve | Select supported model/contract |
| All eligible accounts unavailable and no prior model | Bounded per-account attempts | Failure evidence where DB works | Gateway does not start | Restore at least one eligible provider |

## Credential rotation

1. Replace the value under the existing Actions secret name.
2. Run **Provider Catalog Sync** on protected `main` in `production`.
3. Confirm the account refreshes and the safe eligible-agent count is nonzero.
4. Send a bounded canary through that provider account.
5. Revoke the old provider credential only after the canary succeeds.
6. Confirm the next scheduled refresh and runtime request use the new registry value.

## Incident response

### Suspected credential disclosure

- Revoke/rotate the provider credential immediately.
- Run trusted bootstrap to replace its encrypted registry value.
- Inspect Actions, application, gateway, database-audit, and provider logs by
  credential name and time; never paste the value into a search or ticket.
- Verify exported agent JSON and summaries remain value-free.
- Treat unauthorized provider-side inference as a security incident.

### Catalog poisoning or malformed listing

- Disable the affected `provider_accounts.enabled_flag` row.
- Preserve the raw response only in an access-controlled incident store.
- Verify another provider still covers required roles.
- Add a sanitized failing parser/transport regression before remediation.
- Re-enable only after exact-head security tests and a clean complete refresh.

### Database outage

- Do not choose memory mode automatically.
- Restore PostgreSQL, network reachability, and pgcrypto passphrase access.
- Validate `provider_credentials`, `provider_accounts`, `provider_models`, and
  recent `catalog_refresh_runs` before service restart.
- If an emergency mock deployment is required, run it separately and label all
  evidence non-production.

## Rollback

Code rollback may remove `--provider-catalog-dsn` and return a deployment to an
explicit reviewed agents file, but must not copy provider values into that file
or restore runtime environment lookup. Keep credential and catalog tables during
normal rollback because they preserve audit evidence and do not force consumers
to use them.

If schema rollback is unavoidable, export account/model/capability/modality and
refresh metadata without secret values, stop all catalog-backed services, then
drop only the catalog tables. Do not drop `provider_credentials` as part of a
model-catalog rollback.

## Evidence interpretation

- `refreshed`: current complete provider listing committed successfully.
- `stale_available`: refresh failed but prior catalog data remains.
- `failed`: refresh failed and no prior catalog remains for that account.
- `disabled`: governance deliberately excluded the account.
- `candidate_model_count`: enabled chat-agent count, not a quality claim.
- `unknown`: retained inventory without evidence sufficient for chat routing.
- inferred capability: conservative routing hint, not a provider benchmark.
- missing price/context: null evidence, not free or zero-capacity inference.

Pull-request checks prove deterministic code contracts only. They do not prove
that production provider credentials, provider endpoints, or the production
database are healthy. That evidence exists only after the protected-main sync.

## Verification

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

## Research and standards rationale

FrugalGPT and RouteLLM support optimizing model selection under quality and cost
constraints, not unconditional cheapest-provider routing. Fugu, TRINITY, and
Conductor motivate a swappable pool, role assignment, selective context, and a
single-route versus deeper-orchestration split. RFC 9110 informs safe bounded
retry and `Retry-After`; NIST AI RMF supports inventory, monitoring, and incident
treatment; PostgreSQL pgcrypto provides the existing encryption-at-rest seam.

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
