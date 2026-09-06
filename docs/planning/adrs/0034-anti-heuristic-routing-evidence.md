# ADR 0034: Anti-heuristic routing with identified evidence

- Status: Proposed; partially implemented; superseding clarification 2026-09-01
- Date: 2026-08-25
- Figma file ID: `vsZMd8WAv42HDRgcZuNcWk` (no new visual pattern)
- Doctoring record: [`docs/doctoring/measured-routing-evidence.md`](../../doctoring/measured-routing-evidence.md)

## Product requirement

Buyers of an LLM gateway need a defensible answer to "why did this request go
to that model?" A hand-maintained keyword table, arbitrary priority, manually
chosen similarity rule, invented score, fixed threshold, or undocumented
fallback cannot answer that question. A routing decision therefore requires an
identified source of authority: an exact caller/operator constraint, an
explicit statistical or psychometric estimand with valid observations, an
authoritative protocol/safety constraint, or a trained/evaluated routing model
whose provenance is executable and reviewable.

## 2026-09-01 superseding clarification

The earlier version of this ADR described
`(-role_fit, -priority, has_affinity, -cosine_affinity, agent.id)` as an
"evidence-only" static ordering and combined a Beta-Bernoulli stability value
with EWMA latency into expected successful responses per second. Those formulas
were deterministic, but determinism is not scientific identification. The ADR
did not establish that operator priority, metadata cosine, agent identifier,
or that composite transport score estimated the routing outcome required by the
product. They therefore cannot be used as substantive routing authority under
the no-heuristics contract.

Dense-retrieval cosine similarity is a valid retrieval operation for a retrieval
estimand; it does not by itself validate transferring model-quality estimates
from one prompt to another or selecting an LLM. Likewise, a posterior or EWMA
is mathematically defined, but a hand-composed function of those quantities is
not automatically a validated model-selection objective.

The live repository still contains historical static-ranking and measured-order
code outside the exact-context psychometric repair. Until those paths are
removed or replaced with independently evaluated routing models, they are a
known production gap rather than accepted evidence.

## Decision

1. **Eligibility is not ranking.** Exact capability compatibility, explicit
   provider exclusion, privacy/ZDR requirements, credential-source admission,
   and explicit caller pins may partition the candidate set. They must not be
   converted into an undocumented preference ordering.
2. **Exact caller selection is authoritative.** An explicit eligible model,
   agent, or channel selection may be honored because it is caller intent, not
   an inferred score. Ambiguous or ineligible requests fail closed.
3. **Psychometric quality evidence is exact-context only until a validated
   generalization model exists.** `PsychometricRoutingEvidence` may use the
   fast-mlsirm MLSRM fit and its predicted probability for the exact canonical
   prompt interaction that generated the fitted item. An unseen prompt receives
   no nearest-neighbor/cosine transfer. Equal fitted probabilities are
   unresolved; agent identifiers and input order cannot break the tie.
4. **No arbitrary evidence cardinality.** The historical `max_contexts`
   argument is compatibility-only and may not evict observations that could
   later affect a routing fit unless a separately governed retention model or
   authoritative storage policy supplies that boundary.
5. **No hand-authored fallback ranking.** When the requested virtual pool has
   multiple eligible candidates and no fitted/evaluated model uniquely selects
   one, the gateway must require explicit selection or fail closed. It may not
   fall through to declaration order, provider name, model name, price without
   an exact request shape, discovery order, or a fixed priority value.
6. **Routing research must be implemented as research, not as vocabulary.**
   RouteLLM learns routing from preference data; FrugalGPT learns cascades;
   Conductor learns orchestration with reinforcement learning; TRINITY optimizes
   an explicit coordinator with evolutionary search; Sakana Fugu is a trained
   orchestration model grounded in Conductor and TRINITY. These works support
   trained/evaluated routing and orchestration. They do not justify replacing
   those learned policies with hand-authored thresholds, static lexicographic
   keys, or similarity shortcuts.
7. **Structured model decisions remain fail-closed.** Route-versus-conduct
   triage and verifier decisions must use their exact structured contracts. A
   malformed or unavailable verdict cannot synthesize a heuristic substitute.
8. **fast-mlsirm remains the statistical quality boundary.** Applicable judged
   response-quality observations feed the fast-mlsirm-backed psychometric path.
   Criterion observations may inform the joint fit, but no application-level
   hand weight or cutoff may be invented around them.

## Current implementation status

The `fix/no-heuristic-batch-routing` lane removes heuristic batch admission,
SHA-derived pseudo-embeddings, representative-token cost guesses, ambiguous
embedding-member price/order selection, nearest-context psychometric transfer,
psychometric identifier tie-breaking, and routing-impacting context-count
eviction. It deliberately fails closed where independent routing evidence is
absent.

The broader `TaskOrchestrator` static declaration ordering and measured-group
ordering remain separate causal-owner work on the same repository. This ADR
must not be read as proof that those historical paths are already compliant.

## Acceptance evidence

Executable regressions must establish at minimum:

- implicit latency/priority/token hints cannot select batch execution;
- local embeddings require an explicit semantic embedding implementation;
- table-driven cost selection requires the exact request shape and leaves equal
  minima unresolved;
- ambiguous embedding pools require explicit identity or a separately evaluated
  router;
- unseen prompt contexts cannot borrow the nearest observed fast-mlsirm score;
- equal fast-mlsirm fitted probabilities do not use an identifier tie-break;
- the retired context-cardinality compatibility argument cannot evict routing
  evidence;
- missing/non-converged fast-mlsirm evidence yields no fabricated ranking.

Hosted exact-head tests, security checks, and independent review remain the
merge authority. Predecessor or base-head evidence does not transfer after a
push.

## Research basis (APA 7)

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large language
models while reducing cost and improving performance* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2305.05176

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025).
*Learning to orchestrate agents in natural language with the Conductor*
[Preprint]. arXiv. https://doi.org/10.48550/arXiv.2512.04388

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E., Kadous,
M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with preference
data* [Preprint; revised 2025]. arXiv.
https://doi.org/10.48550/arXiv.2406.18665

Sakana AI. (2026, April 24). *Sakana Fugu: A multi-agent orchestration system as
a foundation model*. https://sakana.ai/fugu-beta/

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025).
*TRINITY: An evolved LLM coordinator* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2512.04695


## 2026-09-01 NIM benchmark token-evidence amendment

The NIM benchmark MUST NOT reconstruct chat prompt or completion usage from character length. ADR-0006 is authoritative: provider chat framing, tool schemas, and multimodal serialization are provider-owned and cannot be recovered from a raw tokenizer or text-length proxy. Equal-budget evaluation therefore records and enforces only complete provider-reported `prompt_tokens` and `completion_tokens`; missing or malformed usage fails closed. Cost evidence is unavailable rather than estimated. The cheapest-worker baseline likewise uses component-wise dominance over the explicit input/output price vector and leaves equal or crossing vectors unresolved instead of imposing an unstated prompt/completion mixture or model-id tie-break.

NVIDIA. (2026). *NVIDIA NIM for large language models: OpenAI-compatible APIs*. NVIDIA Developer Documentation. The chat-completions response contract exposes provider `usage.prompt_tokens`, `usage.completion_tokens`, and `usage.total_tokens`; these reported counts are the benchmark authority rather than character-length reconstruction.
