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

## Meaning-unit retrieval chunking

Embedding search is only useful when each vector is a meaning unit a buyer can
ask for (invoice line, sender, HTML block), not a token-budget fragment that is
later averaged away.

- Zhao, J., Ji, Z., Ye, Y., Feng, X., Zhang, X., & Rong, C. (2024). *Meta-chunking: Learning text segmentation and semantic completion via logical perception*. arXiv. https://doi.org/10.48550/arXiv.2410.12788
  `meta-chunking-2410.12788.pdf` when the arXiv PDF is vendored. Grounds
  paragraph-level meta-chunks: sequential sentences inside a paragraph that
  share a logical relation (here, invoice identifier + balance due) stay
  together, while the greeting is a separate unit.
- Qu, R., Tu, R., & Bao, F. (2025). Is semantic chunking worth the computational
  cost? In *Findings of the Association for Computational Linguistics: NAACL
  2025* (pp. 2012–2027). Association for Computational Linguistics.
  https://aclanthology.org/2025.findings-naacl.114/
  Cite + link + summary only (ACL anthology HTML/PDF redistribution is not
  assumed). Similarity-breakpoint chunking did not consistently beat fixed-size
  splits; this gateway therefore uses linguistic meaning units, not embedding
  distance cuts.
- Unicode Consortium. (2024). *Unicode Standard Annex #29: Unicode text
  segmentation*. https://www.unicode.org/reports/tr29/
  Cite + link (Unicode copyright). Sentence cuts in leftover prose follow UAX
  #29 intent (terminator + continuation) without vendoring the Unicode database.
- Lewis, P., Perez, E., Piktus, A., Petroni, F., Karpukhin, V., Goyal, N.,
  Küttler, H., Lewis, M., Yih, W., Rocktäschel, T., Riedel, S., & Kiela, D.
  (2020). Retrieval-augmented generation for knowledge-intensive NLP tasks. In
  *Advances in Neural Information Processing Systems, 33*.
  https://doi.org/10.48550/arXiv.2005.11401
  Grounds why the retrieved *chunk*, not the whole document, is the generation
  context. `rag-2005.11401.pdf` when vendored.
- Masinter, L. (1998). *The "data" URL scheme* (RFC 2397). RFC Editor.
  https://doi.org/10.17487/RFC2397
  Cite + link (IETF). `data:image` units accept optional media-type parameters,
  `;base64`, and URL-safe `-_` so a scanned invoice keeps one `source_offset`
  for a later OCR job.
- Freed, N., & Borenstein, N. (1996). *Multipurpose Internet Mail Extensions
  (MIME) Part One: Format of Internet Message Bodies* (RFC 2045). RFC Editor.
  https://doi.org/10.17487/RFC2045
  Cite + link (IETF). A 76-column fold may end on a short padded last line.
  The image walker must accept that line; leftover base64 must not join the
  invoice unit.

> Citations are provided for scholarly attribution. Redistribution here relies
> on the arXiv non-exclusive distribution license each author granted; no
> GPL/AGPL-licensed material is vendored anywhere in this repository.
