"""Conductor-style generated workflows (arXiv:2512.04388).

The paper's core mechanism: the coordinator GENERATES the workflow — natural-language
subtasks, a worker assignment, and an access list per step — instead of a fixed
template. These assert the generated plan executes, access lists actually isolate
step context, invalid plans fall back to the template, and the default is unchanged.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402


PLAN = {
    "steps": [
        {"id": 0, "role": "worker", "agent_id": "general_agent", "subtask": "Draft the solution.", "access": []},
        {"id": 1, "role": "worker", "agent_id": "general_agent", "subtask": "Draft an independent alternative.", "access": []},
        {"id": 2, "role": "verifier", "agent_id": "general_agent", "subtask": "Compare both drafts for errors.", "access": [0, 1]},
        {"id": 3, "role": "synthesizer", "agent_id": "general_agent", "subtask": "Merge into the final answer.", "access": [1, 2]},
    ]
}


class _PlannerClient(ModelClient):
    """First chat call (the planner) returns a scripted plan; later calls echo like mock."""

    def __init__(self, plan_text: str) -> None:
        super().__init__()
        self.plan_text = plan_text
        self.calls: list[list[dict]] = []

    def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
        self.calls.append(messages)
        if len(self.calls) == 1:
            return self.plan_text
        return f"step-output({len(self.calls) - 1})"


def _orch(plan_text: str) -> tuple[TaskOrchestrator, _PlannerClient]:
    client = _PlannerClient(plan_text)
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "model-x", tags=("reasoning", "writing", "planning", "research"))],
        client=client,
    )
    orchestrator.policy = replace(orchestrator.policy, workflow_planning="generated")
    return orchestrator, client


def test_generated_plan_executes_with_natural_language_subtasks() -> None:
    orchestrator, client = _orch(json.dumps(PLAN))
    result = orchestrator.conduct([{"role": "user", "content": "solve the hard problem"}])

    assert result["plan_source"] == "generated"
    assert [row["subtask"] for row in result["trace"]] == [s["subtask"] for s in PLAN["steps"]]
    assert result["answer"] == "step-output(4)"  # the synthesizer (last step) answers
    assert len(client.calls) == 5  # 1 planner call + 4 steps


def test_access_lists_actually_isolate_context() -> None:
    orchestrator, client = _orch(json.dumps(PLAN))
    orchestrator.conduct([{"role": "user", "content": "solve the hard problem"}])
    # client.calls: [planner, step0, step1, step2, step3]; step outputs are step-output(n).
    step1_prompt = client.calls[2][1]["content"]
    step2_prompt = client.calls[3][1]["content"]
    step3_prompt = client.calls[4][1]["content"]

    assert "step-output(1)" not in step1_prompt  # access [] -> sees no prior output
    assert "step-output(1)" in step2_prompt and "step-output(2)" in step2_prompt  # access [0,1]
    assert "step-output(1)" not in step3_prompt  # access [1,2] excludes step 0
    assert "step-output(2)" in step3_prompt and "step-output(3)" in step3_prompt


def test_planner_prompt_lists_the_agent_pool() -> None:
    orchestrator, client = _orch(json.dumps(PLAN))
    orchestrator.conduct([{"role": "user", "content": "solve it"}])
    planner_system = client.calls[0][0]["content"]
    assert "workflow conductor" in planner_system
    assert "general_agent" in planner_system  # pool advertised to the planner


def test_invalid_plan_falls_back_to_template() -> None:
    orchestrator, _ = _orch("I think we should split the work. No JSON here.")
    result = orchestrator.conduct([{"role": "user", "content": "solve the hard problem"}])
    assert result["plan_source"] == "template_fallback"
    assert len(result["trace"]) == 4  # fixed thinker/worker/verifier/synthesizer template


def test_default_template_unchanged() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "model-x", tags=("reasoning", "writing", "planning", "research"))]
    )
    result = orchestrator.conduct([{"role": "user", "content": "analyze and verify this deeply"}])
    assert result["plan_source"] == "template"
    assert [row["role"] for row in result["trace"]] == ["thinker", "worker", "verifier", "synthesizer"]


def test_plan_validation_rejects_structural_problems() -> None:
    orchestrator, _ = _orch("{}")
    parse = orchestrator._parse_workflow_plan
    cases = [
        "no json at all",
        json.dumps({"steps": [{"id": 0, "role": "worker", "subtask": "only one step", "access": []}]}),
        json.dumps({"steps": [
            {"id": 0, "role": "worker", "subtask": "a", "access": []},
            {"id": 5, "role": "synthesizer", "subtask": "b", "access": []}]}),  # non-sequential id
        json.dumps({"steps": [
            {"id": 0, "role": "wizard", "subtask": "a", "access": []},
            {"id": 1, "role": "synthesizer", "subtask": "b", "access": []}]}),  # unknown role
        json.dumps({"steps": [
            {"id": 0, "role": "worker", "subtask": "a", "access": [1]},
            {"id": 1, "role": "synthesizer", "subtask": "b", "access": []}]}),  # forward access
        json.dumps({"steps": [
            {"id": 0, "role": "worker", "subtask": "a", "access": []},
            {"id": 1, "role": "verifier", "subtask": "b", "access": [0]}]}),  # verifier can't answer
    ]
    for case in cases:
        raised = False
        try:
            parse(case)
        except ValueError:
            raised = True
        assert raised, f"should reject: {case[:60]}"


def test_unknown_agent_id_is_reselected_not_fatal() -> None:
    plan = json.dumps({"steps": [
        {"id": 0, "role": "worker", "agent_id": "made_up_agent", "subtask": "do the work", "access": []},
        {"id": 1, "role": "synthesizer", "agent_id": "general_agent", "subtask": "answer", "access": [0]},
    ]})
    orchestrator, _ = _orch(plan)
    result = orchestrator.conduct([{"role": "user", "content": "solve"}])
    assert result["plan_source"] == "generated"
    assert result["trace"][0]["agent_id"] == "general_agent"  # reselected from the real pool


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
