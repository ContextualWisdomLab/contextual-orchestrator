# ADR-0012: Standalone product and CWL composition

## Status

`implemented_on_protected_main`

**Date:** 2026-08-17
**Decision owner:** Contextual Orchestrator maintainers
**Scope:** This repository's deployable boundary and its relationship to
sibling ContextualWisdomLab programs. This ADR does not transfer product
authority to naruon, gyeot, or any other service.

## Context and decision drivers

Contextual Orchestrator is the org LLM gateway: an OpenAI-compatible front
door, cost-review hub, and sync/batch router. It is both an independently
useful service and a module in the ContextualWisdomLab ecosystem. Naruon and
gyeot are composition hubs (email/PIM and ESM/EMA). Scopeweave and other
siblings may also call this gateway.

Hidden dependence on a central control plane would break offline tests,
local adoption, failure isolation, and ownership clarity. Duplicating host
identity or business data would create a conflicting authority. Treating
every sibling call as a microservices-architecture (MSA) violation would
force a false split: the org rule is that each program is a **standalone
program that must also work as a git submodule**, grown separately and
together.

Composition is the intended architecture. Naruon and gyeot may call this
orchestrator. That is not an MSA violation. Sibling links stay.

## Considered alternatives

- Require the full CWL stack: integrated but not independently deployable.
  Rejected.
- Copy identity, tenancy, and business records into this service:
  convenient locally but creates ownership and synchronization conflicts.
  Rejected.
- Expose only a library with no service boundary: limits compatible
  adoption. Rejected.
- Rip sibling links to appear more “purely” standalone: rejected. It would
  erase the naruon batch-embeddings contract, Clearfolio viewer hook,
  pg-llm-batch adapter, and documented gyeot/scopeweave consumers.
- Keep standalone defaults and add explicit, optional host/adaptor
  contracts: selected.

## Decision

1. The core runs offline with mock agents and in-memory state, and can run
   as a compatible HTTP service with configured providers.
2. Optional integrations enter through explicit interfaces. Current sibling
   links that this ADR **retains** include:
   - [naruon](https://github.com/ContextualWisdomLab/naruon) — composition
     hub; batch embeddings and cost attribution caller;
   - [gyeot](https://github.com/ContextualWisdomLab/gyeot) — composition
     hub; may call this gateway;
   - [scopeweave](https://github.com/ContextualWisdomLab/scopeweave) —
     documented consumer of the OpenAI-compatible front door;
   - [clearfolio](https://github.com/ContextualWisdomLab/clearfolio) —
     optional admin document viewer;
   - [pg-llm-batch](https://github.com/ContextualWisdomLab/pg-llm-batch) —
     optional batch/embeddings backend;
   - [fast-mlsirm](https://github.com/ContextualWisdomLab/fast-mlsirm) —
     scientific Judge ownership stays there ([ADR-0014](0014-scientific-computation-ownership.md)).
3. The host owns ingress identity, tenant/purpose authorization, business
   records, deployment, and end-user privacy unless a versioned contract
   delegates a specific responsibility.
4. Calling this orchestrator from naruon or gyeot is **composition**, not a
   forbidden MSA edge. Each side remains independently deployable.
5. Do not rip sibling links to satisfy a purity argument.

## Consequences

Basic operation stays dependency-light and testable. Integrations must
translate and authorize at their boundary rather than importing implicit
global state. Shared fixtures (for example
`tests/fixtures/batch_embeddings_contract.json`) are contracts, not hidden
merges of the sibling repositories.

## Failure and recovery

An optional CWL dependency outage degrades only its declared capability. The
standalone route and library path remain available when safe. Recovery
revalidates the adapter contract and never backfills fabricated evidence.

## Security, privacy, and governance impact

Authority and data ownership remain local to the system that has purpose and
tenant context (National Institute of Standards and Technology, 2023;
International Organization for Standardization, 2023b). A viewer, batch
service, or orchestrator response does not grant host access or
merge/release authority.

## Compatibility and migration

Adapters are optional and versioned. Breaking a host boundary requires
staged dual compatibility, ownership reconciliation, and coordinated
rollback. Ponytail still recommends one deployable product here until a
second consumer needs a separately versioned core package
([docs/library_research.md](../library_research.md)).

## Verification and acceptance

Offline install, import, and mock tests run without CWL dependencies.
Contract tests cover each adapter, missing or degraded dependency behavior,
data minimization, authorization handoff, and the naruon embeddings fixture.

## Rollback and supersession

Disable the adapter and retain standalone behavior. Supersession must
preserve an independent mode or explicitly reclassify the product with
migration, availability, and ownership evidence. A superseding ADR may not
delete sibling links without a replacement contract.

## References

National Institute of Standards and Technology. (2023). *Artificial
intelligence risk management framework (AI RMF 1.0)* (NIST AI 100-1).
https://doi.org/10.6028/NIST.AI.100-1

International Organization for Standardization. (2023b). *Information
technology — Artificial intelligence — Management system* (ISO/IEC
42001:2023). https://www.iso.org/standard/81230.html

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1* (NIST SP 800-218).
https://doi.org/10.6028/NIST.SP.800-218

See also [docs/REFERENCES.md](../REFERENCES.md) and
[AGENTS.md](../../AGENTS.md).
