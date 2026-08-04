"""Contract tests for the hourly pull-request-first product-development loop."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "hourly-product-development.yml"
TESTS_WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"


def _workflow_text() -> str:
    """Return the workflow source after proving the scheduled contract exists."""

    assert WORKFLOW.is_file(), "hourly product-development workflow is missing"
    return WORKFLOW.read_text(encoding="utf-8")


def test_hourly_loop_is_scheduled_and_single_flight() -> None:
    """The loop runs hourly without cancelling a task that is already dispatching."""

    workflow = _workflow_text()

    assert 'cron: "47 * * * *"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "hourly-product-development-${{ github.repository }}" in workflow
    assert "cancel-in-progress: false" in workflow


def test_hourly_loop_is_pull_request_first_and_fails_closed() -> None:
    """No development session starts while PR ownership is ambiguous."""

    workflow = _workflow_text()

    pull_request_gate = workflow.index("gh pr list")
    agent_session = workflow.index("opencode run")
    assert pull_request_gate < agent_session
    assert "reason=pull_request_inventory_unavailable" in workflow
    assert "reason=open_pull_request" in workflow
    assert "reason=nim_api_key_unavailable" in workflow
    assert "steps.gate.outputs.dispatch == 'true'" in workflow


def test_hourly_loop_brokers_nim_without_exposing_the_secret_to_opencode() -> None:
    """Only a hardened broker receives the NIM key; the coding agent never does."""

    workflow = _workflow_text()

    assert "NVIDIA_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}" in workflow
    assert "REPOSITORY_TOKEN: ${{ github.token }}" in workflow
    assert "scripts/ci/nim_credential_broker.py" in workflow
    assert '"baseURL": "http://nim-proxy:8001/v1"' in workflow
    assert '"apiKey": "brokered-by-local-proxy"' in workflow
    assert "docker network create --internal" in workflow
    assert "docker network connect --alias nim-proxy" in workflow
    assert "--read-only" in workflow
    assert "--cap-drop=ALL" in workflow
    assert "no-new-privileges" in workflow
    assert "--pids-limit" in workflow
    assert "$GITHUB_WORKSPACE/.git:/workspace/.git:ro" in workflow
    assert "OPENCODE_DISABLE_PROJECT_CONFIG=1" in workflow
    assert "OPENCODE_DISABLE_CLAUDE_CODE=1" in workflow
    assert "persist-credentials: false" in workflow
    assert 'OPENCODE_VERSION: "1.17.13"' in workflow
    assert "sha256sum -c -" in workflow
    assert "/var/run/docker.sock" not in workflow

    agent_start = workflow.index("- name: Run the isolated NVIDIA NIM development agent")
    agent_end = workflow.index("- name: Validate isolated candidate filesystem", agent_start)
    agent_step = workflow[agent_start:agent_end]
    assert "NVIDIA_API_KEY" not in agent_step
    assert "GH_TOKEN" not in agent_step
    assert "GITHUB_TOKEN" not in agent_step
    assert "ACTIONS_ID_TOKEN_REQUEST_TOKEN" not in agent_step

    assert "contents: write" not in workflow
    assert "pull-requests: write" not in workflow
    assert "gh pr create" in workflow
    assert "COPILOT_GITHUB_TOKEN" not in workflow
    assert "/agents/repos" not in workflow
    assert "gh pr merge" not in workflow


def test_hourly_loop_rejects_special_files_before_patch_packaging() -> None:
    """Agent-created links, devices, sockets, and oversized trees fail closed."""

    workflow = _workflow_text()

    assert "os.walk(root, followlinks=False)" in workflow
    assert "stat.S_ISREG(mode)" in workflow
    assert "stat.S_ISDIR(mode)" in workflow
    assert "unsupported candidate filesystem entry" in workflow
    assert "candidate filesystem exceeds 20000 entries" in workflow
    assert "candidate filesystem exceeds 256 MiB" in workflow
    assert "git status --porcelain" in workflow


def test_hourly_loop_separates_agent_execution_from_privileged_publication() -> None:
    """Untrusted agent output crosses a validated artifact boundary to a fresh job."""

    workflow = _workflow_text()

    assert "develop-product-gap:" in workflow
    assert "publish-product-gap:" in workflow
    assert "needs: develop-product-gap" in workflow
    assert "actions: read" in workflow
    assert "id-token: write" in workflow
    assert "actions/upload-artifact@330a01c490aca151604b8cf639adc76d48f6c5d4" in workflow
    assert 'gh run download "$GITHUB_RUN_ID"' in workflow
    assert "candidate.patch" in workflow
    assert "git apply --check --binary --whitespace=error" in workflow
    assert "core.hooksPath" in workflow
    assert "new file mode 120000" in workflow
    assert "new file mode 160000" in workflow
    assert 'left.parts[0] == ".github"' in workflow
    assert "NVIDIA_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}" not in workflow[
        workflow.index("publish-product-gap:") :
    ]
    assert workflow.index("opencode run") < workflow.index("publish-product-gap:")


def test_publication_uses_an_app_token_so_created_prs_trigger_required_checks() -> None:
    """The trusted publisher fails closed unless it obtains a workflow-triggering app token."""

    workflow = _workflow_text()
    publisher = workflow[workflow.index("publish-product-gap:") :]

    assert "Exchange OpenCode app token for autonomous PR publication" in publisher
    assert "OIDC_AUDIENCE: opencode-github-action" in publisher
    assert "/exchange_github_app_token" in publisher
    assert "available=false" in publisher
    assert "available=true" in publisher
    assert "token=$app_token" in publisher
    assert "steps.publisher_app_token.outputs.available != 'true'" in publisher
    assert "GH_TOKEN: ${{ steps.publisher_app_token.outputs.token }}" in publisher
    assert "GH_TOKEN: ${{ github.token }}" in publisher
    assert "contents: read" in publisher
    assert "pull-requests: read" in publisher
    assert "contents: write" not in publisher
    assert "pull-requests: write" not in publisher


def test_broker_has_exact_statement_branch_and_docstring_gates() -> None:
    """The new credential-bearing production module is held to the 100% policy."""

    tests_workflow = TESTS_WORKFLOW.read_text(encoding="utf-8")

    assert "requirements-opencode-review-ci.txt" in tests_workflow
    assert "coverage run --branch" in tests_workflow
    assert "--source=scripts.ci.nim_credential_broker" in tests_workflow
    assert "tests/test_nim_credential_broker.py" in tests_workflow
    assert "coverage report --fail-under=100" in tests_workflow
    assert "--include=scripts/ci/nim_credential_broker.py" in tests_workflow
    assert "interrogate -f 100" in tests_workflow
    assert "scripts/ci/nim_credential_broker.py" in tests_workflow


def test_hourly_loop_prompt_preserves_commercial_and_architecture_contracts() -> None:
    """The delegated task carries the repository's non-negotiable product gates."""

    workflow = _workflow_text()

    required_prompt_terms = (
        "ContextualWisdomLab/contextual-orchestrator",
        "single highest-value buyer-visible",
        "test-first",
        "100% production statement and branch coverage",
        "100% production docstring coverage",
        "two-word-or-longer snake_case",
        "modular MSA",
        "ContextualWisdomLab/.github",
        "naruon",
        "NVIDIA_NIM_API_KEY",
        "GET /v1/models",
        "hypothetical paid cost",
        "CHANGELOG.md",
        "Semantic Versioning",
        "Figma or Product Design",
        "Do not merge, publish, release, or bypass reviews",
        "exactly one bounded pull request",
    )
    for term in required_prompt_terms:
        assert term in workflow
