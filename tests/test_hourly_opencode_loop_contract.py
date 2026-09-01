"""Contract for the hourly OpenCode maintenance loop."""

from pathlib import Path

import yaml


def test_hourly_loop_uses_the_local_auto_orchestrator_without_copilot_token() -> None:
    """Keep scheduled agent traffic on the seeded gateway and required key set."""
    workflow = Path(".github/workflows/opencode-hourly-loop.yml").read_text()
    prompt = Path(".github/opencode/hourly-loop-prompt.md").read_text()

    assert 'cron: "23 * * * *"' in workflow
    assert "--auto-discover-model-agents" in workflow
    assert workflow.count("contextual_orchestrator_gateway/orchestrator/auto") == 2
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
    assert "while :; do" in workflow
    assert "gateway_pid=$!" in workflow
    assert 'kill -0 "$gateway_pid"' in workflow
    assert "gateway exited before becoming healthy" in workflow
    document = yaml.safe_load(workflow)
    loop = document["jobs"]["loop"]
    steps = loop["steps"]
    maintenance_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Run the hourly loop agent"
    )
    setup_budget = sum(
        step["timeout-minutes"] for step in steps[:maintenance_index]
    )
    maintenance_budget = steps[maintenance_index]["timeout-minutes"]
    failure_evidence_budget = steps[-1]["timeout-minutes"]
    assert maintenance_budget >= 120
    assert loop["timeout-minutes"] >= (
        setup_budget + maintenance_budget + failure_evidence_budget
    )
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
