---
id: "0025"
title: "Separate minimal liveness from authenticated readiness"
status: accepted
proposed_date: "2026-08-20"
accepted_date: "2026-08-20"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/server.py"
  - "contextual_orchestrator/api_contract.py"
  - "tests/test_cost_review_server.py"
---

# Separate minimal liveness from authenticated readiness

## Decision

`/healthz` is a minimal, unauthenticated process-liveness contract. It must
not inspect runtime inventories, usage records, provider state, credentials,
or batch backends.

`/readyz` is a separate administrator-authenticated contract. It reports
secret-free required orchestration/synchronous-routing checks and optional
batch checks. It never calls a live model provider. Required-path failure is
HTTP `503`; optional batch degradation is reported without making interactive
traffic unready.

This preserves real operational evidence for authorized operators while
preventing public liveness probes from disclosing internal topology or
activity.

## Evidence and acceptance

- `tests/test_cost_review_server.py` proves the exact minimal liveness payload,
  authentication boundary, readiness status, backend reporting, and omission
  of usage counts.
- `docs/doctoring/liveness-readiness.md` gives the customer/operator action:
  use `/healthz` for process supervision and `/readyz` for authenticated
  operational diagnosis.
- Figma is not required: this is a backend probe contract and introduces no
  user-facing screen or reusable web object. Existing product-design Figma
  file `vsZMd8WAv42HDRgcZuNcWk` remains the source for future admin-console
  changes.

## Research grounding

National Institute of Standards and Technology. (2023). *Artificial
intelligence risk management framework (AI RMF 1.0)* (NIST AI 100-1).
https://doi.org/10.6028/NIST.AI.100-1

The readiness response follows the framework's measurement and governance
principle: expose actionable, bounded evidence to an authorized operator and
avoid treating an availability probe as a disclosure channel.
