# Immutable request partition replay

Status: Proposed. This is a causal continuation of CO #1117, based on `86cb73a8d73f3152f253fc6e4433e3f73511d538`, not a live gateway rollout. The original production blob was independently reconstructed and verified as `9852636cced1c7b961df83b023d5e96cdbf2a4d8`. Both original test files match their published blobs and are unchanged.

## Structure and failure path

The outer request path is `PartitionExecutor.run -> _pack -> _perform -> CheckpointStore.claim -> invoke -> complete`. The injected invocation port must retain the existing gateway's routing, privacy and authorization policy. Neither this executor nor its SQLite state owns Noema's agent runtime or Fugu's learned worker/topology choices.

Before this fix, request identity covered tenant, request, source, policy, backend, task, limits and evidence. It did not bind the actual partition layout. `_pack` ran again on every resume. If the accounting callback changed while the caller supplied the same identity, its grouping could change. Because an operation ID is based on the group, previously completed evidence was resubmitted in a new group with a different operation ID. The same problem affected reduction groups. Even when grouping stayed unchanged, an existing reservation could be reused after the measured input count changed.

The initial regression suite reproduced five failures: map packing in both directions, reducer regrouping and two changes in same-packet accounting. Three preservation cases already passed. These are deterministic protocol failures, not measured LLM quality or a provider-tokenizer benchmark.

## Minimal correction

The trusted store now binds an ordered manifest for each map/reduction layout transactionally before any call from that layout is dispatched. It binds operation IDs, prompt digests, full unit lineage and output allowance. A different layout under the same partition identity raises `checkpoint_partition_changed`. A reused operation whose reservation no longer matches the effective token count raises `checkpoint_accounting_changed`.

Completed responses remain reusable when the identity, layout and accounting are unchanged. Uncertain provider outcomes still raise `reconciliation_required`; no automatic replay or guessed success is introduced. Existing call/token reservations are not reset. Records produced by the old prototype without a map manifest require reconciliation (`checkpoint_manifest_required`), rather than retrospective attestation. A deliberately new backend revision produces a new plan and therefore requires caller-side authorization; it is not a free retry of the old request.

## Fresh test evidence

Runtime: CPython 3.13.5, pytest 9.0.2, SQLite standard library. No live model calls or paid resources were used.

- Exact predecessor plus the two unchanged test files: **53 passed**.
- Initial new cases against the unchanged predecessor: **5 failed, 3 passed**.
- Corrected kernel plus all original tests and 13 new cases: **66 passed**.
- Scoped kernel coverage: **185/185 statements and 60/60 branches**; no exclusions were added.

```sh
python3 -m coverage run --branch --source=contextual_orchestrator/request_partitioning \
  -m pytest -q -W error tests/test_request_partitioning.py \
  tests/test_partition_cancellation_fence.py tests/test_partition_checkpoint_layout.py
python3 -m coverage report -m
```

The new tests exercise file-backed restart, 90 source-unit conservation, reducer drift, unchanged-layout accounting drift, concurrent manifest admission, missing legacy manifests, storage rollback, cancellation, unchanged budget exhaustion and uncertain provider outcomes. The 90-unit fixture is not a claim that LineageWeave #983 was semantically reviewed. Its live source snapshot was `60d2f7800dc93b090a9f2659c9a195f8cdcf4320` over `83eba56149eb802cd63642c507c324c9976ec78e` when inspected.

Verified source blob: `495e03431d2c4473bf237c5eff20aebb0fd7b691`. Verified new test blob: `5686fb2129b59d443bd870ff10dfc50a3a3313f5`. Hosted CI, independent approval, the whole repository, the installed package and live provider behavior are not covered by these local leaf tests.

## Separate reviewer integration finding

Central `.github` #2068 at `b4dfcc994d1a147b2904406de8b6d0f776e26951` appends a memory protocol at the real prompt renderer. Its checked-in `opencode.jsonc` blob `8946175a135d736116bd2b719bbffdecd81f23b6` has an empty MCP map and denies edit, bash and task operations to the reviewer profiles. The runner blob `80f57d1d43cfa176af8936296a7b4ae532a5131e` starts a one-shot review, keeps head/tail evidence on overflow and treats a context error as a fatal candidate failure. These checked-in paths do not demonstrate executable agent memory or fresh-session continuation. Runtime overrides have not been comprehensively inventoried.

Do not solve this by enabling arbitrary edit/bash/task permissions or replacing `orchestrator/free`. The trusted host needs to own inventory admission, checkpoint writes, bounded per-packet prompts, fresh-session invocation, finding-reference conservation and final completeness validation. Noema and Strix require adapters preserving their distinct tool/result and streaming contracts. A prompt instruction does not reset context or create a tool.

## Research interpretation

Fugu's basic variant uses learned worker selection; Fugu-Ultra uses learned workflows and access lists. The Fugu-Ultra report describes agent-specific tool history within a workflow and shared persistent memory across workflows. Its five-step setting is part of its training setup, not a universal limit on a root request, environment interaction count or the new partition layer. This outer capacity and replay contract complements those mechanisms; it is not a reproduction of their learned policy or evaluation results.

RLM's external input and recursive bounded access, and structured-note/subagent context engineering, motivate preserving source/finding references outside a growing prompt. They do not supply CWL defect-detection accuracy or authorize synthetic RMSE promotion. CO #1119 separately retires that diagnostic permission path while preserving parent #1000.

## Open acceptance and ownership

The Python kernel remains a Proposed compatibility prototype. Rust-owned runtime, actual effective-payload accounting, nested provider-call reservation, HTTP/gateway admission and continuation, secure durable storage, host-driven OpenCode/Noema/Strix sessions, immutable owner release and exact-head consumer replay remain open. Root budgets here cover outer adapter invocations only. The current container has no Rust toolchain and cannot resolve external download hosts; no Rust build is claimed. Source/AST inspection was used, not an executed CodeGraph/Graphify index.

Review quality must be measured on held-out unchanged PR snapshots using baseline, agent-memory only, outer-partitioning only and combined conditions. Keep source-local and cross-file defect detection, false positives, incomplete reviews and actual reported usage separate. Do not equate inventory completeness with semantic correctness or approval.

## References

Sakana AI. (2026). *Sakana Fugu technical report* (arXiv:2606.21228, Version 2). https://arxiv.org/html/2606.21228v2

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2026). *Learning to orchestrate agents in natural language with the Conductor* (arXiv:2512.04388, Version 5; original preprint 2025). https://arxiv.org/html/2512.04388v5

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2026). *Trinity: An evolved LLM coordinator* (arXiv:2512.04695, Version 3; original preprint 2025). https://arxiv.org/html/2512.04695v3

Zhang, A. L., Kraska, T., & Khattab, O. (2026). *Recursive language models* (arXiv:2512.24601, Version 3; original preprint 2025). https://arxiv.org/html/2512.24601v3

Anthropic. (2025, September 29). *Effective context engineering for AI agents*. https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
