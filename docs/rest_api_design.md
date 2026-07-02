# REST API Design

## Rules

- API version prefix: `/api/v1`.
- Resource names: plural lower snake_case, at least two words.
- Operation IDs: verb plus resource, lower snake_case.
- Error shape: `{"error_code": "...", "error_message": "...", "error_detail": {...}}` in production.
- Pagination shape: `items`, `total_count`, `page_number`, `page_size` for collections.
- OpenAI-compatible compatibility endpoint remains `/v1/chat/completions`.

## Current Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/openapi.json` | API contract |
| `POST` | `/v1/chat/completions` | Compatibility chat endpoint |
| `GET` | `/api/v1/agent_pools` | List model agents |
| `GET` | `/api/v1/orchestration_policies/default_policy` | Read active policy |
| `GET` | `/api/v1/analytics_snapshots/latest` | Read local runtime KPI and guardrail snapshot |
| `GET` | `/api/v1/sales_readiness/latest` | Read local enterprise-pilot readiness criteria and evidence |
| `GET` | `/api/v1/commercial_readiness/latest` | Read KRW 2,000,000,000 commercial due-diligence readiness criteria and evidence |
| `POST` | `/api/v1/workflow_runs` | Create a route/conduct run |
| `GET` | `/api/v1/workflow_runs` | List recent workflow runs |
| `GET` | `/api/v1/workflow_runs?page_number=1&page_size=20` | Paginate workflow run history with deterministic page metadata |
| `GET` | `/api/v1/workflow_runs/{workflow_run_id}` | Inspect one run and trace |
| `GET` | `/api/v1/access_reports/{workflow_run_id}` | Inspect access-list evidence |
| `PATCH` | `/api/v1/agent_pools/{agent_pool_id}/worker_agents/{worker_agent_id}` | Update status/priority/tags/provider exclusions |
| `POST` | `/api/v1/evaluation_runs` | Replay prompts and return a reproducible evaluation run |
| `GET` | `/api/v1/evaluation_runs/{evaluation_run_id}` | Review replay output |
| `GET` | `/api/v1/locale_bundles/{locale_code}` | Read i18n bundle |
| `GET` | `/admin` | Management console |

## Product Planning Additions (Implemented)

These product surfaces are now implemented in this prototype:

| Method | Path | Purpose | Paper Basis |
|---|---|---|---|
| `GET` | `/api/v1/workflow_runs/{workflow_run_id}` | Inspect one run with role, worker, subtask, access list, verifier result, and synthesis evidence. | TRINITY roles; Conductor workflow steps and access lists. |
| `POST` | `/api/v1/evaluation_runs` | Replay a prompt or dataset against policy variants before changing production routing. | Fugu and TRINITY optimize coordination against measured outcomes. |
| `GET` | `/api/v1/access_reports/{workflow_run_id}` | Produce compliance evidence for which worker saw which prior outputs. | Conductor access-list visibility control. |
| `PATCH` | `/api/v1/agent_pools/{agent_pool_id}/worker_agents/{worker_agent_id}` | Update status, priority, capability tags, or provider exclusion. | Fugu configurable worker pool and provider/compliance constraints. |
| `GET` | `/api/v1/analytics_snapshots/latest` | Produce source-backed local KPI and guardrail evidence without claiming production telemetry. | Fugu evaluation discipline; TRINITY verification evidence; Conductor access-list guardrails. |
| `GET` | `/api/v1/sales_readiness/latest` | Produce a sellable-pilot readiness gate from current runtime, admin, security, analytics, locale, and provider evidence. | Fugu API adoption; TRINITY verification; Conductor trace and access-list evidence. |
| `GET` | `/api/v1/commercial_readiness/latest` | Produce a high-value buyer due-diligence readiness gate for the KRW 2,000,000,000 target without presenting it as a valuation guarantee. | Fugu API adoption; TRINITY verification; Conductor trace/access evidence; enterprise procurement review. |

## Production Library Target

FastAPI should replace the current stdlib HTTP adapter when the API needs authentication, richer OpenAPI schema generation, dependency injection, and typed request/response models.
