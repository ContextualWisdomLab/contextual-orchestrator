# Commercial Close Readiness

Runtime endpoint: `/api/v1/commercial_close_readiness/latest`.

This document defines the final buyer-close readiness gate for a
KRW 2,000,000,000 buyer packet. It separates repo-local sellable product
evidence from buyer signature, legal, procurement, DPA/security acceptance,
budget/PO, and go-live authorization inputs. It is not a valuation guarantee,
purchase commitment, signed order, legal opinion, or production compliance
certificate.

Figma Code Connect is not used.

Review process is not a blocker. Reviewer delay, review bot delay, queued model
review, and pending checks without a concrete failure are not blockers. Blockers
are concrete security failures, API contract failures, document contract
mismatches, reproducible product defects, or Code Connect usage.

Do not create a separate library, Git submodule, or extracted package now. Keep
Contextual Orchestrator as one enterprise control-plane product until a second
product, independent release cadence, or buyer security provenance requirement
creates an extraction trigger.

## Close Readiness Inputs

| Input | Source | Purpose |
| --- | --- | --- |
| Commercial value readiness | `/api/v1/commercial_value_readiness/latest` | Repo-local value evidence and buyer economic-review gaps. |
| Commercial security attestation | `/api/v1/commercial_security_attestations/latest` | Repo-local security evidence and external attestation gaps. |
| Commercial contract readiness | `/api/v1/commercial_contract_readiness/latest` | Legal, privacy, audit/export, license, and buyer order-form context. |
| Commercial onboarding readiness | `/api/v1/commercial_onboarding_readiness/latest` | Paid-onboarding owners, actions, and buyer input context. |
| Commercial operations readiness | `/api/v1/commercial_operations_readiness/latest` | Operations handoff, support, telemetry, incident, backup, and acceptance context. |
| Commercial evidence export | `/api/v1/commercial_evidence_exports/latest` | Portable buyer data-room evidence index. |

## Runtime Shape

`/api/v1/commercial_close_readiness/latest` returns:

- `close_status`: `commercial_close_ready`,
  `commercial_close_ready_with_warnings`, or `commercial_close_blocked`;
- `measurement_status`: `local_commercial_close_readiness`;
- `close_summary`: ready, warning, blocked, buyer-signature gap, and
  review-process blocker counts;
- `close_items`: sellable product packet, contract close packet,
  onboarding/operations packet, buyer evidence export packet, signed order
  form/MSA, DPA/security acceptance, budget approval/PO, go-live authorization,
  review-process policy, and packaging decision;
- `concrete_blockers`: only concrete product, security, API contract, document,
  or Code Connect failures;
- `close_status_rules`: stable ready/warning/blocked rules;
- `related_runtime_reports`: value, security attestation, contract,
  onboarding, operations, evidence export, and lower-level readiness context;
- `library_split_decision`: current single-product packaging decision;
- `plugin_traceability`: Figma, Product Design, Superpowers, Ponytail, and Data
  Analytics responsibilities;
- `close_links`: editable Figma/FigJam links, endpoint, and documentation.

## Close Status Rules

| Status | Rule |
| --- | --- |
| `commercial_close_ready` | Sellable product packet, contract packet, onboarding/operations packet, evidence export, signatures, DPA/security acceptance, budget/PO, go-live authorization, review policy, and packaging evidence are ready. |
| `commercial_close_ready_with_warnings` | Repo-local close packet is ready while buyer signatures, DPA/security acceptance, budget/PO, or go-live authorization remain explicit warnings. |
| `commercial_close_blocked` | Missing local close evidence, concrete product defect, API contract failure, security failure, document mismatch, or Code Connect usage blocks close readiness. |

## KRW 2B Commercial Close Readiness

The repository can package a buyer close packet without pretending the buyer has
already signed or approved every external input:

- sellable product packet ties value, security attestation, and evidence export
  to runtime endpoints and repository artifacts;
- contract close packet treats local legal/procurement evidence as ready while
  final buyer signatures remain separate warnings;
- onboarding and operations packet keeps implementation, support, telemetry,
  incident, backup, acceptance, and security/legal handoff visible;
- buyer evidence export packet acts as the portable data-room index;
- signed order form or MSA remains a buyer-signature warning until accepted;
- DPA and security acceptance remain buyer-signature warnings until signed or
  waived by buyer legal/security;
- budget approval and purchase order remain buyer-signature warnings until
  buyer procurement confirms payment authority;
- go-live authorization remains a buyer-signature warning until production
  activation or paid onboarding is approved;
- review-process delay remains non-blocking until a concrete failure appears;
- single-product packaging remains the default until a real extraction trigger
  exists.

## Plugin Traceability

| Plugin | Close-readiness responsibility |
| --- | --- |
| Product Design | Keep close readiness visible in the existing admin observability surface. |
| Figma | Record the editable FigJam flow named `KRW 2B Commercial Close Readiness`. |
| Data Analytics | Separate local measured close evidence from buyer-specific signature and procurement inputs. |
| Superpowers | Maintain the implementation plan, acceptance checks, and concrete blocker rules. |
| Ponytail | Keep one deployable product and avoid package extraction before a trigger. |

## Verification

```bash
python tests/test_commercial_close_readiness.py
python tests/test_commercial_value_readiness.py
python tests/test_api_contract.py
python tests/test_plugin_driven_artifacts.py
pytest -q
```
