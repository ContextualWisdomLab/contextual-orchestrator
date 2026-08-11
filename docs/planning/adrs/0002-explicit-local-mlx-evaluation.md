---
id: "0002"
title: "Explicit local mlx transport and evaluation adapter"
status: accepted
proposed_date: "2026-08-10"
accepted_date: "2026-08-11"
deciders:
  - "repository maintainer"
consulted:
  - "mlx-lm runtime"
  - "fast-mlsirm evaluation adapter"
informed:
  - "contributors"
affected_components:
  - "contextual_orchestrator/orchestrator.py"
  - "contextual_orchestrator/__main__.py"
  - "examples/agents.mlx.json"
  - "tests/test_local_mlx.py"
effort: M
supersedes: null
superseded-by: null
related:
  - path: "docs/planning/adrs/0001-fail-closed-model-judgment.md"
    relation: informational
  - path: "docs/planning/adrs/0003-keyverse-authentication-boundary.md"
    relation: informational
asr_triggers:
  - kind: performance
    evidence: "The local 3B mlx-lm model is available and orchestration multiplies provider calls."
    note: "Temperature, token cap, template behavior, and bounded local concurrency are explicit controls."
  - kind: security
    evidence: "A local endpoint must never receive a remote provider credential."
    note: "Only explicit loopback mlx/local URLs are keyless and translated to HTTP after validation."
success_criteria:
  - metric: "local provider safety"
    target: "loopback-only mlx/local URL, no Authorization header, remote HTTP rejected"
    measurement_window: "every local transport test run"
    source: "tests/test_local_mlx.py"
  - metric: "judge integration"
    target: "fast-mlsirm judge reaches an injected contextual-orchestrator only"
    measurement_window: "every LLM-as-a-Judge run"
    source: "fast-mlsirm/tests/test_llm_judge.py"
---

# Explicit local mlx transport and evaluation adapter

## Context

mlx-lm exposes an OpenAI-compatible server, but local reasoning models may return a reasoning-only message when thinking consumes the output budget. The gateway previously treated local HTTP as a remote provider shape, and the evaluation package had no provider-neutral boundary that guaranteed contextual-orchestrator was used for LLM-as-a-Judge.

> ModelClient accepts an explicit mlx:// or local:// loopback URL and maps it to HTTP only after validation.
>
> Local requests can forward chat_template_kwargs, including {"enable_thinking": false}, and report an actionable error when content is absent.
>
> ContextualOrchestratorJudge calls an injected .complete(messages, mode=...) object and parses bounded rubric JSON without provider credentials.

## Decision Drivers

* Maximize useful local model output on the available Apple Silicon runtime.
* Keep local tests offline and free of provider SDK dependencies.
* Prevent credentials from being sent to loopback or arbitrary HTTP endpoints.
* Measure quality and latency separately instead of labeling structure as quality.

## Considered Options

* Treat all OpenAI-compatible endpoints identically.
* Add a direct mlx-specific provider dependency to both repositories.
* Keep the core stdlib-only and add explicit loopback transport controls plus an injected evaluation adapter.

## Decision Outcome

Chosen option: "Explicit loopback local transport plus provider-neutral adapter".

| Driver | Generic HTTP | Direct mlx dependency | Explicit loopback + injected adapter |
| --- | --- | --- | --- |
| Local safety | ambiguous | provider-specific | scheme/host/credential checks |
| Runtime footprint | small | larger | stdlib core, installed mlx executable |
| Judge composition | not enforced | couples packages | contextual-orchestrator boundary is testable |
| Performance controls | implicit | provider-specific | temperature/cap/template/concurrency knobs |

The core accepts only mlx:// or local:// with loopback hosts and a valid port for keyless local traffic. Local batch requests use a bounded thread pool; interactive paths remain sequential by default. fast-mlsirm receives an injected contextual-orchestrator adapter, strict criteria, bounded JSON parsing, and usage/trace metadata.

### Consequences

* Good, because the existing mlx_lm.server can be benchmarked without adding a runtime dependency.
* Good, because local reasoning behavior is controlled by explicit template kwargs rather than silent content loss.
* Good, because fast-mlsirm cannot accidentally call a provider outside contextual-orchestrator.
* Bad, because local conduct remains several sequential model calls and can be slow.
* Bad, because the adapter does not manufacture a ground truth; a rubric model is still a model.

### Confirmation

Run python3 tests/test_local_mlx.py, PYTHONPATH=python python3 tests/test_llm_judge.py, and the real mlx route/conduct/judge benchmark. Confirm traces include provider usage and that the judge is disabled-thinking or has enough output budget.

## Pros and Cons of the Options

### Treat all endpoints identically

* Good, because the API surface is smaller.
* Bad, because it hides local security and template semantics.
* Bad, because reasoning-only responses become opaque provider failures.

### Add direct mlx dependencies

* Good, because provider-specific behavior could be wrapped deeply.
* Bad, because both repositories would become harder to install and test.
* Bad, because the installed mlx_lm.server already supplies the required transport.

### Explicit loopback transport and injected adapter (chosen)

* Good, because it reuses the existing OpenAI-compatible surface and stdlib.
* Good, because the trust boundary is visible in configuration and tests.
* Bad, because an external deployment still owns model lifecycle and OIDC integration.

## Problem Register and Remediation Directions

| Finding | Direction | State |
| --- | --- | --- |
| Reasoning-only mlx responses hid the real failure. | Forward template kwargs and emit an actionable content error. | Implemented |
| Local URLs could be confused with remote egress. | Require explicit loopback scheme/host and strip credentials/query data. | Implemented |
| Unbounded local parallelism could exhaust memory. | Cap local_concurrency and preserve sequential default. | Implemented |
| Batch result errors could lose usage/IDs. | Preserve custom IDs and usage per local request. | Implemented |
| LLM-as-a-Judge could bypass the gateway. | Make fast-mlsirm depend on an injected contextual-orchestrator object, not a provider. | Implemented |
| Quality claims could be inferred from latency/step count. | Report structural metrics as structural and use rubric judgments for quality. | Implemented; benchmark ongoing |

## Risks and Mitigations

| risk | likelihood | impact | mitigation | owner |
| --- | --- | --- | --- | --- |
| A malicious config labels a remote endpoint as local. | low | high | Scheme, loopback host, port, credential/query validation and tests. | maintainer |
| Concurrent mlx requests exceed device memory. | medium | high | Default concurrency 1 and bounded user control; measure before raising it. | local-runtime owner |
| A small judge model produces invalid JSON. | medium | medium | Disable thinking, cap prompt/output, strict parse, fail closed. | evaluation owner |

## Rollback / Exit Strategy

Remove the explicit local adapter and use the mock path if the local server is unavailable; retain remote HTTPS validation unchanged. Revert concurrency to one and keep the output-content guard. Do not broaden local URL matching as a convenience fix.

## Affected Components

* contextual_orchestrator/orchestrator.py
* contextual_orchestrator/__main__.py
* examples/agents.mlx.json
* tests/test_local_mlx.py
* fast-mlsirm/python/fast_mlsirm/llm_judge.py
* fast-mlsirm/tests/test_llm_judge.py

## More Information

The public projects are [contextual-orchestrator](https://github.com/ContextualWisdomLab/contextual-orchestrator) and [fast-mlsirm](https://github.com/ContextualWisdomLab/fast-mlsirm). This ADR intentionally does not add a provider SDK or a second orchestration runtime.
