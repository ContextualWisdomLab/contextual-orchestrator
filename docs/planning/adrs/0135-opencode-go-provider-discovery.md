---
id: "0135"
title: "OpenCode Go discovery with a shared credential"
status: proposed
proposed_date: "2026-09-25"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/model_discovery.py"
  - "contextual_orchestrator/provider_catalog_bootstrap.py"
related:
  - path: "docs/planning/adrs/0041-generalize-models-dev-cost-classification.md"
    relation: "extends cost evidence rules"
---

# ADR 0135: OpenCode Go discovery with a shared credential

Status: Proposed. This records the current discovery contract; live subscription entitlement and exact-head CI acceptance remain unverified.

## Context

OpenCode Go has a separate model catalog and serving URL from OpenCode Zen.
The repository owner confirmed that the same `OPENCODE_ZEN_API_KEY` value is
used for both, while Go still requires its own paid subscription. The earlier
[#1008 proposal](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1008)
assumed a second key and is superseded on that point. Its ADR number 0130 is
already used on `main` for output-budget evidence, so this record uses 0135.

## Decision

Register Go as a separate provider source and account with its own
`/zen/go/v1/models` catalog, using the existing Zen KV credential. Both sources
are optional. Preserve source-specific discovery errors and persisted models;
keep the credential when either source has a live model. Roll it back only when
neither source does. Go's subscription cost makes zero token rates insufficient
evidence for `orchestrator/free`. Only models with OpenAI-compatible adapter
evidence and documented chat support enter the chat pool.

## Consequences

- A Zen-only or Go-only subscription can keep its working source usable when
  the other source fails or returns an empty catalog.
- Both sources failing can roll back the shared credential; the operator still
  sees the separate failure evidence and must check entitlement and endpoint
  health before treating the key itself as invalid.
- The CI bootstrap and catalog workflows pass one Zen secret; discovery reads
  it from KV for both sources. No Go secret is added.

## Alternatives considered

- A separate `OPENCODE_GO_API_KEY` would contradict the confirmed credential
  contract and require an unnecessary second CI secret.
- Treating the two catalogs as one account would erase per-source failures and
  make an optional Go failure revoke a healthy Zen source.
- Treating zero token rates as free would admit a paid subscription to the
  free pool.

## Verification

`tests/test_opencode_go.py`, `tests/test_opencode_go_subscription_contract.py`,
`tests/test_provider_catalog_bootstrap.py`, and `tests/test_ci_gateway_bootstrap.py`
cover the source identity, shared key, paid boundary, and rollback cases.
Provider documentation: https://opencode.ai/docs/go/ .
