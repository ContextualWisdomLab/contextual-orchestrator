"""Fugu / Conductor / TRINITY compute allocation over a discovered pool."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.credentials import InMemoryCredentialBackend, register_credential, set_backend  # noqa: E402
from contextual_orchestrator.model_discovery import apply_discovered_pool  # noqa: E402


def test_conduct_assigns_trinity_roles_from_discovered_tags() -> None:
    set_backend(InMemoryCredentialBackend())
    register_credential("NVIDIA_NIM_API_KEY", "nvapi-test")
    orchestrator = TaskOrchestrator([ModelAgent("seed_agent", "mock-seed", tags=("reasoning",))])

    def fetch(endpoint, key):
        return {
            "data": [
                {"id": "nvidia/nemotron-3-ultra-550b-a55b"},
                {"id": "nvidia/nemotron-3-super-120b-a12b"},
                {"id": "qwen/qwen2.5-coder-32b"},
            ]
        }

    apply_discovered_pool(orchestrator, fetcher=fetch)
    orchestrator.agents = [replace(agent, base_url="mock://local") for agent in orchestrator.agents]
    result = orchestrator.conduct(
        [{"role": "user", "content": "Analyze the architecture, implement the parser, and verify risks."}]
    )
    roles = [step["role"] for step in result["trace"]]
    assert roles == ["thinker", "worker", "verifier", "synthesizer"]
    thinker = next(agent for agent in orchestrator.agents if agent.id == result["trace"][0]["agent_id"])
    worker = next(agent for agent in orchestrator.agents if agent.id == result["trace"][1]["agent_id"])
    verifier = next(agent for agent in orchestrator.agents if agent.id == result["trace"][2]["agent_id"])
    assert "planning" in thinker.tags or "reasoning" in thinker.tags
    assert "coding" in worker.tags or "reasoning" in worker.tags
    assert "review" in verifier.tags or "verification" in verifier.tags
    set_backend(None)


def test_fugu_route_prefers_known_cheaper_capable_worker() -> None:
    cheap = ModelAgent(
        "small_coder",
        "super-120b",
        tags=("coding", "reasoning", "cheap"),
        priority=1,
        price_per_million=0.4,
        price_status="known",
        discovery_source="live",
    )
    expensive = ModelAgent(
        "ultra_coder",
        "ultra-550b",
        tags=("coding", "reasoning", "planning"),
        priority=1,
        price_per_million=4.0,
        price_status="known",
        discovery_source="live",
    )
    orchestrator = TaskOrchestrator([expensive, cheap])
    result = orchestrator.route_once([{"role": "user", "content": "Write one function."}])
    assert result["mode"] == "route"
    assert result["trace"][0]["agent_id"] == "small_coder"
    assert result["trace"][0]["selection_reason"] == "capability_then_known_cost"


if __name__ == "__main__":  # pragma: no cover
    test_conduct_assigns_trinity_roles_from_discovered_tags()
    test_fugu_route_prefers_known_cheaper_capable_worker()
    print("ok")
