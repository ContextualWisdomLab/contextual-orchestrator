from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict[str, str]]]] = []

    def chat(self, agent: ModelAgent, messages, temperature: float = 0.2) -> str:
        self.calls.append((agent.id, messages))
        last = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        return f"{agent.id}:{len(self.calls)}:{last[:20]}"


def build(client: RecordingClient | None = None) -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent("planner_agent", "mock-planner", tags=("planning", "reasoning")),
            ModelAgent("builder_agent", "mock-builder", tags=("coding", "implementation")),
            ModelAgent("reviewer_agent", "mock-reviewer", tags=("verification", "security", "review")),
        ],
        client=client,
    )


def test_run_records_workflow_and_access_report() -> None:
    client = RecordingClient()
    orchestrator = build(client)
    result = orchestrator.run([{"role": "user", "content": "Analyze this issue, implement it, verify the risk, then synthesize."}], mode="auto")

    run_id = result["workflow_run_id"]
    workflow_run = orchestrator.get_workflow_run(run_id)
    access_report = orchestrator.get_access_report(run_id)

    assert workflow_run["workflow_run_id"] == run_id
    assert workflow_run["mode"] == "conduct"
    assert len(workflow_run["trace"]) == 4
    assert len(access_report["steps"]) == len(workflow_run["trace"])
    assert access_report["steps"][1]["access"] == [0]
    assert access_report["steps"][2]["access"] == [0, 1]
    assert workflow_run["policy_snapshot"]["workflow_steps"] == ["thinker", "worker", "verifier", "synthesizer"]


def test_agent_patch_updates_governance_fields() -> None:
    orchestrator = build()
    updated = orchestrator.patch_agent(
        "default",
        "builder_agent",
        {"status": "disabled", "priority": 9, "tags": ["coding", "orchestration"], "provider_exclusions": ["worker"]},
    )

    assert updated["status"] == "disabled"
    assert updated["priority"] == 9
    assert updated["tags"] == ["coding", "orchestration"]
    assert updated["provider_exclusions"] == ["worker"]
    assert updated["id"] == "builder_agent"


def test_evaluation_replay_collects_workflow_run_refs() -> None:
    orchestrator = build()
    evaluation = orchestrator.run_evaluation(["first", "second", "third"], mode="route")

    assert evaluation["prompt_count"] == 3
    assert len(evaluation["workflow_run_ids"]) == 3
    assert evaluation["success_count"] == 3
    for run_id in evaluation["workflow_run_ids"]:
        workflow_run = orchestrator.get_workflow_run(run_id)
        assert workflow_run["mode"] == "route"


def test_pagination_supports_run_and_agent_views() -> None:
    orchestrator = build()
    for i in range(15):
        orchestrator.run([{"role": "user", "content": f"Route request {i}"}], mode="route")

    first = orchestrator.list_recent_runs(page_number=1, page_size=10)
    second = orchestrator.list_recent_runs(page_number=2, page_size=10)

    assert len(first) == 10
    assert len(second) == 5
    assert first[0]["workflow_run_id"] != second[0]["workflow_run_id"]

    agents = orchestrator.list_agents(page_number=1, page_size=2)
    assert len(agents) == 2
    assert agents[0]["id"] == "planner_agent"

    error_thrown = False
    try:
        orchestrator.list_agents(page_number=0, page_size=1)
    except ValueError:
        error_thrown = True
    assert error_thrown
