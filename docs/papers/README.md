# Papers grounding the cost-review + routing hub

These papers ground the design of the LLM **cost review** ledger and the
**sync-vs-batch / upstream** routing added in `feat/cost-review-and-batch-routing`.
All three are arXiv preprints distributed under licenses that permit
redistribution; each is cited below with its arXiv identifier.

## Cost optimisation

- **FrugalGPT: How to Use Large Language Models While Reducing Cost and
  Improving Performance** — Lingjiao Chen, Matei Zaharia, James Zou. arXiv:2305.05176, 2023.
  `frugalgpt-cost-2305.05176.pdf`
  Motivates the **configurable price table + per-request cost accounting** and
  cost-optimising model selection: cost varies by orders of magnitude across
  providers/models, so a gateway should price each request and route to the
  cheapest capable upstream. Distributed under arXiv's non-exclusive license to
  distribute (arXiv perpetual, non-exclusive license 1.0).

## Query routing (which upstream / which tier)

- **RouteLLM: Learning to Route LLMs with Preference Data** — Isaac Ong, Amjad
  Almahairi, Vincent Wu, Wei-Lin Chiang, Tianhao Wu, Joseph E. Gonzalez, M.
  Waleed Kadous, Ion Stoica. arXiv:2406.18665, 2024.
  `routellm-routing-2406.18665.pdf`
  Grounds the **routing decision** layer (`RoutingPolicy` + cost-aware upstream
  selection): route strong/weak model choices to hit a cost/quality target.
  arXiv preprint; distributed under the arXiv non-exclusive distribution license.

- **Hybrid LLM: Cost-Efficient and Quality-Aware Query Routing** — Dujian Ding,
  Ankur Mallick, Chi Wang, Robert Sim, Subhabrata Mukherjee, Victor Rühle,
  Laks V. S. Lakshmanan, Ahmed Hassan Awadallah. arXiv:2404.14618 (ICLR 2024).
  `hybrid-llm-query-routing-2404.14618.pdf`
  Grounds **latency-tolerant vs interactive routing** and the sync/batch split:
  route easy/bulk queries to the cheaper path, keep hard/interactive queries on
  the responsive path. Distributed under the arXiv non-exclusive license /
  CC BY as marked on arXiv.

## API contract honesty (mode and trusted-trace on tools passthrough)

Buyers who send `tools` plus `mode=conduct` asked for a Conductor workflow
(Nielsen et al., 2025) with TRINITY-style role traces (Xu et al., 2025). The
tools early-return is a single-worker proxy with no access-list plane. Those
knobs, plus invalid `mode` and non-boolean `include_orchestration_trace`,
must fail closed before `proxy_completion`.

- Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y.
  (2025). *Learning to orchestrate agents in natural language with the
  Conductor*. arXiv. https://doi.org/10.48550/arXiv.2512.04388
  Grounds workflow steps and access-list visibility. Cite + link; PDF is
  arXiv-redistributable but already referenced from `docs/architecture.md`.
- Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y.
  (2025). *Trinity: An evolved LLM coordinator*. arXiv.
  https://doi.org/10.48550/arXiv.2512.04695
  Grounds Thinker / Worker / Verifier traces that `include_orchestration_trace`
  exposes on the orchestration path only.

## API contract honesty (tool schema omit)

Gateway buyers send official OpenAI SDK payloads. Optional
`tools[].function.description`, `parameters`, and `strict` are often serialized
as JSON `null` rather than omitted. Those nulls must be popped before the
provider hop; accepting them in place is not omit-equivalent and several
OpenAI-compatible backends reject a null JSON Schema object.

- OpenAI. (2024). *Create chat completion*. OpenAI API reference.
  https://platform.openai.com/docs/api-reference/chat/create
  Grounds the optional function-tool fields and the omit-vs-present contract
  the gateway must preserve on passthrough.
- Bray, T. (Ed.). (2017). *The JavaScript Object Notation (JSON) data
  interchange format* (RFC 8259). Internet Engineering Task Force.
  https://doi.org/10.17487/RFC8259
  Distinguishes a present `null` member from an omitted member. Redistribution
  of the RFC text is not required here; the citation is the normative source.

## Batch execution / load balancing

The external `pg-llm-batch` service carries its own grounding papers, including
PagedAttention / vLLM (2309.06180) and DeepSpeed-FastGen (2401.08671), which
motivate throughput-oriented **batched** inference and the load-balancing that
makes the latency-tolerant batch route economical. Those sources are referenced
but not vendored here so this repository remains one deployable control plane.

> Citations are provided for scholarly attribution. Redistribution here relies
> on the arXiv non-exclusive distribution license each author granted; no
> GPL/AGPL-licensed material is vendored anywhere in this repository.
