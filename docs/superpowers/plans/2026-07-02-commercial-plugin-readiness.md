# Commercial Plugin Readiness Implementation Plan

> **For agentic workers:** Execute this plan task-by-task. Keep Figma Code
> Connect excluded. Use TDD for repo changes and treat reviewer delay as
> non-blocking unless a concrete security, contract, or product defect appears.

**Goal:** Use Figma, Product Design, Superpowers, Ponytail, and Data Analytics
to make Contextual Orchestrator reviewable as a KRW 2,000,000,000 commercial
due-diligence product.

**Architecture decision:** Keep one repository and one product. Do not create a
separate library, Git submodule, or extracted package until a second external
consumer, independent release cadence, or security provenance requirement proves
that split is worth the extra review and support cost.

Decision statement: Do not create a separate library, Git submodule, or extracted package for this commercial-readiness increment.

**Tech stack:** Existing stdlib Python runtime, Markdown docs, current Figma
design/FigJam/Slides artifacts, GitHub/CI evidence, and no new repo
dependencies.

## Global Constraints

- Figma Code Connect must not be used.
- The KRW 2,000,000,000 target is due-diligence readiness, not guaranteed
  revenue, valuation, procurement approval, or compliance certification.
- Keep the product unified: compatible API plus admin evidence control plane.
- Data Analytics must separate measured evidence from proposed production
  targets.
- Ponytail scope control wins over premature dashboard, dependency, submodule,
  or package extraction.
- English and Korean operator review remain in scope.
- Review process is not a blocker unless it reports a concrete security,
  contract, or product defect.

---

### Task 1: Product Design Commercial Brief

**Files:**

- Modify: `docs/plugin_driven_design_brief.md`
- Test: `tests/test_plugin_driven_artifacts.py`

- [ ] **Step 1: Add KRW 2B completion standard**

Add buyer personas, review workflows, screen priorities, and QA checklist items
for commercial readiness.

- [ ] **Step 2: Verify brief contract**

Run:

```bash
python tests/test_plugin_driven_artifacts.py
```

Expected: the test confirms KRW 2B due-diligence wording, commercial readiness,
and no Code Connect.

### Task 2: Data Analytics Evidence Model

**Files:**

- Modify: `docs/analytics_spec.md`
- Test: `tests/test_plugin_driven_artifacts.py`

- [ ] **Step 1: Add commercial KPIs**

Add `commercial_readiness_pass_rate`, `buyer_evidence_completeness`,
`security_control_pass_rate`, `trace_audit_completeness`,
`support_operability_score`, and `roi_evidence_status`.

- [ ] **Step 2: Separate evidence types**

Use `measured_local`, `proposed_until_production`, and
`proposed_until_buyer_specific` labels.

- [ ] **Step 3: Attach CI maturity evidence**

Record CodeQL, Dependency review, Python supply chain, Trivy,
coverage-evidence, scan-pr-queue, and Strix as measured repository signals when
they pass.

### Task 3: Ponytail Packaging Decision

**Files:**

- Modify: `docs/library_research.md`
- Test: `tests/test_plugin_driven_artifacts.py`

- [ ] **Step 1: Record no-split decision**

State that no separate library, Git submodule, or extracted package should be
created for the current commercial-readiness work.

- [ ] **Step 2: Record extraction triggers**

List the future conditions that would justify a library or submodule split.

### Task 4: Figma Commercial Artifacts

**Files:**

- Modify: `docs/figma_artifacts.md`
- Test: `tests/test_plugin_driven_artifacts.py`

- [ ] **Step 1: Add FigJam commercial flow**

Create or record `KRW 2B Commercial Readiness Flow` on the existing FigJam
board.

- [ ] **Step 2: Add stakeholder deck record**

Record `Contextual Orchestrator KRW 2B Commercial Readiness Plan` as a Figma
Slides artifact. Do not use Code Connect.

### Task 5: Final Verification

Run:

```bash
python tests/test_plugin_driven_artifacts.py &&
python -m compileall contextual_orchestrator tests &&
pytest -q &&
git diff --check
```

Expected:

- All tests pass.
- No whitespace errors.
- No Code Connect usage is introduced.
- PR blockers are limited to real security, contract, or product defects.
