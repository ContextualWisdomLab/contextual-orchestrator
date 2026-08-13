# Tenant Cloud Routing Implementation Plan

> Execute with strict red-green-refactor TDD on the stacked PR based on PR #96.

**Goal:** Add a tenant-scoped, PostgreSQL-backed provider/model registry, a direct OpenAI-compatible model-group endpoint with deterministic fallback, and Cloud Native deployment evidence.

**Architecture:** Provider secret values remain in the existing pgcrypto KV. New normalized tenant-routing metadata references tenant-qualified KV names. A request-scoped group executor creates existing `ModelAgent` values and calls the existing `ModelClient`; the Cloud Gateway is a separate importable/runtime module so the current standalone server remains compatible.

**Stack:** Python standard library, optional psycopg DB extra, PostgreSQL 18/pgcrypto, Docker Compose, Kubernetes manifests, GitHub Actions.

---

## Task 1 — Lock the contracts with failing tests

**Files:**
- Create `tests/test_tenant_registry.py`
- Create `tests/test_model_group_fallback.py`
- Create `tests/test_cloud_gateway_http.py`
- Create `tests/test_cloud_native_contract.py`

1. Write tests for secret non-disclosure, rotation, tenant isolation, endpoint ownership, ordering, disablement, and normalized SQL names.
2. Write tests for first-failure/second-success, empty-result fallback, no out-of-group attempt, deterministic evidence, and all-failed behavior.
3. Write HTTP tests for auth, tenant header, admin CRUD, OpenAI completion shape, minimal liveness, database readiness, and web UI secret handling.
4. Write deployment-contract tests for two Compose gateways, two Kubernetes replicas, probes, provider-key isolation, and live-workflow secret names.
5. Run the exact test files and retain the expected import failures as RED evidence.

## Task 2 — Implement the tenant registry

**Files:**
- Create `contextual_orchestrator/tenant_registry.py`

1. Add immutable domain records and stable domain exceptions.
2. Add an in-memory backend with injectable shared state for deterministic tests.
3. Add PostgreSQL schema and CRUD using parameter binding and pgcrypto.
4. Namespace every KV credential by tenant and label.
5. Resolve only enabled, same-tenant group members in deterministic order.
6. Add beginner-readable public docstrings.

## Task 3 — Implement sequential model-group fallback

**Files:**
- Create `contextual_orchestrator/model_group.py`

1. Build request-scoped `ModelAgent` values from resolved endpoint metadata.
2. Call the existing `ModelClient` without copying provider transport logic.
3. Reject empty/non-string output and continue to the next member.
4. Return secret-free attempt evidence and usage.
5. Raise one stable redacted error after complete exhaustion.

## Task 4 — Add the Cloud Gateway and web control plane

**Files:**
- Create `contextual_orchestrator/cloud_admin.py`
- Create `contextual_orchestrator/cloud_gateway.py`

1. Add KV-resolved admin/inference authentication.
2. Add `/livez`, `/readyz`, and authenticated detailed readiness.
3. Add tenant, credential, group, endpoint, and membership JSON routes.
4. Add OpenAI-compatible `/v1/chat/completions` using `model` as the group name.
5. Add a same-origin admin UI that stores no raw token or provider secret.
6. Add bounded bodies, stable errors, no-store headers, and strict validation.

## Task 5 — Add Cloud Native deployment and bootstrap

**Files:**
- Create `scripts/bootstrap_tenant_registry.py`
- Create `scripts/verify_live_provider_fallback.py`
- Create `deploy/docker-compose.cloud.yml`
- Create `deploy/kubernetes/namespace.yaml`
- Create `deploy/kubernetes/config-map.yaml`
- Create `deploy/kubernetes/deployment.yaml`
- Create `deploy/kubernetes/service.yaml`
- Create `deploy/kubernetes/network-policy.yaml`
- Create `deploy/kubernetes/pod-disruption-budget.yaml`
- Create `deploy/kubernetes/bootstrap-job.yaml`
- Create `.github/workflows/live-tenant-provider-fallback.yml`

1. Keep provider keys only in the one-shot bootstrap environment.
2. Prove two gateway processes share one PostgreSQL registry.
3. Add bounded live probes for OpenRouter, NVIDIA NIM, and Bytez.
4. Force the first group member to fail and verify the next valid provider wins.
5. Emit only secret-redacted summaries.

## Task 6 — Documentation and exact-head verification

**Files:**
- Create `docs/adr/0011-tenant-provider-registry.md`
- Create `docs/tenant-cloud-routing.md`
- Create `docs/doctoring/tenant-cloud-routing-references.md`
- Update `CHANGELOG.md`

1. Run the four focused test files.
2. Run the full branch-coverage suite and public-docstring gate.
3. Run deployment-contract and Postgres integration workflows.
4. Run Security, fuzz, SAST, SBOM, and package checks on the same contributor head.
5. Review every automated/human thread and fix every valid finding.
6. Keep the PR Draft until the security prerequisite, exact-head checks, and independent approval are all satisfied.
