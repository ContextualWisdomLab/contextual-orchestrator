# Contextual Orchestrator

Contextual Orchestrator provides one model-like API for governed multi-model orchestration. Applications keep an OpenAI-compatible interface while operators gain explicit control over worker pools, routing policy, provider boundaries, verification evidence, traces, and operating cost.

[Ask DeepWiki](https://deepwiki.com/ContextualWisdomLab/contextual-orchestrator) · [Repository](https://github.com/ContextualWisdomLab/contextual-orchestrator) · [Releases](https://github.com/ContextualWisdomLab/contextual-orchestrator/releases)

## Start here

- [README and local evaluation paths](../README.md)
- [Provider credentials and model discovery](kv-credentials.md)
- [Product planning](product_planning.md)
- [Security policy](../SECURITY.md)
- [Contributing](../CONTRIBUTING.md)

## Product responsibility

The repository owns orchestration, routing, governed model pools, provider/model discovery, compatible inference interfaces, verification/synthesis, and trace/audit evidence. It keeps those concerns behind one public control-plane model so individual applications do not need to rebuild their own multi-model governance layer.

It does not claim ownership of every adjacent ecosystem concern. Identity, sandboxing, document systems, psychometrics, and enterprise architecture remain separate products or authorities and integrate through explicit contracts.

## How it works

Simple requests can route to one approved worker. Harder requests can enter a short conduct workflow that delegates work, verifies intermediate or final results, and synthesizes a response. Operators can manage candidates and groups using health, availability, cost evidence, priority, and exclusion metadata without treating transient discovery data as permanent truth.

Remote provider credentials are resolved through the product's governed credential path and missing credentials fail closed. Non-mock remote workers use approved HTTPS boundaries; local evaluation paths are explicitly separated from remote-provider behavior.

## Evaluation

The repository supports a full local Compose path and a lighter mock-worker path. The README is the canonical onboarding surface and includes the current commands, security boundaries, model-pool behavior, and admin entry point.

## Releases and evidence

Published releases are the versioned delivery record. Architecture, operational, credential, security, and product-planning material remains versioned with the source so claims can be reviewed against implementation and release evidence.
