# Reliable Provider Failover and Catalog Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** Exhaust safe transient virtual-route candidates and repair Experiential Labs and Bytez discovery without changing explicit concrete-model replay semantics.

**Architecture:** Extend the existing `TaskOrchestrator._invoke` attempt boundary with complete transient-failure evidence and preserve the existing shared cooldown machinery. Centralize Experiential Labs credential canonicalization in model-discovery/bootstrap helpers, keep discovered rows canonical, and make Bytez task-catalog parsing/retry pagination bounded and fail closed.

**Tech Stack:** Python standard library, `urllib`, pytest, existing credential KV and provider error taxonomy; no new dependencies.

## Global Constraints

- `EXPERIENTIAL_LABS_API_KEY` is canonical; `EXPERIENTAL_LABS_API_KEY` is a backward-compatible accepted alias.
- Virtual selectors may fail over across retryable upstream failures; explicit concrete model selections remain sticky.
- Do not infer Experiential Labs ZDR capability.
- Bytez requests use bare-token `Authorization` and task-scoped catalog requests only.
- Runtime credentials come from the KV; environment variables are bootstrap transport only.
- Provider error details must be bounded and secret-free.
- Preserve existing paths, security gates, and `CHANGELOG.d` conventions.

---

### Task 1: Record design and establish branch checkpoint

**Files:**
- Create: `docs/superpowers/specs/2026-09-25-reliable-provider-failover-discovery-design.md`
- Create: `docs/superpowers/plans/2026-09-25-reliable-provider-failover-discovery.md`

- [x] **Step 1: Record the approved design and plan**
- [ ] **Step 2: Commit the documentation checkpoint**

Run:

```bash
git add docs/superpowers/specs/2026-09-25-reliable-provider-failover-discovery-design.md \
  docs/superpowers/plans/2026-09-25-reliable-provider-failover-discovery.md
git commit -m "docs: plan reliable provider failover and discovery"
git push -u origin cursor/reliable-provider-failover-discovery-3abb
```

Expected: one pushed commit on `cursor/reliable-provider-failover-discovery-3abb`.

### Task 2: Prove and repair virtual transient failover

**Files:**
- Modify: `tests/test_provider_reliability.py`
- Modify: `contextual_orchestrator/orchestrator.py`
- Modify: `contextual_orchestrator/provider_errors.py` only if the existing typed evidence boundary requires a narrowly scoped addition
- Modify: `CHANGELOG.d/reliable-provider-failover-discovery.md`

- [ ] **Step 1: Write failing regression tests**

Add tests at the existing `orchestrator/free` boundary that:

```python
def test_free_model_exhausts_429_503_timeout_and_reset_before_failing():
    # Script four distinct free candidates with 429, 503, TimeoutError,
    # and ConnectionResetError; assert all four are called once, no priced
    # candidate is used, and the final typed error exposes four bounded
    # attempt records with statuses/reasons.
    ...
```

Also add a success-after-transient test and retain a concrete-model test proving
the concrete request does not replay across unrelated candidates.

- [ ] **Step 2: Run only the new tests and verify RED**

```bash
python -m pytest tests/test_provider_reliability.py -q -k "exhausts_429_503 or transient_failover_evidence"
```

Expected: failure showing the current invocation path does not satisfy the
complete candidate/exhaustion evidence contract.

- [ ] **Step 3: Implement the smallest shared-loop fix**

Ensure `_invoke` advances after every `ProviderUpstreamError.retryable` failure
and every classified retryable transport failure, records one
`_passthrough_attempt_record`-compatible bounded record per candidate, and
attaches `attempts`, `selected_candidate_ids`, and an exhausted-candidate
terminal reason to the final error. Keep `virtual_selector` gating and existing
`ToolFallbackStoppedError`/ambiguous-outcome terminal behavior intact.

- [ ] **Step 4: Run the focused reliability tests**

```bash
python -m pytest tests/test_provider_reliability.py -q
```

Expected: PASS with no warnings.

- [ ] **Step 5: Commit the fallback change**

```bash
git add contextual_orchestrator/orchestrator.py contextual_orchestrator/provider_errors.py \
  tests/test_provider_reliability.py CHANGELOG.d/reliable-provider-failover-discovery.md
git commit -m "fix: exhaust transient provider candidates"
git push
```

### Task 3: Canonicalize Experiential Labs credentials

**Files:**
- Modify: `contextual_orchestrator/model_discovery.py`
- Modify: `contextual_orchestrator/provider_bootstrap.py`
- Modify: `contextual_orchestrator/review_gateway.py`
- Modify: `tests/test_review_gateway_credential_array.py`
- Modify: `tests/test_experiential_review_admission.py`
- Modify: `tests/test_model_discovery.py`

- [ ] **Step 1: Write failing alias tests**

Cover canonical and typo environment names, KV lookup through the alias,
canonical `DiscoveredModel.credential_name`, free-pool admission for either
input name, and provider-scoped ZDR evidence that does not grant Experiential
Labs a new positive claim.

- [ ] **Step 2: Run the alias tests and verify RED**

```bash
python -m pytest tests/test_review_gateway_credential_array.py \
  tests/test_experiential_review_admission.py tests/test_model_discovery.py -q \
  -k "experiential or credential"
```

Expected: alias input is rejected or remains misspelled in the discovered
identity.

- [ ] **Step 3: Implement canonical/alias helpers**

Define one canonical name, one alias, and helper functions that canonicalize
names and resolve KV values in canonical-first order. Use those helpers when
deriving accepted/bootstrap names, reading source credentials, registering
review credentials, filtering free-pool candidates, and comparing provider
catalog/ZDR identities. Store discovered rows under
`EXPERIENTIAL_LABS_API_KEY`; accept both names from environment and explicit
credential-name lists.

- [ ] **Step 4: Run the alias-focused tests**

```bash
python -m pytest tests/test_review_gateway_credential_array.py \
  tests/test_experiential_review_admission.py tests/test_model_discovery.py -q \
  -k "experiential or credential"
```

Expected: PASS with both exact environment names accepted.

- [ ] **Step 5: Commit the credential change**

```bash
git add contextual_orchestrator/model_discovery.py contextual_orchestrator/provider_bootstrap.py \
  contextual_orchestrator/review_gateway.py tests/test_review_gateway_credential_array.py \
  tests/test_experiential_review_admission.py tests/test_model_discovery.py
git commit -m "fix: accept canonical experiential labs credential"
git push
```

### Task 4: Repair Experiential Labs and Bytez discovery

**Files:**
- Modify: `contextual_orchestrator/model_discovery.py`
- Modify: `tests/test_model_discovery.py`

- [ ] **Step 1: Write failing mock HTTP tests**

Add Experiential tests asserting `GET /v1/models`, `Authorization: Bearer`,
OpenAI `data` model rows, and canonical credential identity. Add Bytez tests
for:

```python
def test_bytez_retries_http_500_then_uses_chat_catalog():
    ...

def test_bytez_reads_bounded_next_cursor_pages():
    ...
```

Use `_Response`/patched trusted opener only; no real provider keys.

- [ ] **Step 2: Run discovery tests and verify RED**

```bash
python -m pytest tests/test_model_discovery.py -q \
  -k "experiential or bytez"
```

Expected: the new response/pagination and alias assertions fail before the
implementation.

- [ ] **Step 3: Implement provider-specific parsing and bounded paging**

Keep Experiential on the OpenAI-compatible parser with identity-only metadata.
For Bytez, preserve bare-token auth and task filters, retry transient
HTTP/transport failures with the existing bounded delay, parse `output`, and
follow only documented bounded cursor/page links or fields from the same
trusted host. Stop on repeated cursors, the configured response-size limit, or
the existing discovery deadline. Never issue an unfiltered fallback request.

- [ ] **Step 4: Run discovery tests**

```bash
python -m pytest tests/test_model_discovery.py -q
```

Expected: PASS with no warnings.

- [ ] **Step 5: Commit the discovery change**

```bash
git add contextual_orchestrator/model_discovery.py tests/test_model_discovery.py
git commit -m "fix: harden experiential and bytez discovery"
git push
```

### Task 5: Verify and prepare the PR

**Files:**
- No additional source files unless verification finds a directly related regression.

- [ ] **Step 1: Run repository checks**

```bash
python -m pytest tests/test_provider_reliability.py tests/test_model_discovery.py \
  tests/test_review_gateway_credential_array.py tests/test_experiential_review_admission.py -q
python tests/test_repository_security_metadata.py
python -m pytest tests -q
```

Expected: focused tests and the full suite pass; any pre-existing unrelated
failure is recorded with its exact command and cause.

- [ ] **Step 2: Review the diff and repository status**

```bash
git diff --check
git status --short
git diff origin/main...HEAD --stat
git log --oneline origin/main..HEAD
```

Expected: only the approved source, tests, changelog, and design/plan files
are changed; no secrets or provider payloads are present.

- [ ] **Step 3: Commit any final verification fix and push**

```bash
git add <reviewed-files>
git commit -m "test: finalize provider failover discovery coverage"
git push
```

### Task 6: Open one non-draft PR

Use `ManagePullRequest.create_pr` with:

- Title: `fix: exhaust transient provider routes and repair catalog discovery`
- Branch: `cursor/reliable-provider-failover-discovery-3abb`
- Base: `main`
- Draft: `false`

The description must include the three root causes, changed behavior, test
commands/results, and these exact accepted Experiential Labs environment names:

```text
EXPERIENTIAL_LABS_API_KEY
EXPERIENTAL_LABS_API_KEY
```

Do not merge the PR.

