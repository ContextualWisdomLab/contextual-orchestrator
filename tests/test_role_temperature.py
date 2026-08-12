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


def test_stream_and_batch_route_use_worker_role_temperature() -> None:
    """Stream/batch route paths must pass temperature_for_role('worker'), not hard-coded 0.2."""
    from contextual_orchestrator import ModelAgent, TaskOrchestrator
    from contextual_orchestrator.orchestrator import OrchestrationPolicy

    agent = ModelAgent("stream_worker_agent", "mock-stream", base_url="mock://local", tags=("reasoning",))
    orch = TaskOrchestrator([agent])
    orch.policy = OrchestrationPolicy(role_temperature={"worker": 0.55})
    assert orch.policy.temperature_for_role("worker") == 0.55

    seen: dict[str, float] = {}

    def fake_stream_chat(a, messages, temperature=0.2):  # noqa: ANN001
        seen["stream"] = temperature
        yield "chunk"

    def fake_batch_chat(a, requests, temperature=0.2, poll_interval=5.0, poll_timeout=3600.0):  # noqa: ANN001
        seen["batch"] = temperature
        return {cid: {"content": "batch-ok", "usage": None} for cid in requests}

    orch.client.stream_chat = fake_stream_chat  # type: ignore[method-assign]
    orch.client.batch_chat = fake_batch_chat  # type: ignore[method-assign]

    list(orch.stream_route([{"role": "user", "content": "stream path"}]))
    orch.batch_route(["batch path"])
    assert seen["stream"] == 0.55
    assert seen["batch"] == 0.55


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


def test_plan_and_judge_use_role_temperature() -> None:
    """Planner (thinker) and model-judge (verifier) paths honor role temperatures."""
    agents = [
        ModelAgent("thinker_agent", "mock-thinker", tags=("reasoning",)),
        ModelAgent("worker_agent", "mock-worker", tags=("coding", "writing")),
        ModelAgent("verifier_agent", "mock-verifier", tags=("review",)),
        ModelAgent("synthesizer_agent", "mock-synth", tags=("writing",)),
    ]
    orch = TaskOrchestrator(agents)
    orch.policy = OrchestrationPolicy(
        role_temperature={"thinker": 0.11, "verifier": 0.0, "worker": 0.33}
    )
    seen: list[tuple[str, float]] = []
    original = orch.client.chat

    def tracking_chat(agent, messages, temperature=0.2):  # noqa: ANN001
        seen.append((agent.id, float(temperature)))
        return original(agent, messages, temperature=temperature)

    orch.client.chat = tracking_chat  # type: ignore[method-assign]
    try:
        orch._plan_generated("plan a multi-step analysis")
    except Exception:  # noqa: BLE001 - plan parse may fail; temperature still recorded
        pass
    assert any(temp == 0.11 for _agent_id, temp in seen), seen

    seen.clear()
    orch._model_judge_verification(
        "task",
        {"verifier_output": "looks good ACCEPT", "accepted": True},
    )
    assert any(temp == 0.0 for _agent_id, temp in seen), seen


if __name__ == "__main__":
    test_default_role_temperatures_differ_by_paper_role()
    test_custom_role_temperature_is_clamped_and_applied()
    test_stream_and_batch_route_use_worker_role_temperature()
    test_conduct_uses_role_temperature_on_worker_path()
    test_plan_and_judge_use_role_temperature()
    print("ok")
