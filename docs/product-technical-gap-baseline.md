# Product & Technical Gap Baseline

Living baseline of buyer-visible product gaps and the technical work that
closes them. Updated every maintenance loop; each row names the evidence
surface a buyer can check. Supersedes scattered gap notes; the historical
register in [`commercial_gap_register.md`](commercial_gap_register.md) is
kept for audit lineage only.

- Last reviewed: 2026-08-25 (loop, post-#843/#844 merges)
- Open PRs at review: 10 (#834, #821, #818, #794, #790, #782, #780, #773,
  #765, #762)
- Open issues at review: 7 (#846, #815, #123, #117, #103, #102, #86)

## 1. How to read this baseline

| Column | Meaning |
| --- | --- |
| Gap ID | Stable identifier; never reused. |
| Buyer impact | What an evaluating buyer would notice. |
| State | `open` / `in-flight` (PR or issue linked) / `closed` (merged evidence). |
| Lever | Expected leverage on saleability (high/med/low). |

## 2. In-flight gaps (linked to open PRs/issues)

| Gap | Buyer impact | State | Evidence |
| --- | --- | --- | --- |
| G-01 Logical model groups + measured routing | One model name across providers; routing decisions auditable via measured ledgers instead of folklore. | in-flight — PR #834 (ADR 0026) | `tests/test_model_group.py`, Admin routing-evidence table |
| G-02 Anti-heuristic evidence ladder | "Why this model?" answers cite declarations, cosine affinity over declared metadata, and measured quality/throughput — no keyword tables to rot. | in-flight — ADR 0027 branch (stacked on #834) | `tests/test_measured_routing_evidence.py` |
| G-03 Token-counting correctness | Billing estimates match provider accounting per strategy; buyers trust cost reports. | in-flight — PR #821 | `tests/test_token_counting*.py` |
| G-04 Session correlation across services | OTel traces join gateway sessions with caller systems for incident forensics. | in-flight — PR #818 (**conflicting**, needs rebase) | `tests/*otel*` |
| G-05 Descriptive DB object naming | Every persisted object name is multi-word snake_case; schema reviews pass enterprise data-governance gates. | in-flight — PR #794 (**conflicting**) | `tests/test_object_name_convention*` |
| G-06 Contextual review gateway bootstrap | Review-time computation allocation (workflow steps, recursion depth, access lists) grounded in Fugu/Conductor/TRINITY-style contracts. | in-flight — PR #790 | `tests/test_review_gateway*` |
| G-07 Workflow evidence bound to authenticated owners | Trace rows cannot be forged cross-principal; audit trails satisfy SOC 2 CC-series evidence requirements. | in-flight — PR #782 (**conflicting**) | ownership-bound evidence tests |
| G-08 Liveness/readiness separation | Load balancers get cheap liveness while auth'd probes verify dependencies; no unauthenticated dependency oracle. | in-flight — PR #780 | probe boundary tests |
| G-09 Gateway-only reasoning contract | Paper-grounded reasoning contract published as the single integration surface; removes drift between docs and code. | in-flight — PR #765 (**conflicting**) | contract tests |
| G-10 Purpose-limited PII protection design doc | Buyers with PII mandates see purpose-binding design (audit-not-mask per ADR 0010) before procurement. | in-flight — PR #762 | `docs/adr/0011-pii-policy` lineage |

## 3. Open issues → planned gaps

| Gap | Buyer impact | State | Plan |
| --- | --- | --- | --- |
| G-11 Orphaned-stack fixes recovery (#846) | Constant-time budget counters, passthrough failover, structured-provider orchestration land despite closed carrier PR #765. | open | Re-land the three fixes as standalone stacked PRs after #834/#765 resolve. |
| G-12 Coverage 92%→100% (#815) | Enterprise procurement asks for statement+branch coverage proof; today's number is below the org bar. | open | Add branch-missing tests module-by-module; wire coverage gate into CI once at 100%. |
| G-13 Sole-collaborator approval deadlock (#123) | Green product PRs stall on last-push approval rules; delivery velocity is buyer-visible. | open | Adjust branch protection via org admin (ruleset change, not code); document runbook in `.github`. |
| G-14 Trace-authority separation (#117) | Orchestration-trace reads must not imply inference authority; least privilege for SOC 2/CSAP reviewers. | open | Split trace-read scope from inference scope in token claims + server checks. |
| G-15 Release readiness fail-closed (#103) | Exact-head review/check evidence must gate release readiness; prevents shipping unverifiable builds. | open | Extend readiness checker to require green exact-head evidence before declaring ready. |
| G-16 Model-group endpoint racing (#102) | Equivalent group endpoints race first-valid-completion; latency without accuracy loss. | open | Design after G-02 lands so raced candidates share the same evidence ladder. |
| G-17 NVIDIA NIM discovery benchmarking (#86) | Buyers need evidence-grade NIM discovery plus cost-quality benchmark numbers, not marketing claims. | open | Extend `model_discovery` with NIM catalog ingest + measured benchmark harness reusing TPS ledger. |

## 4. Closed since last baseline

| Gap | Closed by | Buyer-visible result |
| --- | --- | --- |
| Free orchestration + Responses reasoning streams | PR #843 (merged) | `/v1/responses` streaming orchestration with reasoning summaries. |
| Cache partition isolation fix | PR #844 (merged) | Bearer-less sessions can't collide cache partitions. |
| Embedding/chat capability isolation | PR #768 (merged) | Embedding endpoints never serve general chat. |
| Distributed response cache | PR #772 (merged) | Shared-cache deployments with honest hit accounting. |
| Purpose-limited PII event protection | PR #803 (merged) | Audit-not-mask PII events with purpose binding. |

## 5. Buyer-experienced gaps not yet ticketed (next loop candidates)

1. **Multi-instance ledger persistence** — observation ledgers reset on
   restart by design (ADR 0026); buyers running HA fleets need a
   time-windowed shared table with explicit decay policy before they can
   trust routing evidence across instances.
2. **Reasoning-effort production defaults** — catalog ships but route/
   conduct defaults stay locked until
   `production_default_change_allowed` (issue #568 gate); buyers cannot
   yet realize per-role effort savings.
3. **Rust compute core for measurement arithmetic** — EWMA/Beta updates
   are O(1) and fine in Python today; if batched benchmark ingestion
   (G-17) arrives, port the arithmetic layer to Rust for throughput.
4. **Docs publication** — github.io manual publishing (mkdocs +
   Pages workflow) referenced in loop prompts but not yet shipped;
   buyers evaluate from published docs, not repo browsing.

## 6. Update protocol

Every maintenance loop: re-pull PR/issue lists, move resolved rows to §4,
add newly discovered gaps to §2/§3/§5, and bump the header timestamp.
A gap leaves this file only when its buyer-visible evidence exists in a
merged commit reachable from protected `main`.
