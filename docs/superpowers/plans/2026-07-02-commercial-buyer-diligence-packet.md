# Commercial Buyer Diligence Packet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a buyer-facing diligence packet that shows how Contextual
Orchestrator can be reviewed for a KRW 2,000,000,000 commercial sale without
claiming guaranteed valuation, production compliance, or buyer approval.

**Architecture:** Keep one repository and one deployable product. Add a small
documentation layer and contract test that ties existing runtime endpoints,
Figma/FigJam artifacts, Product Design buyer questions, Ponytail packaging
constraints, Superpowers execution discipline, and Data Analytics evidence
labels into one due-diligence packet.

**Tech Stack:** Markdown documentation, Python stdlib tests, existing Figma
FigJam board, existing GitHub PR workflow.

## Global Constraints

- Figma Code Connect must not be used.
- Review process is not a blocker.
- Do not create a separate library, Git submodule, or extracted package now.
- KRW 2,000,000,000 is a buyer due-diligence readiness target, not a valuation
  guarantee, purchase commitment, revenue claim, or production compliance
  certificate.
- Separate `measured_local`, `repository_artifact`, `figma_artifact`,
  `proposed_until_production`, and `proposed_until_buyer_specific` claims.

---

### Task 1: Buyer Diligence Packet

**Files:**

- Create: `docs/commercial_buyer_diligence_packet.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**

- Consumes: existing docs and endpoints named in README, including
  `/api/v1/commercial_readiness/latest`, `/api/v1/sales_readiness/latest`,
  `/api/v1/analytics_snapshots/latest`, `/admin`, and `/admin/state`.
- Produces: `docs/commercial_buyer_diligence_packet.md` with stable phrases
  asserted by `test_commercial_buyer_diligence_packet_defines_deal_room_evidence`.

- [ ] **Step 1: Write the packet contract test**

Add this test to `tests/test_plugin_driven_artifacts.py`:

```python
def test_commercial_buyer_diligence_packet_defines_deal_room_evidence() -> None:
    packet = read_text("docs/commercial_buyer_diligence_packet.md")

    for expected_text in [
        "Commercial Buyer Diligence Packet",
        "KRW 2,000,000,000 buyer review",
        "Figma Code Connect is not used",
        "Review process is not a blocker",
        "Do not create a separate library, Git submodule, or extracted package now",
        "measured_local",
        "repository_artifact",
        "figma_artifact",
        "proposed_until_production",
        "proposed_until_buyer_specific",
        "/api/v1/commercial_readiness/latest",
        "KRW 2B Buyer Deal Room Evidence Matrix",
    ]:
        assert expected_text in packet
```

Also call it from the `if __name__ == "__main__"` block.

- [ ] **Step 2: Run the focused test and confirm it fails before the document exists**

Run:

```bash
python tests/test_plugin_driven_artifacts.py
```

Expected: failure caused by missing `docs/commercial_buyer_diligence_packet.md`
or missing asserted phrases.

- [ ] **Step 3: Create the buyer diligence packet**

Create `docs/commercial_buyer_diligence_packet.md` with:

- a scope statement for a KRW 2,000,000,000 buyer review;
- Code Connect exclusion;
- review-delay non-blocker rule;
- one-repo packaging decision;
- evidence type table;
- buyer evidence inventory;
- plugin-use table;
- ready, warning, and blocked rules.

- [ ] **Step 4: Run the focused test and confirm it passes**

Run:

```bash
python tests/test_plugin_driven_artifacts.py
```

Expected: `ok`.

- [ ] **Step 5: Commit after verification**

Run:

```bash
git add docs/commercial_buyer_diligence_packet.md tests/test_plugin_driven_artifacts.py
git commit -m "docs: add commercial buyer diligence packet"
```

### Task 2: FigJam Evidence Matrix And Artifact Links

**Files:**

- Modify: `docs/figma_artifacts.md`
- Modify: `README.md`
- Modify: `tests/test_plugin_driven_artifacts.py`

**Interfaces:**

- Consumes: existing FigJam board
  `https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M`.
- Produces: a recorded FigJam diagram named
  `KRW 2B Buyer Deal Room Evidence Matrix` and README link to the diligence
  packet.

- [ ] **Step 1: Generate the FigJam diagram**

Use Figma `generate_diagram` with:

- `fileKey`: `Wr8iMlB9SHkerHSjv0Pe0M`
- `planKey`: `team::1408252278989737675`
- `name`: `KRW 2B Buyer Deal Room Evidence Matrix`

Expected: the tool returns
`https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M`.

- [ ] **Step 2: Update artifact docs**

Add `KRW 2B Buyer Deal Room Evidence Matrix` to
`docs/figma_artifacts.md` and describe it as the buyer deal-room map from
evidence paths to `measured_local`, `repository_artifact`, `figma_artifact`,
`proposed_until_production`, and `proposed_until_buyer_specific`.

- [ ] **Step 3: Update README design artifacts**

Add this bullet to README:

```markdown
- [Commercial buyer diligence packet](docs/commercial_buyer_diligence_packet.md)
```

- [ ] **Step 4: Extend the artifact contract test**

Update `test_figma_artifacts_are_recorded_without_code_connect` to assert:

```python
"KRW 2B Buyer Deal Room Evidence Matrix",
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

- [ ] **Step 2: Commit remaining docs and tests**

Run:

```bash
git add README.md docs/figma_artifacts.md docs/superpowers/plans/2026-07-02-commercial-buyer-diligence-packet.md tests/test_plugin_driven_artifacts.py
git commit -m "docs: add buyer diligence evidence matrix"
```

- [ ] **Step 3: Push and update PR evidence**

Run:

```bash
git push origin product-plugin-driven-planning
gh pr edit 14 --body-file /tmp/contextual-orchestrator-pr14-body.md
gh pr checks 14
```

Expected: required security, supply-chain, contract, and test checks either pass
or are still running without a concrete failure. Review process delay remains a
non-blocker.

