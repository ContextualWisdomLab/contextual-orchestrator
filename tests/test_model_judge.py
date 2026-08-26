"""Structured model-based verifier judging.

Keyword matching is deliberately rejected: verifier reports can quote risks,
use negation, or be written in another language. The judge must return an
explicit structured verdict and uncertainty must fail closed.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import contextual_orchestrator.orchestrator as orchestrator_module
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import (  # noqa: E402
    ModelClient,
    NoViableAgentError,
    ProviderResponseError,
    RequestDeadlineExceeded,
    _parse_model_judge_reply,
)


RISKY_VERIFIER_REPORT = "The plan is sound overall but discusses downtime risks and error handling."


class _ScriptedClient(ModelClient):
    """Template conduct: calls 1-4 are steps (verifier = call 3); call 5 is the judge."""

    def __init__(self, judge_reply: str) -> None:
        super().__init__()
        self.judge_reply = judge_reply
        self.calls = 0

    def chat(self, agent: ModelAgent, messages: list, temperature: float | None = None) -> str:  # type: ignore[override]
        self.calls += 1
        if self.calls == 3:
            return RISKY_VERIFIER_REPORT
        if self.calls == 5:
            return self.judge_reply
        return f"step-output({self.calls})"


def _orch(judge_reply: str) -> tuple[TaskOrchestrator, _ScriptedClient]:
    client = _ScriptedClient(judge_reply)
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "model-x", tags=("reasoning", "writing", "planning", "research"))],
        client=client,
    )
    return orchestrator, client


class _ScriptedCriterion:
    def __init__(self, criterion_id: str, description: str, weight: float) -> None:
        self.criterion_id = criterion_id
        self.description = description
        self.weight = weight


class _ScriptedFastJudge:
    def __init__(self, adapter, *, mode: str, accept_threshold: float) -> None:
        self.adapter = adapter
        self.mode = mode
        self.accept_threshold = accept_threshold

    def judge(self, *, task: str, answer: str, criteria: tuple) -> object:
        del task, answer, criteria
        completion = self.adapter.complete([{"role": "user", "content": "judge"}], mode=self.mode)
        decision, reason = _parse_model_judge_reply(completion["answer"])
        accepted = decision == "ACCEPT"
        return SimpleNamespace(
            accepted=accepted,
            rationale=reason,
            criterion_scores={"evidence_quality": 1.0, "risk_signal": 1.0},
            usage=completion.get("usage"),
            orchestration_mode=self.mode,
            to_irt_row=lambda *, item_type: (int(accepted), int(accepted)),
        )


def _scripted_fast_components() -> orchestrator_module.FastMLSIRMJudgeComponents:
    return orchestrator_module.FastMLSIRMJudgeComponents(
        judge_cls=_ScriptedFastJudge,
        criterion_cls=_ScriptedCriterion,
        format_error=ValueError,
    )


MESSAGES = [{"role": "user", "content": "design and verify the migration plan"}]


def test_keyword_matching_never_decides() -> None:
    orchestrator, _ = _orch("unused")
    result = orchestrator._judge_verifier_output("verified and good", "planner", "worker")
    assert result["accepted"] is False
    assert "keyword matching" in result["reason"]


def test_legacy_keyword_policy_is_rejected() -> None:
    orchestrator, _ = _orch("unused")
    try:
        replace(orchestrator.policy, verifier_judge="terms")
    except ValueError as exc:
        assert "keyword-based" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("keyword-based verifier policy was accepted")


def test_structured_model_judge_accepts() -> None:
    orchestrator, client = _orch('{"decision":"ACCEPT","reason":"The report supports the answer."}')
    with patch.object(
        orchestrator_module,
        "_resolve_fast_mlsirm_components",
        return_value=_scripted_fast_components(),
    ):
        result = orchestrator.conduct(MESSAGES)
    assert result["verification"]["accepted"] is True
    assert result["verification"]["judge"] == "model"
    assert client.calls == 5
    assert result["answer"] == "step-output(4)"


def test_free_conduct_keeps_model_judge_inside_zero_cost_pool() -> None:
    class _RecordingClient(_ScriptedClient):
        def __init__(self) -> None:
            super().__init__('{"decision":"ACCEPT","reason":"Free verification passed."}')
            self.agent_ids: list[str] = []

        def chat(self, agent: ModelAgent, messages: list, **kwargs: object) -> str:  # type: ignore[override]
            self.agent_ids.append(agent.id)
            return super().chat(agent, messages, **kwargs)

    client = _RecordingClient()
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("paid_verifier", "paid-model", tags=("verification",), priority=100),
            ModelAgent("free_verifier", "free-model", tags=("verification", "cost:free")),
        ],
        client=client,
    )
    with patch.object(
        orchestrator_module,
        "_resolve_fast_mlsirm_components",
        return_value=_scripted_fast_components(),
    ):
        orchestrator.conduct(MESSAGES, model_name="orchestrator/free")
    assert set(client.agent_ids) == {"free_verifier"}


def test_group_conduct_keeps_model_judge_inside_requested_group() -> None:
    class _RecordingClient(_ScriptedClient):
        def __init__(self) -> None:
            super().__init__('{"decision":"ACCEPT","reason":"Group verification passed."}')
            self.agent_ids: list[str] = []

        def chat(self, agent: ModelAgent, messages: list, **kwargs: object) -> str:  # type: ignore[override]
            self.agent_ids.append(agent.id)
            return super().chat(agent, messages, **kwargs)

    client = _RecordingClient()
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("group_member", "group-model", group_name="requested_model_group"),
            ModelAgent("outside_verifier", "outside-model", tags=("verification",), priority=100),
        ],
        client=client,
    )
    with patch.object(
        orchestrator_module,
        "_resolve_fast_mlsirm_components",
        return_value=_scripted_fast_components(),
    ):
        result = orchestrator.conduct(MESSAGES, model_name="requested_model_group")
    assert result["verification"]["accepted"] is True
    assert set(client.agent_ids) == {"group_member"}


def test_free_structured_judge_uses_exact_free_agent_with_duplicate_model_id() -> None:
    class _ProxyClient(ModelClient):
        def __init__(self) -> None:
            super().__init__()
            self.agent_ids: list[str] = []

        def proxy_send(self, agent: ModelAgent, endpoint: str, body: dict) -> dict:  # type: ignore[override]
            self.agent_ids.append(agent.id)
            return {"choices": [{"message": {"content": '{"decision":"ACCEPT","reason":"free"}'}}]}

        def probe_structured(self, agent, *, timeout=5.0):  # type: ignore[override]
            del timeout
            return {"agent_id": agent.id, "status": "ready"}

    class _StructuredJudge(_ScriptedFastJudge):
        def judge(self, **_: object) -> object:
            completion = self.adapter.complete_structured(
                [{"role": "user", "content": "judge"}],
                response_format={"type": "json_object"},
            )
            return SimpleNamespace(
                accepted=True,
                rationale=completion["answer"],
                criterion_scores={},
                usage=None,
                orchestration_mode="route",
                to_irt_row=lambda *, item_type: (1, 1),
            )

    client = _ProxyClient()
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("paid_duplicate", "shared-model", tags=("verification",), priority=100),
            ModelAgent("free_duplicate", "shared-model", tags=("verification", "cost:free")),
        ],
        client=client,
    )
    components = orchestrator_module.FastMLSIRMJudgeComponents(
        judge_cls=_StructuredJudge,
        criterion_cls=_ScriptedCriterion,
        format_error=ValueError,
    )
    with patch.object(orchestrator_module, "_resolve_fast_mlsirm_components", return_value=components):
        orchestrator._model_judge_verification(
            "task", {"verifier_output": "report"}, free_only=True
        )
    assert client.agent_ids == ["free_duplicate"]


def test_structured_model_judge_rejects() -> None:
    orchestrator, _ = _orch('{"decision":"REJECT","reason":"The migration plan loses writes."}')
    with patch.object(
        orchestrator_module,
        "_resolve_fast_mlsirm_components",
        return_value=_scripted_fast_components(),
    ):
        result = orchestrator.conduct(MESSAGES)
    assert result["verification"]["accepted"] is False
    assert result["verification"]["judge"] == "model"
    assert result["answer"] == "step-output(2)"


def test_plain_keyword_reply_is_rejected() -> None:
    orchestrator, _ = _orch("ACCEPT because the report looks fine")
    with patch.object(
        orchestrator_module,
        "_resolve_fast_mlsirm_components",
        return_value=_scripted_fast_components(),
    ):
        result = orchestrator.conduct(MESSAGES)
    assert result["verification"]["accepted"] is False
    assert "invalid structured verdict" in result["verification"]["reason"]
    assert result["answer"] == "step-output(2)"


def test_judge_rejects_wrapped_extra_and_duplicate_json() -> None:
    for reply in (
        'prefix {"decision":"ACCEPT","reason":"valid"}',
        '{"decision":"ACCEPT","reason":"valid","extra":true}',
        '{"decision":"ACCEPT","decision":"REJECT","reason":"ambiguous"}',
    ):
        orchestrator, _ = _orch(reply)
        with patch.object(
            orchestrator_module,
            "_resolve_fast_mlsirm_components",
            return_value=_scripted_fast_components(),
        ):
            result = orchestrator.conduct(MESSAGES)
        assert result["verification"]["accepted"] is False
        assert "invalid structured verdict" in result["verification"]["reason"]


def test_judge_failure_fails_closed() -> None:
    class _FailingJudge(_ScriptedClient):
        def chat(self, agent: ModelAgent, messages: list, temperature: float | None = None) -> str:  # type: ignore[override]
            self.calls += 1
            if self.calls == 3:
                return RISKY_VERIFIER_REPORT
            if self.calls == 5:
                raise RuntimeError("judge provider down")
            return f"step-output({self.calls})"

    client = _FailingJudge("unused")
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "model-x", tags=("reasoning", "writing", "planning", "research"))],
        client=client,
    )
    with patch.object(
        orchestrator_module,
        "_resolve_fast_mlsirm_components",
        return_value=_scripted_fast_components(),
    ):
        result = orchestrator.conduct(MESSAGES)
    assert result["verification"]["accepted"] is False
    assert result["verification"]["judge"] == "model"
    assert "failed closed" in result["verification"]["reason"]
    assert result["answer"] == "step-output(2)"


def test_fast_mlsirm_path_is_used_when_available() -> None:
    class _FakeJudge:
        def __init__(self, orchestrator, mode: str = "route", accept_threshold: float = 0.7) -> None:
            self.adapter = orchestrator
            self.mode = mode
            self.accept_threshold = accept_threshold

        def judge(self, **_) -> object:
            self.adapter.complete([{"role": "user", "content": "ping"}])
            return type("Result", (), {
                "accepted": True,
                "rationale": "structured score exceeded threshold",
                "criterion_scores": {"evidence_quality": 0.8, "risk_signal": 0.9},
                "usage": {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7},
                "orchestration_mode": self.mode,
                "to_irt_row": lambda *, item_type: (1, 1),
            })

    class _FormatError(Exception):
        pass

    class _Criterion:
        def __init__(self, criterion_id: str, description: str, weight: float) -> None:
            self.criterion_id = criterion_id
            self.description = description
            self.weight = weight

    orchestrator, _ = _orch("unused")
    orchestrator.policy = replace(orchestrator.policy, workflow_planning="conduct")
    with patch.object(
        orchestrator_module,
        "_resolve_fast_mlsirm_components",
        return_value=orchestrator_module.FastMLSIRMJudgeComponents(
            judge_cls=_FakeJudge,
            criterion_cls=_Criterion,
            format_error=_FormatError,
        ),
    ):
        with patch.object(
            orchestrator,
            "_invoke",
            return_value=("judge completion", "backup_judge", {"total_tokens": 7}),
        ):
            result = orchestrator._model_judge_verification(
                "task",
                {"verifier_output": "report"},
            )

    assert result["accepted"] is True
    assert result["judge"] == "model"
    assert result["judge_agent_id"] == "backup_judge"
    assert result["judge_orchestration_mode"] == "route"
    assert result["judge_usage"] == {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7}
    assert result["judge_criterion_scores"] == {"evidence_quality": 0.8, "risk_signal": 0.9}
    assert result["judge_irt_item_type"] == "dichotomous"
    assert result["judge_irt_row"] == [1, 1]
    assert result["reason"] == "structured score exceeded threshold"


def test_fast_mlsirm_adapter_accepts_contextual_judge_mode_keyword() -> None:
    orchestrator, _ = _orch("unused")
    adapter = orchestrator_module._FastMLSIJudgeAdapter(
        orchestrator,
        "task",
        "general_agent",
        mode="route",
    )
    assert adapter.client is orchestrator.client
    assert (
        adapter.contextual_orchestrator_contract
        == "contextual-orchestrator-contract-v1"
    )
    with patch.object(
        orchestrator,
        "_invoke",
        return_value=("judge completion", "general_agent", None),
    ) as invoke:
        completion = adapter.complete(
            [{"role": "user", "content": "ping"}],
            mode="conduct",
        )
    assert invoke.call_args.kwargs["role"] == "judge"
    assert invoke.call_args.kwargs["eligibility_role"] == "verifier"
    assert completion["answer"] == "judge completion"
    assert completion["mode"] == "conduct"


def test_fast_mlsirm_judge_failover_honors_verifier_exclusions() -> None:
    """A verifier-excluded backup cannot become the model judge on failover."""

    class _PrimaryDownClient(ModelClient):
        def chat(self, agent: ModelAgent, messages: list, **kwargs: object) -> str:  # type: ignore[override]
            del messages, kwargs
            if agent.id == "primary_judge":
                raise RuntimeError("primary judge unavailable")
            return "unexpected backup judge"

    orchestrator = TaskOrchestrator(
        [
            ModelAgent("primary_judge", "primary", tags=("verification",), priority=2),
            ModelAgent(
                "verifier_excluded_backup",
                "backup",
                tags=("verification",),
                provider_exclusions=("verifier",),
            ),
        ],
        client=_PrimaryDownClient(),
    )

    with pytest.raises(RuntimeError, match="all 1 candidate agents failed"):
        orchestrator._invoke(
            orchestrator._agent("primary_judge"),
            [{"role": "user", "content": "judge this"}],
            text="judge this",
            role="judge",
            eligibility_role="verifier",
        )


def test_fast_mlsirm_adapter_routes_structured_completion_through_gateway() -> None:
    orchestrator, _ = _orch("unused")
    orchestrator._structured_readiness["general_agent"] = {
        "status": "ready",
        "checked_at": orchestrator_module.time.monotonic(),
    }
    adapter = orchestrator_module._FastMLSIJudgeAdapter(
        orchestrator,
        "task",
        "general_agent",
        mode="route",
    )
    response_format = {
        "type": "json_schema",
        "json_schema": {"name": "judge", "strict": True, "schema": {"type": "object"}},
    }
    with patch.object(
        orchestrator.client,
        "proxy_send",
        return_value={
            "choices": [{"message": {"content": '{"meets_threshold":true,"rationale":"ok"}'}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        },
    ) as proxy:
        completion = adapter.complete_structured(
            [{"role": "user", "content": "judge"}],
            mode="conduct",
            response_format=response_format,
        )

    proxy.assert_called_once_with(
        orchestrator._agent("general_agent"),
        "chat/completions",
        {
            "model": "model-x",
            "messages": [{"role": "user", "content": "judge"}],
            "temperature": orchestrator.client.temperature,
            "max_tokens": orchestrator.client.max_output_tokens,
            "response_format": response_format,
            "stream": False,
        }
    )
    assert completion["answer"] == '{"meets_threshold":true,"rationale":"ok"}'
    assert completion["mode"] == "conduct"
    assert completion["trace"][0]["usage"]["total_tokens"] == 5


def test_fast_mlsirm_structured_judge_fails_over_with_shared_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A structural provider failure offers the request remainder to the backup."""
    now = [0.0]
    monkeypatch.setattr(orchestrator_module.time, "monotonic", lambda: now[0])

    class DeadlineClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(timeout=90, max_retries=0)
            self.calls: list[tuple[str, float]] = []

        def proxy_send(self, agent, endpoint, payload):  # type: ignore[override]
            del endpoint, payload
            remaining = self.remaining_request_timeout()
            budget = min(float(self.timeout), remaining)
            self.calls.append((agent.id, budget))
            if agent.id == "primary_judge":
                now[0] += budget
                raise ProviderResponseError("primary structured response failed")
            return {
                "choices": [{"message": {"content": '{"accepted":true}'}}],
                "usage": {"total_tokens": 7},
            }

        def probe_structured(self, agent, *, timeout=5.0):  # type: ignore[override]
            del timeout
            return {"agent_id": agent.id, "status": "ready"}

    agents = [
        ModelAgent("primary_judge", "primary-model", tags=("verification",), priority=2),
        ModelAgent("backup_judge", "backup-model", tags=("verification",), priority=1),
    ]
    client = DeadlineClient()
    adapter = orchestrator_module._FastMLSIJudgeAdapter(
        TaskOrchestrator(agents, client=client),
        "task",
        "primary_judge",
        allowed_agent_ids={"primary_judge", "backup_judge"},
    )
    with client.request_settings(request_deadline_monotonic=180.0):
        completion = adapter.complete_structured(
            [{"role": "user", "content": "judge"}],
            response_format={"type": "json_object"},
        )
    assert completion["answer"] == '{"accepted":true}'
    assert completion["trace"][0]["agent_id"] == "backup_judge"
    assert client.calls == [("primary_judge", 90.0), ("backup_judge", 90.0)]


def test_fast_mlsirm_structured_judge_all_fail_at_request_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All structured candidates fail closed when the shared deadline is exhausted."""
    now = [0.0]
    monkeypatch.setattr(orchestrator_module.time, "monotonic", lambda: now[0])

    class AllDownClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(timeout=90, max_retries=0)
            self.calls: list[tuple[str, float]] = []

        def proxy_send(self, agent, endpoint, payload):  # type: ignore[override]
            del endpoint, payload
            remaining = self.remaining_request_timeout()
            budget = min(float(self.timeout), remaining)
            self.calls.append((agent.id, budget))
            now[0] += budget
            raise ProviderResponseError("structured response failed")

        def probe_structured(self, agent, *, timeout=5.0):  # type: ignore[override]
            del timeout
            return {"agent_id": agent.id, "status": "ready"}

    agents = [
        ModelAgent("primary_judge", "primary-model", tags=("verification",), priority=2),
        ModelAgent("backup_judge", "backup-model", tags=("verification",), priority=1),
    ]
    client = AllDownClient()
    adapter = orchestrator_module._FastMLSIJudgeAdapter(
        TaskOrchestrator(agents, client=client),
        "task",
        "primary_judge",
        allowed_agent_ids={"primary_judge", "backup_judge"},
    )
    with client.request_settings(request_deadline_monotonic=180.0):
        with pytest.raises(RequestDeadlineExceeded, match="request deadline exceeded"):
            adapter.complete_structured(
                [{"role": "user", "content": "judge"}],
                response_format={"type": "json_object"},
            )
    assert client.calls == [("primary_judge", 90.0), ("backup_judge", 90.0)]


def test_structured_readiness_excludes_failed_probe_and_uses_ready_backup() -> None:
    """Only a recently structured-ready declared candidate receives the request."""

    class ProbeClient(ModelClient):
        def __init__(self) -> None:
            super().__init__()
            self.probes: list[str] = []
            self.calls: list[str] = []

        def probe_structured(self, agent, *, timeout=5.0):  # type: ignore[override]
            del timeout
            self.probes.append(agent.id)
            return {
                "agent_id": agent.id,
                "status": "ready" if agent.id == "backup_judge" else "not_ready",
            }

        def proxy_send(self, agent, endpoint, payload):  # type: ignore[override]
            del endpoint, payload
            self.calls.append(agent.id)
            return {
                "choices": [{"message": {"content": '{"accepted":true}'}}],
                "usage": {"total_tokens": 7},
            }

    agents = [
        ModelAgent("primary_judge", "primary-model", tags=("verification",), priority=2),
        ModelAgent("backup_judge", "backup-model", tags=("verification",), priority=1),
    ]
    client = ProbeClient()
    adapter = orchestrator_module._FastMLSIJudgeAdapter(
        TaskOrchestrator(agents, client=client),
        "task",
        "primary_judge",
        allowed_agent_ids={"primary_judge", "backup_judge"},
    )

    completion = adapter.complete_structured(
        [{"role": "user", "content": "judge"}],
        response_format={"type": "json_object"},
    )

    assert set(client.probes) == {"primary_judge", "backup_judge"}
    assert client.calls == ["backup_judge"]
    assert completion["trace"][0]["agent_id"] == "backup_judge"


def test_structured_readiness_without_ready_candidate_avoids_provider_call() -> None:
    """No recent ready evidence returns a typed retry contract before execution."""

    class NoReadyClient(ModelClient):
        def probe_structured(self, agent, *, timeout=5.0):  # type: ignore[override]
            del timeout
            return {"agent_id": agent.id, "status": "not_ready"}

        def proxy_send(self, agent, endpoint, payload):  # type: ignore[override]
            raise AssertionError((agent, endpoint, payload))

    agents = [
        ModelAgent("primary_judge", "primary-model", tags=("verification",)),
        ModelAgent("backup_judge", "backup-model", tags=("verification",)),
    ]
    orchestrator = TaskOrchestrator(agents, client=NoReadyClient())
    adapter = orchestrator_module._FastMLSIJudgeAdapter(
        orchestrator,
        "task",
        "primary_judge",
        allowed_agent_ids={"primary_judge", "backup_judge"},
    )

    with pytest.raises(NoViableAgentError) as exc_info:
        adapter.complete_structured(
            [{"role": "user", "content": "judge"}],
            response_format={"type": "json_object"},
        )

    assert exc_info.value.code == "no_viable_agent"
    assert exc_info.value.retry_after_seconds == 30


def test_conduct_excludes_failed_candidates_for_the_entire_request() -> None:
    """A later workflow stage cannot retry a provider that failed in this request."""

    class FailingClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=0)
            self.calls: list[str] = []

        def chat(self, agent, messages, **kwargs):  # type: ignore[override]
            del messages, kwargs
            self.calls.append(agent.id)
            raise ProviderResponseError("provider response unavailable")

    tags = ("reasoning", "writing", "planning", "research", "verification")
    agents = [
        ModelAgent("first_agent", "first-model", tags=tags, group_name="declared_group"),
        ModelAgent("second_agent", "second-model", tags=tags, group_name="declared_group"),
    ]
    client = FailingClient()
    orchestrator = TaskOrchestrator(agents, client=client)

    with pytest.raises(NoViableAgentError) as first_attempt:
        orchestrator.complete(
            [{"role": "user", "content": "produce a verified structured report"}],
            mode="conduct",
        )

    assert first_attempt.value.retry_after_seconds == 30
    assert client.calls == ["first_agent", "second_agent"]

    # A later durable retry is a new request scope, so the candidates may be
    # considered again after the caller has observed the Retry-After contract.
    with pytest.raises(NoViableAgentError):
        orchestrator.complete(
            [{"role": "user", "content": "produce a verified structured report"}],
            mode="conduct",
        )
    assert client.calls == ["first_agent", "second_agent", "first_agent", "second_agent"]


def test_expired_request_deadline_does_not_mark_provider_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caller-budget exhaustion before transport is not a provider failure."""
    monkeypatch.setattr(orchestrator_module.time, "monotonic", lambda: 10.0)
    agent = ModelAgent(
        "healthy_agent",
        "healthy-model",
        tags=("reasoning", "writing", "planning", "research", "verification"),
    )
    client = ModelClient(max_retries=0)
    orchestrator = TaskOrchestrator([agent], client=client)

    with client.request_settings(request_deadline_monotonic=9.0):
        with pytest.raises(RequestDeadlineExceeded):
            orchestrator.complete(
                [{"role": "user", "content": "produce a verified report"}],
                mode="conduct",
            )

    assert orchestrator._structured_readiness == {}
    assert orchestrator._circuit == {}


def test_direct_conduct_entrypoint_has_request_scoped_exclusion() -> None:
    """Streaming callers that invoke conduct directly retain the same boundary."""

    class FailingClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=0)
            self.calls: list[str] = []

        def chat(self, agent, messages, **kwargs):  # type: ignore[override]
            del messages, kwargs
            self.calls.append(agent.id)
            raise ProviderResponseError("provider response unavailable")

    tags = ("reasoning", "writing", "planning", "research", "verification")
    agents = [
        ModelAgent("first_agent", "first-model", tags=tags, group_name="declared_group"),
        ModelAgent("second_agent", "second-model", tags=tags, group_name="declared_group"),
    ]
    client = FailingClient()
    orchestrator = TaskOrchestrator(agents, client=client)

    with pytest.raises(NoViableAgentError):
        orchestrator.conduct(
            [{"role": "user", "content": "produce a verified structured report"}]
        )

    assert client.calls == ["first_agent", "second_agent"]


def test_route_provider_failure_does_not_poison_structured_readiness() -> None:
    """Ordinary chat failure remains separate from structured probe evidence."""

    class FailingClient(ModelClient):
        def chat(self, agent, messages, **kwargs):  # type: ignore[override]
            del agent, messages, kwargs
            raise ProviderResponseError("provider response unavailable")

    agent = ModelAgent(
        "route_agent",
        "route-model",
        tags=("reasoning", "writing", "planning", "research", "verification"),
    )
    orchestrator = TaskOrchestrator([agent], client=FailingClient(max_retries=0))

    with pytest.raises(RuntimeError, match="all 1 candidate agents failed"):
        orchestrator.complete(
            [{"role": "user", "content": "answer directly"}], mode="route"
        )

    assert orchestrator._structured_readiness == {}
def test_structured_readiness_probe_does_not_mutate_transport_circuit() -> None:
    """Capability probes neither clear nor increment provider transport failures."""

    class ProbeClient(ModelClient):
        def probe_structured(self, agent, *, timeout=5.0):  # type: ignore[override]
            del timeout
            return {
                "agent_id": agent.id,
                "status": "ready" if agent.id == "ready_agent" else "not_ready",
            }

    agents = [
        ModelAgent("ready_agent", "ready-model", tags=("verification",)),
        ModelAgent("not_ready_agent", "not-ready-model", tags=("verification",)),
    ]
    orchestrator = TaskOrchestrator(agents, client=ProbeClient())
    orchestrator._record_failure("ready_agent")
    before = {agent_id: dict(state) for agent_id, state in orchestrator._circuit.items()}

    ready = orchestrator._structured_ready_candidates(
        agents[0], "judge", {agent.id for agent in agents}
    )

    assert [agent.id for agent in ready] == ["ready_agent"]
    assert orchestrator._circuit == before


def test_structured_readiness_probe_preserves_request_deadline() -> None:
    """Caller deadline exhaustion remains a typed deadline failure, not readiness 503."""

    class DeadlineClient(ModelClient):
        def proxy_send(self, agent, endpoint, payload):  # type: ignore[override]
            del agent, endpoint, payload
            self.remaining_request_timeout()
            raise AssertionError("expired deadline should raise first")

    client = DeadlineClient()
    agent = ModelAgent("judge_agent", "judge-model", tags=("verification",))
    orchestrator = TaskOrchestrator([agent], client=client)

    with client.request_settings(request_deadline_monotonic=time.monotonic() - 1.0):
        with pytest.raises(RequestDeadlineExceeded, match="request deadline exceeded"):
            orchestrator._structured_ready_candidates(agent, "judge", {agent.id})


def test_fast_mlsirm_judge_contract_does_not_pass_threshold_to_judge_call() -> None:
    class _Judge:
        def __init__(self, _orchestrator, *, mode: str, accept_threshold: float) -> None:
            assert mode == "route"
            assert accept_threshold == 0.7

        def judge(self, *, task: str, answer: str, criteria: tuple) -> object:
            assert task == "task"
            assert answer == "report"
            assert len(criteria) == 2
            return type("Result", (), {
                "accepted": True,
                "rationale": "valid",
                "usage": {},
                "orchestration_mode": "route",
            })

    class _Criterion:
        def __init__(self, criterion_id: str, description: str, weight: float) -> None:
            self.criterion_id = criterion_id
            self.description = description
            self.weight = weight

    orchestrator, _ = _orch("unused")
    with patch.object(
        orchestrator_module,
        "_resolve_fast_mlsirm_components",
        return_value=orchestrator_module.FastMLSIRMJudgeComponents(
            judge_cls=_Judge,
            criterion_cls=_Criterion,
            format_error=ValueError,
        ),
    ):
        result = orchestrator._model_judge_verification("task", {"verifier_output": "report"})

    assert result["accepted"] is True
    assert result["judge_orchestration_mode"] == "route"


def test_fast_mlsirm_invalid_irt_projection_fails_closed() -> None:
    class _Judge:
        def __init__(self, _orchestrator, *, mode: str, accept_threshold: float) -> None:
            del mode, accept_threshold

        def judge(self, **_) -> object:
            return type("Result", (), {
                "accepted": True,
                "rationale": "valid score but invalid item vector",
                "criterion_scores": {"only_item": 0.8},
                "usage": {},
                "orchestration_mode": "route",
                "to_irt_row": lambda *, item_type: (1,),
            })

    class _Criterion:
        def __init__(self, criterion_id: str, description: str, weight: float) -> None:
            self.criterion_id = criterion_id
            self.description = description
            self.weight = weight

    orchestrator, _ = _orch("unused")
    with patch.object(
        orchestrator_module,
        "_resolve_fast_mlsirm_components",
        return_value=orchestrator_module.FastMLSIRMJudgeComponents(
            judge_cls=_Judge,
            criterion_cls=_Criterion,
            format_error=ValueError,
        ),
    ):
        result = orchestrator._model_judge_verification("task", {"verifier_output": "report"})

    assert result["accepted"] is False
    assert "multi-item IRT projection" in result["reason"]


def test_fast_mlsirm_format_error_fails_closed() -> None:
    class _FormatError(Exception):
        pass

    class _FlakyJudge:
        def __init__(self, _orchestrator, mode: str = "route", accept_threshold: float = 0.7) -> None:
            del mode, accept_threshold

        def judge(self, **_) -> None:
            raise _FormatError("invalid structured verdict")

    class _Criterion:
        def __init__(self, criterion_id: str, description: str, weight: float) -> None:
            self.criterion_id = criterion_id
            self.description = description
            self.weight = weight

    orchestrator, _ = _orch("unused")
    with patch.object(
        orchestrator_module,
        "_resolve_fast_mlsirm_components",
        return_value=orchestrator_module.FastMLSIRMJudgeComponents(
            judge_cls=_FlakyJudge,
            criterion_cls=_Criterion,
            format_error=_FormatError,
        ),
    ):
        result = orchestrator._model_judge_verification("task", {"verifier_output": "report"})

    assert result["accepted"] is False
    assert result["judge"] == "model"
    assert result["reason"] == "model judge returned an invalid structured verdict; verification failed closed"


def test_broken_fast_mlsirm_import_does_not_bypass_required_judge_path() -> None:
    orchestrator, _ = _orch("unused")
    with patch.object(
        orchestrator_module,
        "_resolve_fast_mlsirm_components",
        side_effect=RuntimeError("broken fast-mlsirm import"),
    ):
        result = orchestrator._model_judge_verification("task", {"verifier_output": "report"})

    assert result["accepted"] is False
    assert result["reason"] == "fast-mlsirm judge could not be loaded; verification failed closed"


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        ('{"decision":"MAYBE","reason":"uncertain"}', "allowed enum"),
        ('{"decision":"ACCEPT","reason":""}', "reason is missing"),
        ('{"decision":"ACCEPT","reason":17}', "reason is missing"),
    ],
)
def test_model_judge_parser_rejects_invalid_structured_values(reply: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _parse_model_judge_reply(reply)


def test_model_judge_parser_rejects_oversized_reply() -> None:
    with pytest.raises(ValueError, match="maximum size"):
        _parse_model_judge_reply("x" * 32_001)


def test_model_judge_parser_hides_raw_provider_response() -> None:
    raw_provider_response = "provider-secret-response"

    with pytest.raises(ValueError, match="not valid JSON") as error:
        _parse_model_judge_reply(raw_provider_response)

    assert raw_provider_response not in str(error.value)
    assert error.value.__cause__ is None


def test_missing_fast_mlsirm_does_not_use_a_direct_judge_fallback() -> None:
    orchestrator, _ = _orch("unused")
    with patch.object(orchestrator_module, "_resolve_fast_mlsirm_components", return_value=None), patch.object(
        orchestrator, "_invoke"
    ) as invoke:
        result = orchestrator._model_judge_verification(
            "task",
            {"verifier_output": "report"},
        )

    assert result["accepted"] is False
    assert result["reason"] == "fast-mlsirm judge is unavailable; verification failed closed"
    invoke.assert_not_called()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
