# Operational Alert Classification

## Purpose

`contextual-orchestrator` can sit in front of model-gateway operations as a
small incident-routing guard. The guard classifies external alerts before they
become outage tickets or pages. It does not mutate LiteLLM, PostgreSQL, PgCat,
or the monitoring backend; it returns a deterministic routing decision that an
alert pipeline can apply.

## LiteLLM Prisma P2028 Spend-Log Rule

The first supported suppression rule targets this complete signature:

- `LiteLLM`
- `Prisma`
- `P2028`
- `Unable to start a transaction in the given time`
- `[Non-Blocking]`
- `update spend logs`

When all signals are present, the classifier returns:

- `classification_status: suppressed`
- `incident_routing: drop`
- `page_required: false`
- `reason_code: non_blocking_spend_log_transaction_timeout`

Rationale: LiteLLM has already marked the spend-log write path as
non-blocking. A transaction-start timeout here is a persistence backlog or pool
pressure signal. By itself, it is not proof that inference is unavailable or
that users are receiving failed responses.

## Non-Suppression Cases

The classifier must not suppress similar-looking alerts when the complete
signature is missing. Examples:

- P2028 during key lookup, request authorization, model routing, or any
  user-facing request path.
- LiteLLM or Prisma DB errors without `[Non-Blocking]`.
- Spend or ledger errors paired with elevated 5xx, latency, health-check, or
  customer-facing SLO alerts.

Those return `classification_status: escalate` and follow normal incident
policy.

## API

```bash
curl -s http://127.0.0.1:8000/api/v1/operational_alert_classifications \
  -H "authorization: Bearer $CONTEXTUAL_ORCHESTRATOR_ADMIN_TOKEN" \
  -H "content-type: application/json" \
  -d @alert.json | jq .
```

The endpoint is admin-scoped because alert payloads can contain operational
metadata. The response does not echo the raw alert body; it exposes only matched
signal names, the routing decision, a reason code, and operator actions.

## Wiring

1. Send the monitoring webhook payload to
   `/api/v1/operational_alert_classifications`.
2. If `incident_routing == "drop"` and `page_required == false`, do not create
   an outage/page. Record the classifier response as an audit event.
3. Keep separate inference health, latency, 5xx, and customer-SLO alerts active.
4. Trend the suppressed count. If it rises, review LiteLLM/PgCat/PostgreSQL pool
   budget and spend-log backlog during maintenance.

Project coordination follows ContextualWisdomLab/.github#363: read Project #1
first, keep the active work item visible, and link the PR or issue back to the
Project item.
