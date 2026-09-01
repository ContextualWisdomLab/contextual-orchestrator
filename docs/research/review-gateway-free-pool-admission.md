# Review gateway free-pool admission evidence

Date: 2026-09-01

## Scope

This note records the evidence boundary for the trusted CI review sidecar used by
OpenCode, Noema, and Strix. It does not define a learned router, model-quality
score, hand-authored provider ranking, or fallback heuristic. It defines a
pre-routing authorization and capability-admission guard for
`orchestrator/free`.

The bootstrap may register and globally discover all caller-declared provider
credentials, including `OPENAI_API_KEY`. Global discovery is intentionally
broader than the review serving pool. A globally discovered OpenAI model remains
available to other independently authorized pools, but it cannot become a
review-sidecar `orchestrator/free` candidate.

## Decision rule

Let:

- `G` be the models admitted by the shared
  `model_discovery.general_free_serving_candidates` contract, which requires
  explicit zero-cost evidence and the repository's existing blind-serving
  capability/modality constraints;
- `P` be models whose credential source is one of
  `BYTEZ_API_KEY`, `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_API_KEY_SUB`, or
  `OPENROUTER_API_KEY`;
- `R` be models whose credential source was actually registered from the
  caller-declared credential array for the current sidecar bootstrap.

The review candidate set is exactly `G ∩ P ∩ R`.

This set intersection is an authorization/capability invariant, not a heuristic
score. It has no hand-tuned weight, threshold, provider-name inference, arbitrary
priority, or undocumented tie-break. Missing or ambiguous evidence does not
create a candidate. An unrelated credential already present in the process KV
cannot expand `R` for a new sidecar bootstrap.

`OPENAI_API_KEY` may therefore be present, registered, and globally discoverable,
while every OpenAI-derived row contributes zero elements to `P` and consequently
zero elements to the `orchestrator/free` review candidate set.

## Security and routing rationale

NIST SP 800-207 defines zero-trust access as per-session and least-privilege; an
authorization granted for one resource or context is not automatically authority
for another. NIST SP 800-53 Rev. 5 control AC-6 likewise requires processes to
receive only the accesses necessary for their assigned task. Applying the
caller-declared bootstrap credential array at candidate admission prevents a
credential retained from another context from silently widening the providers
that a review request may reach.

The model-routing literature is relevant only after this authorization and
capability boundary has produced an eligible set. FrugalGPT and RouteLLM support
cost/quality-aware routing across eligible models, but neither is used here to
justify provider access. The existing multimodal-routing evidence recorded in
ADR 0032 supports retaining directed modality evidence; this sidecar therefore
reuses `general_free_serving_candidates` rather than implementing a second,
weaker chat-only eligibility test, and preserves the discovered
`input:<modality>` / `output:<modality>` tags when activating agents.

No new routing heuristic is introduced by this change.

## Executable provenance

The PR implementing this contract must prove at least the following cases:

- all five provider credentials may be supplied and registered together;
- globally discovered OpenAI rows never enter the review free pool;
- an OpenAI credential that predates the current bootstrap cannot enter it;
- an otherwise free, permitted provider credential that predates but was not
  requested by the current bootstrap cannot enter it;
- explicit nonzero price evidence cannot enter it;
- a free chat-capable multimodal-input model excluded by the shared blind-serving
  contract cannot enter it;
- capability and directed-modality tags survive conversion from discovered model
  to active review agent;
- the command-line launcher can supply the same ordered credential array as the
  Python API;
- duplicate or unknown credential-array entries fail closed; and
- secret values are neither logged nor persisted in review evidence.

Hosted exact-head checks and independent review remain the merge authority.

## References

Chen, L., Zaharia, M., & Zou, J. (2024). FrugalGPT: How to use large language
models while reducing cost and improving performance. *Transactions on Machine
Learning Research*. https://arxiv.org/abs/2305.05176

Joint Task Force. (2020). *Security and privacy controls for information systems
and organizations* (NIST Special Publication 800-53, Rev. 5). National Institute
of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-53r5

Ma, H., Lai, G., & Ye, H.-J. (2026). *MMR-Bench: A comprehensive benchmark for
multimodal LLM routing* [Preprint]. arXiv. https://arxiv.org/abs/2601.17814

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E., Kadous,
M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with preference
data* [Preprint]. arXiv. https://arxiv.org/abs/2406.18665

Rose, S., Borchert, O., Mitchell, S., & Connelly, S. (2020). *Zero trust
architecture* (NIST Special Publication 800-207). National Institute of Standards
and Technology. https://doi.org/10.6028/NIST.SP.800-207
