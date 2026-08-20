# ADR 0019: No runtime monkey patching for transport contracts

- Status: Accepted
- Date: 2026-08-21

## Context

Provider capability behavior must be visible in the owning transport client.
Import-time mutation of `ModelClient` obscures the effective contract, creates
global process state, and can change behavior for callers that did not opt in.

## Decision

The orchestrator must not monkey patch classes or methods at runtime. Optional
sampling omission, capability negotiation, protocol translation, and retry
behavior are implemented in the owning `ModelClient` transport paths and are
covered by direct tests. Importing the package must not mutate a class or
install a wrapper as a side effect.

## Consequences

- The effective request contract is inspectable in one implementation.
- Chat, streaming, and batch transports share the same provider-neutral policy.
- Upstream capability changes require an ordinary code review instead of a
  hidden import-order dependency.
