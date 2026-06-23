# Product Context

## Name

Contextual Orchestrator

## One-Line Description

A small OpenAI-compatible orchestration service that hides a swappable agent pool behind one model-like API.

## Problem

Teams want the resilience and quality benefits of model orchestration without exposing every caller to agent routing, workflow design, verification, provider selection, or compliance exclusions.

The product risk is different for API callers and enterprise operators:

- Callers need one compatible endpoint.
- Operators need evidence of which agent ran, why it ran, what context it saw, and which policy constraints were applied.

## Approach

Provide one API and one domain model:

- route simple work to one selected worker;
- conduct complex work through planner, worker, verifier, and synthesizer steps;
- keep worker visibility explicit with access lists;
- make the agent pool configurable data.
- expose an admin console for operators to inspect agents, policy, workflow trace, and audit state.

## Source-backed Product Bets

- Fugu/Fugu Ultra: expose a latency-quality policy surface, not a vague "smart mode".
- TRINITY: make thinker, worker, and verifier roles visible in the trace.
- Conductor: show natural-language subtasks and access lists as first-class audit objects.
- Enterprise operations: treat provider exclusion, locale bundles, and replayable workflow evidence as product surfaces.

## Non-Goals

- Training a learned coordinator.
- Claiming compatibility with or ownership of any vendor model.
- Adding provider SDKs before stdlib HTTP proves insufficient.

See `docs/product_planning.md` for the paper-grounded product plan.
