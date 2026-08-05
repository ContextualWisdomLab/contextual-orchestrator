# Adaptive Reasoning Control — Evidence Doctoring

## Claim boundary

The implementation claims provider-neutral control only for settings explicitly declared by a model profile. It does not claim that every model supports every canonical level, that higher effort always improves every task, or that verifier acceptance is equivalent to human-judged quality.

## Source-to-design trace

| Design decision | Source support | Implementation consequence |
|---|---|---|
| Separate direct routing from deeper orchestration | Fugu; Conductor; TRINITY | Existing route/conduct split remains independent from effort control. |
| Use roles and access-constrained workflows | Conductor; TRINITY | Thinker, worker, verifier, and synthesizer receive role-specific decisions; access lists remain authoritative. |
| Allocate test-time compute by task | Snell et al. | Adaptive policy starts cheaply and raises effort only for bounded complexity or risk evidence. |
| Route inexpensive models before costly models | FrugalGPT; RouteLLM | Reasoning control composes with the versioned free-first fallback policy rather than replacing it. |
| Support model-dependent effort values | Official OpenAI, NVIDIA NIM, and Gemini documentation | Capabilities and payload mappings are explicit profiles; model names are not parsed heuristically. |
| Observe reasoning-token consumption | Official provider usage contracts | Trace evidence records counts, never private intermediate reasoning text. |
| Manage AI risk and governance evidence | ISO/IEC 23894:2023; ISO/IEC 42001:2023 | Decisions, caps, overrides, escalation, and ablations are machine-readable and auditable. |

## Activation and ownership boundary

Adaptive reasoning is an optional runtime extension. Package import must remain free of reasoning-related class mutation so standalone consumers, central `.github` automation, naruon, and other CWL services can inspect or import the library without import-order-dependent behavior.

The built-in executable explicitly activates the extension before it loads agent configuration. Programmatic consumers call `enable_reasoning_control()` before loading agents or constructing an orchestrator. The operation is idempotent and retains a lower-level typed installer for isolated alternative runtimes and deterministic test fakes.

This boundary is an architectural control rather than an empirical research claim. It prevents optional capability activation from becoming an implicit global side effect, makes ownership observable at the application composition root, and permits a later replacement of hooks with composition or subclasses without changing the public activation contract.

## Provider documentation reviewed

- OpenAI API model and reasoning guidance: model-dependent effort sets and usage-level reasoning token details.
- NVIDIA NIM for LLMs: `reasoning_effort`, `enable_thinking`, `low_effort`, hard reasoning budgets, and model-dependent parallel reasoning.
- Google Gemini OpenAI compatibility: explicit mapping between OpenAI reasoning effort and Gemini thinking levels or budgets.

These provider contracts evolve. Profiles are therefore operator-controlled data, not hard-coded model inventories. Unsupported or expired mappings must be removed or updated through reviewed configuration.

## APA 7th references

Chen, L., Zaharia, M., & Zou, J. (2023). FrugalGPT: How to use large language models while reducing cost and improving performance. *arXiv*. https://arxiv.org/abs/2305.05176

International Organization for Standardization. (2023a). *ISO/IEC 23894:2023 Information technology—Artificial intelligence—Guidance on risk management*. https://www.iso.org/standard/77304.html

International Organization for Standardization. (2023b). *ISO/IEC 42001:2023 Information technology—Artificial intelligence—Management system*. https://www.iso.org/standard/42001.html

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025). Learning to orchestrate agents in natural language with the Conductor. *arXiv*. https://arxiv.org/abs/2512.04388

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E., Kadous, M. W., & Stoica, I. (2024). RouteLLM: Learning to route LLMs with preference data. *arXiv*. https://arxiv.org/abs/2406.18665

Sakana AI. (2026, June 22). *Sakana Fugu: One model to command them all*. https://sakana.ai/fugu-release/

Snell, C., Lee, J., Xu, K., & Kumar, A. (2024). Scaling LLM test-time compute optimally can be more effective than scaling model parameters. *arXiv*. https://arxiv.org/abs/2408.03314

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025). TRINITY: An evolved LLM coordinator. *arXiv*. https://arxiv.org/abs/2512.04695
