# Commercial readiness endpoints and saleability gates

Moved off the product README. These are local buyer-review evidence snapshots,
not a valuation guarantee, purchase commitment, or production compliance
certificate. Narrative standards live in the matching `docs/commercial_*.md`
files.

The KRW 2,000,000,000 figure is a diligence target used by the readiness
reports. It is not a sale, valuation, or revenue claim.

## Operator evidence (non-commercial)

| Surface | Purpose |
| --- | --- |
| `GET /api/v1/spend_analytics/latest` | Per-model token and cost spend from workflow runs. Output tokens use provider-reported `usage` when available and fall back to a ~4 chars/token estimate otherwise (`usage_source: reported \| mixed \| estimated`). Cost is computed only for models with an operator-supplied price; otherwise `null` and the model is listed under `unpriced_models`. |
| `GET /api/v1/sales_readiness/latest` | Local enterprise-pilot readiness gate for API compatibility, operator evidence, workflow traces, evaluation replay, security posture, analytics truthfulness, locale parity, and provider egress safety. Process-local evidence, not a production compliance certificate. |

## Commercial diligence catalog

| Surface | Purpose |
| --- | --- |
| `GET /api/v1/commercial_readiness/latest` | KRW 2,000,000,000 commercial due-diligence readiness gate. Buyer-review evidence snapshot, not a valuation guarantee. |
| `GET /api/v1/buyer_evidence_manifests/latest` | Buyer evidence manifest: runtime review index across endpoints, repository artifacts, Figma artifacts, verification evidence, and production or buyer-specific caveats. |
| `GET /api/v1/buyer_handoff_bundles/latest` | Buyer handoff bundle across runtime reports, repository packet, Figma artifacts, verification commands, packaging decision, and explicit follow-ups. |
| `GET /api/v1/saleability_decisions/latest` | Final KRW 2,000,000,000 saleability decision gate with concrete blockers, warning conditions, and review-process non-blocker policy. |
| `GET /api/v1/commercial_evidence_exports/latest` | Portable commercial evidence export across saleability, runtime reports, buyer documents, Figma artifacts, verification commands, review-process policy, packaging decision, and external evidence gaps. |
| `GET /api/v1/commercial_acceptance_checks/latest` | Buyer acceptance check across evidence export, runtime endpoint chain, buyer packet, admin surface, verification, Figma, review-process policy, packaging decision, and external evidence gaps. |
| `GET /api/v1/commercial_buyer_acceptance_workflows/latest` | Buyer acceptance workflow across owner-scoped runbook steps, Go/Warning/No-Go rules, runtime evidence, Figma artifacts, analytics truthfulness, review-process policy, and packaging decision. |
| `GET /api/v1/commercial_release_candidates/latest` | Local commercial release-candidate manifest across acceptance, runtime endpoints, repository distribution packet, security metadata, admin surface, verification, Figma, review-process policy, packaging decision, and external release gaps. |
| `GET /api/v1/commercial_gap_registers/latest` | Commercial gap register that turns release-candidate external gaps into owner, source, required-input, and status rows. |
| `GET /api/v1/commercial_procurement_readiness/latest` | Procurement readiness across license, rights, security metadata, distribution packet, admin evidence, production support/SLO input, buyer legal/ROI/procurement input, review-process policy, and packaging decision. |
| `GET /api/v1/commercial_contract_readiness/latest` | Contract readiness across support/SLO terms, security/privacy terms, audit/export obligations, license/commercial rights, buyer order-form inputs, review-process policy, and packaging decision. |
| `GET /api/v1/commercial_onboarding_readiness/latest` | Onboarding readiness that turns production support/SLO and buyer-specific input warnings into paid-onboarding owners, actions, and exit criteria. |
| `GET /api/v1/commercial_operations_readiness/latest` | Operations readiness that turns production telemetry, incident/rollback, backup/recovery, and SLO evidence gaps into operations handoff owners, actions, and exit criteria. |
| `GET /api/v1/commercial_security_attestations/latest` | Security attestation gate that separates repo-local security evidence from external attestation, hosted scan, and buyer privacy/DPA gaps. |
| `GET /api/v1/commercial_value_readiness/latest` | Value readiness that separates repo-local measured value evidence from buyer-specific ROI, reference proof, budget-owner, and payback-input gaps. |
| `GET /api/v1/commercial_close_readiness/latest` | Close readiness that separates repo-local sellable product evidence from buyer signatures, DPA/security acceptance, budget/PO, and go-live authorization gaps. |
| `GET /api/v1/commercial_go_to_market_readiness/latest` | Go-to-market readiness index tying close, value, security, evidence export, buyer handoff, saleability, admin evidence, analytics truthfulness, Figma artifacts, review-process policy, and packaging decision. |
| `GET /api/v1/commercial_launch_readiness/latest` | Launch readiness gate packaging GTM, runtime, acceptance, operator, admin, analytics, Figma, review-process, and packaging evidence while keeping buyer environment, production telemetry, and signature inputs as explicit warnings. |
| `GET /api/v1/commercial_completion_scorecards/latest` | Runtime commercial completion scorecard for the KRW 2,000,000,000 program-completion standard across Product Design, Figma, Superpowers, Ponytail, Data Analytics, runtime, verification, review-policy, packaging, and external follow-up evidence. |
| `GET /api/v1/commercial_demo_scenarios/latest` | KRW 2,000,000,000 commercial demo scenarios packet across compatible API smoke, workflow trace, access-list evidence, evaluation replay, admin readiness, metric truthfulness, Figma review, buyer acceptance, review-process policy, and packaging decision. |
| `GET /api/v1/commercial_proposal_packets/latest` | KRW 2,000,000,000 commercial proposal packet across completion, demo, acceptance, value, security, contract, onboarding, operations, analytics truthfulness, Figma review, review-process policy, packaging decision, and buyer-specific follow-ups. |
| `GET /api/v1/commercial_purchase_approval_packets/latest` | KRW 2,000,000,000 commercial purchase approval packet across proposal, close, procurement, contract, value, security, onboarding, operations, analytics truthfulness, Figma review, review-process policy, packaging decision, and buyer signature/budget authority follow-ups. |
| `GET /api/v1/commercial_due_diligence_rooms/latest` | KRW 2,000,000,000 commercial due diligence room across purchase approval, runtime API evidence, admin trace/access evidence, security, commercial terms, value analytics, implementation readiness, Figma review, review-process policy, packaging decision, and buyer/external missing artifacts. |
| `GET /api/v1/commercial_investment_committee_memos/latest` | KRW 2,000,000,000 commercial investment committee memo across due diligence, purchase approval, financial case, risk/security, commercial terms, implementation readiness, Figma review, review-process policy, packaging decision, and buyer/external approval conditions. |

Matching Markdown standards: [commercial_readiness.md](../commercial_readiness.md),
[commercial_saleability_decision.md](../commercial_saleability_decision.md),
[commercial_buyer_evidence_manifest.md](../commercial_buyer_evidence_manifest.md),
[commercial_buyer_handoff_bundle.md](../commercial_buyer_handoff_bundle.md),
and the other `docs/commercial_*.md` files.
