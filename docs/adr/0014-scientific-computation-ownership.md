# ADR-0014: Scientific computation ownership

## Status

`out_of_scope`

**Date:** 2026-08-17
**Decision owner:** Contextual Orchestrator maintainers

## Context and decision drivers

The wider CWL portfolio includes mathematical, psychometric, and
GPU-accelerated kernels. **fast-mlsirm** owns LLM-as-a-Judge calibration and
evaluation-item quality (aFIPC FIPC + kaefa item-fit). Contextual
Orchestrator coordinates model calls and evidence; it does not own domain
scientific arithmetic.

Adding unrelated kernels here would blur validation, numerical parity, and
data ownership. Calling fast-mlsirm, or being called by it, is composition
and is not an MSA violation ([ADR-0012](0012-standalone-and-cwl-boundary.md)).

## Considered alternatives

- Implement all ecosystem arithmetic in Python here: convenient but
  duplicates domain ownership and weakens performance and parity authority.
- Add GPU code opportunistically per feature: fragments CPU/GPU semantics.
- Call opaque external calculations without a contract: hard to verify.
- Keep domain arithmetic with its owning service: selected.

## Decision

Scientific arithmetic remains owned by the domain service with the relevant
data, validation, and product contract. If Contextual Orchestrator later
owns a new mathematical kernel, a superseding ADR must evaluate
implementation language, optional acceleration, common test vectors,
precision and overflow behavior, deterministic fallback, profiling, and FFI
failure isolation. Orchestration policy and ordinary I/O logic remain Python
unless evidence justifies a different boundary.

This repository does not create speculative Rust or GPU code or claim
numerical capability it does not own. Org direction that a Rust/Python
hybrid may later cut gateway overhead is a future option, not a present
ownership transfer.

## Consequences

Judge, IRT, and item-fit claims stay with fast-mlsirm. This gateway may
transport model calls those services request.

## Failure and recovery

An external domain calculation fails under its adapter contract and cannot
be silently replaced by an approximate model answer. A future accelerator
failure must fall back to a parity-verified CPU path or fail explicitly.

## Security, privacy, and governance impact

Domain data stays with its authorized owner (National Institute of Standards
and Technology, 2023). FFI and accelerator boundaries require memory-safety,
input bounds, dependency provenance, and payload minimization before
adoption.

## Compatibility and migration

No current runtime migration is required. A future ownership transfer needs
a versioned interface, canonical test vectors, dual-run comparison,
rollout, and rollback.

## Verification and acceptance

Future acceptance requires cross-language and CPU/GPU parity, edge/overflow
and property tests, reproducible benchmarks on named hardware, profiler
evidence, and fallback behavior.

## Rollback and supersession

Disable the new adapter or accelerator and return to the last verified
domain implementation. Supersession requires a new ownership map and
numerical validation plan.

## References

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1* (NIST SP 800-218).
https://doi.org/10.6028/NIST.SP.800-218

National Institute of Standards and Technology. (2023). *Artificial
intelligence risk management framework (AI RMF 1.0)* (NIST AI 100-1).
https://doi.org/10.6028/NIST.AI.100-1

National Institute of Standards and Technology. (2024b). *Secure software
development practices for generative AI and dual-use foundation models: An
SSDF community profile* (NIST SP 800-218A).
https://doi.org/10.6028/NIST.SP.800-218A

See also [docs/REFERENCES.md](../REFERENCES.md).
