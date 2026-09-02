"""Contract for the hourly OpenCode maintenance loop."""

from pathlib import Path


def test_hourly_loop_uses_the_local_free_orchestrator_without_copilot_token() -> None:
    """Keep scheduled agent traffic on the governed free pool and required key set."""
    workflow = Path(".github/workflows/opencode-hourly-loop.yml").read_text()
    prompt = Path(".github/opencode/hourly-loop-prompt.md").read_text()

    assert 'cron: "23 * * * *"' in workflow
    assert "--auto-discover-model-agents" in workflow
    assert workflow.count("contextual_orchestrator_gateway/orchestrator/free") == 2
    assert "contextual_orchestrator_gateway/orchestrator/auto" not in workflow
    for credential_name in (
        "BYTEZ_API_KEY",
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ):
        assert f"{credential_name}: ${{{{ secrets.{credential_name} }}}}" in workflow
    assert "COPILOT_GITHUB_TOKEN" not in workflow
    assert "node scripts/ci/install_locked_opencode.mjs" in workflow
    assert "python -m pip install --require-hashes -r requirements.lock" in workflow
    assert "--auth-token-key CONTEXTUAL_ORCHESTRATOR_TOKEN" in workflow
    assert "--auth-token=" not in workflow
    assert "--auth-token " not in workflow
    assert "GATEWAY_BEARER_TOKEN" not in workflow
    assert "umask 077" in workflow
    installer = Path("scripts/ci/install_locked_opencode.mjs").read_text()
    assert "optionalDependencies" in installer
    assert "installed.version !== expectedVersion" in installer
    assert "npm install" not in installer
    assert 'spawnSync(target, ["--version"]' in installer
    assert "no lockfile-authorized OpenCode binary passed its version check" in installer
    assert "fetch(" not in installer
    assert "postinstall.mjs" not in workflow
    assert "pull-requests: write" in workflow
    assert "docs/product-technical-gap-baseline.md" in workflow
    assert "Retry-After" in prompt
    assert "inventing a retry count" in prompt
    assert "Other agents may have pushed concurrently" in prompt
    assert "normal merge" in prompt
    assert "clear redundancy or" in prompt
    assert "Rust is authoritative" in prompt
    assert "LLM-token arithmetic in Python" in prompt


def test_hourly_loop_has_no_repository_authored_model_job_deadline() -> None:
    """Do not terminate model-backed maintenance by a hand-selected wall-clock cap."""
    workflow = Path(".github/workflows/opencode-hourly-loop.yml").read_text()
    prompt = Path(".github/opencode/hourly-loop-prompt.md").read_text()

    loop_header = workflow.split("\n  loop:\n", 1)[1].split("\n    permissions:\n", 1)[0]
    assert "timeout-minutes:" not in loop_header
    assert "at most 45 minutes" not in prompt
    assert "highest-leverage gap" not in prompt
    assert "Do not impose a repository-authored elapsed-time limit on model work" in prompt
    assert "do not invent an ordering" in prompt
