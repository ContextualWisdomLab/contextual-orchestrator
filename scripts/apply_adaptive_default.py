#!/usr/bin/env python3
"""Apply the adaptive performance-cost default to the current PR branch."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feat/reasoning-effort-and-verify-mode"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace exactly one expected source fragment."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    """Patch code and regression tests."""
    branch = os.environ.get("GITHUB_REF_NAME", EXPECTED_BRANCH)
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"refusing to mutate unexpected branch: {branch}")

    path = ROOT / "contextual_orchestrator" / "orchestrator.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(text, "import json\nimport os\n", "import json\nimport math\nimport os\n", "math import")
    text = replace_once(
        text,
        "DEFAULT_COMMERCIAL_TARGET_VALUE_KRW = 2_000_000_000\n",
        "DEFAULT_COMMERCIAL_TARGET_VALUE_KRW = 2_000_000_000\n"
        "AUTO_ROUTING_OBJECTIVE = \"maximize_performance_then_minimize_cost\"\n"
        "AUTO_COST_POLICY = \"lowest_known_price_within_highest_capability_tier\"\n",
        "adaptive constants",
    )
    text = replace_once(
        text,
        '''            "verifier_required": self.verifier_required,
            "workflow_planning": self.workflow_planning,
''',
        '''            "verifier_required": self.verifier_required,
            "auto_routing_objective": AUTO_ROUTING_OBJECTIVE,
            "auto_cost_policy": AUTO_COST_POLICY,
            "workflow_planning": self.workflow_planning,
''',
        "policy snapshot",
    )
    text = replace_once(
        text,
        '''    COMPLEX_HINTS = (
        "analyze",
        "architecture",
        "develop",
        "implement",
        "verify",
        "security",
        "research",
        "paper",
        "multi-step",
        "workflow",
        "분석",
        "개발",
        "구현",
        "검증",
        "논문",
    )
''',
        '''    COMPLEX_HINTS = (
        "analyze",
        "architecture",
        "develop",
        "implement",
        "verify",
        "security",
        "research",
        "paper",
        "multi-step",
        "workflow",
        "분석",
        "개발",
        "구현",
        "검증",
        "논문",
    )
    VERIFICATION_HINTS = (
        "verify",
        "validate",
        "judge",
        "adjudicate",
        "review",
        "check",
        "evaluate",
        "assess",
        "confirm",
        "검증",
        "검토",
        "평가",
        "확인",
        "심사",
    )
''',
        "verification hints",
    )
    text = replace_once(
        text,
        '''    def _dispatch(
        self, messages: list[ChatMessage], mode: str, *, reasoning_effort: str | None = None
    ) -> dict[str, Any]:
        text = self._latest_user_text(messages)
        if mode == "verify":
            return self.route_and_verify(messages, reasoning_effort=reasoning_effort)
        if mode == "route" or (mode == "auto" and not self._needs_workflow(text)):
            return self.route_once(messages, reasoning_effort=reasoning_effort)
        return self.conduct(messages, reasoning_effort=reasoning_effort)

    def would_route(self, messages: list[ChatMessage], mode: str = "auto") -> bool:
        """True when this request takes the single-worker route path (vs the conduct workflow)."""
        text = self._latest_user_text(messages)
        return mode == "route" or (mode == "auto" and not self._needs_workflow(text))
''',
        '''    def _dispatch(
        self, messages: list[ChatMessage], mode: str, *, reasoning_effort: str | None = None
    ) -> dict[str, Any]:
        text = self._latest_user_text(messages)
        if mode == "route":
            return self.route_once(messages, reasoning_effort=reasoning_effort)
        if mode == "verify":
            return self.route_and_verify(messages, reasoning_effort=reasoning_effort)
        if mode == "conduct":
            return self.conduct(messages, reasoning_effort=reasoning_effort)

        decision = self._auto_routing_decision(text)
        if decision["selected_mode"] == "route":
            result = self.route_once(messages, reasoning_effort=reasoning_effort)
        elif decision["selected_mode"] == "verify":
            result = self.route_and_verify(messages, reasoning_effort=reasoning_effort)
        else:
            result = self.conduct(messages, reasoning_effort=reasoning_effort)
        trace = result.get("trace", [])
        selected_agent_ids = [
            str(step.get("served_agent_id", step.get("agent_id", "")))
            for step in trace
            if isinstance(step, dict)
        ]
        model_by_agent = {agent.id: agent.model for agent in self.agents}
        selected_models = [
            model_by_agent[agent_id]
            for agent_id in selected_agent_ids
            if agent_id in model_by_agent
        ]
        decision["selected_agent_ids"] = selected_agent_ids
        decision["selected_models"] = selected_models
        decision["unpriced_selected_models"] = [
            model for model in selected_models if self._model_price(model) is None
        ]
        result["routing_decision"] = decision
        return result

    def _auto_routing_decision(self, text: str) -> dict[str, Any]:
        """Choose route, verify, or conduct before cost-aware role assignment."""
        if self._needs_workflow(text):
            selected_mode = "conduct"
            quality_requirement = "verified_multi_agent_workflow"
            reason = "task_requires_verified_multi_agent_workflow"
        elif self._needs_verification(text):
            selected_mode = "verify"
            quality_requirement = "independent_verification_required"
            reason = "task_requires_bounded_independent_verification"
        else:
            selected_mode = "route"
            quality_requirement = "single_worker_sufficient"
            reason = "single_worker_meets_detected_quality_requirement"
        priced_agent_count = sum(
            1 for agent in self.agents if self._agent_price(agent) is not None
        )
        return {
            "objective": AUTO_ROUTING_OBJECTIVE,
            "requested_mode": "auto",
            "selected_mode": selected_mode,
            "quality_requirement": quality_requirement,
            "reason": reason,
            "cost_policy": AUTO_COST_POLICY,
            "priced_agent_count": priced_agent_count,
            "candidate_agent_count": len(self.agents),
            "selected_agent_ids": [],
            "selected_models": [],
            "unpriced_selected_models": [],
        }

    def would_route(self, messages: list[ChatMessage], mode: str = "auto") -> bool:
        """Return whether the request will use exactly one worker call."""
        if mode == "route":
            return True
        if mode != "auto":
            return False
        text = self._latest_user_text(messages)
        return self._auto_routing_decision(text)["selected_mode"] == "route"
''',
        "adaptive dispatch",
    )
    text = replace_once(
        text,
        '''            "policy_snapshot": self.policy.as_dict(),
            "verification": result.get("verification"),
''',
        '''            "policy_snapshot": self.policy.as_dict(),
            "verification": result.get("verification"),
            "routing_decision": result.get("routing_decision"),
''',
        "persist routing decision",
    )
    text = replace_once(
        text,
        '''    def _score_agent(self, agent: ModelAgent, role: str, lowered: str) -> tuple[int, int, str]:
        if agent.disabled:
            return (-20_000, len(agent.tags), agent.id)
        if role in agent.provider_exclusions:
            return (-10_000, len(agent.tags), agent.id)
        role_score = sum(3 for tag in agent.tags if tag in self.ROLE_TAGS.get(role, ()))
        domain_score = 0
        for tag, hints in self.DOMAIN_HINTS.items():
            if tag in agent.tags and any(hint in lowered for hint in hints):
                domain_score += 2
        return (role_score + domain_score + agent.priority, len(agent.tags), agent.id)
''',
        '''    def _model_price(self, model: str) -> float | None:
        """Return one valid configured model price, otherwise unknown."""
        value = self.price_per_million.get(model)
        if type(value) not in (int, float):
            return None
        normalized = float(value)
        if not math.isfinite(normalized) or normalized < 0:
            return None
        return normalized

    def _agent_price(self, agent: ModelAgent) -> float | None:
        """Return the valid configured output-token price for one agent."""
        return self._model_price(agent.model)

    def _score_agent(
        self, agent: ModelAgent, role: str, lowered: str
    ) -> tuple[int, int, float, int, str]:
        if agent.disabled:
            return (-20_000, 0, float("-inf"), len(agent.tags), agent.id)
        if role in agent.provider_exclusions:
            return (-10_000, 0, float("-inf"), len(agent.tags), agent.id)
        role_score = sum(3 for tag in agent.tags if tag in self.ROLE_TAGS.get(role, ()))
        domain_score = 0
        for tag, hints in self.DOMAIN_HINTS.items():
            if tag in agent.tags and any(hint in lowered for hint in hints):
                domain_score += 2
        price = self._agent_price(agent)
        return (
            role_score + domain_score + agent.priority,
            1 if price is not None else 0,
            -price if price is not None else float("-inf"),
            len(agent.tags),
            agent.id,
        )
''',
        "performance-cost ranking",
    )
    text = replace_once(
        text,
        '''    def _needs_workflow(self, text: str) -> bool:
        lowered = text.lower()
        hits = sum(1 for hint in self.COMPLEX_HINTS if hint in lowered)
        return hits >= self.policy.conduct_hint_threshold or len(text) > 700
''',
        '''    def _needs_workflow(self, text: str) -> bool:
        lowered = text.lower()
        hits = sum(1 for hint in self.COMPLEX_HINTS if hint in lowered)
        return hits >= self.policy.conduct_hint_threshold or len(text) > 700

    def _needs_verification(self, text: str) -> bool:
        """Return whether a bounded independent check is the minimum quality tier."""
        lowered = text.lower()
        return any(hint in lowered for hint in self.VERIFICATION_HINTS)
''',
        "verification detector",
    )
    path.write_text(text, encoding="utf-8")

    test_path = ROOT / "tests" / "test_adaptive_default_routing.py"
    if test_path.exists() and test_path.read_text(encoding="utf-8") != ADAPTIVE_TEST:
        raise RuntimeError("refusing to replace unexpected adaptive routing test")
    test_path.write_text(ADAPTIVE_TEST, encoding="utf-8")


ADAPTIVE_TEST = '''from contextual_orchestrator.orchestrator import ModelAgent, TaskOrchestrator


def _messages(text: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": text}]


def test_auto_route_uses_lowest_known_cost_within_top_performance_tier() -> None:
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(id="cheap_agent", model="cheap-model"),
            ModelAgent(id="expensive_agent", model="expensive-model"),
        ],
        price_per_million={"cheap-model": 1.0, "expensive-model": 12.0},
    )
    result = orchestrator.complete(_messages("Summarize this note."))
    assert result["mode"] == "route"
    assert result["trace"][0]["agent_id"] == "cheap_agent"
    assert result["routing_decision"]["objective"] == "maximize_performance_then_minimize_cost"
    assert result["routing_decision"]["cost_policy"] == "lowest_known_price_within_highest_capability_tier"
    assert result["routing_decision"]["selected_agent_ids"] == ["cheap_agent"]
    assert result["routing_decision"]["selected_models"] == ["cheap-model"]


def test_auto_keeps_higher_performance_tier_even_when_it_costs_more() -> None:
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(id="economy_agent", model="economy-model", priority=0),
            ModelAgent(id="premium_agent", model="premium-model", priority=1),
        ],
        price_per_million={"economy-model": 0.1, "premium-model": 100.0},
    )
    result = orchestrator.complete(_messages("Summarize this note."))
    assert result["trace"][0]["agent_id"] == "premium_agent"


def test_auto_uses_bounded_verify_path_when_one_verification_signal_is_present() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent(id="general_agent", model="general-model", tags=("reasoning", "verification"))],
        price_per_million={"general-model": 3.0},
    )
    result = orchestrator.complete(_messages("Verify this answer."))
    assert result["mode"] == "verify"
    assert result["routing_decision"]["quality_requirement"] == "independent_verification_required"
    assert result["routing_decision"]["selected_agent_ids"] == ["general_agent", "general_agent"]


def test_auto_conducts_complex_work_and_exposes_quality_requirement() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent(id="general_agent", model="general-model", tags=("planning", "reasoning", "verification", "writing"))],
        price_per_million={"general-model": 3.0},
    )
    result = orchestrator.complete(_messages("Analyze the architecture, implement the workflow, and verify security."))
    assert result["mode"] == "conduct"
    assert result["routing_decision"]["quality_requirement"] == "verified_multi_agent_workflow"
    assert result["routing_decision"]["selected_agent_ids"] == ["general_agent"] * 4


def test_auto_treats_invalid_or_missing_prices_as_unknown_cost() -> None:
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(id="priced_agent", model="priced-model"),
            ModelAgent(id="unknown_agent", model="unknown-model"),
            ModelAgent(id="invalid_agent", model="invalid-model"),
        ],
        price_per_million={"priced-model": 2.0, "invalid-model": -1.0},
    )
    result = orchestrator.complete(_messages("Summarize this note."))
    assert result["trace"][0]["agent_id"] == "priced_agent"
    assert result["routing_decision"]["priced_agent_count"] == 1


def test_zero_price_is_known_while_nonfinite_prices_are_unknown() -> None:
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(id="free_agent", model="free-model"),
            ModelAgent(id="nan_agent", model="nan-model"),
            ModelAgent(id="infinite_agent", model="infinite-model"),
        ],
        price_per_million={"free-model": 0.0, "nan-model": float("nan"), "infinite-model": float("inf")},
    )
    result = orchestrator.complete(_messages("Summarize this note."))
    assert result["trace"][0]["agent_id"] == "free_agent"
    assert result["routing_decision"]["priced_agent_count"] == 1


def test_auto_reports_unpriced_selected_model_without_assuming_zero_cost() -> None:
    orchestrator = TaskOrchestrator([ModelAgent(id="general_agent", model="general-model")])
    result = orchestrator.complete(_messages("Summarize this note."))
    assert result["routing_decision"]["unpriced_selected_models"] == ["general-model"]


def test_persisted_auto_run_retains_routing_decision() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent(id="general_agent", model="general-model")],
        price_per_million={"general-model": 1.5},
    )
    record = orchestrator.run(_messages("Summarize this note."), workflow_run_id="run_example")
    assert record["policy_mode"] == "auto"
    assert record["routing_decision"]["objective"] == "maximize_performance_then_minimize_cost"
    assert orchestrator.get_workflow_run("run_example")["routing_decision"] == record["routing_decision"]


def test_policy_snapshot_declares_adaptive_default_objective() -> None:
    orchestrator = TaskOrchestrator([ModelAgent(id="general_agent", model="general-model")])
    assert orchestrator.policy.as_dict()["auto_routing_objective"] == "maximize_performance_then_minimize_cost"


def test_explicit_modes_remain_operator_overrides() -> None:
    orchestrator = TaskOrchestrator([ModelAgent(id="general_agent", model="general-model")])
    complex_messages = _messages("Analyze the architecture and verify security.")
    simple_messages = _messages("Summarize this note.")
    assert orchestrator.complete(complex_messages, mode="route")["mode"] == "route"
    assert orchestrator.complete(simple_messages, mode="verify")["mode"] == "verify"
    assert orchestrator.complete(simple_messages, mode="conduct")["mode"] == "conduct"
    assert orchestrator.would_route(complex_messages, mode="route") is True
    assert orchestrator.would_route(simple_messages, mode="verify") is False
    assert orchestrator.would_route(simple_messages, mode="conduct") is False
    assert orchestrator.would_route(simple_messages, mode="auto") is True
    assert orchestrator.would_route(_messages("Verify this answer."), mode="auto") is False
    assert orchestrator.would_route(complex_messages, mode="auto") is False
'''

if __name__ == "__main__":
    main()
