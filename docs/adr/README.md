# Architecture decision records

These ADRs record decisions this product actually claims. Each entry cites the
papers or standards named in [papers/README.md](../papers/README.md),
[architecture.md](../architecture.md), [rest_api_design.md](../rest_api_design.md),
or [library_research.md](../library_research.md).

| ADR | Decision |
| --- | --- |
| [0001](0001-openai-compatible-control-plane.md) | One public `/v1/chat/completions` interface |
| [0002](0002-cost-aware-routing.md) | Cost-aware routing, spend ledger, sync vs batch |
| [0003](0003-trinity-roles-and-conductor-workflows.md) | Thinker / Worker / Verifier (+ synthesizer) and access lists |
| [0004](0004-fugu-latency-quality-split.md) | Route vs conduct as the Fugu / Fugu-Ultra latency-quality split |
