# Commercial Procurement Readiness

Runtime endpoint: `/api/v1/commercial_procurement_readiness/latest`.

Purpose: package local license, security, distribution, admin, gap-register,
review-process, and packaging evidence into a procurement/legal readiness gate
for the KRW 2,000,000,000 buyer due-diligence standard. It is a local
commercial evidence artifact, not a valuation guarantee, purchase commitment,
or production compliance certificate.

## Scope

The procurement readiness gate supports one product: the OpenAI-compatible
inference API plus the admin evidence control plane. It does not split Fugu,
TRINITY, and Conductor into separate products.

Figma Code Connect is not used for discovery, metadata, code generation, or
artifact creation.

Review process is not a blocker. Reviewer delay, review bot delay, queued model
review, and pending checks without concrete failure remain non-blocking.

Do not create a separate library, Git submodule, or extracted package now. Keep
the repository as one deployable product until a second product, independent
release cadence, or buyer security provenance requirement makes extraction
necessary.

## Procurement Inputs

| Input | Source | Use |
|---|---|---|
| Commercial gap register | `/api/v1/commercial_gap_registers/latest` | Production and buyer-specific input source. |
| Commercial release candidate | `/api/v1/commercial_release_candidates/latest` | Release package source. |
| Commercial acceptance check | `/api/v1/commercial_acceptance_checks/latest` | Acceptance status source. |
| Security metadata | `SECURITY.md`, `requirements.lock`, `.github/workflows/security.yml` | Security review packet. |
| License and package metadata | `LICENSE`, `pyproject.toml` | Rights and distribution review. |
| Admin evidence surface | `/admin`, `contextual_orchestrator/admin.py` | Operator-visible procurement status. |

## Runtime Shape

`/api/v1/commercial_procurement_readiness/latest` returns:

- `procurement_status`: `commercial_procurement_ready`,
  `commercial_procurement_ready_with_warnings`, or
  `commercial_procurement_blocked`;
- `measurement_status`: `local_commercial_procurement_readiness`;
- `procurement_summary`: ready, warning, blocked, production-gap,
  buyer-specific-gap, and review-process counts;
- `procurement_items`: license and rights, security metadata, distribution
  packet, admin evidence, production support/SLO input, buyer legal/ROI/
  procurement input, review-process policy, and packaging decision;
- `concrete_blockers`: security, API contract, document, product, or Code
  Connect failures;
- `related_runtime_reports`: gap register, release, acceptance, export,
  saleability, handoff, manifest, readiness, and analytics statuses;
- `procurement_links`: Figma design file, FigJam board, runtime endpoint, and
  this document.

## Procurement Status Rules

| Status | Rule |
|---|---|
| `commercial_procurement_ready` | License, security, distribution, admin, support, legal, ROI, review, and packaging evidence are ready. |
| `commercial_procurement_ready_with_warnings` | Local packet is ready, but production or buyer-specific inputs remain explicit warnings. |
| `commercial_procurement_blocked` | Missing packet evidence, concrete product defect, API contract failure, security failure, document mismatch, or Code Connect usage blocks procurement. |

## KRW 2B Commercial Procurement Readiness

The procurement gate is acceptable for buyer review when:

- license, rights, security metadata, package metadata, and distribution docs
  exist;
- admin observability exposes procurement readiness;
- production support/SLO evidence is explicitly `proposed_until_production`
  until production context exists;
- buyer legal, ROI, procurement, or deployment evidence is explicitly
  `proposed_until_buyer_specific` until a named buyer supplies inputs;
- review-process delay is not counted as a product blocker;
- library split remains deferred until a real extraction trigger exists.

## Plugin Traceability

| Plugin | Procurement-readiness contribution |
|---|---|
| Superpowers | Converts the procurement gate into a task-by-task implementation plan. |
| Product Design | Keeps buyer, legal, procurement, operator, and support review paths visible. |
| Figma | Records the procurement-readiness flow without Code Connect. |
| Ponytail | Prevents a procurement portal or package split for evidence that can be expressed as a report. |
| Data Analytics | Separates measured local procurement evidence from proposed production or buyer-specific inputs. |

## Verification

```bash
python tests/test_commercial_procurement_readiness.py
python tests/test_commercial_gap_register.py
python tests/test_plugin_driven_artifacts.py
python tests/test_api_contract.py
pytest -q
```
