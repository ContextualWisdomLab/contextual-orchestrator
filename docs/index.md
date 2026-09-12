---
title: Contextual Orchestrator
---

# Contextual Orchestrator

Contextual Orchestrator is a model-like control plane that routes, delegates, verifies, and synthesizes work across governed OpenAI-compatible model workers behind one API.

## Start here

For a local evaluation, run the package with the repository's mock agent registry:

```bash
python -m contextual_orchestrator "Summarize why model orchestration helps long coding tasks." \
  --agents examples/agents.mock.json
```

For the full local stack, follow the Docker Compose and credential-bootstrap path in the [README](https://github.com/ContextualWisdomLab/contextual-orchestrator#readme). Provider credentials stay in the governed credential registry rather than request-time environment lookup.

## Product boundary

The repository owns orchestration policy, worker-pool management, OpenAI-compatible request handling, routing and conduct workflows, verification, operational evidence, and the operator-facing control plane. It deliberately keeps provider credentials, external identity authority, and downstream product decisions behind explicit integration boundaries.

The public runtime exposes one model-like orchestration candidate while retaining the worker pool and orchestration machinery behind it. Local mock workers are available for evaluation; production-facing use requires the repository's documented authentication, credential, network, and persistence controls.

## Architecture and operations

- [Repository README](https://github.com/ContextualWisdomLab/contextual-orchestrator#readme) — installation, quick starts, security posture, API surface, and operational guidance.
- [Product planning](https://github.com/ContextualWisdomLab/contextual-orchestrator/blob/main/docs/product_planning.md) — product thesis, personas, product bets, and deliberate non-goals.
- [Credential guidance](https://github.com/ContextualWisdomLab/contextual-orchestrator/blob/main/docs/kv-credentials.md) — credential registry and provider-discovery boundaries.
- [Architecture decisions](https://github.com/ContextualWisdomLab/contextual-orchestrator/tree/main/docs/planning/adrs) — durable design decisions and safety constraints.
- [Releases](https://github.com/ContextualWisdomLab/contextual-orchestrator/releases) — published release history when available.
- [Ask DeepWiki](https://deepwiki.com/ContextualWisdomLab/contextual-orchestrator) — repository-grounded questions and code navigation.

## Ecosystem role

Contextual Orchestrator is the orchestration control-plane layer in the ContextualWisdomLab ecosystem. It composes model workers and shared ecosystem capabilities without taking ownership of the bounded contexts that belong to those upstream or downstream repositories.

For contribution and implementation details, use the repository documentation and current pull-request governance rather than this public landing page.
