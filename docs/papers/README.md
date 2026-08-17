# Papers grounding Contextual Orchestrator

This index uses **APA 7th** bibliographic entries with DOI. Prose under each
entry is the design mapping: what the paper grounds in this repository.

The cost-review and routing papers below are arXiv preprints distributed under
licenses that permit redistribution; local copies sit next to this file when
redistribution is allowed. Trinity, Conductor, and Sakana Fugu are cited here
because the architecture claims them; this lab implements the public pattern,
not the trained models.

## Cost optimisation

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large language models while reducing cost and improving performance*. arXiv. https://doi.org/10.48550/arXiv.2305.05176

Local copy: `frugalgpt-cost-2305.05176.pdf`

Motivates the **configurable price table + per-request cost accounting** and
cost-optimising model selection: cost varies by orders of magnitude across
providers/models, so a gateway should price each request and route to the
cheapest capable upstream. Distributed under arXiv's non-exclusive license to
distribute (arXiv perpetual, non-exclusive license 1.0).

## Query routing (which upstream / which tier)

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E., Kadous, M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with preference data*. arXiv. https://doi.org/10.48550/arXiv.2406.18665

Local copy: `routellm-routing-2406.18665.pdf`

Grounds the **routing decision** layer (`RoutingPolicy` + cost-aware upstream
selection): route strong/weak model choices to hit a cost/quality target.
arXiv preprint; distributed under the arXiv non-exclusive distribution license.

Ding, D., Mallick, A., Wang, C., Sim, R., Mukherjee, S., Rühle, V., Lakshmanan, L. V. S., & Awadallah, A. H. (2024). Hybrid LLM: Cost-efficient and quality-aware query routing. *The Twelfth International Conference on Learning Representations*. https://doi.org/10.48550/arXiv.2404.14618

Local copy: `hybrid-llm-query-routing-2404.14618.pdf`

Grounds **latency-tolerant vs interactive routing** and the sync/batch split:
route easy/bulk queries to the cheaper path, keep hard/interactive queries on
the responsive path. Distributed under the arXiv non-exclusive license /
CC BY as marked on arXiv.

## Batch execution / load balancing

The external `pg-llm-batch` service carries its own grounding papers, which
motivate throughput-oriented **batched** inference and the load-balancing that
makes the latency-tolerant batch route economical. Those sources are referenced
but not vendored here so this repository remains one deployable control plane.

Kwon, W., Li, Z., Zhuang, S., Sheng, Y., Zheng, L., Yu, C. H., Gonzalez, J. E., Zhang, H., & Stoica, I. (2023). Efficient memory management for large language model serving with PagedAttention. arXiv. https://doi.org/10.48550/arXiv.2309.06180

Holmes, C., Tanaka, M., Wyatt, M., Awan, A. A., Rasley, J., Rajbhandari, S., Aminabadi, R. Y., Qin, Q., Bakhtiari, A., Kurilenko, L., & He, Y. (2024). DeepSpeed-FastGen: High-throughput text generation for LLMs via MII and DeepSpeed-Inference. arXiv. https://doi.org/10.48550/arXiv.2401.08671

## Orchestration control plane

These papers ground the public architecture documented in
[architecture.md](../architecture.md) and the ADRs under [adr/](../adr/).

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025). *Trinity: An evolved LLM coordinator*. arXiv. https://doi.org/10.48550/arXiv.2512.04695

Grounds the compact coordinator idea and the **Thinker, Worker, and Verifier**
role contracts that appear on conducted workflow traces. This lab adds a
**synthesizer** step after verification; that role is a product addition, not a
Trinity claim.

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025). *Learning to orchestrate agents in natural language with the Conductor*. arXiv. https://doi.org/10.48550/arXiv.2512.04388

Grounds the workflow representation: each step is a natural-language subtask,
an assigned worker, and an **access list** of prior step outputs. That is the
mechanism that keeps every worker from seeing the full transcript.

Sakana AI. (2026). *Sakana Fugu technical report* (arXiv:2606.21228). arXiv. https://doi.org/10.48550/arXiv.2606.21228

Grounds the **latency versus quality** product split (Fugu-style fast routing
versus Fugu-Ultra-style deeper workflows) and a swappable agent pool. Cite as
Sakana AI (2026), as the paper requests. This repository implements the public
architecture pattern, not trained Sakana models.

> Citations are provided for scholarly attribution. Redistribution here relies
> on the arXiv non-exclusive distribution license each author granted; no
> GPL/AGPL-licensed material is vendored anywhere in this repository.
