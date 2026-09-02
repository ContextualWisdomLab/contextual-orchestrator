"""Contract for the hourly OpenCode maintenance loop."""

from pathlib import Path


def test_hourly_loop_uses_the_local_free_orchestrator_without_copilot_token() -> None:
    """Keep scheduled agent traffic on the seeded gateway and required key set.

    The requested pool id is the fixed "orchestrator/free" (zero-cost,
    ZDR-first), not "orchestrator/auto" -- see docs/adr/
    0007-hourly-loop-orchestrator-free-pool-pin.md. This matches every other
    OpenCode/Noema consumer across the ecosystem (only Strix's
    security-analysis use case has a documented exception onto "auto").
    "--auto-discover-model-agents" is a separate concern: the gateway's own
    provider/credential discovery, not which pool OpenCode routes through.
    """
    workflow = Path(".github/workflows/opencode-hourly-loop.yml").read_text()
    prompt = Path(".github/opencode/hourly-loop-prompt.md").read_text()

    assert 'cron: "23 * * * *"' in workflow
    assert "--auto-discover-model-agents" in workflow
    assert workflow.count("contextual_orchestrator_gateway/orchestrator/free") == 2
    assert '"orchestrator/free":' in workflow
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
