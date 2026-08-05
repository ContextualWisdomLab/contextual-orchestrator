# Doctoring record: free-first multi-model fallback

## Decision

The reusable boundary is a pure candidate-planning module rather than a new
HTTP gateway. Noema, OpenCode Agent, and Strix have different security,
review-identity, evidence, timeout, and output-validation contracts. Replacing
those transports would combine privileges and would make one provider client a
single point of failure. The orchestrator therefore supplies a shared policy
contract while each consumer retains its proven transport and credentials.

The policy is deterministic and fail-closed:

- cost tier is explicit trusted metadata, never inferred from a mutable model
  catalogue or a model-name suffix;
- all eligible free candidates precede all eligible paid candidates;
- free candidates fall back to other free candidates before paid escalation;
- visibility, capability, and configured-credential-name filters run before a
  provider call;
- duplicate identities, unknown manifest fields, unsafe identifiers, and an
  empty eligible pool are errors;
- candidate selection never accepts provider output. The consuming workflow's
  existing schema, security, and evidence gates remain authoritative;
- secret values are neither retained nor serialized by the policy module.

This is a deterministic cost-ordering baseline, not a learned quality router.
A future learned router must be benchmarked on the exact review/security task
and must preserve the free-before-paid budget boundary when that policy is
selected.

## Evidence and standards mapping

LLM cascade research supports attempting lower-cost models before escalating,
while also showing that quality estimators and task-specific evaluation matter.
The implementation therefore separates a stable cost policy from acceptance
or quality estimation. HTTP retry semantics remain in each transport adapter;
rate limiting and service unavailability must not be converted into approval.

Provider documentation also makes “free” a runtime commercial property rather
than a permanent model property. GitHub Models includes rate-limited usage and
can optionally enable paid use. OpenRouter free variants have lower limits and
changing availability. NVIDIA describes API Catalog access as a prototyping or
trial path. These facts justify explicit operator-owned `cost_tier` metadata
and immutable policy revisions instead of name-based classification.

## Verification contract

- 100% statement and branch coverage across the five fallback policy modules
  (270 statements and 94 branches).
- 100% docstrings for public fallback policy symbols.
- Property under test: no eligible paid candidate appears before an eligible
  free candidate regardless of numeric priority.
- Stable tie ordering, credential/visibility/capability filtering, duplicate
  rejection, strict manifest validation, empty-pool failure, CLI secret
  non-disclosure, and free-only operation are covered by 32 regression tests.
- The module imports on Python 3.10+ and uses only the standard library.

## APA 7 references

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large language
models while reducing cost and improving performance* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2305.05176

Dekoninck, J., Baader, M., & Vechev, M. (2025). *A unified approach to routing
and cascading for LLMs* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2410.10347

GitHub. (n.d.). *GitHub Models billing*. Retrieved August 5, 2026, from
https://docs.github.com/en/billing/concepts/product-billing/github-models

NVIDIA. (2026). *NVIDIA NIM for vision language models: Overview*.
https://docs.nvidia.com/nim/vision-language-models/2.0.0/introduction.html

Nottingham, M., & Fielding, R. (2012). *Additional HTTP status codes*
(RFC 6585). RFC Editor. https://doi.org/10.17487/RFC6585

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E.,
Kadous, M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with
preference data* [Preprint]. arXiv. https://doi.org/10.48550/arXiv.2406.18665

OpenRouter. (n.d.-a). *Free variant*. Retrieved August 5, 2026, from
https://openrouter.ai/docs/guides/routing/model-variants/free

OpenRouter. (n.d.-b). *Model fallbacks*. Retrieved August 5, 2026, from
https://openrouter.ai/docs/guides/routing/model-fallbacks

Rescorla, E., Nottingham, M., & Bishop, M. (2022). *HTTP semantics* (RFC 9110).
RFC Editor. https://doi.org/10.17487/RFC9110
