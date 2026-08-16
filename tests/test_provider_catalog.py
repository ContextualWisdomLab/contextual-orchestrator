"""Paper-grounded contracts for the production multi-provider agent catalog.

Fugu (Sakana, 2026) requires a swappable worker pool behind one public API.
TRINITY (arXiv:2512.04695) needs thinker/worker/verifier capability tags.
Conductor (arXiv:2512.04388) needs those workers assignable by role.
FrugalGPT / RouteLLM / Hybrid LLM ground cost-aware multi-upstream selection.

The production seed is data, not mock-only, and must never include GitHub Models.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.conventions import require_object_name  # noqa: E402
from contextual_orchestrator.provider_catalog import (  # noqa: E402
    BYTEZ_OPENAI_BASE_URL,
    FORBIDDEN_CREDENTIAL_NAMES,
    FORBIDDEN_HOST_MARKERS,
    FORBIDDEN_MODEL_MARKERS,
    NIM_INTEGRATE_BASE_URL,
    OPENAI_API_BASE_URL,
    OPENROUTER_API_BASE_URL,
    ORG_CREDENTIAL_NAMES,
    PRODUCTION_SEED_PATH,
    catalog_allows_agent,
    load_production_seed,
)


ROOT = Path(__file__).resolve().parents[1]


def test_org_credential_names_are_exactly_the_five_actions_secrets() -> None:
    assert ORG_CREDENTIAL_NAMES == (
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "BYTEZ_API_KEY",
    )
    assert "COPILOT_GITHUB_TOKEN" not in ORG_CREDENTIAL_NAMES


def test_production_seed_file_exists_and_is_not_mock_only() -> None:
    assert PRODUCTION_SEED_PATH.is_file()
    payload = json.loads(PRODUCTION_SEED_PATH.read_text(encoding="utf-8"))
    agents = payload["agents"]
    assert len(agents) >= 6
    assert all(not str(item["base_url"]).startswith("mock://") for item in agents)


def test_production_seed_covers_required_upstreams_and_nemotron_models() -> None:
    agents = load_production_seed()
    by_key: dict[str, list[str]] = {}
    models = {agent.model for agent in agents}
    hosts = {agent.base_url for agent in agents}
    for agent in agents:
        by_key.setdefault(agent.credential_name, []).append(agent.id)
        require_object_name(agent.id, "agent.id")

    assert set(by_key) == set(ORG_CREDENTIAL_NAMES)
    assert NIM_INTEGRATE_BASE_URL in hosts
    assert OPENAI_API_BASE_URL in hosts
    assert OPENROUTER_API_BASE_URL in hosts
    assert BYTEZ_OPENAI_BASE_URL in hosts
    assert any("nemotron-super-49b" in model or "nemotron-super-49b" in model.replace("_", "-") for model in models)
    assert any("120b" in model.lower() and "nemotron" in model.lower() for model in models)
    assert any(agent.credential_key == "NVIDIA_NIM_API_KEY_SUB" for agent in agents)
    assert any(agent.credential_key == "NVIDIA_NIM_API_KEY" for agent in agents)


def test_production_seed_tags_support_route_and_conduct_roles() -> None:
    agents = load_production_seed()
    all_tags = {tag for agent in agents for tag in agent.tags}
    for required in ("coding", "review", "reasoning"):
        assert required in all_tags, f"catalog must tag {required} workers for Fugu route vs Conductor/TRINITY conduct"


def test_production_seed_rejects_github_models_and_copilot() -> None:
    raw = PRODUCTION_SEED_PATH.read_text(encoding="utf-8")
    lowered = raw.lower()
    for marker in (
        "github.com/models",
        "models.github.ai",
        "models.inference.ai.azure.com",
        "api.githubcopilot.com",
        "copilot_github_token",
        "gpt-5.6-luna",
        "gpt-5.6-terra",
    ):
        assert marker not in lowered
    for agent in load_production_seed():
        assert catalog_allows_agent(agent) is True


def test_catalog_allows_agent_rejects_github_models_shapes() -> None:
    from contextual_orchestrator import ModelAgent

    forbidden = [
        {
            "id": "github_models_agent",
            "model": "gpt-4o",
            "base_url": "https://models.github.ai/inference",
            "credential_key": "OPENAI_API_KEY",
        },
        {
            "id": "copilot_proxy_agent",
            "model": "gpt-5.6-luna",
            "base_url": "https://api.openai.com/v1",
            "credential_key": "OPENAI_API_KEY",
        },
        {
            "id": "legacy_copilot_agent",
            "model": "gpt-5.5",
            "base_url": "https://api.openai.com/v1",
            "credential_key": "COPILOT_GITHUB_TOKEN",
        },
    ]
    for payload in forbidden:
        assert catalog_allows_agent(payload) is False
    with pytest.raises(ValueError, match="GitHub Models"):
        ModelAgent(
            "blocked_github_agent",
            "gpt-5.6-terra",
            "https://models.inference.ai.azure.com/v1",
            credential_key="COPILOT_GITHUB_TOKEN",
        )


def test_forbidden_markers_are_explicit() -> None:
    assert "models.github.ai" in FORBIDDEN_HOST_MARKERS
    assert "COPILOT_GITHUB_TOKEN" in FORBIDDEN_CREDENTIAL_NAMES
    assert "gpt-5.6-luna" in FORBIDDEN_MODEL_MARKERS
    assert "gpt-5.6-terra" in FORBIDDEN_MODEL_MARKERS


def test_example_agent_ids_in_every_seed_follow_object_name_rule() -> None:
    for path in (ROOT / "examples").glob("agents.*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for agent in payload["agents"]:
            require_object_name(agent["id"], "agent.id")


if __name__ == "__main__":  # pragma: no cover
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
