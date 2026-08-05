# Adaptive Reasoning Control

## Purpose

Contextual Orchestrator controls three independent forms of test-time compute:

1. **model routing** — choose one worker or a fallback candidate;
2. **workflow topology** — route directly or construct a Conductor/TRINITY-style multi-step workflow with explicit subtasks and access lists;
3. **reasoning effort** — request only the model-specific reasoning level justified for each role, task, and workflow position.

The third axis is explicit in this subsystem. It is not inferred from a model name, provider brand, undocumented default, latency target, or response-speed objective.

## Configuration contract

Each model may declare a `reasoning_profile`:

```json
{
  "id": "openai_reasoning_agent",
  "model": "provider-model-id",
  "base_url": "https://provider.example/v1",
  "credential_key": "PROVIDER_API_KEY",
  "reasoning_profile": {
    "preset": "openai_effort",
    "supported_levels": ["none", "low", "medium", "high", "xhigh"],
    "default_level": "low",
    "maximum_level": "high"
  }
}
```

Canonical levels are ordered as:

```text
none < minimal < low < medium < high < xhigh < max
```

A failover model receives the same canonical decision projected to its nearest supported level. Unsupported settings are never guessed.

## Built-in mappings

| Preset | Chat Completions | Responses |
|---|---|---|
| `openai_effort` | `reasoning_effort` | `reasoning.effort` |
| `nvidia_reasoning_effort` | `reasoning_effort` | `reasoning.effort` when the endpoint supports it |
| `nvidia_nemotron_thinking` | `chat_template_kwargs.enable_thinking` and `low_effort` | no implicit mapping |
| `gemini_thinking_level` | `extra_body.google.thinking_config.thinking_level` | no implicit mapping |
| `custom` | validated nested rules | validated nested rules |

NVIDIA NIM also exposes model-dependent hard thinking budgets and parallel-reasoning modes. These are configured through strict `custom` rules and integer mappings rather than being sent to models that may not support them.

```json
{
  "preset": "custom",
  "supported_levels": ["low", "medium", "high"],
  "default_level": "low",
  "maximum_level": "high",
  "level_values": {"low": 64, "medium": 256, "high": 1024},
  "chat_rules": [
    {"path": ["chat_template_kwargs", "enable_thinking"], "value": true},
    {"path": ["chat_template_kwargs", "reasoning_budget"], "value": "$int"}
  ]
}
```

## Adaptive policy

The default policy begins at the model profile's operator-declared default. It raises effort only for bounded evidence and never uses response speed as an allocation signal.

Semantic and role evidence:

- thinker and verifier roles receive one baseline increment;
- two or more complexity signals add one increment;
- long context or explicit multi-step task structure may add one increment;
- two or more high-impact signals may add one increment;
- the model's declared `maximum_level` is an absolute cap;
- synthesizers do not inherit the analysis role's effort automatically.

Workflow-structure evidence:

- `workflow_step_index` and `workflow_step_count` identify the call's position in the direct or deep workflow;
- `decomposition_count` records the number of validated workflow subtasks;
- `recursion_depth` is derived from the accessed-step dependency graph;
- `accessible_step_count` measures access-list fan-in without exposing hidden model reasoning;
- later integration steps with several dependencies may receive more effort than an early worker step;
- a direct route remains a one-step workload and does not inherit deep-workflow increments.

A single keyword or one structural flag cannot force maximum effort. Operators may use a fixed policy for controlled experiments:

```python
ReasoningPolicy(strategy="fixed", fixed_level="medium", max_escalations=0)
```

## Workflow workload evidence

Each visible reasoning decision may carry this strict audit object:

```json
{
  "workflow_step_index": 3,
  "workflow_step_count": 4,
  "recursion_depth": 3,
  "decomposition_count": 4,
  "accessible_step_count": 3
}
```

The values are validated as non-boolean integers with internally consistent bounds. Generated workflows replace the provisional template size before execution. Conducted template workflows derive recursion and fan-in from the access-list prompts, while recomputed verifier and synthesizer steps reconstruct their workload from the trace itself.

## Verification-driven escalation

When a conducted workflow's verifier rejects the worker result, the runtime may retry exactly once at the next supported level. It then recomputes only the affected verifier and synthesizer steps. It does not restart the whole workflow, exceed the policy cap, or retry when no higher supported level exists.

The retried worker retains the same structural workload that produced the rejected result. The recomputed verifier and synthesizer receive workload evidence reconstructed from their actual trace position and access lists. A stale trace identity that no longer resolves to a configured agent fails closed rather than being silently redirected.

The workflow trace records:

- canonical level;
- decision source and bounded factors;
- role and escalation index;
- validated workflow workload;
- provider profile preset, supported levels, and cap;
- provider-reported reasoning-token count when available.

Hidden reasoning text is not retained.

## Caller ownership and security

Caller-supplied complete reasoning paths always win, including explicit `null`. Custom paths are limited to safe identifier segments and eight levels of nesting. Rules accept JSON scalars and fixed templates only; no expression evaluation occurs. A scalar that conflicts with a configured nested path fails closed.

Provider egress continues to use the repository's DNS-pinned HTTPS transport, original-host TLS verification, redirect rejection, no environment proxy, and KV-backed credential boundary.

## Batch and ablation

Batch JSONL bodies are rewritten immediately before the secured upload. Decisions are selected per `custom_id`, not once for an entire batch. Each batch item is treated as an independent one-step route unless a future reviewed batch topology explicitly declares otherwise.

`run_reasoning_ablation` evaluates fixed effort cells over one prompt set and reports verifier acceptance, total tokens, and reasoning tokens. Task-specific benchmark scorers remain authoritative; verifier acceptance is a workflow measure, not a universal quality claim. Ablation is the evidence path for deciding whether role or topology increments improve a specific evaluation set.

## Verification evidence

The exact branch head is verified by the permanent read-only `Reasoning control quality` workflow. It checks out the pull-request head SHA, runs the complete repository suite, measures every reasoning-control production module at 100% statement and branch coverage, enforces 100% public and nested-function docstrings, compiles all Python sources, and checks the Git diff. The latest successful exact-head evidence before documentation-only follow-up commits recorded 447 passing tests, 1,077 reasoning-control statements, and 418 reasoning-control branches with no missing or partial lines. Every later head must rerun the same gate before its evidence is reusable.

## References — APA 7th

Chen, L., Zaharia, M., & Zou, J. (2023). FrugalGPT: How to use large language models while reducing cost and improving performance. *arXiv*. https://arxiv.org/abs/2305.05176

International Organization for Standardization. (2023a). *ISO/IEC 23894:2023 Information technology—Artificial intelligence—Guidance on risk management*. https://www.iso.org/standard/77304.html

International Organization for Standardization. (2023b). *ISO/IEC 42001:2023 Information technology—Artificial intelligence—Management system*. https://www.iso.org/standard/42001.html

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025). Learning to orchestrate agents in natural language with the Conductor. *arXiv*. https://arxiv.org/abs/2512.04388

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E., Kadous, M. W., & Stoica, I. (2024). RouteLLM: Learning to route LLMs with preference data. *arXiv*. https://arxiv.org/abs/2406.18665

Sakana AI. (2026, June 22). *Sakana Fugu: One model to command them all*. https://sakana.ai/fugu-release/

Snell, C., Lee, J., Xu, K., & Kumar, A. (2024). Scaling LLM test-time compute optimally can be more effective than scaling model parameters. *arXiv*. https://arxiv.org/abs/2408.03314

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025). TRINITY: An evolved LLM coordinator. *arXiv*. https://arxiv.org/abs/2512.04695
