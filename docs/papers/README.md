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

## Batch execution / load balancing

The external `pg-llm-batch` service carries its own grounding papers, including
PagedAttention / vLLM (2309.06180) and DeepSpeed-FastGen (2401.08671), which
motivate throughput-oriented **batched** inference and the load-balancing that
makes the latency-tolerant batch route economical. Those sources are referenced
but not vendored here so this repository remains one deployable control plane.

## Visually rich document retrieval (image placement)

Invoice and email figures are retrieval objects, not decoration. Text-only
chunking drops the picture that sat under ``Please pay invoice 1042``.

- Faysse, M., Sibille, H., Wu, T., Omrani, B., Viaud, G., Hudelot, C., &
  Colombo, P. (2024). *ColPali: Efficient document retrieval with vision
  language models* (arXiv:2407.01449). arXiv.
  https://doi.org/10.48550/arXiv.2407.01449
  `colpali-2407.01449.pdf`
  Grounds **keeping the figure as a first-class retrieval unit** next to its
  source offset. Distributed under the arXiv non-exclusive license.

- Xu, Y., Li, M., Cui, L., Huang, S., Wei, F., & Zhou, M. (2020). LayoutLM:
  Pre-training of text and layout for document image understanding. In
  *Proceedings of the 26th ACM SIGKDD International Conference on Knowledge
  Discovery & Data Mining* (pp. 1192–1200). Association for Computing
  Machinery. https://doi.org/10.1145/3394486.3403172
  Grounds **2-D / sequential position** as a retrieval signal. ACM copyright;
  cited and summarized, not vendored.

- Masinter, L. (1998). *The "data" URL scheme* (RFC 2397). Internet
  Engineering Task Force. https://doi.org/10.17487/RFC2397
  Grounds **inline `data:image/...;base64,` identity** without storing the
  payload on the catalog. IETF RFC; public.

Buyer next action: send the PNG as an OpenAI `image_url` part under the pay
line, then search `orchestration.image_content_catalog.image_placements`
for `invoice 1042`.

> Citations are provided for scholarly attribution. Redistribution here relies
> on the arXiv non-exclusive distribution license each author granted; no
> GPL/AGPL-licensed material is vendored anywhere in this repository.
