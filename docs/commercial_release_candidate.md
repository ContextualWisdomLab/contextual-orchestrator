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

**Product evidence** and **release authorization** are separate:

| Surface | Meaning |
|---|---|
| `product_evidence_status` | Local/demo completeness of package artifacts and measured local endpoints. Useful for buyer walkthroughs even when release is not authorized. |
| `release_authorization` | Fail-closed gate over exact protected-head identity, required checks on that head, independent non-author approval, and zero unresolved findings. |
| `release_status` | Combined ship gate: blocked if product evidence is blocked **or** release authorization is incomplete. |

Queued, pending, skipped-required, cancelled, neutral-required, stale-head,
predecessor-head, author-only approval, absent evidence, and unresolved findings
**block release authorization**. They never count as success. Warnings that are
only production/buyer-specific caveats remain warnings for product evidence and
do not authorize a protected release by themselves.

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
| Release authority (optional call arg) | CI/PR exact-head evidence | Fail-closed authorization identity. |

## Runtime Shape

`/api/v1/commercial_release_candidates/latest` returns:

- `release_status`: `commercial_release_ready`,
  `commercial_release_ready_with_warnings`, or `commercial_release_blocked`;
- `product_evidence_status`: same enum, scoped to product/package evidence only;
- `release_authorization`: `{authorization_status, blocker_reasons, evidence_identity}`;
- `measurement_status`: `local_commercial_release_candidate`;
- `release_summary`: artifact counts plus `review_process_is_blocker` (true when
  release authorization is incomplete);
- `release_authority_blockers`: machine-readable authorization blockers;
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
| `commercial_release_ready` | Product artifacts ready, no external gaps, **and** release authorization authorized. |
| `commercial_release_ready_with_warnings` | Product artifacts ready with only caveated external gaps, **and** release authorization authorized. |
| `commercial_release_blocked` | Any product artifact is blocked, a concrete product blocker exists, **or** release authorization is incomplete. |

## Fail-closed release authorization

Callers (or a future CI binder) may pass `release_authority` into
`TaskOrchestrator.commercial_release_candidate_report(...)` with:

```json
{
  "protected_head_sha": "<integrated main SHA>",
  "exact_head_sha": "<same SHA>",
  "required_checks": [
    {"check_name": "Full unit and contract suite", "conclusion": "success", "head_sha": "<same SHA>"}
  ],
  "independent_approvals": [
    {"reviewer_login": "reviewer", "author_association": "MEMBER"}
  ],
  "unresolved_findings": [],
  "author_login": "pr-author"
}
```

Absence of that object is **not** success: authorization is blocked with
`release_authority_evidence_absent` while product evidence remains readable.

Governance alignment: release integrity evidence is fail-closed so buyers cannot
treat pending review queues as authorized ship state (NIST, 2022).

## KRW 2B Commercial Release Candidate

The release candidate is **product-inspectable** when:

- the commercial acceptance check has no concrete blockers;
- runtime endpoint chain and admin surface are visible;
- repository distribution packet and security metadata exist;
- focused tests and `pytest -q` are named as verification evidence;
- Figma artifacts are recorded and editable;
- Code Connect exclusion is explicit;
- library split is deferred until a real extraction trigger exists.

It is **release-authorized** only when product evidence is not blocked **and**
exact-head release authority evidence is complete.

## References

NIST. (2022). *Secure software development framework (SSDF) version 1.1:
Recommendations for mitigating the risk of software vulnerabilities*
(NIST Special Publication 800-218). National Institute of Standards and
Technology. https://doi.org/10.6028/NIST.SP.800-218

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
