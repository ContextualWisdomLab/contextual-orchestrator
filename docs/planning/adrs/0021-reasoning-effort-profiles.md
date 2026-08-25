---
status: accepted
date: 2026-08-20
decision-makers:
  - contextual-orchestrator maintainers
---

# ADR 0021: Provider-neutral reasoning-effort profiles

## Decision

Add an opt-in, versioned role catalog rather than changing the gateway's
production route/conduct defaults. Each profile records native reasoning
effort, output/call/workflow/depth/fan-out budgets, access-list scope, deadline,
cost-token budget, and independent sampling controls. Exact catalog snapshots
are canonically hashed and persisted with runtime evidence.

Native `reasoning_effort` is sent only when the configured `ModelAgent` proves
support. An unknown provider fails closed unless the operator explicitly picks
the `omit` fallback. Temperature is never used as a reasoning-effort proxy.

## Consequences

- Buyers can compare route and conduct under a declared equal budget and a real
  `theta_hat`/RMSE contract.
- Unsupported provider capabilities cannot silently become ordinary sampling.
- The current ablation is synthetic/estimated and therefore cannot authorize a
  production default change; a buyer-held-out measurement must replace it.
- Rust/GPU work is not introduced for this control-plane contract; add it only
  after profiling identifies a measured CPU/concurrency bottleneck.

## Design record

This backend change reuses the existing product-design artifact; no new
frontend surface is required.

- Figma file ID: `vsZMd8WAv42HDRgcZuNcWk`
- Figma file: [Contextual Orchestrator Plugin-Driven Admin Design](https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk)
- Storybook: deferred because this repository has no frontend package.

## Customer verification

Run `uv run pytest -q tests/test_reasoning_effort_profile.py` and inspect
`reasoning_effort_snapshot.snapshot_hash` on route, conduct, stream, batch,
and persisted records before enabling a real provider profile.
