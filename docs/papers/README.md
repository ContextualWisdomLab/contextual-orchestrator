# Papers grounding the cost-review + routing hub

These papers ground the design of the LLM **cost review** ledger and the
**sync-vs-batch / upstream** routing. Citations use APA 7th edition with a
DOI. All three are arXiv preprints; Hybrid LLM’s arXiv comment records ICLR
2024 acceptance, which is noted and not invented as a proceedings page.

Orchestration-role papers (Xu et al., 2026; Nielsen et al., 2026; Tang et
al., 2026) are indexed in [docs/REFERENCES.md](../REFERENCES.md) and
[docs/adr/README.md](../adr/README.md). They are versioned preprints. Do not
treat “to appear” comments as a final record, and do not invent Zhang or Li
as their authors.

## Cost optimisation

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large
language models while reducing cost and improving performance*
(arXiv:2305.05176) [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2305.05176

Motivates the **configurable price table + per-request cost accounting** and
cost-optimising model selection: cost varies by orders of magnitude across
providers/models, so a gateway should price each request and route to the
cheapest capable upstream. Distributed under arXiv's non-exclusive license to
distribute (arXiv perpetual, non-exclusive license 1.0). Local copy:
`frugalgpt-cost-2305.05176.pdf` when present.

## Query routing (which upstream / which tier)

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E.,
Kadous, M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with
preference data* (arXiv:2406.18665, Version 4) [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2406.18665

Grounds the **routing decision** layer (`RoutingPolicy` + cost-aware upstream
selection): route strong/weak model choices to hit a cost/quality target.
Local copy: `routellm-routing-2406.18665.pdf` when present.

Ding, D., Mallick, A., Wang, C., Sim, R., Mukherjee, S., Rühle, V.,
Lakshmanan, L. V. S., & Awadallah, A. H. (2024). *Hybrid LLM: Cost-efficient
and quality-aware query routing* (arXiv:2404.14618) [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2404.14618

Grounds **quality-aware cheap-versus-strong routing**. The repository’s
latency-tolerant versus interactive (sync/batch) split is a product inference
from that difficulty-routing idea, not a paper claim that the two decisions
are identical. Hybrid LLM is marked CC BY-NC-ND 4.0 on arXiv; this repository
does not vendor that PDF for commercial redistribution. Local copy, if
present, is for non-commercial scholarly use only:
`hybrid-llm-query-routing-2404.14618.pdf`.

## Batch execution / load balancing

The external `pg-llm-batch` service carries its own grounding papers,
including PagedAttention / vLLM (arXiv:2309.06180) and DeepSpeed-FastGen
(arXiv:2401.08671), which motivate throughput-oriented **batched** inference
and the load-balancing that makes the latency-tolerant batch route
economical. Those sources are referenced by identifier and not re-authored
here so this repository remains one deployable control plane. See
[ADR-0005](../adr/0005-sync-batch-pg-llm-batch.md).

> Citations are provided for scholarly attribution. Redistribution here relies
> on the arXiv non-exclusive distribution license each author granted, except
> where a work is marked more restrictively. No GPL/AGPL-licensed material is
> vendored anywhere in this repository.
