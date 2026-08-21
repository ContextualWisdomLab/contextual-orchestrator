# Commercial Release Candidate

Runtime endpoint: `/api/v1/commercial_release_candidates/latest`.

Purpose: package the current commercial acceptance evidence into a buyer-facing
release-candidate manifest for the KRW 2,000,000,000 due-diligence standard.
It is a local product readiness artifact, not a valuation guarantee, purchase
commitment, or production compliance certificate.

## Scope

The release candidate covers one product: the OpenAI-compatible inference API
plus the admin evidence control plane. It does not split Fugu, TRINITY, and
Conductor into separate products.

Figma Code Connect is not used for discovery, metadata, code generation, or
artifact creation.

Review process is not a blocker. Reviewer delay, review bot delay, queued model
review, and pending checks without concrete failure remain non-blocking.

Do not create a separate library, Git submodule, or extracted package now. Keep
the repository as one deployable product until a second product, independent
release cadence, or buyer security provenance requirement makes extraction
necessary.

## Release Inputs

| Input | Source | Use |
|---|---|---|
| Commercial acceptance check | `/api/v1/commercial_acceptance_checks/latest` | Primary ready, warning, or blocked input. |
| Commercial evidence export | `/api/v1/commercial_evidence_exports/latest` | Portable buyer evidence source. |
| Saleability decision | `/api/v1/saleability_decisions/latest` | Concrete blocker and warning source. |
| Buyer handoff bundle | `/api/v1/buyer_handoff_bundles/latest` | Packaged buyer handoff source. |
| Buyer evidence manifest | `/api/v1/buyer_evidence_manifests/latest` | Evidence owner and caveat model. |
| Readiness endpoints | `/api/v1/sales_readiness/latest`, `/api/v1/commercial_readiness/latest` | Local readiness gate source. |
| Analytics snapshot | `/api/v1/analytics_snapshots/latest` | Local KPI and guardrail source. |
| Admin console | `/admin` | Operator-visible release status. |
| Repository packet | `README.md`, `docs/rest_api_design.md`, commercial docs | Distribution and due-diligence packet. |

## Runtime Shape

`/api/v1/commercial_release_candidates/latest` returns:

- `release_status`: `commercial_release_ready`,
  `commercial_release_ready_with_warnings`, or `commercial_release_blocked`;
- `measurement_status`: `local_commercial_release_candidate`;
- `release_summary`: artifact count, blocked count, warning count, and
  `review_process_is_blocker=false`;
- `release_artifacts`: acceptance check, runtime endpoint chain, repository
  distribution packet, security/package metadata, admin operator surface,
  verification evidence, Figma artifacts, review-process policy, and packaging
  decision;
- `external_release_gaps`: production or buyer-specific evidence that remains
  proposed until the buyer supplies deployment, support, legal, or ROI context;
- `concrete_blockers`: concrete security, API contract, document, product, or
  Code Connect failures;
- `library_split_decision`: keep one product now;
- `release_links`: Figma design file, FigJam board, runtime endpoint, and this
  document.

## Release Status Rules

| Status | Rule |
|---|---|
| `commercial_release_ready` | All release artifacts are ready and no external gaps remain. |
| `commercial_release_ready_with_warnings` | Release artifacts are ready, but production or buyer-specific evidence still needs review. |
| `commercial_release_blocked` | Any release artifact is blocked or a concrete blocker exists. |

## KRW 2B Commercial Release Candidate

The release candidate is ready for buyer review when:

- the commercial acceptance check has no concrete blockers;
- runtime endpoint chain and admin surface are visible;
- repository distribution packet and security metadata exist;
- focused tests and `pytest -q` are named as verification evidence;
- Figma artifacts are recorded and editable;
- Code Connect exclusion is explicit;
- review-process delay is not counted as a product blocker;
- library split is deferred until a real extraction trigger exists.

Warnings remain acceptable when they are explicitly labeled as
`proposed_until_production` or `proposed_until_buyer_specific`.

## Plugin Traceability

| Plugin | Release-candidate contribution |
|---|---|
| Superpowers | Converts the accepted commercial evidence into an implementation-ready release plan. |
| Product Design | Keeps buyer, operator, security, and procurement review paths mapped to admin and evidence surfaces. |
| Figma | Records editable design, FigJam, and deck artifacts without Code Connect. |
| Ponytail | Prevents premature library, submodule, or package extraction. |
| Data Analytics | Separates measured local evidence from proposed production or buyer-specific evidence. |

## Verification

```bash
python tests/test_commercial_release_candidate.py
python tests/test_commercial_acceptance_check.py
python tests/test_commercial_evidence_export.py
python tests/test_plugin_driven_artifacts.py
python tests/test_api_contract.py
pytest -q
```
