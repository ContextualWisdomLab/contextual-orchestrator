# Commercial Go-To-Market Readiness

Runtime endpoint: `/api/v1/commercial_go_to_market_readiness/latest`.

This document defines the buyer and stakeholder go-to-market readiness index for
a KRW 2,000,000,000 commercial packet. It indexes repo-local sellable product,
evidence, admin, analytics, and stakeholder artifacts separately from buyer
signatures, external proof, and production telemetry. It is not a valuation
guarantee, purchase commitment, signed order, legal opinion, production
compliance certificate, or revenue proof.

Figma Code Connect is not used.

Review process is not a blocker. Reviewer delay, review bot delay, queued model
review, and pending checks without a concrete failure are not blockers. Blockers
are concrete security failures, API contract failures, document contract
mismatches, reproducible product defects, or Code Connect usage.

Do not create a separate library, Git submodule, or extracted package now. Keep
Contextual Orchestrator as one enterprise control-plane product until a second
product, independent release cadence, or buyer security provenance requirement
creates an extraction trigger.

## Go-To-Market Inputs

| Input | Source | Purpose |
| --- | --- | --- |
| Commercial close readiness | `/api/v1/commercial_close_readiness/latest` | Final close packet and buyer signature gaps. |
| Commercial value readiness | `/api/v1/commercial_value_readiness/latest` | Economic value evidence and buyer financial/proof gaps. |
| Commercial security attestation | `/api/v1/commercial_security_attestations/latest` | Security trust packet and external attestation gaps. |
| Commercial evidence export | `/api/v1/commercial_evidence_exports/latest` | Portable buyer data-room evidence index. |
| Buyer handoff bundle | `/api/v1/buyer_handoff_bundles/latest` | Buyer-facing artifact bundle and follow-up context. |
| Saleability decision | `/api/v1/saleability_decisions/latest` | Go/no-go status for buyer diligence. |
| Analytics snapshot | `/api/v1/analytics_snapshots/latest`, `docs/analytics_spec.md` | Separates measured local evidence from proposed or buyer-specific metrics. |
| Admin evidence surface | `/admin`, `docs/screen_design.md` | Operator-visible status, measurement, and warning/blocker summary. |
| Figma stakeholder artifacts | `docs/figma_artifacts.md` | Editable design, FigJam, and stakeholder flow evidence without Code Connect. |

## Runtime Shape

`/api/v1/commercial_go_to_market_readiness/latest` returns:

- `go_to_market_status`: `commercial_go_to_market_ready`,
  `commercial_go_to_market_ready_with_warnings`, or
  `commercial_go_to_market_blocked`;
- `measurement_status`: `local_commercial_go_to_market_readiness`;
- `go_to_market_summary`: ready, warning, blocked, buyer-signature gap,
  external-or-production gap, and review-process blocker counts;
- `go_to_market_items`: close packet, economic value packet, security trust
  packet, buyer evidence packet, saleability decision packet, admin operator
  evidence, analytics truthfulness packet, stakeholder artifacts packet, buyer
  signature/budget follow-up, production/external proof follow-up,
  review-process policy, and packaging decision;
- `concrete_blockers`: only concrete product, security, API contract, document,
  or Code Connect failures;
- `go_to_market_status_rules`: stable ready/warning/blocked rules;
- `related_runtime_reports`: close, value, security attestation, evidence
  export, buyer handoff, saleability, and lower-level readiness context;
- `library_split_decision`: current single-product packaging decision;
- `plugin_traceability`: Figma, Product Design, Superpowers, Ponytail, and Data
  Analytics responsibilities;
- `go_to_market_links`: editable Figma/FigJam links, endpoint, and
  documentation.

## Go-To-Market Status Rules

| Status | Rule |
| --- | --- |
| `commercial_go_to_market_ready` | Close, value, security, evidence, saleability, admin, analytics, stakeholder artifacts, buyer inputs, external proof, review policy, and packaging evidence are ready. |
| `commercial_go_to_market_ready_with_warnings` | Repo-local GTM packet is ready while buyer signatures, budget/PO, DPA/security acceptance, production telemetry, reference proof, hosted scan, or third-party attestation remain explicit warnings. |
| `commercial_go_to_market_blocked` | Missing local GTM packet evidence, concrete product defect, API contract failure, security failure, document mismatch, or Code Connect usage blocks GTM readiness. |

## KRW 2B Commercial Go To Market Readiness

The repository can package a go-to-market packet without pretending that buyer
or production evidence already exists:

- commercial close packet exposes the final repo-local readiness gate;
- economic value packet keeps value claims tied to measured local analytics and
  buyer-specific value gaps;
- security trust packet separates local security evidence from hosted scan,
  third-party attestation, and buyer privacy/DPA inputs;
- buyer evidence packet keeps the data-room index and handoff bundle portable;
- saleability decision packet distinguishes warnings from concrete blockers;
- admin operator evidence keeps status visible in the existing control-plane
  surface instead of creating a separate dashboard;
- analytics truthfulness packet prevents unmeasured production or revenue claims;
- stakeholder artifacts packet records editable Figma and FigJam outputs;
- buyer signature and budget follow-up remains a warning until signed order,
  MSA, DPA/security acceptance, budget/PO, and go-live authorization are
  accepted or waived;
- production and external proof follow-up remains a warning until hosted scans,
  third-party attestation, reference proof, and production telemetry are
  attached or waived;
- review-process delay remains non-blocking until a concrete failure appears;
- single-product packaging remains the default until a real extraction trigger
  exists.

## Plugin Traceability

| Plugin | GTM-readiness responsibility |
| --- | --- |
| Product Design | Keep GTM readiness visible in the existing admin observability surface. |
| Figma | Record the editable FigJam flow named `KRW 2B Commercial Go To Market Readiness`. |
| Data Analytics | Separate local measured GTM evidence from buyer-specific and production proof inputs. |
| Superpowers | Maintain the implementation plan, acceptance checks, and concrete blocker rules. |
| Ponytail | Keep one deployable product and avoid package extraction before a trigger. |

## Verification

```bash
python tests/test_commercial_go_to_market_readiness.py
python tests/test_commercial_close_readiness.py
python tests/test_api_contract.py
python tests/test_plugin_driven_artifacts.py
pytest -q
```
