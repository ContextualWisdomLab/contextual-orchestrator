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
| `POST` | `/api/v1/workflow_runs` | Create a route/conduct run |
| `GET` | `/api/v1/locale_bundles/{locale_code}` | Read i18n bundle |
| `GET` | `/admin` | Management console |

## Production Library Target

FastAPI should replace the current stdlib HTTP adapter when the API needs authentication, richer OpenAPI schema generation, dependency injection, and typed request/response models.

