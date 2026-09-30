# Experiential No-Heuristics Bounds Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove undocumented catalog, receipt-pagination, polling, output-token, timeout, and identifier-length decisions from the opt-in Experiential billing probe while preserving its single-send and fail-closed evidence contract.

**Architecture:** Follow the provider's returned catalog pagination contract and documented settled-export cursor until completion, rejecting inconsistent or repeated evidence instead of imposing local page counts. Perform one immediate receipt read after the single inference because the provider publishes no settlement-ready signal or research-backed polling policy. Use the gateway's null timeout and the provider's documented minimal chat body.

**Tech Stack:** Python 3.12 standard library, pytest, GitHub Actions YAML.

**Spec:** `docs/doctoring/experiential_billing_measurement.md`

## Global Constraints

- No Force Push, destructive rebase, inference retry, provider fallback, or paid bypass.
- Every decision-affecting threshold must come from the provider contract or fail closed.
- Preserve exact callable model and promotion identity; multiple eligible candidates remain ambiguous.
- Runtime credentials remain KV-backed; environment is bootstrap transport only.
- Hosted Checks and independent approval remain merge gates.

---

### Task 1: Replace undocumented measurement bounds with provider contracts

**Files:**
- Modify: `tests/test_experiential_billing_probe.py`
- Modify: `contextual_orchestrator/experiential_billing_probe.py`
- Modify: `.github/workflows/provider-catalog-sync.yml`
- Modify: `docs/doctoring/experiential_billing_measurement.md`
- Modify: `docs/product-technical-gap-baseline.md`
- Modify: `CHANGELOG.d/experiential-billing-measurement.md`

**Interfaces:**
- Consumes: `_catalog(request)`, `_settled_charge(request, label, secret)`, `run_probe(...)`, `_request(...)`.
- Produces: the same public functions, with provider-driven pagination, one receipt observation, null transport timeout, and a minimal inference payload.

- [x] **Step 1: Write failing contract tests**

Add behavioral tests proving that catalog discovery follows a consistent provider-declared page sequence beyond the former 16-page ceiling, settled usage follows more than three unique documented cursors, missing receipts cause exactly one GET observation without elapsed-time polling, transport passes `timeout=None`, the inference body omits undocumented `max_tokens` and `stream` fields, and valid provider/Actions identities are not rejected by local length ceilings.

- [x] **Step 2: Run RED tests**

Run:

```bash
../../.venv/bin/python -W error -m pytest tests/test_experiential_billing_probe.py -q
```

Expected: failures identify the old 16/1,600 catalog ceiling, three-page usage ceiling, three-round/five-second polling policy, 30-second transport timeout, 16-token request cap, 200-character provider-identity ceiling, and 30-digit run-identity ceiling.

- [x] **Step 3: Implement the minimal repair**

Use the first catalog response's exact positive `limit`, non-negative `total`, and zero `offset` to advance until `len(models) == total`; reject any inconsistent or non-progressing page. Follow usage `next_cursor` until `null`, rejecting malformed or repeated cursors. Read generation and settled usage once after the send. Pass `None` to `ModelClient` and `_open_provider`; remove the billing job timeout, undocumented sampling fields, and local identifier-length ceilings.

- [x] **Step 4: Run focused GREEN verification**

Run:

```bash
../../.venv/bin/python -W error -m pytest tests/test_experiential_billing_probe.py -q
```

Expected: all focused contracts pass with no warnings.

- [x] **Step 5: Run adjacent regression and static verification**

Run:

```bash
../../.venv/bin/python -W error -m pytest \
  tests/test_experiential_billing_probe.py \
  tests/test_provider_bootstrap_secret_normalization.py \
  tests/test_release_checks_required_allowlist.py \
  tests/test_repository_security_metadata.py -q
../../.venv/bin/python -m compileall -q contextual_orchestrator tests
git diff --check
```

Expected: zero failures, warnings, compile errors, or whitespace errors.

- [x] **Step 6: Record exact evidence and commit**

Update the doctoring record, product-technical Gap baseline, and changelog with the predecessor SHA, provider-contract basis, RED/GREEN counts, and remaining hosted/live evidence boundary. Commit only the six files above plus this plan.
