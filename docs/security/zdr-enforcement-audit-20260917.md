# ZDR enforcement audit — 2026-09-17

Scope: verify Zero Data Retention (ZDR) enforcement for private-repository
requests through contextual-orchestrator (the org's LLM gateway), per the
maintainer report that the requirement's implementation was believed
inaccurate. This matters directly for the late-life anxiety reanalysis, which
runs against private research code and data.

## 1. Authoritative definition of the requirement

- `docs/adr/0007-hourly-loop-orchestrator-free-pool-pin.md`: "`ContextualWisdomLab/.github` ADR-0003 records the central review-sidecar
  contract and its 2026-09-02 correction: OpenCode, Noema, and Strix use
  `orchestrator/free`; private targets additionally require ZDR admission,"
  and "Private-repository ZDR enforcement remains a gateway admission
  requirement, not a leaf-side provider selection shortcut." This is the
  authoritative statement that **private-repo requests must be gateway-
  admitted under ZDR**, and that admission logic belongs in this repo, not in
  a calling workflow.
- `CLAUDE.md` (this repo, org role section): confirms this repo is the org's
  LLM gateway, consumed by `gyeot`/`scopeweave`, and is being adopted as the
  shared backend for the org's CI review pipeline (OpenCode/Noema/Strix) —
  i.e. the exact caller class that must carry ZDR admission for private
  targets.
- In code, the requirement is implemented as an opt-in per-request policy,
  not automatic repo-visibility detection: a caller sets `zdr_only: true` on
  the request (`server.py` `_validate_zdr_only`, `ALLOWED_*_KEYS`), which sets
  a request-scoped `ContextVar` (`orchestrator.py:362`
  `_REQUEST_ZDR_ONLY`) via `TaskOrchestrator.request_policy(zdr_only)`. This
  gateway does not itself learn "this repo is private" — the private/public
  classification and the decision to set `zdr_only=True` is the caller's
  (OpenCode/Noema/Strix/`.github`) responsibility per ADR-0003; this repo's
  job is to admit, enforce, and preserve that flag correctly once set,
  fail-closed on any unknown ZDR status. That caller-side classification is
  out of this repo's tree and was not re-audited here — flagged as a
  dependency in §4.
- Agent-level ZDR evidence is discovered, not asserted, in
  `model_discovery.py` (`_openrouter_zdr_model_ids`, `supports_zero_data_retention`,
  `zdr_capable`, `privacy_tags_for_discovered`) and stored as the `privacy:zdr`
  tag consumed everywhere selection happens.

## 2. Provider ZDR terms (official docs, cited)

| Provider | Terms | Source | Accessed |
|---|---|---|---|
| OpenAI | ZDR is an enterprise-tier, sales-approved arrangement per eligible endpoint (`/v1/chat/completions`, `/v1/responses`, `/v1/embeddings`, `/v1/audio/*`, …); not automatic, not on free/pay-as-you-go tiers by default. Even under ZDR, abuse-classifier hits (e.g. CSAM) are retained for review. | [Offering Zero Data Retention for frontier models](https://openai.com/index/offering-zero-data-retention-for-frontier-models/); [Data controls in the OpenAI platform](https://platform.openai.com/docs/guides/your-data) | 2026-09-17 |
| Anthropic | ZDR is a per-organization, sales-reviewed agreement; applies only to eligible Claude Platform/API products and Claude Code for Enterprise using the org's API key. Safety-classifier results and policy-violation flagged sessions can still be retained (up to 2 years) despite ZDR. | [Claude Platform Docs: API and data retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention); [Privacy Center: ZDR product scope](https://privacy.claude.com/en/articles/8956058-i-have-a-zero-data-retention-agreement-with-anthropic-what-products-does-it-apply-to) | 2026-09-17 |
| OpenRouter | ZDR is enforceable per-request via a `zdr` request parameter that restricts routing to ZDR-eligible endpoints only; the eligible-endpoint set is published at `https://openrouter.ai/api/v1/endpoints/zdr` (already the source this repo's `model_discovery._openrouter_zdr_model_ids` reads). Explicitly **does not** cover caller-enabled tools/plugins (e.g. web search), and OpenRouter treats in-memory prompt caching as not "retention," so a ZDR-routed request can still be served from an upstream implicit cache. | [OpenRouter docs: Zero Data Retention](https://openrouter.ai/docs/guides/features/zdr); [OpenRouter blog: What ZDR means for AI APIs](https://openrouter.ai/blog/insights/zero-data-retention/) | 2026-09-17 |

Implication for this gateway: "ZDR-capable" per provider is a *routing*
guarantee about what the upstream provider does with the payload after
receipt. It says nothing about what **this gateway** does with the same
payload before/after that call (its own cache, ledger, logs, workflow-run
persistence). Provider ZDR and gateway-side retention are two independent
controls, and the second is entirely this repo's responsibility — see §3.4.

## 3. Path-by-path trace and verdict

For every path, "enforced before dispatch" = `_REQUEST_ZDR_ONLY` is set via
`request_policy(zdr_only)` before any agent selection; "fail-closed on
unknown" = `_zdr_agent_allowed` (`orchestrator.py:4576`) requires the explicit
`privacy:zdr` tag — an agent with no evidence, or `zdr_capable=None`, is
**not** admitted, it is not treated as eligible-by-default.

### 3.1 Chat completions — route / conduct (`server.py` → `cost_router.py:complete` → `orchestrator.py:run`/`complete`)

- Enforced before dispatch: **Yes.** `server.py:6606` validates `zdr_only`
  from the request body and opens `orchestrator.request_policy(zdr_only)`
  before any candidate selection.
- Fail-closed on unknown ZDR status: **Yes.** `_zdr_agent_allowed` requires
  the `privacy:zdr` tag; a candidate with unknown/absent evidence is
  excluded, and `_ranked_agents` raises `RuntimeError("no ZDR-eligible agent
  is available...")` when the eligible set is empty (`orchestrator.py:8154`)
  rather than silently falling back off-policy.
- Preserved across fallback/failover: **Yes.** `_zdr_agent_allowed` gates
  every candidate-filtering call site used by failover reselection
  (`orchestrator.py:4806, 4904, 4911, 5096, 5290, 5297, 6001, 6026, 6209,
  7464, 7692, 7702, 7950, 8013, 8133, 9273`) — there is no separate
  "failover candidate" code path that bypasses the gate.
- Endpoint racing: **Yes**, same gate applies to race-candidate assembly
  (`cost_router.py` race context wraps `orchestrator.run` inside
  `request_policy(zdr_only)`; race members are drawn from the same
  ZDR-filtered candidate set, not reselected independently).
- Private-repo classification correctness: **out of scope / caller-owned**
  (see §1) — this repo enforces the flag once set; it does not compute repo
  visibility itself.
- Cache: **LEAK FOUND AND FIXED.** See §3.4.
- Debug/response logging: **Clean.** See §3.5.

### 3.2 Batch chat / embeddings (`batch_routing.py`, `cost_router.py` batch paths)

- `EmbeddingBatchRequest`/chat batch request dataclasses carry `zdr_only`
  (`batch_routing.py:192, 624`) and it is explicitly excluded from the
  provider-facing JSONL body (`to_jsonl_line`) — confirmed by
  `tests/test_batch_routing_boundaries.py::test_embedding_request_jsonl_preserves_zdr_policy`
  and `test_chat_request_jsonl_preserves_zdr_policy`: the flag is enforced
  gateway-side for member/model selection and never leaks into the provider
  payload as an unrecognized field.
- `cost_router.py:1391-1396` and `:1848-1864` route embeddings selection
  through `request_policy(zdr_only)` before resolving a target model/agent.
- An unknown/explicit non-existent ZDR model is a non-retryable
  `400 invalid_model` client error (`CHANGELOG.d/batch-routing-owner-model-error.md`,
  `tests/test_cost_review_server.py::test_batch_routing_rejects_unknown_zdr_model_as_client_error`),
  and a `zdr_only` batch with no eligible member returns
  `503`/unavailable rather than silently downgrading
  (`tests/test_cost_review_server.py::test_zdr_batch_without_an_eligible_member_returns_service_unavailable`).
- Verdict: **Correctly enforced, fail-closed.**

### 3.3 Model-group racing / passthrough selection (`select_model_group_members`)

- `orchestrator.py:4587-4610`: `zdr_only` is an explicit parameter that, when
  given, wraps the *caller-supplied* candidate pool (e.g. a virtual
  model-group array from `naruon`) in `request_policy` before filtering —
  so an externally supplied candidate array cannot bypass the same
  `_zdr_agent_allowed` gate applied to the built-in pool.
- Verdict: **Correctly enforced.**

### 3.4 Response cache (`response_cache.py`, `orchestrator.py:complete`) — LEAK FOUND

- **Before this audit:** `TaskOrchestrator.complete()`
  (`orchestrator.py:6051`) only skipped the shared response cache
  (`ResponseCacheProvider`, e.g. Redis-backed) when the *cache provider was
  absent* or the caller explicitly passed `bypass_cache=True`. The active
  `zdr_only` request policy was folded into the cache **key** (so a ZDR and
  non-ZDR request for the same prompt would not collide), but a ZDR request
  was still fully read from and written to that cache. `cost_router.py:733`
  only sets `bypass_cache` from an explicit `cache_bypass` request field —
  never from `zdr_only`.
  Net effect: a private-repo, ZDR-flagged request's prompt and answer were
  persisted verbatim into whatever backend `cache_provider` points at
  (in-memory locally; Redis/Dragonfly in the documented deployment target —
  see `RedisResponseCacheProvider`), and a stale cached answer could be
  served to a *later* ZDR request without the private-repo caller's data ever
  reaching the current live model call boundary again. This directly
  contradicts the task's own retention control even though the *provider*-side
  ZDR contract (§2) was untouched — this is a gateway-side retention gap, not
  a provider one.
  RED test added:
  `tests/test_distributed_cache_truth_and_isolation.py::test_zdr_only_request_never_reads_or_writes_the_response_cache`
  and `::test_zdr_only_request_ignores_a_preexisting_cache_entry`.
- **Fix (this PR):** `TaskOrchestrator.complete()` now also bypasses the
  cache whenever `_REQUEST_ZDR_ONLY.get()` is true, independent of any
  caller-supplied `bypass_cache`/`cache_bypass` value — fail-closed rather
  than opt-in. `cache_status` reports `"bypass"` for these requests.
- Verdict: **Fixed.** GREEN: both new tests plus the full existing
  `test_distributed_cache_truth_and_isolation.py`,
  `test_cost_router_boundaries.py`, `test_model_judge.py`,
  `test_batch_embeddings.py`, `test_batch_routing_boundaries.py` (zdr/cache
  subset), and `test_cost_review_server.py` (zdr/cache subset) suites pass
  unchanged.

### 3.5 Debug logging (`debug_logging.py`, `server.py` response/summary logging)

- `debug_logging.py` is a credential-shape redaction safety net; it does not
  log request/response bodies at all.
- `server.py:_response_payload` (`server.py:5121-5138`) logs, at DEBUG, only
  an explicit allowlisted metadata shape (`has_error`/`model`/`choice_count`/
  `usage` via `response_metadata_for_log`) — never `choices[].message.content`
  or other response text — with an explicit comment noting exactly the
  CWE-532 risk this audit was checking for. Request-line logging
  (`server.py:5693-5710`) logs only `method`/`path`/`status`/`latency`, never
  the body.
- No ZDR-specific carve-out exists in logging because none is needed: prompt
  and answer content already never reach a log call for *any* request, ZDR
  or not.
- Verdict: **Clean, no change required.**

### 3.6 Metering / cost-ledger persistence (`cost_ledger.py`)

- `UsageEvent`/ledger records are explicitly documented as "OpenTelemetry-shaped
  usage event**s** without prompt or answer content" (`cost_ledger.py:336`);
  fields are limited to counts, cost, provider/model identifiers, and
  attribution — no message content type exists on the record.
- Verdict: **Clean, no change required.**

### 3.7 Workflow-run trace persistence (in-memory / `--state-db`)

- Out of scope of the leak class this audit targeted (provider-facing ZDR
  contract and this gateway's own cache/log retention), but noted for
  follow-up: `_replace_workflow_run` persists `prompt_text`/`answer`/`trace`
  into the in-memory run history and, when `--state-db PATH` is configured,
  into sqlite, for every request regardless of `zdr_only`. This is a
  distinct, pre-existing product behavior (operator-facing run history), not
  the caches/logs surface named in this audit's task, and disabling it for
  ZDR requests would remove operator visibility into exactly the requests
  most likely to need incident review. **Recommendation, not fixed here:**
  decide, as a follow-up product decision, whether `zdr_only` runs should be
  redacted or excluded from `--state-db` persistence; flagging for a
  maintainer decision rather than silently changing operator-facing
  behavior in a security-audit PR.

## 4. Out-of-scope dependency

Private-repository classification itself (which target repos are private,
and the decision to set `zdr_only=True` for them) lives in
`ContextualWisdomLab/.github`'s OpenCode/Noema/Strix sidecar contract per
ADR-0003, not in this repository. This audit verified that once `zdr_only`
is set by a caller, this gateway enforces and preserves it correctly (with
the one cache exception now fixed); it did not re-audit the `.github` sidecar's
own private/public detection logic, which is a different repository.

## 5. Summary

| Path | Enforced pre-dispatch | Fail-closed on unknown | Preserved across fallback/racing/batch | Cache/log clean | Verdict |
|---|---|---|---|---|---|
| Chat route/conduct | Yes | Yes | Yes | Cache: fixed; logs: clean | Fixed |
| Batch chat/embeddings | Yes | Yes | Yes | Clean | Pass |
| Model-group racing/passthrough | Yes | Yes | Yes | N/A | Pass |
| Response cache | N/A | N/A | N/A | Was leaking, now bypassed for ZDR | **Fixed this audit** |
| Debug logging | N/A | N/A | N/A | Clean | Pass |
| Cost ledger | N/A | N/A | N/A | Clean | Pass |
| Workflow-run/state-db trace | N/A | N/A | N/A | Persists prompt/answer regardless of zdr_only | Flagged, not fixed (product decision) |

One real leak was found and fixed in this audit: **the shared response cache
did not honor `zdr_only`.** All other traced paths already enforced ZDR
correctly, fail-closed, and did not weaken any other gate.
