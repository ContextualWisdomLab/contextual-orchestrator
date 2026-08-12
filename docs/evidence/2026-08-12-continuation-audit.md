# Continuation evidence audit — 2026-08-12

**Document state:** `active_pr`; this appendix records collected evidence and
does not make the documentation branch or any other pull request shipped<br>
**Audit date:** 2026-08-12 (Asia/Seoul)<br>
**Protected-main revision observed:**
`6841b71935e0b7cb98fb52bcb4709cc5100c8d87`

This continuation preserves the 2026-08-11 audit as immutable history and
records the next live evidence collection. Every identity below becomes
`historical` as soon as its branch, protected base, workflow attempt, review,
or ruleset changes.

## Evidence identity rules

- `exact_head_success` means the repository workflow evidence explicitly bound
  the relevant checkout to the contributor commit. A green workflow merely
  associated with a commit is not promoted when its job checkout is unknown or
  used a synthetic merge.
- `blocked` means a required authority is missing or non-passing. It does not
  mean the implementation is defective.
- `absent` means no qualifying evidence was observed; a status, reaction,
  author review, dismissed review, or model review is not substituted.
- `historical` evidence remains useful for diagnosis but cannot authorize a
  later head, merge, or release.

## Protected and dependency authority

| Authority | Exact revision | Collected evidence | Decision |
|---|---|---|---|
| contextual-orchestrator protected `main` | `6841b71935e0b7cb98fb52bcb4709cc5100c8d87` | Protected ref remained unchanged during collection. | Shipped authority; release acceptance gaps below remain open. |
| central `.github` protected `main` | `6eb06cdd08c79a06f7b390069d4ffa49e2eb7dba` | Read-only dependency; none of the three current repair heads was integrated. | Central working-branch evidence is not repository authority. |
| central PR #937 | `67d834f510fe044dd9d53cd4f4b9783353e303bd` | Eleven terminal-success workflows, zero unresolved threads, and one OpenCode `APPROVED` model review. | `blocked`: the model review is not a qualifying independent human approval and the PR remains open. |
| central PR #939 | `ac5665148bb113f92e97d2fc49a729bca2f050b5` | Nine terminal-success workflows, zero unresolved threads, and no formal review. | `blocked`: review and protected integration are `absent`. |
| central PR #943 | `601b254f3a8ea4cc593e7089d6baeadd9d8d3ee4` | Nine terminal-success workflows, zero unresolved threads, and no formal review. | `blocked`: review and protected integration are `absent`. |

The central repository was inspected only. No central branch, comment, thread,
review, workflow, or merge state was mutated by this repository loop.

## Open pull-request continuation snapshot

The branch ref and protected base were resolved independently where the PR was
evaluated. Workflow summaries below distinguish explicit contributor-checkout
evidence from head-associated records that were not independently promoted.
Every open PR remained ineligible for immediate protected merge because a
qualifying independent non-author approval was `absent`, the PR was Draft or
stack-blocked, or a current changes-requested review remained effective.

| PR | Contributor head | Collected evidence | Continuation decision |
|---:|---|---|---|
| #63 | `292c87da7bdf3d538710a28f9d94802767ff15f7` | Tests, Security, and Fuzz terminal-success; OpenCode changes requested; author approval only; zero unresolved threads. | `blocked`; downstream dependency update stays Draft and author approval is non-qualifying. |
| #66 | `e7020795c6c5cbaac884dbcee3e0a37c409ab360` | Five terminal-success workflow records; OpenCode changes requested; zero unresolved threads. | `blocked`; reconstruct after the accepted #96/#75 line and regenerate evidence. |
| #69 | `27432737188ea43a0e81ecd279d66cb16c3a00ab` | Tests, Security, and Fuzz terminal-success; OpenCode changes requested; author approval only. | `blocked`; stack order remains #96, #82, then #69. |
| #71 | `1c058275259daad1cbcce96683b0e44137d99a38` | Tests, Security, and Fuzz terminal-success; OpenCode changes requested; author approval only. | `blocked`; dependency work cannot precede #96 integration. |
| #75 | `8bc91f370eefc2a907170303ae27315ec567bf74` | Five terminal-success workflow records; current OpenCode changes requested; zero unresolved threads. | `blocked`; the review request remains non-passing and the stack is stale. |
| #82 | `9341bac45484bdc53b2f8813baac85ee118b176b` | Tests, Security, and Fuzz terminal-success; OpenCode changes requested; zero unresolved threads. | `blocked`; remains Draft behind #96 and must be rebuilt or refreshed after protected integration. |
| #83 | `b5780716c07fc16391e3a525917786ead065dc60` | Tests, Security, and Fuzz terminal-success; OpenCode changes requested; author approval only. | `blocked`; dependency work cannot precede #96 integration. |
| #90 | `26f8d8dc5634f0371fad0801056e9a3450c78bff` | Tests, Security, and Fuzz terminal-success; sixteen COMMENTED reviews; zero currently unresolved threads. | `blocked`; benchmark evidence stays `active_pr` and must be reconciled after #96. |
| #94 | `73ed3a077f88a2f03cf734f1067bee2dcce2467f` | Quality, Tests, Security, and Fuzz terminal-success; three dismissed predecessor reviews; zero unresolved threads. | `blocked`; dismissed review evidence is `historical`, not approval. |
| #96 | `3703d0da9823b8258a0be94f1801aa5d61bfad9f` | Tests, Security, and Fuzz are `exact_head_success`; Security Scan and Semgrep include integration identity; zero unresolved threads. | `blocked`; required automated-review authority, qualifying approval, and protected central acceptance are `absent`. |
| #99 | `b80a30eb4bf9cc0f7c77c58e4d429c9d9fe268db` | Quality, Tests, Security, and Fuzz terminal-success; no formal review; zero unresolved threads. | `blocked`; stacked fallback dependency and qualifying approval are unresolved. |
| #104 | `2b7bf1a8bb8aa361bd1e9ec9038547b3807a730f` | Tests, Security, and Fuzz exact-head records; one CodeRabbit COMMENTED review; zero unresolved threads. | `blocked`; remains Draft behind #105 and #96. |
| #105 | `5543d1b493ceb9dbac485e10347820929d6bee92` | Tests, Security, and Fuzz exact-head records; one predecessor-head CodeRabbit COMMENTED review; zero unresolved threads. | `blocked`; documentation is `active_pr`, not protected-main authority. |
| #107 | `28088b9fc86d975b43637b7758d25e20d61c5786` | Tests, Security, and Fuzz terminal-success; no formal review; zero unresolved threads. | `blocked`; remains a bounded dependency update behind #96. |
| #108 | `1e2600ee442a4894c4ad023f57efa13acfc93a87` | Tests, Security, and Fuzz terminal-success; COMMENTED reviews only; zero unresolved threads. | `blocked`; package metadata remains on the unintegrated security base. |
| #109 | `216177f2c3524a145b24e6b9eafa3e8ca86306f5` | Five terminal-success workflow records and COMMENTED reviews; zero unresolved threads; direct-head coverage acceptance remains non-passing. | `blocked`; workflow association is not substituted for the missing 100% direct-head acceptance and approval. |
| #110 | `5a065bb44b4b7296f68ec992b04ab36b85d90e0e` | No workflow run or formal review was observed on the stacked head; zero unresolved threads. | `blocked`; parent #109 is mutable and required evidence is `absent`. |

## Open issue continuation snapshot

| Issue | Status-qualified continuation |
|---:|---|
| Issue #86 | `active_pr` in #90; dynamic NIM benchmark claims remain unshipped. |
| Issue #95 | `active_pr` in #96; close only after protected integration and acceptance. |
| Issue #102 | `planned`; equivalent-endpoint racing must wait for the accepted security and review boundary. |
| Issue #103 | `planned`; release readiness must fail closed on exact-head checks and qualifying reviews. |

## Operational and release acceptance

The protected-main revision remained unchanged from the preceding acceptance
run: 300 functional tests passed, while owned production coverage was 88% and
public-docstring coverage was 95.4%. Those values are protected-main facts,
not failures attributed to an active branch. They remain below the accepted
100% production statement/branch and public-docstring release contract.

No protected merge, release tag, package publication, SBOM/provenance release
receipt, reproducibility receipt, migration/rollback exercise, certification,
or production SLO acceptance was observed. Successful active-PR checks cannot
fill those release-evidence gaps.

## Next acceptance boundary

Preserve stable heads while the external review/governance path is pending.
The next merge decision must refetch the exact contributor head, exact base
branch tip, protected target tip, required contexts and their checked-out
commits, formal reviews, unresolved threads, rulesets, and release evidence.
After #96 reaches protected `main`, rebuild each dependent PR in dependency
order and regenerate every check and review; no row in this appendix transfers.
