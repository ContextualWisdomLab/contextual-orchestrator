# Commercial Buyer Acceptance Runbook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a buyer-facing acceptance runbook that converts KRW
2,000,000,000 due-diligence evidence into a concrete go/warning/no-go workflow.

**Architecture:** Keep the repo as one product and one deployable control plane.
Use documentation and one FigJam workflow diagram to connect existing runtime
endpoints, Figma artifacts, security checks, analytics caveats, and packaging
decisions without adding dependencies or splitting libraries.

**Tech Stack:** Markdown documentation, Python stdlib document contract tests,
existing FigJam board, existing GitHub PR workflow.

## Global Constraints

- Figma Code Connect must not be used.
- Review process is not a blocker.
- Do not create a separate library, Git submodule, or extracted package now.
- KRW 2,000,000,000 is buyer due-diligence readiness, not guaranteed revenue,
  valuation, purchase approval, or production compliance certification.
- Keep measured, repository, Figma, production-proposed, and buyer-specific
  evidence separate.

---

### Task 1: Acceptance Runbook

**Files:**

- Create: `docs/commercial_buyer_acceptance_runbook.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**

- Consumes: `docs/commercial_buyer_diligence_packet.md`,
  `docs/commercial_completion_scorecard.md`,
  `/api/v1/commercial_readiness/latest`, `/api/v1/sales_readiness/latest`,
  `/api/v1/analytics_snapshots/latest`, `/admin`, and `/admin/state`.
- Produces: `docs/commercial_buyer_acceptance_runbook.md` with stable phrases
  asserted by `test_commercial_buyer_acceptance_runbook_defines_go_no_go_workflow`.

- [ ] **Step 1: Add the document contract test**

Add this test to `tests/test_plugin_driven_artifacts.py`:

```python
def test_commercial_buyer_acceptance_runbook_defines_go_no_go_workflow() -> None:
    runbook = read_text("docs/commercial_buyer_acceptance_runbook.md")

    for expected_text in [
        "Commercial Buyer Acceptance Runbook",
        "KRW 2,000,000,000 commercial review",
        "Figma Code Connect is not used",
        "Review process is not a blocker",
        "Do not create a separate library, Git submodule, or extracted package now",
        "Acceptance Workflow",
        "Go, Warning, No-Go Rules",
        "KRW 2B Buyer Acceptance Go No Go Workflow",
        "/api/v1/commercial_readiness/latest",
        "measured_local",
        "proposed_until_production",
        "proposed_until_buyer_specific",
    ]:
        assert expected_text in runbook
```

Call it from the `if __name__ == "__main__"` block.

- [ ] **Step 2: Run the focused test and confirm it fails before the document exists**

Run:

```bash
python tests/test_plugin_driven_artifacts.py
```

Expected: failure caused by missing `docs/commercial_buyer_acceptance_runbook.md`
or missing asserted phrases.

- [ ] **Step 3: Create the acceptance runbook**

Create `docs/commercial_buyer_acceptance_runbook.md` with:

- due-diligence scope statement;
- Figma Code Connect exclusion;
- review-process non-blocker policy;
- one-repo packaging decision;
- acceptance workflow table;
- go, warning, and no-go rules;
- plugin responsibilities;
- final handoff checklist.

- [ ] **Step 4: Run the focused test and confirm it passes**

Run:

```bash
python tests/test_plugin_driven_artifacts.py
```

Expected: `ok`.

### Task 2: FigJam Workflow And Artifact Links

**Files:**

- Modify: `docs/figma_artifacts.md`
- Modify: `README.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**

- Consumes: existing FigJam board
  `https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M`.
- Produces: recorded FigJam diagram
  `KRW 2B Buyer Acceptance Go No Go Workflow` and README link to the runbook.

- [ ] **Step 1: Generate the FigJam workflow**

Use Figma `generate_diagram` with:

- `fileKey`: `Wr8iMlB9SHkerHSjv0Pe0M`
- `planKey`: `team::1408252278989737675`
- `name`: `KRW 2B Buyer Acceptance Go No Go Workflow`

Expected: the tool returns
`https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M`.

- [ ] **Step 2: Update artifact docs**

Add `KRW 2B Buyer Acceptance Go No Go Workflow` to
`docs/figma_artifacts.md` and describe it as the buyer go/warning/no-go flow.

- [ ] **Step 3: Update README design artifacts**

Add this bullet to README:

```markdown
- [Commercial buyer acceptance runbook](docs/commercial_buyer_acceptance_runbook.md)
```

- [ ] **Step 4: Extend the artifact contract test**

Update `test_figma_artifacts_are_recorded_without_code_connect` to assert:

```python
"KRW 2B Buyer Acceptance Go No Go Workflow",
```

- [ ] **Step 5: Verify documentation contracts**

Run:

```bash
python tests/test_plugin_driven_artifacts.py
```

Expected: `ok`.

### Task 3: Final Verification And PR Update

**Files:**

- No source files beyond Tasks 1 and 2.

**Interfaces:**

- Consumes: repository test commands and PR `#14`.
- Produces: pushed branch and updated PR evidence.

- [ ] **Step 1: Run final verification**

Run:

```bash
python tests/test_plugin_driven_artifacts.py
python -m compileall contextual_orchestrator tests
pytest -q
git diff --check
```

Expected:

- `python tests/test_plugin_driven_artifacts.py` prints `ok`;
- `compileall` exits 0;
- `pytest -q` reports all tests passing;
- `git diff --check` exits 0.

- [ ] **Step 2: Commit**

Run:

```bash
git add README.md docs/figma_artifacts.md docs/commercial_buyer_acceptance_runbook.md docs/superpowers/plans/2026-07-02-commercial-buyer-acceptance-runbook.md tests/test_plugin_driven_artifacts.py
git commit -m "docs: add commercial buyer acceptance runbook"
```

- [ ] **Step 3: Push and update PR**

Run:

```bash
git push origin product-plugin-driven-planning
gh pr edit 14 --body-file /tmp/contextual-orchestrator-pr14-body.md
gh pr checks 14
```

Expected: required checks pass or remain in progress without concrete failure.
Review process delay remains a non-blocker.

