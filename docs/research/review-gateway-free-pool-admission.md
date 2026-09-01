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

Every member of `G ∩ P ∩ R` remains a candidate. The review admission boundary
does not truncate the set to a fixed count, impose a provider quota, select a
cheapest subset, or synthesize a priority ordering. Active review agents leave
this boundary with neutral priority. If the downstream router cannot establish a
model choice from its own explicit evidence contract, this admission layer does
not manufacture a fallback preference for it.

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
- adding more than twelve independently eligible models does not evict any
  eligible model through a hidden/default candidate-count cap;
- every admitted sidecar agent leaves admission with neutral priority rather
  than a discovery-order, provider-diversity, or price-derived rank;
- the command-line surface exposes no decision-affecting model-count cap;
- duplicate or unknown credential-array entries fail closed; and
- secret values are neither logged nor persisted in review evidence.

Hosted exact-head checks and independent review remain the merge authority.

## Redistribution boundary and source summaries

No third-party paper PDF is copied into this PR. The repository rule permits a
citation, source link, redistribution explanation, and summary when a local copy
is not appropriate. This change does not need a bundled paper to execute, and the
PR does not assert a redistribution license for the arXiv/TMLR author manuscripts;
the stable source records below are therefore used instead of republishing those
files. NIST publications are linked to their authoritative DOI/publication
records rather than duplicated so the repository keeps the controlling revision
and provenance visible.

- **FrugalGPT (Chen et al., 2024):** formulates cost/quality-aware use of LLMs and
  evaluates cascades that can reduce serving cost while preserving or improving
  task performance. It is relevant only after provider authorization and
  capability admission; it does not authorize a provider credential.
- **RouteLLM (Ong et al., 2024):** trains routers from preference data to choose
  between candidate LLMs under a quality/cost trade-off. It supports learned,
  evidence-evaluated routing rather than a hand-authored provider ordering.
- **MMR-Bench (Ma et al., 2026):** evaluates multimodal routing with controlled
  candidate sets, modality-aware inputs, compute budgets, and cost/accuracy
  frontiers. It supports retaining explicit modality evidence before routing.
- **NIST SP 800-53 Rev. 5 (Joint Task Force, 2020):** AC-6 establishes
  least-privilege controls; the current-bootstrap credential set therefore must
  not be widened by credentials retained from another execution context.
- **NIST SP 800-207 (Rose et al., 2020):** defines zero-trust architecture around
  resource-focused, per-session authentication/authorization without implicit
  trust. That is the security basis for separating global discovery from the
  narrower free-review authorization boundary.

These sources support the admission invariants and the requirement for measured
routing evidence. They do **not** justify an arbitrary model-count cap,
hand-assigned priority, fixed tie-break, or heuristic fallback.

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
