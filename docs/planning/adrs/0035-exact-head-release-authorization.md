---
id: "0035"
title: "Separate product evidence from exact-head release authorization"
status: accepted
proposed_date: "2026-08-26"
accepted_date: "2026-08-26"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/orchestrator.py"
  - "docs/commercial_release_candidate.md"
  - "tests/test_commercial_release_candidate.py"
related:
  - path: "docs/planning/adrs/0004-pr-review-merge-loop.md"
    relation: implements
---

# Separate product evidence from exact-head release authorization

## Context

The commercial release-candidate report treated pending review and checks as
non-blocking. That made useful local product evidence indistinguishable from
authority to release the protected artifact. A warning state could therefore
be read as authorization even when exact-head checks or independent approval
were absent.

## Decision

The report exposes two independent decisions:

1. `product_evidence_status` continues to describe local product-evidence
   completeness and explicit production or customer-specific gaps.
2. `release_authorization` validates the integrated protected-head identity,
   every ruleset-declared required check, the ruleset-declared number of
   independent approvals, and the unresolved-finding count. `release_status`
   fails closed unless this evidence is complete.

The caller supplies policy facts discovered from the protected repository;
the orchestrator does not guess check names, approval counts, model quality,
or provider order. Boolean and integer fields use exact JSON types, so `true`
cannot masquerade as the integer `1`. Responses expose aggregate counts and
commit identities, never reviewer or credential material.

## Consequences

- Local evidence remains useful while governance gates wait.
- Missing, pending, cancelled, stale, predecessor, synthetic-only, malformed,
  or author-only evidence cannot authorize a release.
- The runtime endpoint remains blocked until an authorized integration supplies
  exact protected-head evidence; local telemetry cannot grant authority.
- This decision does not alter provider discovery, model selection, routing,
  or reasoning-effort policy.

## Verification

`tests/test_commercial_release_candidate.py` covers complete exact-head evidence
and absent, pending, stale, author-only, unresolved, and type-confused inputs.
