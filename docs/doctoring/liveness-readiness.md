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
