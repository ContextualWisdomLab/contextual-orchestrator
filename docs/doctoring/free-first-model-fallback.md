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
- visibility, capability, and declared-credential-name filters run before a
  provider call;
- duplicate identities, unknown manifest fields, unsafe identifiers, and an
  empty eligible pool are errors;
- candidate selection never accepts provider output. The consuming workflow's
  existing schema, security, and evidence gates remain authoritative;
- secret values are never read, retained, or serialized by the policy module.

This is a deterministic cost-ordering baseline, not a learned quality router.
A future learned router must be benchmarked on the exact review/security task
and must preserve the free-before-paid budget boundary when that policy is
selected.

## Credential-availability trust boundary

The policy CLI previously accepted credential names and inspected the matching
environment values. That behavior contradicted the provider- and
transport-neutral boundary because it made the planning process a secret-value
consumer and coupled availability to one process environment.

The corrected contract is explicit:

1. the trusted composition root already owns the provider transport and secret
   store;
2. it determines which credential identities are available;
3. it passes only validated names through repeated `--available-credential`
   arguments or through `FallbackContext.available_credentials`;
4. the planning module never looks up, prints, hashes, caches, or serializes the
   corresponding values;
5. the downstream transport still resolves the actual value and fails closed
   if the composition root declared availability incorrectly.

A credential name is therefore trusted control data, not proof that a secret
is usable. This separation reduces the privilege and data surface of the
policy-only process while preserving the existing transport's authentication,
output-validation, and reviewer-identity controls. NIST SP 800-204D's CI/CD
software-supply-chain strategies and NIST SP 800-218A's AI-specific secure
development profile support keeping pipeline responsibilities, artifacts, and
security evidence explicit and independently verifiable.

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

Exact head `e3b814f1027fe504328cb27efc34668ad14baa12` was checked out by the
permanent read-only `Model fallback policy quality` workflow. Run
`30989460499` established:

- 33 focused behavior regressions passed;
- all five fallback policy modules reached 270/270 statements and 94/94
  branches, or 100% statement and branch coverage;
- public-symbol docstrings reached 100%;
- `compileall` and `git diff --check` passed;
- the CLI accepts declarative available names, rejects the removed
  `--credential-env` selector, treats undeclared names as unavailable, and
  proves provider credential values are not inspected;
- no eligible paid candidate appears before an eligible free candidate,
  regardless of numeric priority;
- stable tie ordering, visibility/capability filtering, duplicate rejection,
  strict manifest validation, empty-pool failure, and free-only operation remain
  covered.

The module imports on Python 3.10+ and uses only the standard library. Full
repository and integrated-stack checks remain mandatory after the security
prerequisite merges.

## APA 7 references

Booth, H., Souppaya, M., Vassilev, A., Ogata, M., Stanley, M., & Scarfone, K.
(2024). *Secure software development practices for generative AI and dual-use
foundation models: An SSDF community profile* (NIST Special Publication
800-218A). National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-218A

Chandramouli, R., Kautz, F., & Torres-Arias, S. (2024). *Strategies for the
integration of software supply chain security in DevSecOps CI/CD pipelines*
(NIST Special Publication 800-204D). National Institute of Standards and
Technology. https://doi.org/10.6028/NIST.SP.800-204D

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
