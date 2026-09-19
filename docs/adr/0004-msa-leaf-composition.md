# ADR 0004: MSA leaf — standalone and callable

- Status: Accepted
- Date: 2026-08-25
- Decision owners: ContextualWisdomLab
- Series: `docs/adr` only. This is not a planning-ADR number.

## Context

ContextualWisdomLab components are standalone programs that must also be
callable as peers (and may be checked out as git submodules). This
repository is the org LLM gateway. Other hubs — including naruon and gyeot —
may call it. Optional siblings include `pg-llm-batch` (batch/embeddings
backend) and `fast-mlsirm` (model-judge calibration).

A hard checkout coupling (this repo cannot start unless every sibling is
present) would break the standalone lab and the stdlib runtime. A hard
runtime coupling that silently skips a missing judge would break the
already-accepted fail-closed model-judgment rule in planning ADR 0001.

NIST SP 800-204 describes microservices as independently developed and
scaled components that communicate through APIs, and recommends isolating a
failing instance rather than cascading (Chandramouli, 2019). That
independently deployable leaf is the composition rule here. Planning ADR
0001 already decided that model judgment requires `fast-mlsirm` in the same
interpreter and fails closed when the package is absent or broken. This ADR
does not rewrite that product decision.

## Decision

1. **Leaf runtime.** `contextual-orchestrator` must run standalone with the
   standard library, the in-memory KV, `mock://` agents, and the in-process
   batch backend. No sibling repository checkout is required to serve,
   complete, or test the core.
2. **Callable hub.** Other programs may call this OpenAI-compatible API.
   naruon and gyeot are permitted callers. Their repositories are not
   required dependencies of this repo, its tests, or its default deploy.
3. **Optional `pg-llm-batch`.** The production batch and embeddings backend
   is an **injected client**, not a required sibling checkout. When the
   client and a DSN are present, KV-backed counting and the production batch
   path activate. When they are absent, the local in-process backend
   preserves the standalone path.
4. **Fail-closed judge composition.** Model-judge verification requires
   `fast-mlsirm` importable in the **same interpreter** and fails closed
   when it is absent or broken. That is composition-at-judgment-time, not a
   hard checkout coupling: the gateway still starts, routes, and conducts;
   a conducted verifier that needs a model verdict rejects instead of
   falling back to keywords or a direct provider call. See planning
   ADR 0001; do not re-open that decision here.
5. **No silent sibling fallback.** Absence of an optional batch client must
   not be repaired by inventing a second batch protocol. Absence of
   `fast-mlsirm` must not be repaired by a direct contextual judge.

## Consequences

### Positive

- The lab remains one deployable control plane.
- Callers can adopt the hub without vendoring this repo's siblings.
- Judge calibration stays a fail-closed seam instead of an implicit
  dependency of process start.

### Negative

- A live conducted verification without `fast-mlsirm` installed in that
  interpreter will reject. Operators who want model judgment must install
  both packages into one environment (see the operator README and planning
  ADR 0001).
- Batch economics that need `pg-llm-batch` require a separate deploy of
  that client; this repo will not vendor it.

## References

Chandramouli, R. (2019). *Security strategies for microservices-based
application systems* (NIST Special Publication 800-204). National Institute
of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-204

ContextualWisdomLab. (2026). *Fail-closed structured model judgment*
(Planning ADR 0001).
https://github.com/ContextualWisdomLab/contextual-orchestrator/blob/main/docs/planning/adrs/0001-fail-closed-model-judgment.md
