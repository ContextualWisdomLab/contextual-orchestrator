# Conduct Final-Answer Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make conduct verification evaluate the response candidate that can be returned, using a conjunctive fast-mlsirm decision rule without an arbitrary cutoff.

**Architecture:** Preserve fast-mlsirm as the only semantic judge. Pass the synthesizer/final-step candidate as the judged answer and the verifier report as reference evidence. Configure the judge so acceptance requires every positive-weight required criterion to attain its maximum score; no hand-tuned fractional threshold or decision-affecting relative weight remains.

**Tech Stack:** Python 3.12+, pytest, contextual-orchestrator, released fast-mlsirm adapter contract.

**Spec:** `docs/planning/adrs/2026-09-27-final-answer-judgment-boundary.md`

## Global Constraints

- Preserve the exact PR head lineage with ordinary commits; no force push or destructive rebase.
- All model-response quality judgment crosses the released fast-mlsirm adapter.
- Unknown, malformed, or unavailable judgment fails closed.
- No arbitrary decision threshold, weighting, tie-break, or fallback.

---

### Task 1: Pin the response-quality boundary

**Files:**
- Modify: `tests/test_orchestrator_dispatch_boundaries.py`
- Modify: `tests/test_model_judge.py`

**Interfaces:**
- Consumes: `TaskOrchestrator.conduct()` and `_model_judge_verification()`.
- Produces: regression evidence that the final response candidate, verifier reference, and conjunctive threshold reach fast-mlsirm.

- [x] **Step 1: Write a failing test** asserting template and generated conduct pass their final-step output as `answer`, the verifier report as `reference_answer`, and `accept_threshold=1.0`.
- [x] **Step 2: Run the focused tests and confirm failure occurs because current code judges the verifier report and uses `0.7`.**
- [x] **Step 3: Record the exact RED output.**

### Task 2: Repair the minimal production boundary

**Files:**
- Modify: `contextual_orchestrator/orchestrator.py`

**Interfaces:**
- Consumes: optional `answer` argument from conduct callers and the existing verifier report.
- Produces: `ContextualOrchestratorJudge.judge(task=..., answer=..., reference_answer=..., criteria=...)` under a maximum-score conjunction.

- [x] **Step 1: Add an optional final-answer input to `_model_judge_verification`, defaulting to the existing direct-route behavior.**
- [x] **Step 2: Pass the generated/template final output at both conduct call sites.**
- [x] **Step 3: Replace `accept_threshold=0.7` with the documented maximum-score conjunction and remove explicit decision-affecting criterion weights.**
- [x] **Step 4: Run the focused tests and confirm GREEN.**

### Task 3: Preserve the decision and Gap record

**Files:**
- Modify: `CHANGELOG.d/conduct-verifier-not-required-final-answer.md`
- Create: `docs/planning/adrs/2026-09-27-final-answer-judgment-boundary.md`
- Modify: `docs/product-technical-gap-baseline.md`

**Interfaces:**
- Consumes: RED/GREEN commands and exact source behavior.
- Produces: reconstructable rationale, limitations, evidence, and follow-up state.

- [x] **Step 1: Document why judging the verifier report cannot establish final-response quality.**
- [x] **Step 2: Document the conjunction rule and why its unit threshold is structural rather than calibrated.**
- [x] **Step 3: Keep broader held-out calibration and immutable upstream release work explicitly open.**

### Task 4: Verify and publish the ordinary child commit

**Files:**
- Verify all modified files above.

**Interfaces:**
- Consumes: exact worktree and project interpreter.
- Produces: focused pytest, diff checks, commit/tree SHA, hosted exact-head Checks.

- [ ] **Step 1: Run focused pytest and `git diff --check`.**
- [ ] **Step 2: Inspect the final diff for unrelated changes.**
- [ ] **Step 3: Commit once, update the PR branch without force, and re-fetch the remote exact head.**
- [ ] **Step 4: Leave the PR Draft until current-head required Checks and independent approval are terminal.**
