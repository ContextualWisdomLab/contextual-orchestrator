# Durable Provider Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the five organization provider credentials and normalized model catalogs, then start `contextual-orchestrator` from an automatically discovered, role-tagged, multi-provider agent pool.

**Architecture:** A trusted default-branch workflow seeds the existing encrypted credential registry and refreshes a normalized PostgreSQL provider catalog account by account. Runtime startup loads enabled catalog rows into ordinary `ModelAgent` records and uses the existing route/conduct engine plus a narrow native Bytez transport. Failures remain provider-scoped when last-known-good data exists and fail closed when no usable candidate remains.

**Tech Stack:** Python 3.10+, standard-library HTTP/TLS, PostgreSQL + pgcrypto/psycopg optional DB extra, pytest/Hypothesis-compatible deterministic tests, GitHub Actions.

## Global Constraints

- Runtime provider keys resolve from the credential registry, never directly from environment variables.
- GitHub Actions environment variables are bootstrap transport only.
- Fixed credentials: `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_API_KEY_SUB`, `BYTEZ_API_KEY`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`.
- Production durable bootstrap also requires `CONTEXTUAL_ORCHESTRATOR_KV_DSN` and `CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE`.
- Database objects use two-or-more-word snake_case and third normal form.
- Capability and role fit outrank known price; price is a bounded tie-break.
- Provider catalog/network/database errors never include credential values or raw provider bodies.
- Exact-head repository coverage and public-docstring coverage remain 100%.
- Existing security, fuzz, review, and branch-protection gates may not be weakened.

---

### Task 1: Lock the provider inventory and normalization contracts

**Files:**
- Create: `tests/test_provider_catalog.py`
- Create: `tests/test_provider_catalog_coverage.py`
- Create: `contextual_orchestrator/provider_catalog.py`

**Interfaces:**
- Produces: `ProviderAccount`, `DiscoveredModel`, `CatalogModelRecord`, `DEFAULT_PROVIDER_ACCOUNTS`, `normalize_models_document(document) -> list[DiscoveredModel]`.
- Consumes: `register_credential`, `get_credential`, `ModelAgent`.

- [x] **Step 1: Write failing inventory and normalization tests**

```python
def test_default_accounts_cover_every_configured_secret_and_split_nvidia_accounts():
    assert [row.credential_name for row in DEFAULT_PROVIDER_ACCOUNTS] == [
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "BYTEZ_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ]
```

- [x] **Step 2: Verify RED**

Run:

```bash
python -m pytest tests/test_provider_catalog.py -q
```

Expected before implementation: import failure for `contextual_orchestrator.provider_catalog`.

- [x] **Step 3: Implement the fixed accounts and provider-neutral normalizer**

Implement bounded ids, contexts, prices, modalities, and conservative capability inference. Keep unknown values `None`; never fabricate a price or context window.

- [x] **Step 4: Verify GREEN**

```bash
python -m pytest tests/test_provider_catalog.py tests/test_provider_catalog_coverage.py -q
```

Expected: inventory and normalization contracts pass.

- [x] **Step 5: Commit**

```bash
git add tests/test_provider_catalog.py tests/test_provider_catalog_coverage.py contextual_orchestrator/provider_catalog.py
git commit -m "feat: add durable multi-provider model catalog"
```

### Task 2: Add isolated refresh and normalized persistence

**Files:**
- Modify: `contextual_orchestrator/provider_catalog.py`
- Test: `tests/test_provider_catalog.py`
- Test: `tests/test_provider_catalog_coverage.py`

**Interfaces:**
- Produces: `ProviderCatalogStore`, `InMemoryProviderCatalogStore`, `PostgresProviderCatalogStore`, `ProviderCatalogService.refresh_all()`, `PROVIDER_CATALOG_SCHEMA_SQL`.
- Consumes: provider accounts and normalized models from Task 1.

- [x] **Step 1: Write failing last-known-good and no-candidate tests**

```python
def test_refresh_isolates_provider_failure_and_preserves_last_known_good_catalog():
    # Seed two accounts; fail one refresh; assert its old model remains and peer updates.
    ...
```

- [x] **Step 2: Verify RED**

```bash
python -m pytest tests/test_provider_catalog.py -k refresh -q
```

Expected before implementation: missing service/store methods.

- [x] **Step 3: Implement account-scoped transactions and refresh evidence**

Use `provider_accounts`, `provider_models`, `model_capabilities`, `model_modalities`, and `catalog_refresh_runs`. Disable missing models only after a complete successful account refresh. A failed refresh inserts failure evidence and leaves prior model rows untouched.

- [x] **Step 4: Verify GREEN and schema rules**

```bash
python -m pytest tests/test_provider_catalog.py -k "refresh or schema" -q
```

Expected: isolated refresh, stale availability, empty-catalog failure, and no-secret schema tests pass.

- [x] **Step 5: Commit**

```bash
git add contextual_orchestrator/provider_catalog.py tests/test_provider_catalog.py tests/test_provider_catalog_coverage.py
git commit -m "feat: persist normalized provider catalogs"
```

### Task 3: Build the automatic runtime pool and native Bytez seam

**Files:**
- Modify: `contextual_orchestrator/provider_catalog.py`
- Modify: `contextual_orchestrator/__init__.py`
- Modify: `contextual_orchestrator/__main__.py`
- Create: `tests/test_provider_catalog_cli.py`
- Test: `tests/test_provider_catalog.py`

**Interfaces:**
- Produces: `ProviderCatalogService.candidate_agents()`, `ProviderAwareModelClient`, `build_catalog_orchestrator()`, CLI `--provider-catalog-dsn`.
- Consumes: `TaskOrchestrator`, `ModelClient`, enabled catalog rows, KV credential names.

- [x] **Step 1: Write failing role-routing, failover, Bytez, and CLI tests**

```python
def test_catalog_orchestrator_uses_role_tags_and_retains_cross_provider_failover():
    orchestrator = build_catalog_orchestrator(store, accounts=(reasoning, coding))
    assert orchestrator._select_agent("plan", "thinker").model == "deep-reasoner"
    assert orchestrator._select_agent("implement code", "worker").model == "code-specialist"
```

- [x] **Step 2: Verify RED**

```bash
python -m pytest tests/test_provider_catalog.py tests/test_provider_catalog_cli.py -q
```

Expected before implementation: missing catalog factory/client/CLI option.

- [x] **Step 3: Implement agent conversion and provider-aware transport**

Generate bounded two-or-more-word snake-case ids. Map chat/reasoning/coding/vision/audio capabilities into existing role tags. Keep role fit ahead of context and price. Delegate OpenAI-compatible providers to the existing secure client; use native Bytez `Key` plus `input` only for ordinary Bytez chat and fail closed for unsupported passthrough shapes.

- [x] **Step 4: Verify GREEN**

```bash
python -m pytest tests/test_provider_catalog.py tests/test_provider_catalog_coverage.py tests/test_provider_catalog_cli.py -q
```

Expected: role selection, two-account NIM failover, Bytez native output, and catalog CLI startup pass.

- [x] **Step 5: Commit**

```bash
git add contextual_orchestrator/provider_catalog.py contextual_orchestrator/__init__.py contextual_orchestrator/__main__.py tests/test_provider_catalog*.py
git commit -m "feat: start runtime from discovered provider models"
```

### Task 4: Add the trust-separated GitHub Actions bootstrap

**Files:**
- Create: `.github/workflows/provider-catalog-sync.yml`
- Test: `tests/test_provider_catalog.py`

**Interfaces:**
- Produces: pull-request offline contract job and protected-main credential/catalog synchronization job.
- Consumes: fixed provider secrets, durable KV DSN/passphrase, module CLI `bootstrap-and-sync`.

- [x] **Step 1: Encode the untrusted/trusted job boundary**

Pull requests receive no provider or database secrets. Scheduled/manual execution is restricted to `refs/heads/main` and the protected `production` environment.

- [x] **Step 2: Add complete-inventory validation**

```bash
required=(
  CONTEXTUAL_ORCHESTRATOR_KV_DSN
  CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE
  NVIDIA_NIM_API_KEY NVIDIA_NIM_API_KEY_SUB BYTEZ_API_KEY OPENROUTER_API_KEY OPENAI_API_KEY
)
```

Fail before bootstrap when any value is empty; add each configured value to Actions masking without printing it.

- [x] **Step 3: Seed, refresh, and verify secret-free evidence**

```bash
python -m contextual_orchestrator.provider_catalog bootstrap-and-sync \
  --require-all --agents-output "$RUNNER_TEMP/provider-agents.json"
```

Parse the generated agent pool and safe summary; fail if no candidate exists or any secret value appears.

- [x] **Step 4: Validate workflow syntax and offline contracts**

```bash
python -m pytest tests/test_provider_catalog.py tests/test_provider_catalog_coverage.py -q
python -m compileall -q contextual_orchestrator
```

- [x] **Step 5: Commit**

```bash
git add .github/workflows/provider-catalog-sync.yml
git commit -m "ci: add trusted provider catalog bootstrap"
```

### Task 5: Ground, document, and verify the exact head

**Files:**
- Create: `docs/superpowers/specs/2026-08-16-durable-provider-catalog-design.md`
- Create: `docs/superpowers/plans/2026-08-16-durable-provider-catalog.md`
- Create: `docs/doctoring/durable-provider-catalog.md`
- Create: `docs/provider_catalog.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: operator recovery/rollback instructions, APA 7 source record, release note.
- Consumes: implementation and workflow behavior from Tasks 1–4.

- [x] **Step 1: Document architecture and operational actions**

State credential/catalog separation, 3NF objects, refresh semantics, Bytez native boundary, startup behavior, exact secret inventory, and required DB bootstrap secrets.

- [x] **Step 2: Add APA 7 doctoring**

Ground the design in FrugalGPT, RouteLLM, Fugu/TRINITY/Conductor, HTTP semantics, NIST AI RMF, and PostgreSQL pgcrypto. Do not attach a PDF unless redistribution is permitted; reuse the repository's existing OA routing PDFs.

- [ ] **Step 3: Run exact full verification**

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

- [ ] **Step 4: Run repository security gates**

```bash
trivy --download-db-only
trivy fs --severity CRITICAL,HIGH --ignore-unfixed .
python -m pip_audit -r requirements.lock
```

Expected: no unremediated high/critical finding. Do not weaken a gate.

- [ ] **Step 5: Publish the stacked PR and wait for protected evidence**

```bash
git push -u origin feature/durable-provider-catalog-v2
gh pr create --base fix/atheris-interpreter-lock \
  --head feature/durable-provider-catalog-v2 \
  --title "feat: durable automatic multi-provider catalog"
```

Target the accepted provider-security branch so DNS-pinned/strict-response work is inherited before protected `main`. Require all exact-head checks, current reviews, zero unresolved valid findings, and qualifying independent approval before normal merge.
