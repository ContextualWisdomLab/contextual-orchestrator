# Commercial Readiness Standard

This document defines the Contextual Orchestrator acceptance bar for a KRW
2,000,000,000 enterprise sale review. It is an evidence standard for buyer
due diligence, not a valuation guarantee, purchase commitment, or production
compliance certificate.

## Acceptance Criteria

| Area | Acceptance bar | Evidence source |
| --- | --- | --- |
| Product capability evidence | The program exposes one OpenAI-compatible API plus an operator control plane with agent pool, policy, trace, access-list, evaluation replay, and locale evidence. | `/v1/chat/completions`, `/admin`, `/admin/state`, `/api/v1/sales_readiness/latest` |
| Security and access control | Admin and inference scopes are split, public bind is opt-in, traces are hidden by default, rate limits and concurrency limits are active, and remote provider egress uses HTTPS with explicit key env vars. | `SecurityConfig.readiness_profile()`, `sales_readiness_report()` |
| Operational resilience | The runtime reports policy-safe routing, request rate limits, run concurrency limits, and remediation for missing production SLOs. | `/api/v1/analytics_snapshots/latest`, `/api/v1/commercial_readiness/latest` |
| Audit and compliance evidence | Workflow traces include role, agent, access list, output, verification, provider exclusion, and replay evidence. | workflow run records, access reports, analytics guardrails |
| Buyer due-diligence packet | Product, API, security, analytics, and commercial readiness documents are present and linked to runtime evidence. | `README.md`, `SECURITY.md`, `docs/product_planning.md`, `docs/rest_api_design.md`, `docs/analytics_spec.md`, this document |
| Support and localization | English and Korean admin locale bundles remain aligned, and security/support ownership is documented for customer operations. | admin locale bundles, `SECURITY.md` |
| Commercial value case | The product can explain a KRW 2,000,000,000 target contract value through API compatibility, evidence control plane, replay, and audit controls. | `commercial_readiness_report(target_contract_value_krw=2000000000)` |

## Buyer due-diligence evidence map

| Buyer question | Product answer | Runtime or document proof |
| --- | --- | --- |
| Can this replace a direct model call without a migration project? | Yes, the compatibility API accepts OpenAI-style chat completions. | `/v1/chat/completions`, API contract tests |
| Can operators see what the orchestrator did? | Yes, the admin console exposes agent pool, policy, workflow trace, access lists, evaluation replay, analytics, and readiness evidence. | `/admin`, `/admin/state`, `/api/v1/workflow_runs` |
| Can compliance reviewers inspect data exposure? | Yes, conducted traces record step access lists and access reports expose which worker saw which prior outputs. | `/api/v1/access_reports/{workflow_run_id}` |
| Are metrics measured or merely proposed? | Local runtime metrics are marked as `local_runtime_snapshot`; unmeasured production claims are not made. | `analytics_snapshot()`, `docs/analytics_spec.md` |
| Is the KRW 2,000,000,000 claim guaranteed? | No. It is a diligence readiness target and must be backed by buyer-specific ROI and procurement evidence. | `commercial_readiness_report()` source note |

## Non-Goals

- This standard does not certify SOC 2, ISO 27001, HIPAA, or financial audit
  compliance.
- This standard does not claim production telemetry exists when the runtime only
  has local in-memory evidence.
- This standard does not guarantee a KRW 2,000,000,000 sale, valuation, or buyer
  approval.
- This standard does not split Contextual Orchestrator into separate Fugu,
  TRINITY, or Conductor products.

## External Dependencies

- Buyer-specific legal, security, procurement, and ROI evidence remains external
  to this repository.
- Production deployment evidence, SLOs, backups, incident response drills, and
  customer data-processing agreements must be produced during paid onboarding.
- Reviewer delay is not a blocker. The blocking conditions are security test
  failure, contract/API mismatch, or a reproducible product defect.
- Review process is not a blocker unless it reports a concrete security,
  contract, or product defect.

## Implementation Hook

The runtime endpoint `/api/v1/commercial_readiness/latest` exposes the current
commercial readiness snapshot for the default KRW 2,000,000,000 target. The
report includes `commercial_status`, `commercial_summary`,
`target_contract_value_krw`, `measurement_status`, `source_note`, criteria with
remediation, repository documentation evidence, and the nested
`sales_readiness` report.
