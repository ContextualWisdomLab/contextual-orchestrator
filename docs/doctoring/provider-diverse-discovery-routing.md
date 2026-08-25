---
title: "Provider-diverse discovery and cost-honest failover routing"
status: "implemented"
date: "2026-08-21"
scope: "PR #770"
---

# Provider-diverse discovery and cost-honest failover routing

## Decision

PR #770 makes the pricing ledger and direct price ranking fail closed for
invalid or unpriced catalog rows, retains those candidates only as an explicit
unknown-price fallback, and selects a provider-diverse bootstrap pool before ordinary
chat routing. The selector is deterministic eligibility and cost accounting;
it is not a learned answer-quality judge and does not claim to reproduce the
learning systems in the cited work.

## Research-to-code mapping

| Implementation boundary | Evidence-informed reason | Acceptance evidence |
| --- | --- | --- |
| Reject malformed, negative, or non-finite price rows | A cost-aware router must not treat missing or invalid evidence as zero cost. | Discovery and persisted-price tests reject the row before selection. |
| Keep unknown-price candidates only as an explicit fallback | Cost optimization must remain honest when price evidence is incomplete. | Selection tests never rank an unknown price above a valid priced candidate. |
| Prefer distinct providers in the bootstrap pool | A gateway needs an upstream failover set rather than several aliases for one provider. | Provider-diversity tests assert the configured pool spans available providers. |
| Leave quality judgment to evaluation/review policy | Routing signals and answer-quality judgment have different failure modes. | Existing model-judge and fail-closed routing tests remain the quality boundary. |

The routing papers and OA PDFs are already committed in the prerequisite
stack base under `docs/papers/` (`routellm-routing-2406.18665.pdf`,
`hybrid-llm-query-routing-2404.14618.pdf`, and
`frugalgpt-cost-2305.05176.pdf`). This doctoring record makes their relevance
to the exact discovery selector explicit instead of treating inherited files
as incidental documentation.

## APA 7 references

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large
language models while reducing cost and improving performance*. arXiv.
https://arxiv.org/abs/2305.05176

Ding, D., Mallick, A., Wang, C., Sim, R., Mukherjee, S., Rühle, V.,
Lakshmanan, L. V. S., & Awadallah, A. H. (2024). *Hybrid LLM:
Cost-efficient and quality-aware query routing*. International Conference on
Learning Representations. https://arxiv.org/abs/2404.14618

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E.,
Kadous, M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with
preference data*. arXiv. https://arxiv.org/abs/2406.18665
