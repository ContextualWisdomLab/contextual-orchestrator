# Architecture decision records

`docs/adr/` is the accepted, citation-backed architecture-decision set for
this control-plane lab. Numbers in this directory are a **single series**.
They do not share numbering with `docs/planning/adrs/`.

## This series (`docs/adr`)

| ID | Title | Status | Grounding |
|---|---|---|---|
| [0001](0001-tool-execution-fallback-policy.md) | Safety-aware tool-execution fallback policy | Accepted | RFC 9110 §9.2.1–9.2.2; NIST SP 800-53 Rev. 5 SI-11, SC-24; NIST SP 800-204 circuit-breaker / fail-fast only |
| [0002](0002-control-plane-orchestrator.md) | Control-plane orchestrator, not a trained coordinator | Accepted | Xu et al. (2025) TRINITY arXiv:2512.04695; Nielsen et al. (2025) Conductor arXiv:2512.04388; Sakana Fugu (2026) live pages |
| [0003](0003-cost-aware-sync-batch-routing.md) | Cost-aware sync-versus-batch routing | Accepted | Chen et al. (2023) FrugalGPT arXiv:2305.05176; Ong et al. (2024) RouteLLM arXiv:2406.18665; Ding et al. (2024) Hybrid LLM arXiv:2404.14618 |
| [0004](0004-msa-leaf-composition.md) | MSA leaf — standalone and callable | Accepted | NIST SP 800-204 independent deployability; planning ADR 0001 fail-closed judge composition |
| [0007](0007-verbose-debug-logging.md) | Verbose/debug logging with a redaction safety net | Accepted | OWASP Logging Cheat Sheet; NIST SP 800-92 log management; Python `logging` HOWTO |

Each record uses Context / Decision / Consequences plus an APA 7th
**References** section. Cite only verified DOI or official URLs. arXiv
records are marked as preprints and are not treated as final.

## Planning records (`docs/planning/adrs`)

`docs/planning/adrs/` holds **planning** ADRs (fail-closed model judgment,
local MLX evaluation, Keyverse auth, PR loop, IRT matrix, polytomous
LLM-judge calibration, SAST, fast-judge, supply-chain, PII audit-not-mask,
provider error boundary, auto embedding selection, and so on).

Those files are planning history. They are not a second source of truth for the same number as this directory. Example: planning ADR 0001 is fail-closed model judgment; this directory's ADR 0001 is the tool-execution fallback policy. When a planning decision is still in force (especially planning ADR 0001), architecture ADRs link to it; they do not duplicate it as a new `docs/adr` number and they do not rewrite its product decision.

## How to add a record

1. Take the next `docs/adr/NNNN` number. Do not reuse a planning number as
   if the two series were one.
2. Keep the decision text honest to the running control plane (heuristic
   routing, injected batch client, fail-closed judge composition).
3. Verify every DOI or official URL before citing. If a URL does not
   resolve, omit the source.
4. Add a row to the table above and a short Unreleased note in
   `CHANGELOG.md`.
