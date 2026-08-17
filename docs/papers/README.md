# Papers grounding the cost-review + routing hub

These papers ground the design of the LLM **cost review** ledger and the
**sync-vs-batch / upstream** routing added in `feat/cost-review-and-batch-routing`.
Citations follow the *Publication Manual of the American Psychological
Association* (7th ed.). Redistributable arXiv preprints already vendored here
are listed with their filenames. Trinity and Conductor are cited and linked
only; their PDFs are not copied here.

## Cost optimisation

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large language
models while reducing cost and improving performance* (arXiv:2305.05176).
https://doi.org/10.48550/arXiv.2305.05176
`frugalgpt-cost-2305.05176.pdf`
Motivates the **configurable price table + per-request cost accounting** and
cost-optimising model selection: cost varies by orders of magnitude across
providers/models, so a gateway should price each request and route to the
cheapest capable upstream. Distributed under arXiv's non-exclusive license to
distribute (arXiv perpetual, non-exclusive license 1.0).

## Query routing (which upstream / which tier)

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E.,
Kadous, M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with
preference data* (arXiv:2406.18665). https://doi.org/10.48550/arXiv.2406.18665
`routellm-routing-2406.18665.pdf`
Grounds the **routing decision** layer (`RoutingPolicy` + cost-aware upstream
selection): route strong/weak model choices to hit a cost/quality target.
arXiv preprint; distributed under the arXiv non-exclusive distribution license.

Ding, D., Mallick, A., Wang, C., Sim, R., Mukherjee, S., Rühle, V.,
Lakshmanan, L. V. S., & Awadallah, A. H. (2024). *Hybrid LLM: Cost-efficient
and quality-aware query routing* (arXiv:2404.14618).
https://doi.org/10.48550/arXiv.2404.14618
`hybrid-llm-query-routing-2404.14618.pdf`
Grounds **latency-tolerant vs interactive routing** and the sync/batch split:
route easy/bulk queries to the cheaper path, keep hard/interactive queries on
the responsive path. Distributed under the arXiv non-exclusive license /
CC BY as marked on arXiv.

## Orchestration coordinators (cite + link)

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025).
*Trinity: An evolved LLM coordinator* (arXiv:2512.04695).
https://doi.org/10.48550/arXiv.2512.04695
Grounds thinker / worker / verifier role contracts.

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025).
*Learning to orchestrate agents in natural language with the Conductor*
(arXiv:2512.04388). https://doi.org/10.48550/arXiv.2512.04388
Grounds natural-language workflow steps and access lists.

See also [architecture.md](../architecture.md),
[doctoring/cost_performance_routing.md](../doctoring/cost_performance_routing.md),
and [doctoring/provider-catalog.md](../doctoring/provider-catalog.md).

## Batch execution / load balancing

The external `pg-llm-batch` service carries its own grounding papers, including
PagedAttention / vLLM (2309.06180) and DeepSpeed-FastGen (2401.08671), which
motivate throughput-oriented **batched** inference and the load-balancing that
makes the latency-tolerant batch route economical. Those sources are referenced
but not vendored here so this repository remains one deployable control plane.

> Citations are provided for scholarly attribution. Redistribution here relies
> on the arXiv non-exclusive distribution license each author granted; no
> GPL/AGPL-licensed material is vendored anywhere in this repository.
