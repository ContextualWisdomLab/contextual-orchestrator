# ADR-0014: Scientific computation ownership

## Status

`out_of_scope`

## Context and decision drivers

The wider CWL portfolio may include mathematical, financial, psychometric, or
GPU-accelerated kernels. Contextual Orchestrator currently coordinates model
calls and evidence; it does not own domain scientific arithmetic. Adding
unrelated kernels here would blur validation, numerical parity, and data
ownership.

## Considered alternatives

- implement all ecosystem arithmetic in Python here: convenient but duplicates
  domain ownership and weakens performance/parity authority;
- add GPU code opportunistically per feature: fragments CPU/GPU semantics;
- call opaque external calculations without a contract: hard to verify;
- keep domain arithmetic with its owning service and define a Rust-first rule
  only if this service gains such ownership: selected.

## Decision

Scientific arithmetic remains owned by the domain service with the relevant
data, validation, and product contract. If Contextual Orchestrator later owns a
new mathematical kernel, its decision ADR must evaluate Rust-first CPU
implementation, optional GPU acceleration, common test vectors, precision and
overflow behavior, deterministic fallback, profiling, and FFI failure isolation.
Orchestration policy and ordinary I/O logic remain Python unless evidence
justifies a different boundary.

## Consequences

This repository does not create speculative Rust/GPU code or claim numerical
capability it does not own. Future kernels face a clear evidence threshold.

## Failure and recovery

An external domain calculation fails under its adapter contract and cannot be
silently replaced by an approximate model answer. A future accelerator failure
must fall back to a parity-verified CPU path or fail explicitly.

## Security, privacy, and governance impact

Domain data stays with its authorized owner. FFI and accelerator boundaries
require memory-safety, input bounds, dependency provenance, and payload
minimization before adoption.

## Compatibility and migration

No current runtime migration is required. A future ownership transfer needs a
versioned interface, canonical test vectors, dual-run comparison, rollout, and
rollback.

## Verification and acceptance

Future acceptance requires cross-language and CPU/GPU parity, edge/overflow and
property tests, reproducible benchmarks on named hardware, profiler evidence,
fallback behavior, and 100% owned wrapper/error-path coverage.

## Rollback and supersession

Disable the new adapter or accelerator and return to the last verified domain
implementation. Supersession requires a new ownership map and numerical
validation plan.

## References

NIST SP 800-218 and NIST SP 800-218A. See
[the reference index](../REFERENCES.md).
