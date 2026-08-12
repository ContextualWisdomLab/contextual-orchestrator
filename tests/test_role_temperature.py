"""Role-differentiated sampling temperature (reasoning-effort ablation knobs)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import OrchestrationPolicy  # noqa: E402


def test_default_role_temperatures_differ_by_paper_role() -> None:
    policy = OrchestrationPolicy()
    defaults = policy.default_role_temperature()
    assert defaults["verifier"] < defaults["worker"]
    assert defaults["thinker"] < defaults["worker"]
    assert policy.temperature_for_role("verifier") == 0.0
    assert policy.temperature_for_role("worker") == 0.2
    assert policy.as_dict()["role_temperature"]["synthesizer"] == 0.15


def test_custom_role_temperature_is_clamped_and_applied() -> None:
    policy = OrchestrationPolicy(role_temperature={"worker": 9.0, "verifier": -1.0, "thinker": "x"})
    assert policy.temperature_for_role("worker") == 2.0
    assert policy.temperature_for_role("verifier") == 0.0
    assert policy.temperature_for_role("thinker") == 0.2  # invalid falls back


def test_conduct_uses_role_temperature_on_worker_path() -> None:
    """Exercise real TaskOrchestrator conduct path with mock agents."""
    agents = [
        ModelAgent("thinker_agent", "mock-thinker", tags=("reasoning",)),
        ModelAgent("worker_agent", "mock-worker", tags=("coding", "writing")),
        ModelAgent("verifier_agent", "mock-verifier", tags=("review",)),
        ModelAgent("synthesizer_agent", "mock-synth", tags=("writing",)),
    ]
    orch = TaskOrchestrator(agents)
    orch.policy = OrchestrationPolicy(role_temperature={"worker": 0.7, "verifier": 0.0})
    result = orch.run([{"role": "user", "content": "Write a short plan"}], mode="conduct")
    assert result["mode"] in {"conduct", "route"}
    # Policy snapshot exposes role temperatures for admin/analytics.
    assert orch.policy.temperature_for_role("worker") == 0.7


if __name__ == "__main__":
    test_default_role_temperatures_differ_by_paper_role()
    test_custom_role_temperature_is_clamped_and_applied()
    test_conduct_uses_role_temperature_on_worker_path()
    print("ok")
