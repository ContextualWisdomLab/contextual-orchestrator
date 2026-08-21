# Commercial Gap Register

Runtime endpoint: `/api/v1/commercial_gap_registers/latest`.

Purpose: convert release-candidate warning gaps into owner, action, source, and
required-input rows for the KRW 2,000,000,000 buyer due-diligence standard. It
is a local commercial evidence register, not a valuation guarantee, purchase
commitment, or production compliance certificate.

## Scope

The gap register supports one product: the OpenAI-compatible inference API plus
the admin evidence control plane. It does not split Fugu, TRINITY, and Conductor
into separate products.

Figma Code Connect is not used for discovery, metadata, code generation, or
artifact creation.

Review process is not a blocker. Reviewer delay, review bot delay, queued model
review, and pending checks without concrete failure remain non-blocking.

Do not create a separate library, Git submodule, or extracted package now. Keep
the repository as one deployable product until a second product, independent
release cadence, or buyer security provenance requirement makes extraction
necessary.

## Gap Inputs

| Input | Source | Use |
|---|---|---|
| Commercial release candidate | `/api/v1/commercial_release_candidates/latest` | Primary source for `external_release_gaps`. |
| Commercial acceptance check | `/api/v1/commercial_acceptance_checks/latest` | Acceptance status and follow-up source. |
| Commercial evidence export | `/api/v1/commercial_evidence_exports/latest` | Portable evidence source. |
| Saleability decision | `/api/v1/saleability_decisions/latest` | Concrete blocker and review-process policy source. |
| Buyer handoff bundle | `/api/v1/buyer_handoff_bundles/latest` | Buyer handoff package source. |
| Buyer evidence manifest | `/api/v1/buyer_evidence_manifests/latest` | Evidence owner and caveat source. |
| Readiness endpoints | `/api/v1/sales_readiness/latest`, `/api/v1/commercial_readiness/latest` | Local readiness source. |
| Analytics snapshot | `/api/v1/analytics_snapshots/latest` | Local KPI and guardrail source. |

## Runtime Shape

`/api/v1/commercial_gap_registers/latest` returns:

- `gap_register_status`: `commercial_gap_register_clear`,
  `commercial_gap_register_open`, or `commercial_gap_register_blocked`;
- `measurement_status`: `local_commercial_gap_register`;
- `gap_summary`: total gap count, production gap count, buyer-specific gap
  count, blocked count, and `review_process_is_blocker=false`;
- `gap_items`: owner/action rows with `gap_name`, `gap_type`, `gap_status`,
  `owner`, `reviewer`, `sources`, `source_evidence_type`, `current_evidence`,
  `required_input`, and `is_blocker`;
- `concrete_blockers`: security, API contract, document, product, or Code
  Connect failures;
- `related_runtime_reports`: release, acceptance, export, saleability, handoff,
  manifest, readiness, and analytics statuses;
- `gap_register_links`: Figma design file, FigJam board, runtime endpoint, and
  this document.

## Gap Status Rules

| Status | Rule |
|---|---|
| `production_input_required` | Production deployment, support, SLO, or operational evidence must be supplied before production claims. |
| `buyer_input_required` | Buyer-specific legal, procurement, ROI, deployment, or data-processing context must be supplied before buyer-specific claims. |
| `blocked` | A concrete security, API contract, document, product, or Code Connect failure blocks commercial release. |

## KRW 2B Commercial Gap Register

The register is acceptable for buyer review when:

- release-candidate artifacts are ready or explicitly caveated;
- all external release gaps have owner, source, required input, and status;
- `proposed_until_production` is classified as `production_input_required`;
- `proposed_until_buyer_specific` is classified as `buyer_input_required`;
- review-process delay is not counted as a product blocker;
- library split remains deferred until a real extraction trigger exists.

## Plugin Traceability

| Plugin | Gap-register contribution |
|---|---|
| Superpowers | Converts release-candidate warnings into an implementation-ready action register. |
| Product Design | Keeps buyer, operator, security, procurement, and support review paths visible. |
| Figma | Records the editable gap-register flow without Code Connect. |
| Ponytail | Prevents a separate workflow system or package split for two warning rows. |
| Data Analytics | Separates measured local evidence from proposed production or buyer-specific inputs. |

## Verification

```bash
python tests/test_commercial_gap_register.py
python tests/test_commercial_release_candidate.py
python tests/test_plugin_driven_artifacts.py
python tests/test_api_contract.py
pytest -q
```
