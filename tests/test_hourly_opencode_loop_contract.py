"""Contract for the hourly OpenCode maintenance loop."""

from pathlib import Path


def test_hourly_loop_uses_the_local_auto_orchestrator_without_copilot_token() -> None:
    """Keep scheduled agent traffic on the seeded gateway and required key set."""
    workflow = Path(".github/workflows/opencode-hourly-loop.yml").read_text()

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
    assert "node node_modules/opencode-ai/postinstall.mjs" in workflow
    assert "pull-requests: write" in workflow
    assert "docs/product-technical-gap-baseline.md" in workflow
