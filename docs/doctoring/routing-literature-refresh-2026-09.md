# Routing literature refresh — 2026-09

## Scope

This record refreshes the research boundary for model routing and test-time orchestration. It does not create a new routing score, threshold, fallback order, or production selector. Its purpose is to distinguish mechanisms that have been trained and evaluated in the literature from mechanisms this repository is currently justified to execute on its own deployment evidence.

## Updated evidence

### Sakana Fugu, TRINITY, and Conductor

Sakana AI now presents Fugu as the production-facing continuation of two learned-coordination lines: TRINITY and the Conductor. TRINITY uses a learned/evolved lightweight coordinator to select workers and roles over multiple turns. The Conductor is trained end-to-end with reinforcement learning to generate natural-language coordination strategies and communication topologies. The 2026 Fugu technical report extends learned coordination into adaptive agent scaffolds over frontier-model pools.

These results support a strict boundary for this repository: the presence of a role name, workflow step, provider, latency observation, token budget, or model identifier does not identify a valid routing function. Reproducing the vocabulary of TRINITY/Conductor/Fugu without the trained coordinator and its evaluation evidence would be a hand-authored substitute, not paper conformance.

### Per-task routing and execution-grounded evaluation

Zhou et al. (2026) evaluate multiple inference-time reasoning paradigms and find that no fixed paradigm dominates. Their Select-then-Solve mechanism uses a learned embedding-based router and held-out evaluation rather than a manually authored task rule. TwinRouterBench (Yang et al., 2026) evaluates routing at agent-step level using execution-verified target tiers and realized task outcomes/costs, emphasizing that realistic routing claims require downstream execution evidence rather than static proxy preferences.

These results do not authorize this repository to copy a particular embedding threshold, score, cost weight, or benchmark tier. They strengthen the requirement that any learned selector be trained and validated for a declared target estimand and deployment domain, and that an unavailable/invalid selector fail closed instead of being replaced by an operator-invented ranking.

## Current repository decision

Until a learned router or other explicit decision model has deployment-valid training/evaluation evidence, the production compatibility boundary remains the no-heuristics behavior implemented in the active repair lineage:

- endpoint/capability/privacy/cost-evidence predicates may determine eligibility when they are exact contracts rather than preference scores;
- explicit caller model/agent selection is allowed only when it uniquely identifies an eligible configured target;
- multiple eligible models require complete exact-context `fast-mlsirm` psychometric evidence or another independently validated model-selection mechanism;
- missing, tied, incomplete, non-converged, or out-of-domain routing evidence remains unresolved and fails closed;
- transport observations, provider names, catalog/list order, token budgets, static priorities, arbitrary cardinality caps, cosine-nearest transfer, and fixed workflow preferences do not become routing authority merely because they are observable;
- Fugu/TRINITY/Conductor concepts may inform trace/audit structure, but their trained coordination results cannot be reproduced by hand-authored workflow or routing rules.

This conservative contract is intentionally narrower than the cited learned systems. It is not a claim that fail-closed exact-context psychometric selection is a universally optimal router; it is the absence-of-validated-model behavior required to avoid inventing one.

## Acceptance evidence required before a learned replacement

A future learned routing mechanism must identify, at minimum, its target decision/estimand, candidate pool and eligibility boundary, training and validation populations, held-out or prospective evaluation design, quality and cost outcome definitions, uncertainty/calibration treatment, out-of-domain behavior, tie/missing-evidence semantics, reproducible model/version provenance, and execution-grounded regression evidence. Thresholds or weights must be estimated/identified by that declared mechanism or externally governed standard; they cannot be hand-tuned into production after evaluation.

## References (APA 7)

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025). *Learning to orchestrate agents in natural language with the Conductor* [Preprint]. arXiv. https://arxiv.org/abs/2512.04388

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025). *TRINITY: An evolved LLM coordinator* [Preprint]. arXiv. https://doi.org/10.48550/arXiv.2512.04695

Tang, Y., Cetin, E., Xu, J., Sun, Q., Nielsen, S., Richard, V., Goda, H., Tymchenko, I., et al. (2026). *Sakana Fugu technical report* [Preprint]. arXiv:2606.21228.

Zhou, H., Tan, Z., Zhang, Z., Fan, Y., Lin, Y., Kang, L., Song, X., Li, R., Huang, S., Yu, A., Fan, Y., Chen, Y., Xu, K., Liu, X., Qin, Y., Torr, P., Zhang, C., & Yin, Z. (2026). *Select-then-Solve: Paradigm routing as inference-time optimization for LLM agents* [Preprint]. arXiv:2604.06753.

Yang, P., Chen, W., Yang, T., Feng, P., Xing, J., Guo, W., Yao, Y., Han, Y., Li, H., Wang, X., Wang, Z., Xiao, J., Yang, A., Tian, L., Ai, L., Yang, E., & Shi, T. (2026). *TwinRouterBench: Fast static and live dynamic evaluation for realistic agentic LLM routing* [Preprint]. arXiv:2605.18859.
