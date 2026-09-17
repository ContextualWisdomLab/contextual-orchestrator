---
id: "0126"
title: "Permit provider-neutral evaluation ACL modules outside orchestrator.py"
status: proposed
proposed_date: "2026-09-02"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/evaluation_criterion_binding.py"
  - "contextual_orchestrator/rater_observation.py"
  - "contextual_orchestrator/dynamic_item_generation.py"
related:
  - path: "docs/planning/adrs/0125-domain-neutral-rater-observation-context.md"
    relation: "constrains-module-boundary"
success_criteria:
  - metric: "orchestration ownership"
    target: "planning, routing, provider execution, fallback, and workflow composition remain in orchestrator.py"
    source: "repository import graph and tests"
  - metric: "second concrete consumer"
    target: "the immutable criterion binding is consumed by rater observation and dynamic item generation"
    source: "PR #917 and PR #1014"
---

# Permit provider-neutral evaluation ACL modules outside orchestrator.py

## Context

This repository normally keeps orchestration-domain behavior in
`orchestrator.py` until a second implementation makes extraction necessary.
That convention prevents speculative framework decomposition and preserves one
obvious domain heart.

The criterion-binding change is not a second planner, router, or provider
runtime. It is an immutable Published-Language value contract consumed at two
separate untrusted-input boundaries: governed rater observation in PR #917 and
dynamic item generation in stacked PR #1014. Keeping the contract inside either
consumer would duplicate criterion identity, digest, category-order, and
substitution rules; placing it in `orchestrator.py` would make provider-neutral
measurement meaning depend on provider execution code.

## Decision

Allow the following narrow Anti-Corruption Layer modules outside
`orchestrator.py`:

- `evaluation_criterion_binding.py` owns only immutable criterion, category,
  scope, and content-digest validation;
- `rater_observation.py` owns only provider-neutral observation admission under
  a separately trusted criterion set;
- `dynamic_item_generation.py` owns only provider-neutral generation-invocation
  evidence and consumes the same criterion contract.

`orchestrator.py` remains the sole owner of planning, agent selection, provider
routing, provider calls, retry/fallback, workflow composition, and execution
trace assembly. The ACL modules must not import provider clients, choose prompts,
open network connections, persist panels or responses, assign scores, perform
adjudication, or publish product decisions.

The dependency direction is one way:

```text
orchestrator execution services
        |
        v
provider-neutral invocation ACLs
        |
        v
immutable criterion value contract
```

The criterion contract does not import orchestration or provider code. A future
unrelated consumer must use the released owner contract rather than expand
these modules into a mutable shared framework.

## Consequences

- The repository convention remains the default; this is an explicit exception
  justified by two concrete consumers and a stable one-way dependency.
- Criterion digest and substitution logic have one implementation instead of
  drifting between generation and observation.
- Review must reject any future provider execution, scoring, persistence, or
  adjudication behavior added to these modules.

## Verification

- import-boundary inspection shows no provider-client or network dependency;
- tests require an independently supplied trusted criterion set;
- tests reject whole-policy substitution and stale content digests;
- constructors are sealed and integrity is replayed after admission;
- PR #1014 consumes the same criterion contract after restacking.
