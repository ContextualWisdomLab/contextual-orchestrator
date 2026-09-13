# Learned-policy evidence is not a mutable ablation report

Status: Proposed. This is a bounded child of #1000 at `37cf3f6bb0810ff3bcf0132ac08f093523809667`; it neither retires that PR nor inherits its historical GREEN. The original effort module is Git blob `3058312c441c9a49b72f45cae8ad4c90217351be`, independently confirmed also on protected `42f9d905b2f8a09aa8ed80303d892fae4d0398d7`. The original full test file was reconstructed with matching blob `d3389078c5167969320a89585d5bdcfba1838c3c` before modifying one obsolete permission assertion.

## Reproduced fault

`production_default_change_allowed` trusted two RMSE values and an editable `robustness_passed` flag. It denied only the literal measurement label `estimated`, so missing, blank, unknown and self-declared measured/reported labels could authorize a default change. Negative candidate RMSE and coercible booleans/strings also crossed the gate. A synthetic report could be relabelled and its candidate score edited to authorize a supposedly empirical policy improvement. The function did not authenticate observations, a dataset, the fitted artifact, equal-budget design or an approver.

Twelve focused tests were executed against the complete original leaf: 11 failed, one passed. The minimum safe repair retires this diagnostic-only permission path while retaining its boolean API: it always refuses authorization and does not read caller-controlled mapping methods. The historical threshold export remains only for import compatibility and no longer affects permission. This is a fail-closed retirement, not an implementation stub that pretends to authorize valid empirical evidence.

The matching legacy test now rejects its self-declared measured dictionary; all other test bodies remain. The new focused suite is 12/12 GREEN with warnings treated as errors, and both new executable gate lines were covered. The complete repository suite and the original integration test module were not run in the local partial checkout; no full-module coverage or independent approval is claimed.

## What the original numerical routine does

`estimate_theta` constructs each estimate directly from the supplied true theta using a shrinkage coefficient depending on hard-coded effort, workflow depth and access ranks. Lower error from more effort is built into that construction. `_estimated_tokens_used` is likewise arithmetic over those ranks, not provider usage. A correct RMSE formula applied to this constructed vector cannot prove an estimator recovered unknown parameters or that a learned coordinator improved model responses.

Those legacy diagnostics and hand-authored profile defaults remain an open #1000 migration finding. This patch corrects their evidence descriptions and removes promotion authority; it does not claim they are now empirical estimators. Move synthetic generators to unit-test fixtures through a compatibility plan, collect observed model responses independently of true-parameter generation, and use the released Rust/fast-mlsirm estimator boundary for fitted parameters. No new Python numerical runtime is introduced here.

## Primary-source conformance, including a correction to the existing finding

| Reference | Supported mechanism | CWL consequence |
|---|---|---|
| Fugu report §3.1.1–3.1.3 | Learned hidden-state worker selection; basic Fugu does not assign TRINITY roles | A role label or hand-written score is not that model; require training/artifact and execution evidence before claiming equivalence |
| Fugu-Ultra §3.2.1–3.2.2 | Learned workflows/access lists, agent-specific tool histories within a workflow and memory across workflows | Preserve tool-call origin and communication isolation; do not pass every transcript to every child |
| Fugu-Ultra §3.2.3 | Training instructs workflows of up to five steps and permits unrestricted environment interactions for multi-turn agents | Correct any blanket claim that five has no paper basis. It is a training setting, not a universal root-call, retry, or context-partition limit |
| TRINITY | Evolved coordinator selecting model and Thinker/Worker/Verifier roles | Native `reasoning_effort` levels and synthetic shrinkage are different concepts |
| Conductor | Learned natural-language subtasks, worker assignment and access lists | Deterministic templates can be compatibility baselines, not a reproduction claim |
| RLM | External input access with recursive bounded calls | Whole-request decomposition can remain outside model selection; count all subcalls and keep source/finding references |

The source texts were read as HTML, not inferred from titles. Their experimental gains are not assigned to CWL. In particular, the outer request layer is not justified by claiming that Fugu has no memory or cannot decompose work; the engineering need is independently enforced context capacity, completeness and continuation across caller and gateway boundaries.

## Required empirical successor

Separate training, calibration and locked evaluation data. Fix candidate identity to model/provider revision, prompt, tools, effort, delegation policy and capability snapshot. Obtain real observations and include unsuccessful/unfinished runs in denominators. Compare baseline, agent-memory only, outer decomposition only and both on identical held-out PR snapshots; score source-local and cross-file defects separately with adjudicated references. Keep false-positive rate, missed defects, review completeness, calibrated uncertainty and reported token/cost usage separate rather than collapse them into a hand-authored utility.

An empirical authorization record must bind those results to the exact policy artifact and an independently approved evaluation design. Ordinary GitHub release authorization is a separate deployment condition, not evidence of psychometric validity. No alternate threshold, permissive report label or synthetic numerical improvement may replace the missing authority. Production routing itself, provider discovery, timeouts and free-pool policy are unchanged by this repair.

## Related ownership and open delivery

CO #1117 owns the outer request-partition prototype. Central .github#2068 owns reviewer work memory. Both still need Rust-owned runtime integration, effective-payload accounting, secure durable continuation, actual OpenCode/Noema/Strix adapters and immutable released contracts. The canonical product-technical-gap-baseline and broader AGENTS/CLAUDE/architecture/changelog claim reconciliation remain full-tree owner integration work; this record does not assert those existing files were updated.

## References

Sakana AI. (2026). *Sakana Fugu technical report* (arXiv:2606.21228, Version 2). arXiv. https://arxiv.org/html/2606.21228v2

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2026). *Trinity: An evolved LLM coordinator* (arXiv:2512.04695, Version 3; original preprint 2025). arXiv. https://arxiv.org/html/2512.04695v3

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2026). *Learning to orchestrate agents in natural language with the Conductor* (arXiv:2512.04388, Version 5; original preprint 2025). arXiv. https://arxiv.org/html/2512.04388v5

Zhang, A. L., Kraska, T., & Khattab, O. (2026). *Recursive language models* (arXiv:2512.24601, Version 3; original preprint 2025). arXiv. https://arxiv.org/html/2512.24601v3
