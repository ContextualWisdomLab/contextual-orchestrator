# ADR 0006: Authoritative chat token accounting

- Status: Accepted
- Date: 2026-08-31
- Decision owners: ContextualWisdomLab
- Series: `docs/adr` only. This is not a planning-ADR number.

## Context

Chat routing, run budgets, cost records, analytics, and streamed responses
historically filled missing provider usage with deterministic word or
character estimates. Those values were reproducible but not authoritative:
chat framing, tools, and multimodal parts are provider protocol inputs rather
than raw text, and their serialization is not reconstructible from a generic
OpenAI-compatible request.

OpenAI's public `tiktoken` table maps exact model identifiers to encodings and
separately exposes prefix mappings. A prefix match can also accept a model
identifier that does not exist, so it is not evidence that an arbitrary model
uses an encoding. The packaged PyO3 extension already provides exact raw-text
tokenization without adding a provider SDK.

OpenAI-compatible Chat Completions responses expose provider usage when the
provider measured it. Streamed responses may omit the terminal usage frame,
including when a stream is interrupted. Missing usage is therefore an
unavailable measurement, not zero and not permission to estimate.

## Decision

1. **Provider usage is authoritative.** Valid non-negative integral prompt
   and completion counts reported by the provider are the usage and billing
   evidence. The orchestrator does not replace or reconcile them with a local
   estimate.
2. **Local tokenization is raw-output-only.** The packaged Rust extension may
   count a textual model output only when the complete model identifier has an
   explicit encoding mapping in this decision. `gpt-4`, `gpt-3.5-turbo`,
   `gpt-3.5`, `gpt-35-turbo`, `davinci-002`, and `babbage-002` use
   `cl100k_base`; `o1`, `o3`, `o4-mini`, `gpt-5`, `gpt-4.1`, and `gpt-4o` use
   `o200k_base`. Prefix matching and provider/model-name inference are
   prohibited.
3. **Chat prompts are not locally reconstructed.** Raw tokenizers do not count
   provider chat framing, tool schemas, or multimodal serialization. When a
   provider does not report prompt usage, prompt usage and any cost that
   depends on it are explicitly unavailable. A PostgreSQL raw-text tokenizer
   follows the same boundary.
4. **Routing is conservative when usage is unavailable.** Explicit batch,
   bulk, and latency declarations continue to decide routing. When only the
   token threshold could select batch and prompt usage is unavailable, the
   request stays synchronous.
5. **Enabled budgets fail closed.** An enabled output-token or cost budget
   cannot be evaluated from an unavailable required count. Dispatch is blocked
   with an explicit unavailable measurement status; unavailable is never
   interpreted as zero remaining spend.
6. **Wire and ledger truth remain distinguishable.** API usage and cost fields
   are nullable and include an explicit measurement status. Storage schemas
   that require numeric token/cost columns may store zero only as a sentinel
   beside `measurement_status=unavailable`; readers must return null rather
   than treating that sentinel as measured free usage.
7. **Streams do not synthesize usage.** A terminal provider usage frame is
   forwarded as measured. Its absence produces `usage=null` with explicit
   unavailable status. The request and SSE event protocol otherwise remains
   unchanged.
8. **Heuristic fields are removed from this subsystem.** Chat accounting does
   not publish `estimated_*` usage or cost aliases. Historical psychometric
   simulation estimates outside chat accounting are unaffected by this
   decision.

## Consequences

### Positive

- Routing, budgets, accounting, analytics, and SSE agree on one evidence
  boundary.
- A missing provider usage frame is visible instead of being converted to a
  plausible-looking charge.
- Known raw textual outputs can still support exact output-token budgets
  through the existing native dependency.

### Negative

- Some providers and model identifiers now expose unavailable usage/cost where
  the previous implementation returned an estimate.
- Token-triggered batch routing stays synchronous without authoritative prompt
  usage.
- Cost budgets block when required usage evidence is absent.

## References

OpenAI. (n.d.). *Tiktoken model mappings*.
https://github.com/openai/tiktoken/blob/main/tiktoken/model.py

OpenAI. (n.d.). *Chat Completions API reference*.
https://platform.openai.com/docs/api-reference/chat/create

PyO3 Project. (n.d.). *Python modules*.
https://pyo3.rs/main/module

ContextualWisdomLab. (2026). *Cost-aware sync-versus-batch routing*
(ADR 0003).
https://github.com/ContextualWisdomLab/contextual-orchestrator/blob/main/docs/adr/0003-cost-aware-sync-batch-routing.md
