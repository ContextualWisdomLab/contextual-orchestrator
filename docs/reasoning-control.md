# Adaptive Reasoning Control

## Purpose

Contextual Orchestrator controls three independent forms of test-time compute:

1. **model routing** — choose one worker or a fallback candidate;
2. **workflow topology** — route directly or construct a Conductor/TRINITY-style multi-step workflow with explicit access lists;
3. **reasoning effort** — request only the model-specific reasoning level justified for each role and task.

The third axis is explicit in this subsystem. It is not inferred from a model name, provider brand, or undocumented default.

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

The default policy starts at the model profile's inexpensive default and raises effort only for bounded evidence:

- thinker and verifier roles receive one baseline increment;
- two or more complexity signals add one increment;
- long context or explicit multi-step structure may add one increment;
- two or more high-impact signals may add one increment;
- the model's declared `maximum_level` is an absolute cap;
- synthesizers do not inherit the analysis role's effort automatically.

A single keyword cannot force maximum effort. Operators may instead use a fixed policy for controlled experiments:

```python
ReasoningPolicy(strategy="fixed", fixed_level="medium", max_escalations=0)
```

## Verification-driven escalation

When a conducted workflow's verifier rejects the worker result, the runtime may retry exactly once at the next supported level. It then recomputes the affected verifier and synthesizer steps. It does not restart the whole workflow, exceed the policy cap, or retry when no higher supported level exists.

The workflow trace records:

- canonical level;
- decision source and bounded factors;
- role and escalation index;
- provider profile preset, supported levels, and cap;
- provider-reported reasoning-token count when available.

Hidden reasoning text is not retained.

## Caller ownership and security

Caller-supplied complete reasoning paths always win, including explicit `null`. Custom paths are limited to safe identifier segments and eight levels of nesting. Rules accept JSON scalars and fixed templates only; no expression evaluation occurs. A scalar that conflicts with a configured nested path fails closed.

Provider egress continues to use the repository's DNS-pinned HTTPS transport, original-host TLS verification, redirect rejection, no environment proxy, and KV-backed credential boundary.

## Batch and ablation

Batch JSONL bodies are rewritten immediately before the secured upload. Decisions are selected per `custom_id`, not once for an entire batch. `run_reasoning_ablation` evaluates fixed effort cells over one prompt set and reports verifier acceptance, total tokens, and reasoning tokens. Task-specific benchmark scorers remain authoritative; verifier acceptance is a workflow measure, not a universal quality claim.

## Verification evidence

Focused tests exercise configuration, provider projection, caller ownership, failover projection, routing, conducted workflows, streaming, passthrough, Batch, policy snapshots, admin profile visibility, durable profile re-save, bounded escalation, and realistic effort ablation. The current local slice verification covers all reasoning-control production modules at 100% statement and branch coverage, with complete module, class, function, method, and nested-function docstrings.

## References — APA 7th

Chen, L., Zaharia, M., & Zou, J. (2023). FrugalGPT: How to use large language models while reducing cost and improving performance. *arXiv*. https://arxiv.org/abs/2305.05176

International Organization for Standardization. (2023a). *ISO/IEC 23894:2023 Information technology—Artificial intelligence—Guidance on risk management*. https://www.iso.org/standard/77304.html

International Organization for Standardization. (2023b). *ISO/IEC 42001:2023 Information technology—Artificial intelligence—Management system*. https://www.iso.org/standard/42001.html

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025). Learning to orchestrate agents in natural language with the Conductor. *arXiv*. https://arxiv.org/abs/2512.04388

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E., Kadous, M. W., & Stoica, I. (2024). RouteLLM: Learning to route LLMs with preference data. *arXiv*. https://arxiv.org/abs/2406.18665

Sakana AI. (2026, June 22). *Sakana Fugu: One model to command them all*. https://sakana.ai/fugu-release/

Snell, C., Lee, J., Xu, K., & Kumar, A. (2024). Scaling LLM test-time compute optimally can be more effective than scaling model parameters. *arXiv*. https://arxiv.org/abs/2408.03314

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025). TRINITY: An evolved LLM coordinator. *arXiv*. https://arxiv.org/abs/2512.04695
