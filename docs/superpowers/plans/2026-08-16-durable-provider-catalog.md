# Durable Provider Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the five organization provider credentials and normalized model catalogs, then start `contextual-orchestrator` from an automatically discovered, role-tagged, multi-provider chat pool.

**Architecture:** A trusted protected-main workflow seeds the existing encrypted credential registry and refreshes a normalized PostgreSQL catalog account by account. Runtime startup converts only eligible chat/reasoning/coding rows into ordinary `ModelAgent` records, preserving the current route/conduct engine and a narrow native Bytez transport. Provider failures remain account-scoped when last-known-good data exists and fail closed when no eligible candidate remains.

**Tech Stack:** Python 3.10+, standard-library HTTP/TLS, PostgreSQL and pgcrypto through the optional psycopg DB extra, pytest, coverage, GitHub Actions.

## Global Constraints

- Runtime provider keys resolve from the credential registry, never directly from environment variables.
- Fixed keys are `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_API_KEY_SUB`, `BYTEZ_API_KEY`, `OPENROUTER_API_KEY`, and `OPENAI_API_KEY`.
- Durable bootstrap also requires `CONTEXTUAL_ORCHESTRATOR_KV_DSN` and `CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE`.
- Database objects use two-or-more-word snake_case and third normal form.
- Only chat/reasoning/coding candidates enter the chat pool; other models remain inventory data.
- Capability and role fit outrank context and known price.
- Provider/database errors never expose credentials or raw provider bodies.
- Exact-head branch coverage and public-docstring coverage remain 100%.
- Existing security, fuzz, review, and branch-protection gates may not be weakened.

---

### Task 1: Fix the provider inventory and credential bootstrap contract

**Files:**
- Create: `contextual_orchestrator/provider_catalog.py`
- Create: `tests/test_provider_catalog.py`

**Interfaces:**
- Produces: `ProviderAccount`, `DEFAULT_PROVIDER_ACCOUNTS`, `bootstrap_provider_credentials(environment, require_all, accounts)`.
- Consumes: `register_credential`, `get_credential`.

- [x] **Step 1: Write the failing fixed-inventory test**

```python
def test_fixed_inventory_covers_five_secrets_and_keeps_nvidia_accounts_distinct():
    assert [row.credential_name for row in DEFAULT_PROVIDER_ACCOUNTS] == [
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "BYTEZ_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ]
```

- [x] **Step 2: Verify RED**

```bash
python -m pytest tests/test_provider_catalog.py -q
```

Expected before implementation: import failure for `contextual_orchestrator.provider_catalog`.

- [x] **Step 3: Implement complete-generation validation and name-only summaries**

Required bootstrap first reads and validates every fixed name, then writes values through the credential seam. Optional local bootstrap writes present values and reports missing names.

- [x] **Step 4: Verify GREEN**

```bash
python -m pytest tests/test_provider_catalog.py -k bootstrap -q
```

- [x] **Step 5: Commit**

```bash
git add contextual_orchestrator/provider_catalog.py tests/test_provider_catalog.py
git commit -m "feat: add durable automatic provider catalog"
```

### Task 2: Normalize and persist provider model metadata

**Files:**
- Modify: `contextual_orchestrator/provider_catalog.py`
- Modify: `docs/database_design.sql`
- Test: `tests/test_provider_catalog.py`
- Test: `tests/test_provider_catalog_coverage.py`

**Interfaces:**
- Produces: `DiscoveredModel`, `CatalogModelRecord`, `normalize_models_document`, `InMemoryProviderCatalogStore`, `PostgresProviderCatalogStore`, `PROVIDER_CATALOG_SCHEMA_SQL`.
- Consumes: provider account definitions from Task 1.

- [x] **Step 1: Write failing normalization and 3NF tests**

```python
def test_schema_is_normalized_and_contains_no_provider_secret_value_column():
    assert "create table if not exists provider_accounts" in normalized_sql
    assert "create table if not exists provider_models" in normalized_sql
    assert "encrypted_value" not in normalized_sql
```

- [x] **Step 2: Verify RED**

```bash
python -m pytest tests/test_provider_catalog.py -k "normalizer or schema" -q
```

- [x] **Step 3: Implement bounded metadata and normalized tables**

Persist accounts, models, capabilities, modalities, and immutable refresh evidence separately. Unknown context/price remains null. Specialized and unknown model families remain inventoried but are not automatically marked chat-capable.

- [x] **Step 4: Verify GREEN**

```bash
python -m pytest tests/test_provider_catalog.py tests/test_provider_catalog_coverage.py -k "normal or schema" -q
```

- [x] **Step 5: Commit**

```bash
git add contextual_orchestrator/provider_catalog.py docs/database_design.sql tests/test_provider_catalog*.py
git commit -m "feat: persist normalized provider model metadata"
```

### Task 3: Add resilient account-isolated discovery

**Files:**
- Modify: `contextual_orchestrator/provider_catalog.py`
- Test: `tests/test_provider_catalog.py`
- Test: `tests/test_provider_catalog_coverage.py`

**Interfaces:**
- Produces: `CatalogHttpError`, `ProviderCatalogHttpClient`, `ProviderCatalogService.refresh_all()`.
- Consumes: credential names, catalog store, strict provider JSON parser.

- [x] **Step 1: Write failing retry, stale-catalog, and no-candidate tests**

```python
def test_refresh_isolates_provider_failure_and_preserves_last_known_good_models():
    # Fail primary, refresh secondary, retain primary's prior complete catalog.
    ...
```

- [x] **Step 2: Verify RED**

```bash
python -m pytest tests/test_provider_catalog.py tests/test_provider_catalog_coverage.py -k "refresh or retry" -q
```

- [x] **Step 3: Implement bounded secure discovery**

Use HTTPS, direct public-address pinning, hostname TLS verification, no redirects or ambient proxy, strict bounded JSON, bounded attempts, jitter, deadlines, and capped delta/date `Retry-After`. A failure writes stable code evidence only and never disables prior models.

- [x] **Step 4: Verify GREEN**

```bash
python -m pytest tests/test_provider_catalog.py tests/test_provider_catalog_coverage.py -q
```

- [x] **Step 5: Commit**

```bash
git add contextual_orchestrator/provider_catalog.py tests/test_provider_catalog*.py
git commit -m "feat: add resilient provider model discovery"
```

### Task 4: Construct the runtime pool and native Bytez adapter

**Files:**
- Modify: `contextual_orchestrator/provider_catalog.py`
- Modify: `contextual_orchestrator/__init__.py`
- Modify: `contextual_orchestrator/__main__.py`
- Create: `tests/test_provider_catalog_cli.py`

**Interfaces:**
- Produces: `ProviderCatalogService.candidate_agents()`, `ProviderAwareModelClient`, `build_catalog_orchestrator()`, CLI `--provider-catalog-dsn`.
- Consumes: enabled catalog rows, `ModelAgent`, `ModelClient`, `TaskOrchestrator`.

- [x] **Step 1: Write failing eligibility, role, failover, Bytez, and CLI tests**

```python
def test_candidate_agents_filter_non_chat_models_and_keep_account_credentials_distinct():
    assert all(SERVING_CAPABILITIES.intersection(agent.tags) for agent in agents)
```

- [x] **Step 2: Verify RED**

```bash
python -m pytest tests/test_provider_catalog.py tests/test_provider_catalog_cli.py -q
```

- [x] **Step 3: Implement candidate conversion and startup authority**

Generate governed ids and role tags only for eligible rows. Delegate OpenAI-compatible providers to the inherited hardened client. Serialize text-only messages for native Bytez `Key`/`input`; reject unsupported messages, output, and passthrough. Catalog DSN startup must never fall back to the bundled mock pool.

- [x] **Step 4: Verify GREEN**

```bash
python -m pytest tests/test_provider_catalog.py tests/test_provider_catalog_coverage.py tests/test_provider_catalog_cli.py -q
```

- [x] **Step 5: Commit**

```bash
git add contextual_orchestrator/provider_catalog.py contextual_orchestrator/__init__.py contextual_orchestrator/__main__.py tests/test_provider_catalog*.py
git commit -m "feat: start gateway from discovered provider candidates"
```

### Task 5: Add the protected synchronization workflow

**Files:**
- Create: `.github/workflows/provider-catalog-sync.yml`

**Interfaces:**
- Produces: secret-free PR contract job and protected-main production sync job.
- Consumes: complete provider inventory, durable DSN/passphrase, module CLI `bootstrap-and-sync`.

- [x] **Step 1: Separate PR and protected-main trust domains**

Pull requests run offline tests only. Scheduled/manual synchronization runs only on `refs/heads/main` in the `production` environment.

- [x] **Step 2: Validate and mask the complete inventory**

```bash
required=(
  CONTEXTUAL_ORCHESTRATOR_KV_DSN
  CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE
  NVIDIA_NIM_API_KEY NVIDIA_NIM_API_KEY_SUB BYTEZ_API_KEY OPENROUTER_API_KEY OPENAI_API_KEY
)
```

- [x] **Step 3: Seed, refresh, and inspect generated evidence**

```bash
python -m contextual_orchestrator.provider_catalog bootstrap-and-sync \
  --require-all --agents-output "$RUNNER_TEMP/provider-agents.json"
```

Reject zero eligible agents and any generated document containing an exact provider-secret value.

- [x] **Step 4: Commit**

```bash
git add .github/workflows/provider-catalog-sync.yml
git commit -m "ci: add protected provider catalog synchronization"
```

### Task 6: Document and verify the exact head

**Files:**
- Create: `docs/superpowers/specs/2026-08-16-durable-provider-catalog-design.md`
- Create: `docs/superpowers/plans/2026-08-16-durable-provider-catalog.md`
- Create: `docs/doctoring/durable-provider-catalog.md`
- Create: `docs/provider_catalog.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: operator runbook, APA 7 doctoring, rollback and release notes.
- Consumes: behavior from Tasks 1–5.

- [x] **Step 1: Record architecture, recovery, rotation, and rollback**

- [x] **Step 2: Record APA 7 research and standards basis**

Use the repository's existing lawful OA routing PDFs and citations; do not add a restricted PDF.

- [ ] **Step 3: Run full exact-head verification**

```bash
python -m coverage erase
python -m coverage run --branch -m pytest -q
python -m coverage report --fail-under=100
interrogate --fail-under 100 contextual_orchestrator
python -m compileall -q contextual_orchestrator
python -m pip check
git diff --check
```

Expected: zero failures, 100% measured branch coverage, 100% public-docstring coverage, no dependency conflict, and no whitespace errors.

- [ ] **Step 4: Run security gates without weakening policy**

```bash
trivy --download-db-only
trivy fs --severity CRITICAL,HIGH --ignore-unfixed .
python -m pip_audit -r requirements.lock
```

- [ ] **Step 5: Publish the stacked PR**

```bash
git push -u origin feature/durable-provider-catalog-v3
gh pr create \
  --base fix/atheris-interpreter-lock \
  --head feature/durable-provider-catalog-v3 \
  --title "feat: durable automatic multi-provider catalog"
```

Require one unchanged exact head with all protected checks, zero valid unresolved findings, current semantic reviews, qualifying independent approval, and normal merge authorization. After protected-main integration, run the trusted sync before claiming live database registration.
