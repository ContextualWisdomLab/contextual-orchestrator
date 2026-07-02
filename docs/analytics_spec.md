# Analytics Spec

## Measurement Context

This repository does not include production telemetry, event logs, or a
warehouse. The metrics below are therefore proposed definitions and source
requirements, not measured product results. The first implementation should
instrument compact events from the stdlib server and admin console before any
dashboard claims real usage.

In short: this spec provides proposed definitions and source requirements, not measured product results.

The stdlib prototype now exposes `/api/v1/analytics_snapshots/latest` as a
local runtime snapshot. It measures only in-memory events and workflow records
from the current process, so it is source-backed for smoke tests and pilot
readiness checks, but it is still not production telemetry or a warehouse-backed
dashboard.

The prototype also exposes `/api/v1/sales_readiness/latest`. That endpoint
turns the local snapshot, admin state, HTTP security profile, locale bundles,
and provider configuration into explicit pass/warn/fail criteria for enterprise
pilot review. It is a readiness gate for a sellable pilot, not a production
compliance certificate or proof of real customer usage.

The prototype also exposes `/api/v1/commercial_readiness/latest`. That endpoint
rolls product, security, operations, audit, documentation, support,
localization, and value-case evidence into a KRW 2,000,000,000 buyer
due-diligence gate. It is measured only as local due-diligence evidence and is
not a valuation guarantee, purchase commitment, or production compliance
certificate.

Decision supported: decide whether Contextual Orchestrator is ready to move from
lab prototype to enterprise pilot while preserving traceability, compliance
evidence, and API compatibility.

Review cadence: weekly during pilot, then monthly for operating review.

Primary owners:

- Product owner: adoption and replay metrics.
- Platform operator: health, latency, mode mix, and capacity metrics.
- Compliance reviewer: access exposure, provider exclusion, and audit exception
  metrics.
- Localization owner: locale coverage and translation review metrics.

## Recommended KPIs

| KPI | Definition | Decision use | Source expectation |
|---|---|---|---|
| Compatible API adoption | Count of successful `/v1/chat/completions` requests by application or token scope over a completed review window. | Shows whether the single API wedge is being used without client rewrites. | HTTP request logs with endpoint, status, auth scope, and timestamp. |
| Trace-complete workflow rate | Share of conducted workflow runs that include role, worker, subtask, access list, verifier result, and final synthesis fields. | Verifies that enterprise evidence is present when deep orchestration is used. | `workflow_runs` records plus trace schema validation. |
| Policy-safe routing rate | Share of runs where selected mode, provider exclusions, and verifier requirement match the active orchestration policy. | Detects routing or policy regressions before rollout. | Policy snapshot joined to each run decision. |

The local runtime snapshot reports these KPIs as `compatible_api_adoption`,
`trace_complete_workflow_rate`, and `policy_safe_routing_rate`.

## Commercial Due-Diligence KPIs

These metrics support the KRW 2,000,000,000 commercial-readiness review. The
`evidence_type` column is mandatory so measured local evidence is never mixed
with proposed production targets.

| KPI | Definition | Evidence type | Source expectation |
|---|---|---|---|
| `commercial_readiness_pass_rate` | Share of `commercial_readiness_report()` criteria with `status=pass`. | measured_local | `/api/v1/commercial_readiness/latest` response. |
| `buyer_evidence_completeness` | Share of required buyer due-diligence documents present in the repository. | measured_local | commercial readiness documentation profile. |
| `security_control_pass_rate` | Share of security posture checks passing across auth, bind, trace, rate limit, concurrency, and provider egress controls. | measured_local | `SecurityConfig.readiness_profile()` plus provider configuration. |
| `security_attestation_gap_count` | Count of hosted scan, third-party attestation, and buyer privacy/DPA inputs still required for buyer security review. | proposed_until_buyer_specific | `/api/v1/commercial_security_attestations/latest` response. |
| `trace_audit_completeness` | Share of conducted runs with role, agent, subtask, access list, verifier, and synthesis evidence. | measured_local | workflow run trace records. |
| `support_operability_score` | Availability of SLO, support ownership, incident runbook, backup, and escalation evidence. | proposed_until_production | production operations documents and ticketing records. |
| `roi_evidence_status` | Buyer-specific value case tying API compatibility, audit evidence, replay, and operating cost reduction to the KRW 2,000,000,000 target. | proposed_until_buyer_specific | customer discovery, procurement, and ROI model. |

Current GitHub/CI maturity evidence is a measured local or repository signal:
CodeQL, Dependency review, Python supply chain, Trivy, coverage-evidence,
scan-pr-queue, and Strix passing are readiness evidence. OpenCode or reviewer
delay is review latency, not product failure, unless it reports a concrete
security, contract, or functional defect.

## Drivers

| Driver | Definition | Related KPI |
|---|---|---|
| Admin evidence engagement | Count of `/admin/state`, workflow run detail, access report, and evaluation replay views by operator session. | Trace-complete workflow rate |
| Route-versus-conduct mix | Share of runs handled by fast route versus deep conduct mode, segmented by prompt category. | Compatible API adoption, policy-safe routing rate |
| Evaluation replay usage | Count of replay runs created before a policy change or provider exclusion change. | Policy-safe routing rate |
| Agent health coverage | Share of configured agents reporting status, capacity, tags, provider, and exclusion metadata. | Policy-safe routing rate |

## Guardrails

| Guardrail | Definition | Why it matters |
|---|---|---|
| P95 latency by mode | P95 response time split by route and conduct. | Deep orchestration should not silently degrade interactive surfaces. |
| Verifier revision rate | Share of conducted runs where verifier requires revision before synthesis. | High rates may indicate weak worker selection or brittle prompts. |
| Access exposure count | Number of prior outputs visible to each step, with max and distribution by run. | Prevents context visibility from drifting beyond Conductor-style access lists. |
| Provider exclusion miss rate | Count of runs using an excluded provider or model. | Must stay at zero for enterprise compliance trust. |
| Locale key parity | Share of English translation keys present in Korean with non-empty values. | Prevents i18n from becoming a cosmetic afterthought. |

## Event Model

Minimum event or record names use lower snake_case with at least two words:

- `chat_completion_requested`
- `workflow_run_created`
- `workflow_step_completed`
- `access_report_viewed`
- `evaluation_run_created`
- `agent_status_changed`
- `provider_exclusion_changed`
- `locale_bundle_loaded`

The stdlib server records these events in memory only. The event stream is
intended to prove schema shape and guardrail logic before a production log sink
exists.

Recommended shared fields:

- `event_time`
- `request_id`
- `actor_scope`
- `endpoint_path`
- `run_mode`
- `workflow_run_id`
- `policy_version`
- `agent_id`
- `provider_name`
- `locale_code`
- `status_code`
- `duration_ms`

Do not log prompt text, API keys, provider secrets, or raw model outputs in the
analytics stream. Store redacted IDs and schema validation results instead.

## Dashboard Shape

The first dashboard should be source-backed only after events exist. Until then,
the Figma dashboard should be labeled as a measurement design.

Default sections:

1. Pilot readiness: API adoption, trace completeness, policy-safe routing.
2. Runtime health: latency by mode, route-versus-conduct mix, agent health.
3. Compliance evidence: access exposure, provider exclusion miss rate, audit
   exceptions.
4. Evaluation loop: replay usage, verifier revision rate, policy change
   coverage.
5. Locale readiness: English/Korean key parity and missing-key list.
6. Sales readiness: criteria status, evidence, and remediation for API
   compatibility, admin evidence, trace evidence, replay, security posture,
   analytics truthfulness, locale readiness, and provider egress safety.
7. Commercial readiness: KRW 2,000,000,000 due-diligence gate, buyer evidence
   completeness, support gaps, and value-case caveats.

## Data Quality Checks

- Reconcile request counts between HTTP logs and workflow run records.
- Confirm every conducted run has exactly one policy snapshot.
- Confirm access-list records reference existing workflow steps.
- Confirm provider exclusion changes have actor scope, timestamp, and before
  and after values.
- Confirm locale key parity uses English as the fallback source.

## Targets

Initial pilot targets should be provisional because no production baseline
exists:

- Trace-complete workflow rate: 100 percent for conducted runs.
- Provider exclusion miss rate: 0.
- Locale key parity: 100 percent for English and Korean admin keys.
- Evaluation replay usage: at least one replay run before any policy threshold
  change in pilot.
- P95 latency by mode: set after the first real pilot week, not from mock runs.
