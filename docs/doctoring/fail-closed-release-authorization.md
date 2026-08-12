# Fail-closed release authorization (issue #103)

## Contract

Buyer-facing `release_status` is **fail-closed** for release authorization:

- Product evidence (`product_evidence_status`) may remain inspectable for demos.
- `release_authorization` requires exact protected-head identity, required checks
  on that head, independent non-author approval, and zero unresolved findings.
- Pending/queued/skipped-required/cancelled/neutral/stale/absent evidence never
  authorizes a ship state.

## Implementation

- `evaluate_release_authorization()` in `contextual_orchestrator/orchestrator.py`
- Exposed on `/api/v1/commercial_release_candidates/latest` via
  `commercial_release_candidate_report(... release_authority=...)`

## Standards

NIST. (2022). *Secure software development framework (SSDF) version 1.1*
(NIST SP 800-218). https://doi.org/10.6028/NIST.SP.800-218
