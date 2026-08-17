# ADR 0004: Fugu latency-quality split

- Status: Accepted
- Date: 2026-08-16

## Context

Sakana Fugu presents one model-like API with two operating points: a
low-latency path that selects a worker without expensive coordinator
generation (Fugu), and a quality path that builds deeper workflows over a
broader pool (Fugu-Ultra). The agent pool is swappable so provider preference,
exclusion, and compliance controls stay data, not code.

This repository is **not** a Sakana product and does **not** ship or reproduce
trained Sakana models. It implements the public architecture pattern described
in Sakana AI (2026) and the launch notes cited in
[architecture.md](../architecture.md).

## Decision

Map the Fugu / Fugu-Ultra split onto two explicit modes:

- **`route`** — select one worker for simple or latency-sensitive requests
  (Fugu-style fast path).
- **`conduct`** — run the thinker → worker → verifier → synthesizer workflow
  when the task needs decomposition, verification, or synthesis (Fugu-Ultra-style
  quality path).

`TaskOrchestrator.complete()` chooses between them (`auto` uses a
deterministic policy). The agent pool remains configuration. Evaluation replay
(`compare_to_baseline` / `--eval`) measures orchestration against a
single-worker baseline as a tradeoff report, not a human-quality claim.

## Consequences

- Operators tune a latency-quality policy instead of choosing among separate
  products.
- Callers still see one `/v1/chat/completions` interface.
- Honesty constraint: docs and readiness reports must not claim trained Fugu
  weights, Sakana compatibility, or learned coordinator quality.

## References

Sakana AI. (2026). *Sakana Fugu technical report* (arXiv:2606.21228). arXiv. https://doi.org/10.48550/arXiv.2606.21228
