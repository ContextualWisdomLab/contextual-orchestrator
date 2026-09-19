# Sales-Ready Completion Design

## Purpose

Contextual Orchestrator should be sellable as an enterprise pilot control-plane
program, not only as a planning artifact or local lab. "Sales-ready" means a
buyer, operator, or compliance reviewer can run the program, inspect the API and
admin evidence surfaces, and see a truthful readiness report that separates
working pilot capabilities from enterprise-stack follow-ups.

## Scope

This design keeps the repo as one unified product: an OpenAI-compatible
inference API with an admin/evidence control plane. It does not add Figma Code
Connect, a new frontend framework, billing, SSO, RBAC, a database runtime, or a
separate product line.

## Acceptance Criteria

- The runtime exposes a source-backed sales readiness report.
- The report uses explicit `pass`, `warn`, and `fail` statuses.
- The report never claims production telemetry when only process-local runtime
  data exists.
- The report checks API compatibility, admin evidence, trace completeness,
  evaluation replay, analytics labeling, locale parity, provider egress safety,
  and security posture.
- The admin console links to the readiness report and renders it as operator
  evidence.
- The OpenAPI contract documents the readiness endpoint.
- English and Korean operator copy remains available.
- Tests prove the readiness contract, endpoint, and admin exposure.

## Design

Add `TaskOrchestrator.sales_readiness_report(locale_bundles=None,
security_profile=None)` returning:

- `readiness_status`: `sales_ready`, `pilot_ready_with_warnings`, or
  `not_ready`.
- `measurement_status`: `local_runtime_snapshot`.
- `source_note`: explicit non-production-telemetry caveat.
- `criteria`: rows with `criterion_name`, `status`, `label`, `evidence`, and
  `remediation`.
- `summary`: counts for `pass`, `warn`, and `fail`.

Add `GET /api/v1/sales_readiness/latest` as an admin-scoped endpoint. The
endpoint passes security configuration facts such as auth mode, split-token use,
public bind setting, trace exposure setting, and request/concurrency limits into
the report without exposing secret values.

Extend the static admin console with a compact readiness panel in the
observability view. It should fetch the readiness endpoint beside analytics and
show status rows without adding dependencies or a new UI stack.

## Testing

Use TDD. Add `tests/test_sales_readiness.py` first and verify it fails before
implementation. The test must cover the direct orchestrator report, the HTTP
endpoint, OpenAPI registration, admin HTML references, and warning behavior for
single-token local deployment.

## Documentation

Update README and product/API docs to describe the readiness report as a pilot
sales gate, not proof of production operation.
