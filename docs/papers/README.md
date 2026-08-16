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

## API-shape honesty (structured outputs)

- OpenAI. (2024). *Create chat completion*. OpenAI API reference.
  https://platform.openai.com/docs/api-reference/chat/create
  Grounds the official `tools[].function` and `response_format.json_schema`
  optional fields (`description`, `parameters`/`schema`, `strict`). Official
  SDKs serialize omitted optionals as JSON `null`; this gateway pops those
  keys before proxy so passthrough matches omit. Copyrighted vendor docs —
  cite + link only; no PDF vendored.

- OpenAI. (2024). *Structured outputs*. OpenAI Platform.
  https://platform.openai.com/docs/guides/structured-outputs
  Grounds fail-closed unknown keys on the `json_schema` object and the
  requirement that `schema` is a JSON Schema object when structured output
  is requested. Copyrighted vendor docs — cite + link only.

- OpenAI. (2024). *Create a model response*. OpenAI API reference.
  https://platform.openai.com/docs/api-reference/responses/create
  Grounds the official Responses `text.format` plane (flat `type`, `name`,
  `schema`, `description`, `strict`) that SDKs send instead of chat
  `response_format`. Copyrighted vendor docs — cite + link only.

- Wright, A., Andrews, H., Hutton, B., & Dennis, G. (2022). *JSON Schema: A
  media type for describing JSON documents* (Internet-Draft
  draft-bhutton-json-schema-01). Internet Engineering Task Force.
  https://datatracker.ietf.org/doc/html/draft-bhutton-json-schema-01
  Latest widely deployed JSON Schema dialect (2020-12) used when this
  gateway type-checks `tool.function.parameters` and
  `response_format.json_schema.schema` as objects without re-implementing
  full schema validation. IETF Internet-Draft; cite + link only.

## Batch execution / load balancing

The external `pg-llm-batch` service carries its own grounding papers, including
PagedAttention / vLLM (2309.06180) and DeepSpeed-FastGen (2401.08671), which
motivate throughput-oriented **batched** inference and the load-balancing that
makes the latency-tolerant batch route economical. Those sources are referenced
but not vendored here so this repository remains one deployable control plane.

> Citations are provided for scholarly attribution. Redistribution here relies
> on the arXiv non-exclusive distribution license each author granted; no
> GPL/AGPL-licensed material is vendored anywhere in this repository.
