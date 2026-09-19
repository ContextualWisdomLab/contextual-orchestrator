# Plugin-Driven Product Design Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce durable Product Design, Figma, Data Analytics, Superpowers, and Ponytail artifacts for Contextual Orchestrator without using Figma Code Connect.

**Architecture:** Keep the repository as a single enterprise orchestration control plane. Add documentation and design artifacts that extend the current stdlib admin console, REST API contract, i18n design, and screen-design tokens. Do not add a new runtime stack or split the product into separate product lines.

**Tech Stack:** Markdown docs, existing stdlib Python tests, Figma design files, FigJam diagrams, Figma Slides, and no new repo dependencies.

## Global Constraints

- Figma Code Connect must not be used.
- Product surfaces must map to API compatibility, pool management, policy control, trace audit, access-list evidence, evaluation replay, or i18n.
- Analytics outputs must separate proposed metric definitions from measured results.
- English and Korean operator copy remain in scope.
- Prefer existing docs and implementation over new abstractions.
- No new repo dependencies.
- Object, event, and resource names use lower snake_case with at least two words where applicable.

---

### Task 1: Ground The Product Brief

**Files:**
- Create: `docs/plugin_driven_design_brief.md`
- Test: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**
- Consumes: `docs/product_planning.md`, `docs/screen_design.md`, `docs/rest_api_design.md`, `docs/i18n_design.md`
- Produces: a confirmed design brief for later Figma and analytics artifacts

- [ ] **Step 1: Read current docs**

Run:

```bash
sed -n '1,220p' docs/product_planning.md
sed -n '1,220p' docs/screen_design.md
sed -n '1,220p' docs/rest_api_design.md
sed -n '1,180p' docs/i18n_design.md
```

Expected: each file exists and describes the current enterprise control-plane product.

- [ ] **Step 2: Write the design brief**

Create `docs/plugin_driven_design_brief.md` with purpose, audience, source audit, required surfaces, canonical visual direction, and design QA checklist.

- [ ] **Step 3: Add a contract test**

Create `tests/test_plugin_driven_artifacts.py` and assert the brief contains the canonical constraints: `Code Connect`, `agent_pools`, `workflow_runs`, `access_reports`, `evaluation_runs`, `locale_bundles`, `English`, and `Korean`.

- [ ] **Step 4: Run the focused test**

Run:

```bash
python tests/test_plugin_driven_artifacts.py
```

Expected: `ok`.

### Task 2: Define Visual Directions

**Files:**
- Create: `docs/plugin_visual_directions.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**
- Consumes: the design brief from Task 1
- Produces: exactly three design directions and one canonical selection

- [ ] **Step 1: Add the three directions**

Create `docs/plugin_visual_directions.md` with these direction names:

- `Evidence Console`
- `Policy Studio`
- `Audit Timeline`

Mark `Evidence Console` as the canonical direction because it follows the current screen-design tokens and table-first constraint.

- [ ] **Step 2: Test direction coverage**

Update `tests/test_plugin_driven_artifacts.py` to assert all three direction names are present and that `Evidence Console` is canonical.

- [ ] **Step 3: Run the focused test**

Run:

```bash
python tests/test_plugin_driven_artifacts.py
```

Expected: `ok`.

### Task 3: Define Analytics And Dashboard Spec

**Files:**
- Create: `docs/analytics_spec.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**
- Consumes: product bets and API endpoints from existing docs
- Produces: KPI definitions, event model, dashboard shape, guardrails, and source caveats

- [ ] **Step 1: Add KPI framework**

Create `docs/analytics_spec.md` with primary KPIs for compatible API adoption, trace-complete workflow rate, and policy-safe routing rate.

- [ ] **Step 2: Add source caveat**

State that the repo has no production telemetry and that metrics are proposed definitions, not measured product results.

- [ ] **Step 3: Add event model**

Use lower snake_case event names such as `chat_completion_requested`, `workflow_run_created`, and `provider_exclusion_changed`.

- [ ] **Step 4: Test analytics coverage**

Update `tests/test_plugin_driven_artifacts.py` to assert the source caveat, KPI names, event names, and guardrails are present.

- [ ] **Step 5: Run the focused test**

Run:

```bash
python tests/test_plugin_driven_artifacts.py
```

Expected: `ok`.

### Task 4: Create Figma And Presentation Artifacts

**Files:**
- Create: `docs/figma_artifacts.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**
- Consumes: design brief, visual directions, analytics spec
- Produces: links and descriptions for Figma design, FigJam diagrams, and stakeholder deck

- [ ] **Step 1: Create Figma design file**

Create a Figma design file named `Contextual Orchestrator Plugin-Driven Admin Design`.

- [ ] **Step 2: Build editable frames**

In the Figma design file, create editable frames for overview dashboard, agent pool, orchestration policy, workflow trace, access report, evaluation replay, locale review, and visual directions.

- [ ] **Step 3: Create FigJam diagrams**

Create diagrams for orchestration architecture, route-versus-conduct flow, workflow trace/access-list visibility, and API/control-plane relationship. Use supported Mermaid diagram types only.

- [ ] **Step 4: Create stakeholder deck**

Create a concise Figma Slides deck covering product thesis, three design directions, canonical screen set, analytics model, and implementation path.

- [ ] **Step 5: Record artifact links**

Create `docs/figma_artifacts.md` with artifact names, URLs, purpose, and a statement that Code Connect was not used.

- [ ] **Step 6: Test artifact doc**

Update `tests/test_plugin_driven_artifacts.py` to assert the artifact doc mentions the design file, FigJam diagrams, stakeholder deck, and no Code Connect.

### Task 5: Final Verification

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: all new docs and artifact links
- Produces: discoverable README references and passing checks

- [ ] **Step 1: Update README**

Add the new design, analytics, visual direction, Figma artifact, and implementation plan docs to the Design Artifacts list.

- [ ] **Step 2: Run all repo checks**

Run:

```bash
python tests/test_self_check.py
python tests/test_paper_contracts.py
python tests/test_admin_contract.py
python tests/test_conventions.py
python tests/test_api_contract.py
python tests/test_security_hardening.py
python tests/test_repository_security_metadata.py
python tests/test_product_planning_contract.py
python tests/test_plugin_driven_artifacts.py
```

Expected: every command prints `ok`.

- [ ] **Step 3: Review git diff**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors and only intentional files changed.
