# Liveness and readiness boundary

`GET /healthz` is an unauthenticated process probe. It returns only the stable
`status` and `service` fields and does not inspect agents, providers, batch
backends, credentials, usage records, or external services.

`GET /readyz` is an administrator-authenticated operational probe. It returns
secret-free required and optional dependency states without calling a live LLM
provider. A `503` means the required orchestration or synchronous routing path
is unavailable; a degraded optional batch path does not restart a healthy
interactive service.

Run the contract check with:

```bash
python tests/test_cost_review_server.py
```

The probe split follows the Kubernetes distinction between a process that is
alive and a process that is ready to receive work. It also keeps liveness
available during dependency degradation so a supervisor does not create a
restart storm.

## CI sidecar liveness (issue #926)

`GET /v1/readiness` is an inference-scoped, per-candidate liveness probe for a
minimal-privilege caller such as the org's CI review sidecar
(`ContextualWisdomLab/.github`, ADR-0005). Before this route existed, the only
per-candidate diagnostic surface was the admin-scoped
`GET /api/v1/provider_readiness/latest`, so a sidecar that only holds an
`inference`-scoped bearer token had no way to get real
`status`/`failure_code`/`latency_ms` diagnostics without being granted
admin-level access to the gateway -- a real privilege widening `.github` was
unwilling to accept.

`/v1/readiness` calls `TaskOrchestrator.inference_readiness_report()`, which
reuses `provider_readiness_report()` (there is no second probe
implementation to keep in sync) and returns an explicit allowlist of fields:
`agent_id`, `model`, `provider_name`, `status`, `failure_code`, `latency_ms`,
and, when a report exposes them, `rate_limited_until`/`earliest_ready_seconds`.
Credentials, base URLs, admin audit fields, and raw error bodies (and any
other field outside that allowlist, e.g. `usage`) never appear in the
response. `?refresh=true` triggers a fresh probe exactly like the admin route,
serialized through the same `provider_readiness_report` lock; no separate
rate limit is layered on top; there was none to reuse in the admin path
beyond that lock, so none was invented here.

Run the contract check with:

```bash
python tests/test_inference_readiness_probe.py
```
