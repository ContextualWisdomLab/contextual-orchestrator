# Doctoring: tool-execution retry and fallback

## Standards traceability

The fallback policy treats replay safety as an explicit semantic property, not as a guess derived from an exception string. RFC 9110 defines idempotency by whether repeated identical requests have the same intended effect, permits automatic replay after communication failure for idempotent requests, and cautions against automatically retrying non-idempotent requests unless the implementation can prove idempotency or prove that the original request was not applied.

The implementation generalizes that principle beyond HTTP methods to model tools: timeout and transport failures retry only when a tool adapter explicitly declares replay safety. If a non-idempotent operation may have completed, the orchestrator returns an ambiguous-outcome failure rather than duplicating the side effect.

NIST AI 600-1 frames generative-AI risk management around governance, measurement, pre-deployment testing, incident disclosure, security, resilience, accountability, and transparency. The implementation supports those objectives through deterministic failure categories, bounded actions, fail-closed authorization/policy behavior, regression tests, and secret-free audit evidence.

## Design-to-source map

| Product decision | Source basis | Implementation |
|---|---|---|
| Retry only when replay is known safe | RFC 9110 §9.2.2 | `idempotent` metadata gates `retry_same_agent`. |
| Stop when a non-idempotent result might already have occurred | RFC 9110 §9.2.2 | Timeout/transport uncertainty maps to `ambiguous_outcome`. |
| Test and measure failure behavior | NIST AI 600-1 | Exact Strix regression plus statement/branch coverage. |
| Preserve accountability without disclosing sensitive content | NIST AI 600-1 | Stable reason codes and secret-free audit events. |
| Do not bypass policy through fallback | NIST AI 600-1 | Permission and policy failures always `fail_closed`. |

## References — APA 7th

Autio, C., Schwartz, R., Dunietz, J., Jain, S., Stanley, M., Tabassi, E., Hall, P., & Roberts, K. (2024). *Artificial intelligence risk management framework: Generative artificial intelligence profile* (NIST AI 600-1). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.AI.600-1

Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC 9110; STD 97). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc9110
