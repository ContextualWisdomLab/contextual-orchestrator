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
| `GET` | `/api/v1/analytics_snapshots/latest` | Read local runtime KPI and guardrail snapshot |
| `GET` | `/api/v1/sales_readiness/latest` | Read local enterprise-pilot readiness criteria and evidence |
| `GET` | `/api/v1/commercial_readiness/latest` | Read KRW 2,000,000,000 commercial due-diligence readiness criteria and evidence |
| `GET` | `/api/v1/buyer_evidence_manifests/latest` | Read buyer evidence manifest for commercial diligence review |
| `GET` | `/api/v1/buyer_handoff_bundles/latest` | Read buyer handoff bundle for commercial diligence review |
| `GET` | `/api/v1/saleability_decisions/latest` | Read KRW 2,000,000,000 saleability decision for commercial diligence review |
| `GET` | `/api/v1/commercial_evidence_exports/latest` | Read portable commercial evidence export for buyer due diligence |
| `GET` | `/api/v1/commercial_acceptance_checks/latest` | Read commercial acceptance check for buyer due diligence |
| `GET` | `/api/v1/commercial_release_candidates/latest` | Read commercial release-candidate package for buyer due diligence |
| `GET` | `/api/v1/commercial_gap_registers/latest` | Read commercial gap register for buyer due diligence |
| `GET` | `/api/v1/commercial_procurement_readiness/latest` | Read commercial procurement readiness for buyer due diligence |
| `GET` | `/api/v1/commercial_contract_readiness/latest` | Read commercial contract readiness for buyer due diligence |
| `GET` | `/api/v1/commercial_onboarding_readiness/latest` | Read commercial onboarding readiness for buyer close |
| `GET` | `/api/v1/commercial_operations_readiness/latest` | Read commercial operations readiness for buyer handoff |
| `GET` | `/api/v1/commercial_security_attestations/latest` | Read commercial security attestation for buyer security review |
| `GET` | `/api/v1/commercial_value_readiness/latest` | Read commercial value readiness for buyer economic review |
| `POST` | `/api/v1/workflow_runs` | Create a route/conduct run |
| `GET` | `/api/v1/workflow_runs` | List recent workflow runs |
| `GET` | `/api/v1/workflow_runs?page_number=1&page_size=20` | Paginate workflow run history with deterministic page metadata |
| `GET` | `/api/v1/workflow_runs/{workflow_run_id}` | Inspect one run and trace |
| `GET` | `/api/v1/access_reports/{workflow_run_id}` | Inspect access-list evidence |
| `PATCH` | `/api/v1/agent_pools/{agent_pool_id}/worker_agents/{worker_agent_id}` | Update status/priority/tags/provider exclusions |
| `POST` | `/api/v1/evaluation_runs` | Replay prompts and return a reproducible evaluation run |
| `GET` | `/api/v1/evaluation_runs/{evaluation_run_id}` | Review replay output |
| `GET` | `/api/v1/locale_bundles/{locale_code}` | Read i18n bundle |
| `GET` | `/admin` | Management console |

## Product Planning Additions (Implemented)

These product surfaces are now implemented in this prototype:

| Method | Path | Purpose | Paper Basis |
|---|---|---|---|
| `GET` | `/api/v1/workflow_runs/{workflow_run_id}` | Inspect one run with role, worker, subtask, access list, verifier result, and synthesis evidence. | TRINITY roles; Conductor workflow steps and access lists. |
| `POST` | `/api/v1/evaluation_runs` | Replay a prompt or dataset against policy variants before changing production routing. | Fugu and TRINITY optimize coordination against measured outcomes. |
| `GET` | `/api/v1/access_reports/{workflow_run_id}` | Produce compliance evidence for which worker saw which prior outputs. | Conductor access-list visibility control. |
| `PATCH` | `/api/v1/agent_pools/{agent_pool_id}/worker_agents/{worker_agent_id}` | Update status, priority, capability tags, or provider exclusion. | Fugu configurable worker pool and provider/compliance constraints. |
| `GET` | `/api/v1/analytics_snapshots/latest` | Produce source-backed local KPI and guardrail evidence without claiming production telemetry. | Fugu evaluation discipline; TRINITY verification evidence; Conductor access-list guardrails. |
| `GET` | `/api/v1/sales_readiness/latest` | Produce a sellable-pilot readiness gate from current runtime, admin, security, analytics, locale, and provider evidence. | Fugu API adoption; TRINITY verification; Conductor trace and access-list evidence. |
| `GET` | `/api/v1/commercial_readiness/latest` | Produce a high-value buyer due-diligence readiness gate for the KRW 2,000,000,000 target without presenting it as a valuation guarantee. | Fugu API adoption; TRINITY verification; Conductor trace/access evidence; enterprise procurement review. |
| `GET` | `/api/v1/buyer_evidence_manifests/latest` | Produce a buyer-facing evidence index across runtime reports, repository artifacts, Figma artifacts, verification commands, and caveats. | Fugu API adoption; TRINITY verification; Conductor trace/access evidence; procurement evidence review. |
| `GET` | `/api/v1/buyer_handoff_bundles/latest` | Produce the buyer handoff bundle that packages runtime reports, repository packet, Figma artifacts, verification commands, packaging decision, and explicit follow-ups. | Fugu API adoption; TRINITY verification; Conductor trace/access evidence; procurement handoff review. |
| `GET` | `/api/v1/saleability_decisions/latest` | Produce the final saleability decision gate that separates concrete blockers from warning follow-ups and review-process non-blockers. | Fugu API adoption; TRINITY verification; Conductor trace/access evidence; buyer diligence decision. |
| `GET` | `/api/v1/commercial_evidence_exports/latest` | Produce the portable commercial evidence export that packages the saleability decision, runtime reports, buyer documents, Figma artifacts, verification commands, review-process policy, packaging decision, and required external evidence gaps. | Fugu API adoption; TRINITY verification; Conductor trace/access evidence; buyer diligence export. |
| `GET` | `/api/v1/commercial_acceptance_checks/latest` | Produce the buyer acceptance check that turns the commercial evidence export into ready, warning, or blocked acceptance status. | Fugu API adoption; TRINITY verification; Conductor trace/access evidence; buyer acceptance review. |
| `GET` | `/api/v1/commercial_release_candidates/latest` | Produce the commercial release-candidate manifest that packages acceptance status, runtime endpoints, repository distribution packet, security metadata, admin visibility, verification, Figma artifacts, review-process policy, packaging decision, and external release gaps. | Fugu API adoption; TRINITY verification; Conductor trace/access evidence; buyer release-candidate review. |
| `GET` | `/api/v1/commercial_gap_registers/latest` | Produce the commercial gap register that converts release-candidate external gaps into owner, source, required-input, and status rows for buyer due diligence. | Fugu API adoption; TRINITY verification; Conductor trace/access evidence; buyer gap closure review. |
| `GET` | `/api/v1/commercial_procurement_readiness/latest` | Produce the procurement readiness gate that packages license, rights, security metadata, distribution docs, admin evidence, support/SLO input, buyer legal/ROI/procurement input, review-process policy, and packaging decision. | Fugu API adoption; TRINITY verification; Conductor trace/access evidence; procurement and legal review. |
| `GET` | `/api/v1/commercial_contract_readiness/latest` | Produce the contract readiness gate that packages support/SLO terms, security/privacy terms, audit/export obligations, license/commercial rights, buyer order-form input, review-process policy, and packaging decision. | Fugu API adoption; TRINITY verification; Conductor trace/access evidence; legal and procurement contract review. |
| `GET` | `/api/v1/commercial_onboarding_readiness/latest` | Produce the onboarding readiness gate that converts production support/SLO and buyer-specific input warnings into paid-onboarding owners, actions, and exit criteria. | Fugu API adoption; TRINITY verification; Conductor trace/access evidence; buyer close and onboarding review. |
| `GET` | `/api/v1/commercial_operations_readiness/latest` | Produce the operations readiness gate that converts production telemetry, incident/rollback, backup/recovery, and SLO evidence gaps into operations handoff owners, actions, and exit criteria. | Fugu API adoption; TRINITY verification; Conductor trace/access evidence; buyer operations handoff review. |
| `GET` | `/api/v1/commercial_security_attestations/latest` | Produce the security attestation gate that separates repo-local security evidence from external attestation, hosted scan, and buyer privacy/DPA gaps. | Fugu API adoption; TRINITY verification; Conductor trace/access evidence; buyer security review. |
| `GET` | `/api/v1/commercial_value_readiness/latest` | Produce the value readiness gate that separates repo-local measured value evidence from buyer-specific ROI, reference proof, budget-owner, and payback-input gaps. | Fugu API adoption; TRINITY verification; Conductor trace/access evidence; buyer economic review. |

## Production Library Target

FastAPI should replace the current stdlib HTTP adapter when the API needs authentication, richer OpenAPI schema generation, dependency injection, and typed request/response models.
