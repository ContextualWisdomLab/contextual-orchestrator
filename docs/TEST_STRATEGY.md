# Test and evidence strategy

**Document state:** `accepted_architecture`

## Test layers

| Layer | Purpose | Representative evidence |
|---|---|---|
| Unit and contract | Domain invariants, parsers, policies, cost arithmetic, naming, API shapes. | `tests/test_*.py` |
| Realistic integration | Local HTTP, SSE, provider failure, SQLite restart, batch lifecycle, admin/API behavior. | provider, server, persistence, batch, and admin tests |
| Property/fuzz | Untrusted request, config, redaction, and orchestration seams. | Hypothesis and bounded Atheris workflows |
| Security | CodeQL, dependency review, pip-audit, SBOM, Trivy, OSV, Scorecard, Semgrep under repository/central ownership. | Exact workflow jobs and security results |
| Research contract | Turn primary-paper concepts into observable route/conduct, roles, and access-list behavior. | `tests/test_paper_contracts.py` |
| Documentation fitness | Keep canonical documents, statuses, diagrams, ADRs, names, and data ownership coherent. | `tests/test_documentation_contract.py` |
| Package/release | Build, install, import isolation, provenance, reproducibility, and release artifact identity. | Required before release; not inferred from unit tests |
| Live-model evaluation | Comparable-budget route/conduct/fallback/effort cells with provenance and uncertainty. | Uses bounded `NVIDIA_NIM_API_KEY`; never required for offline unit tests |

## Coverage contract

- Release evidence requires 100% owned production statement and branch coverage
  and 100% public-docstring coverage.
- Exclusions are allowed only for genuinely unreachable platform or optional
  integration paths with separate executable evidence, never to hide ordinary
  behavior.
- A coverage test that exposes a real 4xx/5xx or state-transition defect becomes
  a product-defect RCA; the test is not weakened to preserve a percentage.
- Every valid defect follows observable RED, minimal root-cause fix, focused
  GREEN, full suite, then exact-head CI/security/fuzz proof.

## Realism requirements

- Provider tests distinguish caller errors, transient errors, retry exhaustion,
  failover, circuit opening, and recovery.
- Streaming tests use valid and malformed SSE framing and final `[DONE]` state.
- Persistence tests create a new process object over the same store and verify
  restart semantics, parameter binding, bounds, and failure behavior.
- Cost tests distinguish reported/estimated tokens, configured/unknown prices,
  attribution, and export degradation.
- Batch tests cover submit, poll, retrieve, partial/malformed results, token
  splitting, and external-backend failure.
- Privacy tests use credential-shaped and PII-bearing fixtures and assert
  audience-appropriate preservation or minimization.
- Live orchestration comparisons use fixed tasks, common call/token budgets,
  versioned scorers, repeated cells, uncertainty, and full assignment evidence.

## Exact-head evidence taxonomy

| Evidence | May prove |
|---|---|
| Contributor-head job that explicitly checks out that SHA | Repository-local behavior at that head. |
| Synthetic merge job | Integration behavior for that exact synthetic tree only. |
| Commit status | The named status producer's claim only. |
| Automated review | Findings/verdict from that identity and head only. |
| Independent human approval | Repository review governance if the reviewer is eligible and head remains current. |
| Protected-main run | Operational behavior of the integrated protected revision. |

Queued, pending, skipped-required, cancelled, absent, failed, predecessor-head,
stale-base, author-only, status-only, rate-limited, and infrastructure-only
states are not success.

## Model-test credential boundary

Offline tests use `mock://` agents and no provider secret. A deliberately live
model evaluation receives `NVIDIA_NIM_API_KEY` only in the step performing the
bounded call, after deterministic admission checks. `COPILOT_GITHUB_TOKEN` is
not a model-development credential. Review-agent credentials remain separate.

## Release acceptance

One unchanged integrated head must have:

1. full functional, realistic integration, fuzz, and security evidence;
2. 100% coverage/docstrings under the repository contract;
3. package build/install/import and compatibility proof;
4. SBOM, provenance, and reproducibility evidence;
5. current reviews, zero valid unresolved findings, and independent approval;
6. migration/rollback and operator acceptance for affected state;
7. protected-main smoke or scheduled evidence before incident closure.

No version bump or publication occurs from an unmerged branch or synthetic
tree.
