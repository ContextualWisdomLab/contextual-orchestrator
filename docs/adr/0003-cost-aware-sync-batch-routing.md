# ADR 0003: Evidence-bounded sync-versus-batch routing

- Status: Accepted; amended 2026-09-01
- Date: 2026-08-25
- Decision owners: ContextualWisdomLab
- Series: `docs/adr` only. This is not planning ADR 0003
  (`docs/planning/adrs/0003-keyverse-authentication-boundary.md`).

## Context

LLM API prices differ materially across providers and models, and some providers
expose distinct asynchronous batch products. FrugalGPT, RouteLLM, and Hybrid
LLM show that cost/quality routing is an estimable or learned decision problem.
They do **not** validate a hand-written `batch_min_tokens`, caller `priority`,
`latency_tolerant` switch, fixed representative request shape, provider-order
tie break, or pseudo-semantic hash embedding.

The preceding version of this ADR cited those papers while explicitly saying
that this repository implemented a deterministic config policy instead of the
learned/evaluated algorithms in the papers. Under the no-heuristics contract,
that mismatch is not an acceptable permanent approximation: missing routing
evidence must stay unresolved or fail closed rather than being replaced by an
operational rule of thumb.

The already-vendored research inventory in `docs/papers/README.md` remains the
paper source. This amendment changes the authority assigned to the evidence; it
does not claim the repository has suddenly implemented RouteLLM, Hybrid LLM,
Fugu, TRINITY, or Conductor.

## Decision

1. **Measured cost remains first-class.** Every completion, sync and batch,
   continues to write prompt-safe usage evidence with authoritative token
   counts and price provenance when those measurements exist. Unknown usage or
   incomparable price evidence stays unknown rather than becoming zero.
2. **Sync versus batch is explicit contract selection until an evaluated
   router exists.** `routing.channel=sync|batch` is authoritative caller
   intent. An omitted or unrecognized channel stays synchronous because the
   synchronous API contract must not silently change response shape. The
   `batch_enabled=false` setting is an operator kill switch. Compatibility
   fields such as `latency_tolerant`, `priority`, prompt length,
   `batch_min_tokens`, and `interactive_forces_sync` cannot select a channel.
3. **Cost comparison uses the exact request shape.** Table-driven comparison
   requires caller/runtime-supplied prompt and completion token quantities for
   the request being compared. The former 1000-prompt/1000-completion token
   assumption is retired. Unknown prices and equal minimum costs leave the
   candidate unresolved instead of using input order as a tie break.
4. **Local embeddings require explicit semantics.** A local embedding backend
   may execute new work only when a semantic embedding implementation and an
   authoritative tokenizer are explicitly injected. SHA/digest-derived values
   may serve as identifiers or integrity digests, but are prohibited as
   semantic vectors. The legacy pseudo-embedding entry point is retained only
   as a fail-closed compatibility tombstone and is not exported by the package.
5. **Multiple embedding candidates require evidence.** A single eligible
   candidate needs no comparative ranking. When multiple candidates remain,
   the caller must identify the exact agent or an independently validated
   routing model must produce a unique decision. Price-only ranking, static
   input order, and fallback-first ordering are not substitutes for that model.
6. **Future automatic routing requires executable provenance.** A new router
   must identify its estimand, training/evaluation design, calibration or
   uncertainty contract, and exact decision inputs before production authority
   changes. Fugu, Conductor, and TRINITY architecture contracts do not by
   themselves justify thresholds, hand-set weights, or fallback ordering.

## Consequences

The synchronous API no longer changes to batch because a request is labelled
bulk/latency-tolerant or crosses a configured token threshold. Offline tests may
still inject a deterministic test embedder, but the production/default path
cannot fabricate semantic vectors. Cost optimization remains available when
exact request measurements identify a unique minimum; otherwise uncertainty is
preserved explicitly.

This is intentionally more conservative than the retired deterministic policy.
It may leave work synchronous or selection unresolved until sufficient evidence
exists. That behavior is the specified fail-closed boundary, not an implicit
routing preference.

## References

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large
language models while reducing cost and improving performance* [Preprint].
arXiv. https://doi.org/10.48550/arXiv.2305.05176

Ding, D., Mallick, A., Wang, C., Sim, R., Mukherjee, S., Ruhle, V.,
Lakshmanan, L. V. S., & Awadallah, A. (2024). *Hybrid LLM: Cost-efficient
and quality-aware query routing* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2404.14618

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E.,
Kadous, M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with
preference data* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2406.18665
