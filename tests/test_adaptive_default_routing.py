from contextual_orchestrator.orchestrator import ModelAgent, TaskOrchestrator


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
