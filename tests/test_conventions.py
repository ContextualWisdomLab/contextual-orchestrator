from __future__ import annotations

from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.conventions import is_two_word_snake_case, require_object_name  # noqa: E402


def test_two_word_snake_case_rule() -> None:
    assert is_two_word_snake_case("agent_pool")
    assert is_two_word_snake_case("workflow_step")
    assert not is_two_word_snake_case("agent")
    assert not is_two_word_snake_case("agentPool")


def test_example_agent_ids_follow_object_name_rule() -> None:
    config_path = Path(__file__).resolve().parents[1] / "examples" / "agents.mock.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))

    for agent in config["agents"]:
        require_object_name(agent["id"], "agent.id")


if __name__ == "__main__":
    test_two_word_snake_case_rule()
    test_example_agent_ids_follow_object_name_rule()
    print("ok")
