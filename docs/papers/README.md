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

## Nucleus sampling on streamed route

Streamed `/v1/chat/completions` must apply the same `top_p` /
`presence_penalty` / `frequency_penalty` as the JSON `chat()` path.
Otherwise a buyer who sends `stream=true` silently changes the sampling
policy.

- Holtzman, A., Buys, J., Du, L., Forbes, M., & Choi, Y. (2020). The
  curious case of neural text degeneration. *International Conference on
  Learning Representations*. https://arxiv.org/abs/1904.09751
  Grounds `top_p` (nucleus) as the mass-truncated sampling control the
  gateway must honor on both JSON and SSE route completions. arXiv
  preprint (1904.09751) under the arXiv non-exclusive distribution
  license; PDF not vendored in this slice.

## Tool calling / streamed function calls

Offline `mock://` must emit the same OpenAI `tool_calls` JSON and
`delta.tool_calls` SSE shape as a live provider so SDK clients can be
exercised without a billed hop. The papers below ground *why* a gateway
exposes tools as first-class actions rather than free text.

- Schick, T., Dwivedi-Yu, J., Dessì, R., Raileanu, R., Lomeli, M.,
  Hambro, E., Zettlemoyer, L., Cancedda, N., & Scialom, T. (2023).
  Toolformer: Language models can teach themselves to use tools.
  *Advances in Neural Information Processing Systems, 36*.
  https://arxiv.org/abs/2302.04761
  Grounds treating API calls as structured tool invocations (name +
  arguments) instead of natural-language side effects. arXiv preprint
  under the arXiv non-exclusive distribution license; PDF not vendored
  here because the gateway cites the contract, not the training method.
- Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K., &
  Cao, Y. (2023). ReAct: Synergizing reasoning and acting in language
  models. *International Conference on Learning Representations*.
  https://arxiv.org/abs/2210.03629
  Grounds interleaving a thought/action/observation loop: the gateway
  must surface `finish_reason=tool_calls` so the buyer can run the tool
  and send the observation back, then synthesize a final `content` /
  `stop` answer from that bound `role=tool` result. arXiv preprint;
  cite + link only.
- OpenAI. (2024). *Function calling*. OpenAI API documentation.
  https://platform.openai.com/docs/guides/function-calling
  Normative stream shape: `delta.tool_calls` then
  `finish_reason=tool_calls`. Redistribution of the vendor docs is not
  permitted; the citation is the contract source.
- CEN. (2017). *Electronic invoicing — Part 1: Semantic data model of
  the core elements of an electronic invoice* (EN 16931-1:2017).
  European Committee for Standardization.
  https://standards.cencenelec.eu/
  Grounds treating the invoice identifier (BT-1) as the bind target
  regardless of clerk phrasing (`invoice no.`, `nr`, `inv#`). CEN texts
  are not OA; cite + link only.

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
