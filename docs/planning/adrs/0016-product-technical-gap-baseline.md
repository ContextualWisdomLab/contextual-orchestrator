---
status: accepted
date: 2026-08-20
decision-makers:
  - contextual-orchestrator maintainers
---

# ADR 0016: Product and technical gap baseline

## Decision

Keep the gateway as one standalone OpenAI-compatible product and maintain one
current-head gap register for PR, Issue, research, security, release, and
consumer-integration work. Implement the smallest independently verifiable gap
next; do not split a repository without a second consumer, independent release
cadence, or security-provenance boundary.

The authoritative, normative baseline is
[`docs/product-technical-gap-baseline.md`](../../product-technical-gap-baseline.md).
That baseline links back to this ADR as its governing decision record.
Each PR must refresh its exact head, Checks, review threads, and protected merge
state before it is called merge-ready.

## Design record

This backend baseline reuses the existing editable Figma artifact and does not
create a new visual surface:

- Figma file ID: `vsZMd8WAv42HDRgcZuNcWk`
- Figma file: [Contextual Orchestrator Plugin-Driven Admin Design](https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk)
- Artifact record: [`docs/figma_artifacts.md`](../../figma_artifacts.md)
- Storybook: deferred because this repository has no frontend package.

## Consequences

- Buyers receive one API and one evidence/control-plane boundary.
- PR queues remain stackable, but a green local result cannot replace a
  qualifying independent approval or a protected hosted Check.
- PII remains usable for authorized purposes; purpose-limited authorization and
  field-level encryption are tracked as implementation gaps rather than hidden
  behind blanket masking.
- Rust is a measured optimization boundary, not a speculative rewrite. Add it
  only when profiling demonstrates a transport, parsing, or concurrency limit
  and the standalone/module contract remains stable.

## Evidence

Research and standards are cited in the baseline and the existing architecture
record. Customer-facing claims must link to runtime or repository evidence and
must label local evidence separately from production telemetry or certification.
