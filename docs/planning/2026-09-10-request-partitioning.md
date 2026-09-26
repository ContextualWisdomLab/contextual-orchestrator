# Whole-request partitioning outside model coordination

Status: Proposed. The kernel and its focused tests are implemented; default HTTP admission, live-provider adapters, and organizational rollout are not complete.

## Problem and evidence

LineageWeave #983 was inspected at head `9c3bcd0c0a5f6162eb5708433c1f23da9845618f`: 84 files and 134 commits. Its comments also report a Codex review-usage limit, CodeRabbit auto-pause, and a separate file-limit skip. Those causes must not all be classified as context overflow.

The central OpenCode launcher, blob `80f57d1d43cfa176af8936296a7b4ae532a5131e`, constructs a full review contract and, when evidence exceeds its byte cap, retains only the head and tail of the inline evidence. It subsequently treats context overflow as a fatal candidate failure. Source remains in the full evidence file, but this does not establish that the middle was reviewed or that reading it all in the next call will fit.

## Decision and ownership

`contextual_orchestrator.request_partitioning` owns a single inference request's evidence inventory, capacity packing, bounded map/reduce, and restart checkpoints. It sits before the existing route/conduct invocation adapter. It does not own Noema's general agent runtime, workflow scheduler, tools, approvals, or recovery authority. It does not choose providers or duplicate Fugu/TRINITY/Conductor selection policy.

The caller supplies immutable semantic units, including any cross-file relationship obligations. Each unit appears once in the map inventory; reductions carry complete lineage outside model prompts. A single unit that does not fit is rejected rather than sliced as arbitrary characters or truncated. The caller must refine that unit semantically. Native tool transcripts, system/user boundaries and multimodal payloads are not silently split by this text protocol.

The capacity adapter must count the effective payload, including model-specific framing, tool schemas, policy instructions and gateway additions. For virtual routing it must cover every eligible route, or bind admission to the eventual selected route. Unknown accounting fails closed. Output reserve and root call/token reservation limits are explicit operator inputs, not claimed research optima. The existing gateway adapter must preserve free/ZDR, IAM, tool authorization, provider routing and Keyverse-backed credentials.

`CheckpointStore` uses a trusted service-owned SQLite connection. Claim and reservation commit before the external call; completion commits afterward. A crash/lost response leaves an uncertain running operation and requires reconciliation. It is never automatically replayed. Completed children can be reused after an interruption before the next dispatch. This is not a provider-level exactly-once guarantee.

Reducers must reduce the number of records and fit the same capacity contract. A set of reports that cannot make progress fails explicitly rather than recursively growing or dropping reports. Non-stop/truncated/empty/tool-pending or unbounded completions cannot become completed checkpoints. The root result proves inventory coverage, not correctness or review approval. Review finding artifacts must be conserved separately by the reviewer ledger, outside lossy summaries.

The root limits account for calls made through this outer adapter and their reserved input/output tokens. They do **not yet** account for every internal Fugu worker, race loser or retry. A production adapter must join the existing usage/cost ledger and enforce shared admission at the internal invocation boundary; no aggregate cost guarantee is claimed by this kernel.

## Research boundary

- Sakana Fugu Technical Report, arXiv:2606.21228v2, 2026-06-23: https://arxiv.org/abs/2606.21228 . Fugu is a trained coordinator capable of dynamic delegation, verification, synthesis and recursive self-use. A hand-authored dispatch tree is not the trained Fugu system.
- TRINITY, arXiv:2512.04695v3: https://arxiv.org/abs/2512.04695 . The coordinator learns model/role choices; naming roles Thinker/Worker/Verifier does not reproduce that policy.
- Conductor, arXiv:2512.04388v5: https://arxiv.org/html/2512.04388v5 . Natural-language task orchestration and communication/access decisions are learned. The paper does not itself establish CWL's fixed routing thresholds or benchmark depth as valid deployed policy.
- Recursive Language Models, arXiv:2512.24601v3: https://arxiv.org/html/2512.24601v3 . Externalizing a long input and accessing bounded parts motivates this ownership separation. This implementation is not a reproduction of RLM experiments and inherits none of their performance results.
- Anthropic, Effective context engineering for AI agents, 2025-09-29: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents . Structured notes and fresh subagent contexts complement, rather than replace, complete evidence accounting.

No synthetic token counter, dry-run score, named paper role or coverage percentage can unlock a production model-policy change.

## Verification and rollout gap

The initial focused kernel suite has 49 passing tests, 162/162 measured statements and 48/48 branches. It covers 84-unit conservation, bounded calls, hierarchical reduction, restart, source/policy/tenant isolation, uncertain-call non-replay, SQLite concurrent claims/rollback, malformed completions, budget exhaustion and manifest-lineage corruption. Its byte counter is an explicitly synthetic exact accounting fixture, **not** a production tokenizer or a measured LLM-quality result.

Before rollout: bind the real effective-payload counter and existing gateway adapter; add typed HTTP admission/continuation and incomplete-status mapping; enforce the inner-call cost reservation; provision isolated durable storage and retention; run exact-head OpenCode/Noema/Strix integration and private/ZDR cases; exercise provider failures and cancelled jobs; obtain independent review and required checks. Do not pin a mutable PR branch into production.

Quality evaluation must compare unchanged PR snapshots under baseline, agent memory, outer partitioning, and both together. Keep source-local and cross-file defects separate, adjudicate findings against source/test evidence, retain false positives and unresolved cases, and report detection/false-negative rates separately from coverage and actual usage. This ADR does not invent a passing threshold or a measured improvement.
