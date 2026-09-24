# Review gateway free-pool admission evidence

Date: 2026-09-08

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
  `BYTEZ_API_KEY`, `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_API_KEY_SUB`,
  `OPENROUTER_API_KEY`, or `OPENCODE_ZEN_API_KEY`;
- `R` be models whose credential source was actually registered from the
  caller-declared credential array for the current sidecar bootstrap.
  Default bootstrap uses every accepted provider credential name, so a
  CI-seeded `OPENCODE_ZEN_API_KEY` is registered when present.

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

`OPENCODE_ZEN_API_KEY` is the shared KV credential for OpenCode Zen and
OpenCode Go. Those catalogs are independent provider accounts. Honest free
rows from either catalog may enter `P` through that one credential. Missing
or non-zero price evidence still fails `G`, so an unpriced Go listing does
not become free by credential name.

Operational evidence for this widening is ContextualWisdomLab/contextual-orchestrator
PR #1094, Noema job 101747622034: the sidecar returned HTTP 429 on
`google/gemma-4-31b-it:free` with caller `attempts=1` after 184s, while
preflight `ready_count=1` was a NIM vision model. `OPENCODE_ZEN_API_KEY` was
seeded in CI but excluded from `P` and from default `R`, so Zen/Go free
evidence never entered the review pool. OpenCode handshake job 101759907361
then failed waiting for a current-head verdict from the same sidecar.

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

### Request-shaped tool admission (2026-09-25, proposed)

For a review-pool `orchestrator/free` Chat Completions request with tools, the
gateway now uses its existing discovery evidence before sending to a provider.
`tool_call:multi` admits either one or several tools; `tool_call:single` admits
a request that does not require parallel calls. A review candidate without
either positive signal can still serve plain chat, but cannot serve a tool
request. If no free candidate proves the requested tool shape, the gateway
returns `503 request_capability_unavailable` with `capability=tool_call` and
does not send a completion. The same eligible set reaches every conduct role
and final synthesis when the caller requests an orchestrated response. This
addresses the plain-chat-ready/tool-404
counterexample in issue #1106 without a provider-name branch in the consumer.
The actual `/v1/chat/completions` virtual-selector path enters route or conduct,
so its request-scoped tool settings now feed the same free-agent predicate before
planning, cache lookup, or provider send. HTTP regressions cover both modes,
including an empty eligible set.

The signal proves only the probed tool-call contract. It does not prove live
availability, output quality, a provider idempotency guarantee, or completion
of a long review. The catalog admission result remains distinct from an
execution receipt. Calibrated allocation, a released request-scoped contract,
immutable owner release, and the consumer's deletion of its own preflight
remain open acceptance conditions for issue #1106.

For a review-pool request asking for JSON object or JSON schema output, the
serving candidate must also carry positive catalog evidence that its endpoint
accepts `response_format`. An empty eligible set returns typed HTTP 503 before
conduct or provider send; an unproven higher-priority candidate cannot become
the final synthesizer. A catalog parameter declaration does not prove that the
model will satisfy a particular schema. The gateway still validates returned
content, and the caller must treat a failed or incomplete review as failure.
The same admission rule applies to the Responses API's `text.format` request
when it is converted to the chat-shaped provider contract.

### Completion replay boundary

For a review-tagged `orchestrator/free` candidate, a read timeout or connection
reset after the transport began has unknown outcome and stops the request with
`provider_outcome_unknown`; a second provider is not called. HTTP 429, 503,
408, 409, and 425 alone likewise do not prove the completion was never
applied, so these responses terminate this request. Provider-declared cooldown
is still recorded for later requests. Direct local-slot admission failure
before the transport call, or a provider response explicitly identifying
`model_not_found` / request-size rejection,
can advance to another eligible candidate. The test counts transport calls
on each side of the local slot and asserts that an unknown outcome never
causes a second send. This narrows the earlier virtual-selector failover
behavior for the review pool; other virtual selectors retain their prior
contract. The same no-replay rule covers review candidates in conduct role
calls and final structured synthesis, including mixed free pools. A non-review
candidate in a mixed pool retains its existing failover policy. An HTTP 404
without an explicit model refusal is not proof of safe replay. No provider
idempotency agreement has been established here. The HTTP route and conduct
paths stop after a review candidate's 429 without a second send or a storm
wait for that request.
The structured-synthesis path uses the same explicit-refusal boundary: a bare
404 is terminal, while an HTTP error body naming `model_not_found` permits
advancing to another already eligible candidate.
The live chat stream applies it before any content delta as well. A review
candidate's 429/503 or uncertain transport failure stops that request, even
when the gateway has not yet emitted a content byte. The failed attempt is
retained as a workflow trace step, and the chat-stream usage ledger records an
`unavailable` measurement when the provider supplied no usage. A direct local
slot refusal, explicit model refusal, or request-size rejection can still
advance; a streamed response that already emitted content never replays.
This matches the non-idempotent retry boundary in
[RFC 9110 §9.2.2](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.2.2).

### Request route receipt (proposed)

A served review-free passthrough response now carries
`orchestration.route.contract_version=1`, the request-filtered candidate IDs,
the actual failed and served attempts in order, and `terminal_reason=served`.
The gateway overwrites a provider-supplied `route` field. Classified failures
carry the same receipt version and the existing attempt evidence in their
error detail. A selected ID is an admitted candidate, not a live-readiness or
quality finding; an attempt row records only what the gateway observed. The
receipt does not authorize the consumer to build its own fallback list.
The virtual-selector HTTP route/conduct response carries a corresponding
`orchestration.route` with `admitted_agent_ids` and `served_steps`. Those fields
record the request's pre-send eligibility and the returned workflow steps;
they are not a complete wire-attempt log and do not certify answer quality.
The matching HTTP error detail carries the contract version, admitted IDs,
and a terminal reason, including the zero-candidate admission rejection.
Cache hits omit this receipt because their earlier candidate set cannot be
presented as current request admission.

The PR implementing this contract must prove at least the following cases:

- all five required provider credentials may be supplied and registered together;
- a CI-seeded `OPENCODE_ZEN_API_KEY` is registered by default bootstrap and
  honest-free Zen and Go rows enter the review free pool;
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

FrugalGPT and RouteLLM remain cited and linked in `docs/papers/README.md`.
The 2026-09-05 redistribution audit removed the earlier bundled copies because
arXiv's distribution grant did not establish repository redistribution permission.
This does not withdraw their research relevance or change the admission rule. The newer
MMR-Bench source is cited and summarized here rather than vendored because this
change does not need a local copy to execute and this PR does not assert a
redistribution license for that manuscript. NIST publications are linked to
their authoritative DOI/publication records rather than duplicated so the
controlling revision and provenance remain explicit.

- **FrugalGPT (Chen et al., 2023):** the
  [arXiv preprint](https://arxiv.org/abs/2305.05176v1) formulates cost/quality-aware use of
  LLMs and evaluates cascades that can reduce serving cost while preserving or
  improving task performance. It is relevant only after provider authorization
  and capability admission; it does not authorize a provider credential.
- **RouteLLM (Ong et al., 2024):** the
  [arXiv paper](https://arxiv.org/abs/2406.18665) trains routers from preference
  data to choose between candidate LLMs under a quality/cost trade-off. It
  supports learned, evidence-evaluated routing rather than a hand-authored
  provider ordering.
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

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large language
models while reducing cost and improving performance* [Preprint]. arXiv.
https://arxiv.org/abs/2305.05176v1

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
