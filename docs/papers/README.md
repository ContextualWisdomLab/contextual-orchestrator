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

> Citations are provided for scholarly attribution. Redistribution here relies
> on the arXiv non-exclusive distribution license each author granted; no
> GPL/AGPL-licensed material is vendored anywhere in this repository.

## Adaptive reasoning and orchestration

These sources govern model and reasoning-policy decisions. They are cited and
linked rather than vendored because this repository does not assume that every
paper permits redistribution of its PDF.

- **Sakana Fugu Technical Report** — Yujin Tang et al. arXiv:2606.21228,
  2026. https://arxiv.org/abs/2606.21228
  Grounds query-adaptive scaffolds over specialized agent teams. It supports
  preserving modality evidence for each assigned specialist; it does not
  justify selecting a model from its name.
- **TRINITY: An Evolved LLM Coordinator** — Jinglue Xu, Qi Sun, Peter
  Schwendeman, Stefan Nielsen, Edoardo Cetin, Yujin Tang. arXiv:2512.04695,
  2025. https://arxiv.org/abs/2512.04695
  Grounds explicit Thinker, Worker, and Verifier role assignment over a
  heterogeneous pool.
- **Learning to Orchestrate Agents in Natural Language with the Conductor** —
  Stefan Nielsen, Edoardo Cetin, Peter Schwendeman, Qi Sun, Jinglue Xu, Yujin
  Tang. arXiv:2512.04388, 2025. https://arxiv.org/abs/2512.04388
  Grounds targeted communication topology and natural-language subtasks. The
  access list controls prior agent outputs, not removal of the source image.

- **Route to Reason: Adaptive Routing for LLM and Reasoning Strategy Selection**
  — Zhihong Pan, Kai Zhang, Yuze Zhao, Yupeng Han. arXiv:2505.19435, 2025.
  https://arxiv.org/abs/2505.19435
  Grounds joint routing of models and reasoning strategies under a budget.
- **Route-and-Reason: Scaling Large Language Model Reasoning with Reinforced
  Model Router** — Chenyang Shao, Xinyang Liu, Yutang Lin, Fengli Xu, Yong Li.
  arXiv:2506.05901, 2025. https://arxiv.org/abs/2506.05901
  Grounds decomposition and allocation across heterogeneous workers.
- **Reasoning on a Budget: A Survey of Adaptive and Controllable Test-Time
  Compute in LLMs** — Mohammad Ali Alomrani et al. arXiv:2507.02076, 2025.
  https://arxiv.org/abs/2507.02076
  Grounds the distinction between fixed effort control and adaptive effort
  allocation.
- **Ares: Adaptive Reasoning Effort Selection for Efficient LLM Agents** —
  Jingbo Yang, Bairu Hou, Wei Wei, Yujia Bao, Shiyu Chang. arXiv:2603.07915,
  2026. https://arxiv.org/abs/2603.07915
  Grounds per-step selection of the minimum sufficient effort with repeated
  verification rather than a fixed effort for every step.
- **Improving Factuality and Reasoning in Language Models through Multiagent
  Debate** — Yilun Du, Shuang Li, Antonio Torralba, Joshua B. Tenenbaum, Igor
  Mordatch. arXiv:2305.14325, 2023. https://arxiv.org/abs/2305.14325
  Grounds independent proposals, multi-round debate, and final synthesis as
  an optional escalation path. It does not justify treating majority vote as
  proof or using debate for every request.
- **Adaptive Test-Time Compute Allocation for Reasoning LLMs via Constrained
  Policy Optimization** — Zhiyuan Zhai, Bingcong Li, Bingnan Xiao, Ming Li,
  Xin Wang. arXiv:2604.14853, 2026. https://arxiv.org/abs/2604.14853
  Grounds budget-constrained, per-input compute allocation instead of a fixed
  reasoning-effort-to-worker-count mapping.

## Transport references (not policy sources)

The provider API documentation is used only to verify request-shape and
capability compatibility. It does not select models, assign reasoning effort,
or establish quality claims; those decisions remain grounded in the papers
above and runtime measurement.

- **OpenAI Responses API reference** — reasoning effort, output limits, and
  structured output format compatibility:
  https://platform.openai.com/docs/api-reference/responses
