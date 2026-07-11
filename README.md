# Contextual Orchestrator

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/ContextualWisdomLab/contextual-orchestrator)
[![Security](https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/workflows/security.yml/badge.svg)](https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/workflows/security.yml)

Stdlib Python lab for a single API that routes, delegates, verifies, and synthesizes work across a configurable pool of OpenAI-compatible model agents.

This is not a Sakana AI product or a reproduction of their trained models. It is a small implementation of the public architecture pattern: expose one model-like interface while keeping the agent pool, routing, workflow, and verification logic behind it.

## Quick Start

```bash
python -m contextual_orchestrator "Summarize why model orchestration helps long coding tasks." \
  --agents examples/agents.mock.json
```

Run the OpenAI-compatible subset:

```bash
export CONTEXTUAL_ORCHESTRATOR_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m contextual_orchestrator --serve --agents examples/agents.mock.json --port 8000
```

Admin console:

```text
http://127.0.0.1:8000/admin
```

```bash
curl -s http://127.0.0.1:8000/v1/chat/completions \
  -H "authorization: Bearer $CONTEXTUAL_ORCHESTRATOR_TOKEN" \
  -H 'content-type: application/json' \
  -d '{"model":"contextual-orchestrator","messages":[{"role":"user","content":"Analyze this code review task and verify the answer."}]}' | jq .
```

HTTP serving is hardened for local lab use:

- `/admin`, `/admin/state`, `/api/v1/*`, and `/v1/chat/completions` require a Bearer token. Use `--admin-token` and `--inference-token` to separate operator and runtime access, or `--auth-token` / `CONTEXTUAL_ORCHESTRATOR_TOKEN` for one local-development token.
- Binding to `0.0.0.0` or `::` requires `--allow-public-bind`.
- JSON request bodies, chat message roles, orchestration modes, body sizes, request rate, and concurrent run counts are validated before orchestration runs.
- Full orchestration traces are not returned by default. Set `include_orchestration_trace: true` per chat request or start with `--expose-trace-by-default` when the caller is trusted.
- State is in-memory by default. Pass `--state-db PATH` (or `CONTEXTUAL_ORCHESTRATOR_STATE_DB`) to persist workflow runs, evaluation runs, audit, and analytics to a stdlib sqlite file so they survive a restart; without it, behavior is unchanged.
- Response caching is off by default. Pass `--cache-ttl SECONDS` to serve identical requests (same messages + mode) from an in-memory TTL+LRU cache and skip the provider calls; `0` disables it.
- `ModelClient.batch_chat(agent, {custom_id: messages})` runs many requests through the provider's Batch API (async, 24h completion window, typically ~50% cheaper) — suited to evaluation/benchmark workloads, not latency-sensitive chat. The mock path answers synchronously.

Use real workers by replacing `mock://` agents with OpenAI-compatible endpoints. Provider secrets are resolved from a KV credential registry via `get_credential`, never from `os.getenv` at request time (see [docs/kv-credentials.md](docs/kv-credentials.md)):

```json
{
  "agents": [
    {
      "id": "coding_agent",
      "model": "gpt-5.5",
      "base_url": "https://api.openai.com/v1",
      "credential_key": "OPENAI_API_KEY",
      "tags": ["coding", "debugging", "reasoning"]
    }
  ]
}
```

Seed the credential into the KV once at bootstrap:

```bash
echo "$OPENAI_API_KEY" | python -m contextual_orchestrator register-credential --name OPENAI_API_KEY --value-stdin
```

Non-mock providers must use `https://` URLs and a **resolvable KV credential** — a non-mock agent whose credential is missing raises `NotConfigured` rather than falling back to an environment variable. The runtime blocks loopback, private, link-local, multicast, and reserved provider addresses before sending a key. Set `CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS` to a comma-separated host allowlist when only approved model gateways should be reachable. External calls use a timeout and default output token cap.

> The legacy `api_key_env` field is still accepted for back-compat, but its value is now treated as the **credential name** in the KV, not as an environment variable to read. This supersedes the old `api_key_env` env pattern.

## Architecture

One public interface:

- `/v1/chat/completions` accepts normal chat messages, and `"stream": true` returns an OpenAI-compatible `text/event-stream` of `chat.completion.chunk` deltas terminated by `data: [DONE]`. In **route** mode the worker's tokens are streamed live as they arrive from the provider (real token streaming); in **conduct** mode the multi-step answer is produced then framed as deltas (a workflow can't honestly token-stream a synthesizer that hasn't run yet).
- `TaskOrchestrator.complete()` decides whether to route to one worker or run a short workflow.
- `TaskOrchestrator.compare_to_baseline(prompts, mode)` (CLI `--eval PROMPT...`) measures the orchestration engine against a single-worker baseline — per-prompt and aggregate latency plus a structural coverage delta (contributing steps + verifier-pass presence). It is a measured tradeoff report, not a human-quality claim.
- Responses include orchestration mode metadata, and trusted callers can request the full trace for audit.
- `/admin` exposes an operator console for agent pool, policy, trace, and audit review.
- `/api/v1/spend_analytics/latest` exposes per-model token and cost spend aggregated from workflow runs. Output tokens use provider-reported `usage` when available and fall back to a ~4 chars/token estimate otherwise (each model row is labeled `usage_source: reported | mixed | estimated`); cost is computed only for models with an operator-supplied price (`TaskOrchestrator(price_per_million=...)`), otherwise reported as null with the model listed under `unpriced_models`. See [Observability & spend](#observability--spend).
- `/api/v1/sales_readiness/latest` exposes a local enterprise-pilot readiness gate for API compatibility, operator evidence, workflow traces, evaluation replay, security posture, analytics truthfulness, locale parity, and provider egress safety. It is process-local evidence, not a production compliance certificate.
- `/api/v1/commercial_readiness/latest` exposes a KRW 2,000,000,000 commercial due-diligence readiness gate. It is a buyer-review evidence snapshot, not a valuation guarantee or purchase commitment.
- `/api/v1/buyer_evidence_manifests/latest` exposes the buyer evidence manifest as a runtime review index across endpoints, repository artifacts, Figma artifacts, verification evidence, and production or buyer-specific caveats.
- `/api/v1/buyer_handoff_bundles/latest` exposes the buyer handoff bundle across runtime reports, repository packet, Figma artifacts, verification commands, packaging decision, and explicit production or buyer-specific follow-ups.
- `/api/v1/saleability_decisions/latest` exposes the final KRW 2,000,000,000 saleability decision gate with concrete blockers, warning conditions, and review-process non-blocker policy.
- `/api/v1/commercial_evidence_exports/latest` exposes the portable commercial evidence export across saleability, runtime reports, buyer documents, Figma artifacts, verification commands, review-process policy, packaging decision, and external evidence gaps.
- `/api/v1/commercial_acceptance_checks/latest` exposes the buyer acceptance check across evidence export, runtime endpoint chain, buyer packet, admin surface, verification, Figma, review-process policy, packaging decision, and external evidence gaps.
- `/api/v1/commercial_buyer_acceptance_workflows/latest` exposes the buyer acceptance workflow across owner-scoped runbook steps, Go/Warning/No-Go rules, runtime evidence, Figma artifacts, analytics truthfulness, review-process policy, and packaging decision.
- `/api/v1/commercial_release_candidates/latest` exposes the local commercial release-candidate manifest across acceptance, runtime endpoints, repository distribution packet, security metadata, admin surface, verification, Figma, review-process policy, packaging decision, and external release gaps.
- `/api/v1/commercial_gap_registers/latest` exposes the commercial gap register that turns release-candidate external gaps into owner, source, required-input, and status rows for buyer due diligence.
- `/api/v1/commercial_procurement_readiness/latest` exposes the commercial procurement readiness gate across license, rights, security metadata, distribution packet, admin evidence, production support/SLO input, buyer legal/ROI/procurement input, review-process policy, and packaging decision.
- `/api/v1/commercial_contract_readiness/latest` exposes the commercial contract readiness gate across support/SLO terms, security/privacy terms, audit/export obligations, license/commercial rights, buyer order-form inputs, review-process policy, and packaging decision.
- `/api/v1/commercial_onboarding_readiness/latest` exposes the commercial onboarding readiness gate that turns production support/SLO and buyer-specific input warnings into paid-onboarding owners, actions, and exit criteria.
- `/api/v1/commercial_operations_readiness/latest` exposes the commercial operations readiness gate that turns production telemetry, incident/rollback, backup/recovery, and SLO evidence gaps into operations handoff owners, actions, and exit criteria.
- `/api/v1/commercial_security_attestations/latest` exposes the commercial security attestation gate that separates repo-local security evidence from external attestation, hosted scan, and buyer privacy/DPA gaps.
- `/api/v1/commercial_value_readiness/latest` exposes the commercial value readiness gate that separates repo-local measured value evidence from buyer-specific ROI, reference proof, budget-owner, and payback-input gaps.
- `/api/v1/commercial_close_readiness/latest` exposes the commercial close readiness gate that separates repo-local sellable product evidence from buyer signatures, DPA/security acceptance, budget/PO, and go-live authorization gaps.
- `/api/v1/commercial_go_to_market_readiness/latest` exposes the commercial go-to-market readiness index that ties close, value, security, evidence export, buyer handoff, saleability, admin evidence, analytics truthfulness, Figma artifacts, review-process policy, and packaging decision into one buyer/stakeholder review packet.
- `/api/v1/commercial_launch_readiness/latest` exposes the commercial launch readiness gate that packages GTM, runtime, acceptance, operator, admin, analytics, Figma, review-process, and packaging evidence while keeping buyer environment, production telemetry, and signature inputs as explicit warnings.
- `/api/v1/commercial_completion_scorecards/latest` exposes the runtime commercial completion scorecard for the KRW 2,000,000,000 program-completion standard across Product Design, Figma, Superpowers, Ponytail, Data Analytics, runtime, verification, review-policy, packaging, and external follow-up evidence.
- `/api/v1/commercial_demo_scenarios/latest` exposes the KRW 2,000,000,000 commercial demo scenarios packet across compatible API smoke, workflow trace, access-list evidence, evaluation replay, admin readiness, metric truthfulness, Figma review, buyer acceptance, review-process policy, and packaging decision.
- `/api/v1/commercial_proposal_packets/latest` exposes the KRW 2,000,000,000 commercial proposal packet across completion, demo, acceptance, value, security, contract, onboarding, operations, analytics truthfulness, Figma review, review-process policy, packaging decision, and buyer-specific follow-ups.
- `/api/v1/commercial_purchase_approval_packets/latest` exposes the KRW 2,000,000,000 commercial purchase approval packet across proposal, close, procurement, contract, value, security, onboarding, operations, analytics truthfulness, Figma review, review-process policy, packaging decision, and buyer signature/budget authority follow-ups.
- `/api/v1/commercial_due_diligence_rooms/latest` exposes the KRW 2,000,000,000 commercial due diligence room across purchase approval, runtime API evidence, admin trace/access evidence, security, commercial terms, value analytics, implementation readiness, Figma review, review-process policy, packaging decision, and buyer/external missing artifacts.
- `/api/v1/commercial_investment_committee_memos/latest` exposes the KRW 2,000,000,000 commercial investment committee memo across due diligence, purchase approval, financial case, risk/security, commercial terms, implementation readiness, Figma review, review-process policy, packaging decision, and buyer/external approval conditions.

One fused orchestration loop:

- Fast path: one worker is selected for simple or latency-sensitive requests.
- Deep path: a natural-language workflow is built with planner, worker, verifier, and synthesizer steps.
- Each step has an access list, so workers see only the prior outputs intentionally exposed to them.
- Agent definitions are data, so provider preference, exclusions, privacy constraints, and mock testing do not require code changes.
- Provider calls are resilient: transient failures (timeouts, 429, 5xx) retry with full-jitter exponential backoff, while caller errors (4xx) fail fast. If an agent still fails, the request fails over to the next capability-matched agent in the pool, and a per-agent circuit breaker skips a persistently failing provider until it cools down. Failover is recorded in the trace (`served_agent_id`, `failover_from`).

See [docs/architecture.md](docs/architecture.md) for the source-backed analysis.

## Observability & spend

Local spend observability, aggregated from in-memory workflow runs. It is honest by construction — estimates are labeled, and cost is only reported when a price is configured.

```bash
curl -s http://127.0.0.1:8000/api/v1/spend_analytics/latest \
  -H "authorization: Bearer $CONTEXTUAL_ORCHESTRATOR_TOKEN" | jq '.totals, .by_model, .budget'
```

- **Tokens.** `by_model[].output_tokens` uses the provider-reported `usage.completion_tokens` when a real worker returns it, and falls back to a `~4 chars/token` estimate otherwise. Each row carries `usage_source`: `reported` (all steps reported), `mixed`, or `estimated`. `estimated_output_tokens` is always the estimate, kept alongside for comparison. `measurement_status` is `local_runtime_estimate`, not production telemetry.
- **Cost.** Supply a price table to turn tokens into money — `TaskOrchestrator(price_per_million={"gpt-5.5": 10.0})` (USD per 1M output tokens). Models without a price appear under `unpriced_models` with `estimated_cost_usd: null`. No prices are assumed or fabricated.
- **Budget cap.** Set an operator cap to refuse runaway spend (default: no cap):

  ```bash
  python -m contextual_orchestrator --serve --agents examples/agents.mock.json \
    --budget-max-output-tokens 2000000 --budget-max-cost-usd 50
  ```

  Or in code: `TaskOrchestrator(budget_max_output_tokens=..., budget_max_cost_usd=...)`. Once spend reaches a cap, the next run is refused — `run()` raises `BudgetExceededError` and `/v1/chat/completions` returns HTTP `429 budget_exceeded`. Current state is in `spend_analytics()["budget"]` (`enabled`, limits, `spent_*`, `remaining_*`, `exceeded`). Cost caps require a price table; token caps do not.
- **Admin.** The `/admin` **Observability** view renders the totals and the per-model table (unpriced models show an `unpriced` chip).

These are process-local measured signals for a stdlib lab, not a billing system or production compliance data.

## Cost review + routing hub

The orchestrator is the single control point for **LLM cost review** and
**sync-vs-batch routing** (a LiteLLM-plus scope: cost optimiser + upstream load
balancing + batch routing). All config — prices, thresholds, batch endpoints —
is read from a **KV config store**, never `os.getenv`.

- **Usage + cost ledger.** Every completion, sync *and* batch, builds a
  prompt-safe usage record with generated IDs, token counts, cost, provider,
  model, channel, route mode, and attribution dimensions. Raw prompt and answer
  text are not part of the usage record or telemetry event. The default
  in-memory ledger keeps local reports available; external persistence/export
  should be wired through the OpenTelemetry-shaped usage event sink or the
  bounded `NonBlockingLedgerStore`, so store failures are observable as usage
  export health without failing completions. Cost is attributable on seven
  first-class dimensions catalogued in `cost_attribution_dimensions`: **account,
  service, upstream API/provider, model name, team, group, company**. Token
  counts reuse `pg-llm-batch`'s `pg_tiktoken` counter when a Postgres DSN is
  configured, and fall back to a deterministic heuristic otherwise.
- **Reporting.** `GET /api/v1/cost_reports/rollup?dimension=team&start=&end=`
  rolls up cost + tokens by any dimension over any time window;
  `GET /api/v1/llm_usage_records` lists raw ledger rows;
  `GET /api/v1/cost_attribution_dimensions` lists the dimension catalog.
- **Routing.** `RoutingPolicy` decides sync vs batch from request hints
  (`{"routing": {"latency_tolerant": true}}` on `/v1/chat/completions`) plus
  KV thresholds. Interactive requests stay on the fast sync path; latency-tolerant
  or bulk requests are dispatched to a batch backend.
- **Batch routing to pg-llm-batch.** The production batch backend is an injected
  [`pg-llm-batch`](https://github.com/ContextualWisdomLab/pg-llm-batch)
  OpenAI-compatible Batch API client (submit JSONL -> poll -> retrieve). A local
  in-process backend preserves the mock/standalone path with no external service
  or repository split.
  Submit via `POST /api/v1/batch_routing_jobs`, poll
  `GET /api/v1/batch_routing_jobs/{id}`, retrieve
  `POST /api/v1/batch_routing_jobs/{id}/results` (which records usage + cost).
- **Batch embeddings.** Bulk, latency-tolerant embedding work (e.g. naruon's
  email-import backfill) submits to `POST /v1/batch/embeddings`
  (`{model, input|inputs:[...], endpoint, metadata|attribution}`) and polls
  `GET /v1/batch/embeddings/{batch_id}`. The response is
  `{batch_id, status, embeddings:[{index, embedding}], cost_micro_usd,
  token_counts, total_tokens, part_count, input_part_counts, map_reduce}`. Before
  the provider call, the coordinator maps oversized inputs into token-budgeted
  embedding parts (`routing.embedding_max_tokens_per_request`, default 280,000;
  `routing.embedding_max_chars_per_part`, default 240,000) and reduces part
  vectors with a token-weighted average, so Azure/LiteLLM over-limit embedding
  requests are split internally instead of surfacing as caller errors. It routes
  through the same RoutingPolicy/cost optimiser and `pg-llm-batch` embeddings
  backend (local in-process backend standalone), and records one usage-ledger row
  per original vector with the full attribution dimensions (service, team,
  group, company, provider) carried in `metadata`.
- **Health.** `GET /healthz` is an unauthenticated liveness probe.
- **Standalone + optional pg-llm-batch integration.** The hub runs standalone
  with the in-memory config store and local batch backend; wiring a Postgres DSN
  and an installed/deployed `pg_llm_batch` client activates the KV/secret stores,
  `pg_tiktoken` counting, and the production batch backend without adding a
  repository split here.

Grounding papers (LLM cost, routing, load balancing) live in
[docs/papers](docs/papers/README.md) with citations.

## Design Artifacts

- [Library research](docs/library_research.md)
- [Product planning](docs/product_planning.md)
- [Screen design](docs/screen_design.md)
- [User stories](docs/user_stories.md)
- [REST API design](docs/rest_api_design.md)
- [Code conventions](docs/code_conventions.md)
- [Database conventions](docs/database_conventions.md)
- [i18n design](docs/i18n_design.md)
- [Plugin-driven design brief](docs/plugin_driven_design_brief.md)
- [Plugin visual directions](docs/plugin_visual_directions.md)
- [Analytics spec](docs/analytics_spec.md)
- [Commercial readiness standard](docs/commercial_readiness.md)
- [Commercial buyer diligence packet](docs/commercial_buyer_diligence_packet.md)
- [Commercial buyer acceptance runbook](docs/commercial_buyer_acceptance_runbook.md)
- [Commercial buyer evidence manifest](docs/commercial_buyer_evidence_manifest.md)
- [Commercial buyer handoff bundle](docs/commercial_buyer_handoff_bundle.md)
- [Commercial saleability decision](docs/commercial_saleability_decision.md)
- [Commercial evidence export](docs/commercial_evidence_export.md)
- [Commercial acceptance check](docs/commercial_acceptance_check.md)
- [Commercial release candidate](docs/commercial_release_candidate.md)
- [Commercial gap register](docs/commercial_gap_register.md)
- [Commercial procurement readiness](docs/commercial_procurement_readiness.md)
- [Commercial contract readiness](docs/commercial_contract_readiness.md)
- [Commercial onboarding readiness](docs/commercial_onboarding_readiness.md)
- [Commercial operations readiness](docs/commercial_operations_readiness.md)
- [Commercial security attestation](docs/commercial_security_attestation.md)
- [Commercial value readiness](docs/commercial_value_readiness.md)
- [Commercial close readiness](docs/commercial_close_readiness.md)
- [Commercial go-to-market readiness](docs/commercial_go_to_market_readiness.md)
- [Commercial launch readiness](docs/commercial_launch_readiness.md)
- [Commercial completion scorecard](docs/commercial_completion_scorecard.md)
- [Commercial demo scenarios](docs/commercial_demo_scenarios.md)
- [Commercial proposal packet](docs/commercial_proposal_packet.md)
- [Commercial purchase approval packet](docs/commercial_purchase_approval_packet.md)
- [Commercial due diligence room](docs/commercial_due_diligence_room.md)
- [Commercial investment committee memo](docs/commercial_investment_committee_memo.md)
- [Commercial plugin operating model](docs/commercial_plugin_operating_model.md)
- [Figma artifacts](docs/figma_artifacts.md)
- [Plugin-driven implementation plan](docs/superpowers/plans/2026-07-02-plugin-driven-product-design.md)
- [Commercial plugin readiness plan](docs/superpowers/plans/2026-07-02-commercial-plugin-readiness.md)

## Check

```bash
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps -e .
python tests/test_self_check.py
python tests/test_paper_contracts.py
python tests/test_admin_contract.py
python tests/test_conventions.py
python tests/test_api_contract.py
python tests/test_security_hardening.py
python tests/test_repository_security_metadata.py
python tests/test_product_planning_contract.py
python tests/test_plugin_driven_artifacts.py
python tests/test_analytics_runtime.py
python tests/test_sales_readiness.py
python tests/test_buyer_evidence_manifest.py
python tests/test_buyer_handoff_bundle.py
python tests/test_saleability_decision.py
python tests/test_commercial_evidence_export.py
python tests/test_commercial_acceptance_check.py
python tests/test_commercial_buyer_acceptance_workflow.py
python tests/test_commercial_release_candidate.py
python tests/test_commercial_gap_register.py
python tests/test_commercial_procurement_readiness.py
python tests/test_commercial_contract_readiness.py
python tests/test_commercial_onboarding_readiness.py
python tests/test_commercial_operations_readiness.py
python tests/test_commercial_security_attestation.py
python tests/test_commercial_value_readiness.py
python tests/test_commercial_close_readiness.py
python tests/test_commercial_go_to_market_readiness.py
python tests/test_commercial_launch_readiness.py
python tests/test_commercial_completion_scorecard.py
python tests/test_commercial_demo_scenarios.py
python tests/test_commercial_proposal_packet.py
python tests/test_commercial_purchase_approval_packet.py
python tests/test_commercial_due_diligence_room.py
python tests/test_commercial_investment_committee_memo.py
```
