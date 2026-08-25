# ADR 0034: Anti-heuristic routing with measured evidence ledgers

- Status: Proposed; stacked on ADR 0032 (PR #834)
- Date: 2026-08-25
- Figma file ID: `vsZMd8WAv42HDRgcZuNcWk` (no new visual pattern; Admin routing-evidence table gains a token-throughput column)
- Doctoring record: [`docs/doctoring/measured-routing-evidence.md`](../../doctoring/measured-routing-evidence.md)

## Product requirement

Buyers of an LLM gateway ask one question first: "why did this request go to
that model?" Any answer that cites a hand-maintained keyword table is not
auditable, silently rots as vocabulary drifts, and cannot be defended in an
enterprise review. Routing therefore must be explainable only through three
evidence classes: operator declarations (priority, capability tags,
exclusions), semantic similarity computed from operator-declared metadata,
and measured transport behavior observed on this deployment.

## Decision

All task-keyword heuristics are removed from the routing path.
`DOMAIN_HINTS` and `COMPLEX_HINTS` tables are deleted from the orchestrator;
the conduct-hint threshold policy field is retired from route selection.

The replacement ordering ladder is evidence-only:

1. **Eligibility contracts** — operator `provider_exclusions` and the
   general-chat capability gate (`is_general_chat_agent_model_id`) always
   partition candidates before any scoring. These are endpoint-compatibility
   gates, not heuristics.
2. **Static declaration order** — `_static_rank_key` orders by
   `(-role_fit, -priority, has_affinity, -cosine_affinity, agent.id)`.
   Role fit is exact tag membership declared by operators. Cosine affinity
   is computed between the request text embedding and each candidate's
   declared metadata document via the pool's own embedding member
   (Karpukhin et al., 2020 dense-retrieval formulation), cached per text
   hash with an LRU bound so repeated requests cost no additional calls.
3. **Measured intra-group order** — inside one logical model group, members
   are ordered by judged answer quality first (real-time judge feeding the
   quality Beta-Bernoulli ledger) and transport evidence second. Both ledgers
   rank by posterior stability divided by EWMA latency, in expected successful
   responses per second. Token throughput remains separately observable and
   never changes the comparable-unit score.

### Workflow triage without keywords

The auto-mode decision "route directly or run the multi-agent workflow" is
made by a structured triage call, not by keyword counting. The triage model
must reply with exactly `{"workflow_required": bool}`; any other payload
(including extra keys, wrong types, or duplicate keys) fails closed to the
conducted workflow. Verdicts are memoized by content hash. Speed is
explicitly not a design constraint here; correctness is.

### Real-time judging on direct routes

When `policy.realtime_judge` is enabled (default), every direct-route answer
is judged before it is returned. Accepted answers record one success
observation in the quality ledger (with provider token counts when
reported); rejected answers record one failure and fail over to the next
measured candidate within the configured retry budget. The final trace row
carries the verdict so callers can audit every accept/reject decision.
Disabling the flag keeps the legacy verification shape for deployments
without a judge-capable member.

## Alternatives rejected

- Keeping keyword tables behind a feature flag: preserves silent rot and
  unauditable decisions; deletion is cheaper than guarding.
- Learned routers trained offline (RouteLLM-style): require labeled
  preference data this gateway does not have per deployment; measured
  ledgers give per-deployment truth without training data.
- Pure latency routing: ignores whether answers were actually acceptable;
  the quality ledger exists precisely because fast wrong answers are worse
  than slower verified ones.

## Consequences

- Every miss now costs triage + worker + (optional) judge provider calls.
  Cache-hit economics are unaffected: hits replay stored answers with zero
  executions. Tests that assert exact call counts pin single-step routing
  with the judge disabled to keep counts meaningful.
- The mock transport's deterministic embeddings exist only as a test
  fixture (`MOCK_EMBEDDING_DIMENSION = 8`) and never serve production.
- Admin surfaces gain `routing_evidence.quality` alongside the existing
  transport ledger so operators can see both accuracy and throughput.

```mermaid
flowchart LR
  Req[request] --> Tri{triage gate<br/>structured JSON}
  Tri -- workflow_required=true --> Cond[multi-agent conduct]
  Tri -- false / cache hit --> Rank[evidence ladder]
  Rank --> E1[eligibility partition]
  E1 --> E2[declaration order<br/>+ cosine affinity]
  E2 --> E3[measured group order<br/>quality then successful responses/sec]
  E3 --> Serve[serve answer]
  Serve --> Judge{real-time judge}
  Judge -- accepted --> LedgerQ[quality ledger +1 success]
  Judge -- rejected --> Failover[next measured candidate]
```

## Acceptance evidence

- `tests/test_measured_routing_evidence.py`: 29 tests covering exact
  Jacobson EWMA arithmetic, Laplace-prior stability products, cosine
  ordering, strict triage parsing, verdict caching, and judge-driven
  failover within budget.
- `tests/test_chat_model_capability_isolation.py::test_stale_embedding_agent_cannot_win_synthesizer_selection`
  proves the capability gate survives the rewrite.
- Full suite green: 1891 unit/contract tests plus 12 property/fuzz tests.

## References

See the doctoring record for full APA 7 references (Jacobson, 1988;
Laplace via Gelman et al., 2013; Karpukhin et al., 2020; Ong et al., 2024;
Chen et al., 2023; Zheng et al., 2023; Jeon et al., 2021).
