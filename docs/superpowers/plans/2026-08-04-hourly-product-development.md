# Hourly Product Development Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fail-closed hourly dispatcher that creates one bounded product-development pull request only when the repository has no open pull request and no active or unknown-state Agent Task.

**Architecture:** Keep pull-request review, repair, checks, approval, and merge in the organization-central `ContextualWisdomLab/.github` workflows. Add one repository-local read-only scheduler because the delegated prompt must preserve Contextual Orchestrator's product, MSA, research, release, NVIDIA NIM, naming, documentation, and quality contracts. Use the GitHub CLI for read-only repository inventory and the Agent Tasks REST API for single-flight task inventory and creation.

**Tech Stack:** GitHub Actions YAML, Bash with `set -euo pipefail`, GitHub CLI, `jq`, Python 3.12, pytest.

## Global Constraints

- Schedule once per hour at cron minute `47` and support a manual dry run.
- Do not duplicate organization-central PR-maintenance logic.
- Use `GITHUB_TOKEN` only for read-only repository inventory.
- Use `COPILOT_GITHUB_TOKEN` only for Agent Task inventory and creation.
- Fail closed on open PRs, missing credentials, inventory failures, unexpected API schemas, active tasks, and unknown task states.
- Create exactly one bounded pull-request-producing task per clear single-flight decision.
- Preserve standalone operation and modular MSA compatibility with `ContextualWisdomLab/.github`, naruon, and other CWL services.
- Require descriptive two-word-or-longer `snake_case` names for new database objects; `snake_case` is preferred.
- Maintain 100% production statement and branch coverage and 100% production docstring coverage.
- Use current authoritative standards, primary technical documentation, and peer-reviewed evidence when behavior is ambiguous.
- Use Figma or Product Design only for a genuine user interface or interaction contract.
- Keep NVIDIA NIM evaluation provider-neutral, dynamically discover models through `GET /v1/models`, and separate actual-free cost from hypothetical paid cost.
- Update `CHANGELOG.md` and affected documentation; follow Semantic Versioning only when release-ready.
- The dispatcher and delegated task must not merge, publish, release, or bypass review and branch-protection gates.

---

### Task 1: Define the Workflow Contract with Failing Tests

**Files:**
- Create: `tests/test_hourly_product_development_workflow.py`
- Test: `tests/test_hourly_product_development_workflow.py`

**Interfaces:**
- Consumes: repository root resolved from `Path(__file__).resolve().parents[1]`.
- Produces: string-level contracts for `.github/workflows/hourly-product-development.yml` covering scheduling, single-flight gating, permissions, Agent Tasks API use, and delegated prompt requirements.

- [x] **Step 1: Write the failing workflow-presence helper**

```python
ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "hourly-product-development.yml"


def _workflow_text() -> str:
    """Return the workflow source after proving the scheduled contract exists."""

    assert WORKFLOW.is_file(), "hourly product-development workflow is missing"
    return WORKFLOW.read_text(encoding="utf-8")
```

- [x] **Step 2: Add schedule and single-flight assertions**

```python
def test_hourly_loop_is_scheduled_and_single_flight() -> None:
    workflow = _workflow_text()
    assert 'cron: "47 * * * *"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "hourly-product-development-${{ github.repository }}" in workflow
    assert "cancel-in-progress: false" in workflow
```

- [x] **Step 3: Add fail-closed inventory assertions**

```python
def test_hourly_loop_is_pull_request_first_and_fails_closed() -> None:
    workflow = _workflow_text()
    assert workflow.index("gh pr list") < workflow.index(
        "/agents/repos/${GITHUB_REPOSITORY}/tasks?per_page=100"
    )
    assert "reason=open_pull_request" in workflow
    assert "reason=agent_task_token_unavailable" in workflow
    assert "reason=task_inventory_unavailable" in workflow
    assert "reason=active_agent_task" in workflow
    assert '(.state // "unknown")' in workflow
```

- [x] **Step 4: Add least-privilege API and prompt assertions**

```python
def test_hourly_loop_uses_the_agent_tasks_api_without_widening_repo_token() -> None:
    workflow = _workflow_text()
    assert "AGENT_TASK_TOKEN: ${{ secrets.COPILOT_GITHUB_TOKEN }}" in workflow
    assert "REPOSITORY_TOKEN: ${{ github.token }}" in workflow
    assert "X-GitHub-Api-Version: 2026-03-10" in workflow
    assert "contents: read" in workflow
    assert "pull-requests: read" in workflow
    assert "contents: write" not in workflow
    assert "pull-requests: write" not in workflow
```

- [x] **Step 5: Run the test and preserve the RED evidence**

Run:

```bash
python -m pytest -q tests/test_hourly_product_development_workflow.py
```

Expected and observed result before implementation: four failures with `AssertionError: hourly product-development workflow is missing`.

- [x] **Step 6: Commit the test-first contract**

```bash
git add tests/test_hourly_product_development_workflow.py
git commit -m "test: define the hourly product-development workflow contract"
```

---

### Task 2: Implement the Pull-Request-First Scheduler

**Files:**
- Create: `.github/workflows/hourly-product-development.yml`
- Test: `tests/test_hourly_product_development_workflow.py`

**Interfaces:**
- Consumes: `github.repository`, `github.token`, optional boolean `inputs.dry_run`, and secret `COPILOT_GITHUB_TOKEN`.
- Produces: gate outputs `dispatch` and `reason`; when clear, one Agent Tasks API request with `base_ref: main` and `create_pull_request: true`.

- [x] **Step 1: Add the schedule, manual trigger, concurrency, and permissions**

```yaml
on:
  workflow_dispatch:
    inputs:
      dry_run:
        required: false
        default: false
        type: boolean
  schedule:
    - cron: "47 * * * *"

concurrency:
  group: hourly-product-development-${{ github.repository }}
  cancel-in-progress: false

permissions:
  contents: read
  pull-requests: read
```

- [x] **Step 2: Gate on the pull-request inventory before Agent Tasks**

```bash
if ! open_prs="$(
  GH_TOKEN="$REPOSITORY_TOKEN" gh pr list \
    --repo "$GITHUB_REPOSITORY" --state open --limit 1 --json number,url
)"; then
  echo "dispatch=false" >>"$GITHUB_OUTPUT"
  echo "reason=pull_request_inventory_unavailable" >>"$GITHUB_OUTPUT"
  exit 0
fi

if [ "$(jq 'length' <<<"$open_prs")" -gt 0 ]; then
  echo "dispatch=false" >>"$GITHUB_OUTPUT"
  echo "reason=open_pull_request" >>"$GITHUB_OUTPUT"
  exit 0
fi
```

- [x] **Step 3: Fail closed when the Agent Task token or inventory is unavailable**

```bash
if [ -z "${AGENT_TASK_TOKEN:-}" ]; then
  echo "dispatch=false" >>"$GITHUB_OUTPUT"
  echo "reason=agent_task_token_unavailable" >>"$GITHUB_OUTPUT"
  exit 0
fi

tasks_endpoint="/agents/repos/${GITHUB_REPOSITORY}/tasks?per_page=100"
if ! tasks_json="$(
  GH_TOKEN="$AGENT_TASK_TOKEN" gh api --paginate --slurp \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2026-03-10" \
    "$tasks_endpoint"
)"; then
  echo "dispatch=false" >>"$GITHUB_OUTPUT"
  echo "reason=task_inventory_unavailable" >>"$GITHUB_OUTPUT"
  exit 0
fi
```

- [x] **Step 4: Validate task schema and treat unknown state as active**

```bash
jq -e 'all(.[]; (.tasks | type) == "array")' <<<"$tasks_json" >/dev/null
active_tasks="$(
  jq '[
    .[] | .tasks[]?
    | ((.state // "unknown") | ascii_downcase) as $state
    | select(
        $state != "completed" and
        $state != "failed" and
        $state != "timed_out" and
        $state != "cancelled"
      )
  ] | length' <<<"$tasks_json"
)"
```

The implementation wraps schema failure in `reason=task_inventory_unavailable` instead of allowing partial or malformed inventory to dispatch work.

- [x] **Step 5: Generate the bounded repository-specific prompt**

The prompt explicitly requires:

```text
single highest-value buyer-visible
work test-first
100% production statement and branch coverage
100% production docstring coverage
two-word-or-longer snake_case
modular MSA
ContextualWisdomLab/.github
naruon
NVIDIA_NIM_API_KEY
GET /v1/models
hypothetical paid cost
CHANGELOG.md
Semantic Versioning
Figma or Product Design
Do not merge, publish, release, or bypass reviews
exactly one bounded pull request
```

- [x] **Step 6: Create the task only after a clear gate**

```bash
jq -n \
  --rawfile prompt "$RUNNER_TEMP/contextual-orchestrator-agent-prompt.md" \
  --arg base "$DEFAULT_BRANCH" \
  '{prompt: $prompt, base_ref: $base, create_pull_request: true}' \
  >"$request_file"

GH_TOKEN="$AGENT_TASK_TOKEN" gh api \
  --method POST \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  "/agents/repos/${GITHUB_REPOSITORY}/tasks" \
  --input "$request_file"
```

- [ ] **Step 7: Run focused and complete tests after implementation**

Run:

```bash
python -m pytest -q tests/test_hourly_product_development_workflow.py
python -m pytest -q
```

Expected: all workflow contract tests pass and the full repository test suite passes.

- [x] **Step 8: Commit the implementation**

```bash
git add .github/workflows/hourly-product-development.yml
git commit -m "ci: implement pull-request-first hourly product development"
```

---

### Task 3: Document Operations, Verify Security, and Prepare Review

**Files:**
- Create: `docs/operations/hourly-product-development.md`
- Create: `docs/superpowers/plans/2026-08-04-hourly-product-development.md`
- Modify only when required by review: `.github/workflows/hourly-product-development.yml`
- Test: `tests/test_hourly_product_development_workflow.py`

**Interfaces:**
- Consumes: the workflow's exact gate reasons, token split, terminal-state set, dry-run behavior, and organization-central governance boundary.
- Produces: an operator-facing configuration, failure, verification, and disablement contract plus a reproducible implementation plan.

- [x] **Step 1: Document schedule and queue ownership**

Record that the dispatcher runs at minute 47, stops when any PR is open, and leaves review, repair, check reruns, independent approval, and merge to `ContextualWisdomLab/.github`.

- [x] **Step 2: Document credential boundaries**

Record that `GITHUB_TOKEN` is read-only, `COPILOT_GITHUB_TOKEN` needs only Agent tasks read/write permission, and `NVIDIA_NIM_API_KEY` is not injected into the dispatcher.

- [x] **Step 3: Document failure semantics and dry run**

Record safe no-op reasons for open PRs, missing token, inventory failure, unexpected schema, and active/unknown tasks. Record that task-creation failure remains a visible job failure.

- [ ] **Step 4: Re-run current-head CI and security evidence**

Require successful current-head results for:

```text
Tests
Fuzz
Security
Security Scan
SAST Semgrep
central OpenCode review
CodeRabbit when configured
branch-protection required checks
```

Any finding must be fixed on the same branch and revalidated at the new head.

- [ ] **Step 5: Review the diff for scope and security**

Run or inspect the equivalent of:

```bash
git diff --check main...HEAD
git diff --stat main...HEAD
git grep -n -E 'contents: write|pull-requests: write' -- .github/workflows/hourly-product-development.yml
git grep -n 'NVIDIA_NIM_API_KEY' -- .github/workflows/hourly-product-development.yml docs/operations/hourly-product-development.md
```

Expected: no whitespace errors; only test, workflow, operations, and plan files changed; no repository-write permission; NVIDIA secret appears only in delegated-policy documentation, not as a dispatcher environment variable.

- [ ] **Step 6: Mark the pull request ready and enable policy-controlled auto-merge**

After current-head checks and review threads are clean:

```bash
gh pr ready 85
gh pr merge 85 --auto --squash
```

The command queues repository-native auto-merge; it does not bypass independent approval or required checks.

- [ ] **Step 7: Verify activation after merge**

Confirm `.github/workflows/hourly-product-development.yml` exists on `main`, the schedule is enabled, and an open PR causes a safe `reason=open_pull_request` no-op. A dry run on an empty queue must either report a precise token/inventory blocker or print the bounded prompt without creating a task.
