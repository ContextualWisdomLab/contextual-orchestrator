# Provider-neutral reasoning-effort profiles

## Customer next action

Construct `default_role_effort_catalog()` only for an evaluation or an
explicitly configured deployment, run `run_equal_budget_ablation(true_theta)`,
and keep production defaults unchanged while
`production_default_change_allowed(report)` is `false`.

## Contract

`ReasoningEffortProfile` is a versioned, JSON-safe snapshot for thinker,
worker, verifier, synthesizer, planner, and judge. It validates finite numeric
budgets, rejects booleans-as-numbers and unknown keys, and keeps
`reasoning_effort` separate from `temperature`, `top_p`, and `seed`.

The catalog is hashed canonically so synchronous route, streaming route, batch
route, generated planning, verification, and persisted runs can be replayed
against the same configuration. A provider must explicitly declare
`reasoning_effort_supported=true` before the native field is sent. Unknown
support fails closed; the explicit `omit` fallback sends only independently
valid output and sampling controls.

The ablation emits estimated `theta_hat`, RMSE against supplied true
parameters, token budget, workflow/depth/access-list factors, and an
`estimated` measurement status. Synthetic estimates are evidence for tests,
not production quality claims, and cannot unlock a default change.

## Verification

```text
uv run pytest -q tests/test_reasoning_effort_profile.py tests/fuzz/test_fuzz_properties.py
uv run ruff check .
```

## Research basis (APA 7th)

### Fugu read scope and implementation boundary, 2026-09-09

The June 22 report is pinned to author-repository revision
`1397abb416e4b774003a09b689ea120e0da02262`; PDF SHA-256
`00a0e5065551c80c12a019018e18d8365cc3da229303f1765aa49fdf22876ce2`.
Read scope: opening abstract and pages 3–8; page 5/Figure 2 was rendered and
directly inspected, with legible labels, arrows, and caption. No full-report
review or reproduction is claimed; no PDF is vendored.
Page 8 was also directly inspected as a 1132×1600 render: the two reward
conditions and equations 6–7 are legible without clipping. This verifies the
source reading, not CO's rendered documentation or a numerical reproduction.

Section 3.1 uses a trained lightweight head over backbone hidden states for
worker selection without autoregressive decision text. Unlike TRINITY, this
Fugu variant does not assign roles. Section 3.1.2 derives soft training targets
from repeated worker outcomes on tasks with reference solutions. These are
not CO's deterministic effort-rank fixture or evidence validating its role
catalog. Figure 1's non-Fugu scores are provider-reported, not a common CO
evaluation cohort.

Section 3.1.3 optimizes repeated end-to-end task completion under a fixed turn
budget, not isolated turn accuracy. Section 3.2.1 describes Fugu-Ultra's different
training reward: malformed workflows receive 0, parseable incorrect workflows
0.5, and correct final outputs 1. That shaped reward is not a correctness rate.
For CO experiments, retain separate format validity, final correctness, and
training reward fields; never count the intermediate reward as half a correct
customer answer. Repeated runs and turns share a task/harness context and must
not inflate the independent sample count. This is an evaluation-design inference,
not a reproduced result or authorization to train on customer transcripts.

Engineering inference: compare decision-only selection with generative triage
under the same observed cohort, correctness guardrail, and resource accounting.
Do not claim Fugu's results for a black-box API router without its trained
representation/head, or treat temperature as reasoning effort. This motivates
an experiment, not a default change or a new unvalidated estimator.

Sakana AI. (2026). *Sakana Fugu technical report*.
https://github.com/SakanaAI/fugu/blob/1397abb416e4b774003a09b689ea120e0da02262/Fugu_technical_report.pdf

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025).
*Trinity: An evolved LLM coordinator* (arXiv:2512.04695).
https://doi.org/10.48550/arXiv.2512.04695

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025).
*Learning to orchestrate agents in natural language with the Conductor*
(arXiv:2512.04388). https://doi.org/10.48550/arXiv.2512.04388

Baker, F. B. (2001). *The basics of item response theory* (2nd ed.). ERIC
Clearinghouse on Assessment and Evaluation. https://eric.ed.gov/?id=ED458219
