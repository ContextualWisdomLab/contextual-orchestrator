"""CI sidecar contract: OpenCode/Strix call this repo as one OpenAI-compatible provider.

The org no longer uses GitHub Models. ContextualWisdomLab/.github OpenCode review
registers the five Actions secrets into the KV, serves loopback-only, and points
OpenCode at http://127.0.0.1:8000/v1 with model contextual-orchestrator.

App unit tests (tests.yml) and the Security workflow stay secret-free.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_opencode_sidecar_doc_states_exact_env_port_and_smoke_curl() -> None:
    text = read_text("docs/opencode-sidecar.md")
    for expected in (
        "http://127.0.0.1:8000/v1",
        "contextual-orchestrator",
        "CONTEXTUAL_ORCHESTRATOR_TOKEN",
        "CONTEXTUAL_ORCHESTRATOR_INFERENCE_TOKEN",
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "BYTEZ_API_KEY",
        "register-credential",
        "seed-provider-catalog",
        "--allow-public-bind",
        "/v1/chat/completions",
        "examples/agents.production.json",
        "GitHub Models",
    ):
        assert expected in text
    assert "do not pass --allow-public-bind in ci" in text.lower()


def test_sidecar_workflow_is_not_the_app_test_job_and_stays_loopback() -> None:
    workflow = read_text(".github/workflows/opencode-sidecar.yml")
    tests = read_text(".github/workflows/tests.yml")
    security = read_text(".github/workflows/security.yml")

    assert "seed-provider-catalog" in workflow
    assert "127.0.0.1" in workflow
    assert "--allow-public-bind" not in workflow
    assert "workflow_call:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "secrets.NVIDIA_NIM_API_KEY" in workflow
    assert "secrets.OPENAI_API_KEY" in workflow
    assert "pull_request:" not in workflow  # never inject provider secrets into PR app tests

    for secret_name in (
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "BYTEZ_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ):
        assert f"secrets.{secret_name}" not in tests
        assert f"secrets.{secret_name}" not in security


def test_agents_and_changelog_drop_github_models_as_the_opencode_provider() -> None:
    agents = read_text("AGENTS.md")
    changelog = read_text("CHANGELOG.md")
    doctoring = read_text("docs/doctoring/provider-catalog.md")
    assert "GitHub Models" in agents
    assert "no longer uses GitHub Models" in agents or "no longer use GitHub Models" in agents
    assert "get_credential" in agents
    assert "os.environ.get(agent.api_key_env)" not in agents
    assert "OpenCode" in changelog
    assert "APA" in doctoring
    assert "claim boundary" in doctoring.lower()
    assert "FrugalGPT" in doctoring


if __name__ == "__main__":  # pragma: no cover
    test_opencode_sidecar_doc_states_exact_env_port_and_smoke_curl()
    test_sidecar_workflow_is_not_the_app_test_job_and_stays_loopback()
    test_agents_and_changelog_drop_github_models_as_the_opencode_provider()
    print("ok")
