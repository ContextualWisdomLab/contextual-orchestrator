"""Realtime fast-mlsirm judge observation wired into structured synthesis.

Covers ``_orchestrated_provider_completion``'s one success point calling
``_realtime_route_judge`` for its recording side effect only (quality ledger
and psychometric routing evidence), never branching on the verdict:

- the call receives the actually-served answer/agent and the already
  canonicalized usage (not the raw provider dict), and records one quality
  success;
- ``policy.realtime_judge = False`` skips the judge call and every ledger
  write entirely, exactly as the disabled route-path contract already does;
- the observation genuinely reaches ``PsychometricRoutingEvidence`` and can
  move an evidenced candidate ahead of a higher-static-priority one on a
  later ranking call, proving the routing gap this wiring closes.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import ProviderUpstreamError  # noqa: E402

_STUB_CONDUCT = {
    "mode": "conduct",
    "answer": "evidence",
    "trace": [],
    "verification": {"accepted": True, "reason": "test", "verifier_output": ""},
}


class _ResponsesUsageClient:
    """One fixed Responses-shaped answer with Responses-API usage keys only."""

    def __init__(self, *, content: str, usage: dict[str, int]) -> None:
        self._content = content
        self._usage = usage
        self.calls: list[tuple[str, str]] = []

    def proxy_send_once(
        self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Record the attempt and return a fixed provider-shaped response."""
        del payload
        self.calls.append((agent.id, endpoint))
        return {
            "id": "resp_test",
            "object": "response",
            "model": agent.model,
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": self._content}],
                }
            ],
            "usage": dict(self._usage),
        }

    proxy_send = proxy_send_once


def test_orchestrated_completion_wires_realtime_judge_with_canonicalized_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The new call gets the served answer/agent and canonicalized usage, and records success."""
    agent = ModelAgent("solo_agent", "mock-model", tags=("reasoning",))
    client = _ResponsesUsageClient(
        content="final answer",
        usage={"input_tokens": 7, "output_tokens": 13, "total_tokens": 20},
    )
    orchestrator = TaskOrchestrator([agent], client=client)
    orchestrator.conduct = lambda *args, **kwargs: dict(_STUB_CONDUCT)  # type: ignore[method-assign]

    captured: dict[str, object] = {}
    original_judge = TaskOrchestrator._realtime_route_judge

    def _spy(self: TaskOrchestrator, **kwargs: object) -> dict[str, Any]:
        captured.update(kwargs)
        return original_judge(self, **kwargs)

    monkeypatch.setattr(TaskOrchestrator, "_realtime_route_judge", _spy)
    monkeypatch.setattr(
        orchestrator,
        "_model_judge_verification",
        lambda task, fallback, *, free_only=False, **_ignored: {
            "accepted": True,
            "reason": "stub verdict",
            "verifier_output": fallback.get("verifier_output", ""),
            "judge": "model",
        },
    )

    messages = [{"role": "user", "content": "hello world"}]
    expected_prompt_context = TaskOrchestrator._prompt_interaction(messages)

    result = orchestrator.proxy_completion(
        {"input": "hello world"}, endpoint="responses", single_agent=False
    )

    assert result["output_text"] == "final answer"
    assert client.calls == [("solo_agent", "responses")]

    assert captured["text"] == "hello world"
    assert captured["answer"] == "final answer"
    assert captured["served_id"] == "solo_agent"
    assert captured["free_only"] is False
    assert captured["prompt_context"] == expected_prompt_context
    assert isinstance(captured["latency_seconds"], float)
    assert captured["latency_seconds"] >= 0
    # The raw provider dict only has Responses-API keys; the judge must
    # receive the already-canonicalized usage (with the completion_tokens
    # alias _usage_completion_tokens actually reads), not raw.get("usage").
    assert captured["usage"] == {
        "input_tokens": 7,
        "output_tokens": 13,
        "total_tokens": 20,
        "prompt_tokens": 7,
        "completion_tokens": 13,
    }

    quality = orchestrator._quality_router.member_report("solo_agent")
    assert quality["success_count"] == 1


def test_disabled_realtime_judge_skips_judge_call_and_ledger_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``policy.realtime_judge = False`` means no judge call and no ledger write."""
    from dataclasses import replace

    agent = ModelAgent("worker_agent", "mock", tags=("reasoning",))
    orchestrator = TaskOrchestrator([agent])
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    orchestrator.conduct = lambda *args, **kwargs: dict(_STUB_CONDUCT)  # type: ignore[method-assign]

    def _explode(*args: object, **kwargs: object) -> dict[str, Any]:
        raise AssertionError("model judge must not be called when realtime_judge is disabled")

    monkeypatch.setattr(orchestrator, "_model_judge_verification", _explode)

    result = orchestrator.proxy_completion(
        {"input": "hello world"}, endpoint="responses", single_agent=False
    )

    assert result["output_text"] == "[worker_agent] chat-mock"
    assert orchestrator._quality_router.member_observation_count("worker_agent") == 0
    assert orchestrator._psychometric_router.has_observations() is False


def test_orchestrated_completion_observation_flows_into_psychometric_reordering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A served answer's real observation can later re-rank a synthesizer partition."""
    import fast_mlsirm

    alpha = ModelAgent("candidate_alpha", "mock", tags=("reasoning",), priority=50)
    beta = ModelAgent("candidate_beta", "mock", tags=("reasoning",), priority=1)
    orchestrator = TaskOrchestrator([alpha, beta])
    orchestrator.conduct = lambda *args, **kwargs: dict(_STUB_CONDUCT)  # type: ignore[method-assign]

    messages = [{"role": "user", "content": "shared prompt text"}]
    task = orchestrator._latest_user_text(messages)
    prompt_context = orchestrator._prompt_interaction(messages)

    assert orchestrator._psychometric_router.has_observations() is False
    baseline = orchestrator._ranked_agents(task, "synthesizer", prompt_context=prompt_context)
    assert [candidate.id for candidate in baseline] == ["candidate_alpha", "candidate_beta"]

    monkeypatch.setattr(
        orchestrator,
        "_model_judge_verification",
        lambda task, fallback, *, free_only=False, **_ignored: {
            "accepted": True,
            "reason": "stub verdict",
            "verifier_output": fallback.get("verifier_output", ""),
            "judge": "model",
        },
    )

    # Force the lower-static-priority agent to be the one that actually
    # serves, so a real evidence-first reorder (not the static order it
    # already had) is what proves the observation moved routing.
    result = orchestrator.proxy_completion(
        {"input": "shared prompt text", "_required_agent_id": "candidate_beta"},
        endpoint="responses",
        single_agent=False,
    )
    assert result["output_text"] == "[candidate_beta] chat-mock"
    assert orchestrator._psychometric_router.has_observations() is True

    # The fast-mlsirm native fit legitimately refuses to converge on a
    # single-item response matrix (see PsychometricRoutingEvidence._fit_locked);
    # stub only that numeric boundary -- exactly as
    # test_fast_mlsirm_fit_uses_judge_acceptance_item_for_context_score does --
    # so the real observation recorded above is what drives a real re-rank.
    class _Result:
        convergence_status = "converged"
        params = object()
        model = "MLSRM"

    def fake_fit_experiment(fit_callable: object, responses: object, item_type: str, **kwargs: object) -> _Result:
        del fit_callable, responses, item_type, kwargs
        return _Result()

    def fake_predict(_params: object, factor_id: object, *, model: str) -> np.ndarray:
        del _params, model
        return np.array([[0.99]] * len(factor_id)).reshape(1, len(factor_id))

    monkeypatch.setattr(fast_mlsirm, "fit_irt_experiment", fake_fit_experiment)
    monkeypatch.setattr(fast_mlsirm, "predict_proba", fake_predict)

    reordered = orchestrator._ranked_agents(task, "synthesizer", prompt_context=prompt_context)
    assert [candidate.id for candidate in reordered] == ["candidate_beta", "candidate_alpha"]


def test_explicit_model_pin_constrains_realtime_judge_to_selected_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit model pin stays pinned through the observation-only judge too.

    Devin review (PR #1032): ``_realtime_route_judge`` must forward the same
    ``allowed_agent_ids`` the request's own synthesis was already constrained
    to, so this extra call can never reach an unrelated, higher-ranked
    verifier the caller never selected.
    """
    pinned = ModelAgent("pinned_agent", "mock", tags=("reasoning",), priority=1)
    unrelated = ModelAgent("unrelated_verifier", "mock", tags=("reasoning",), priority=100)
    orchestrator = TaskOrchestrator([pinned, unrelated])
    orchestrator.conduct = lambda *args, **kwargs: dict(_STUB_CONDUCT)  # type: ignore[method-assign]

    captured: dict[str, object] = {}

    def _spy(
        task: str,
        fallback: dict[str, Any],
        *,
        free_only: bool = False,
        allowed_agent_ids: set[str] | None = None,
        excluded_agent_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        captured["allowed_agent_ids"] = allowed_agent_ids
        return {
            "accepted": True,
            "reason": "stub verdict",
            "verifier_output": fallback.get("verifier_output", ""),
            "judge": "model",
        }

    monkeypatch.setattr(orchestrator, "_model_judge_verification", _spy)

    result = orchestrator.proxy_completion(
        {"input": "hello world", "_required_agent_id": "pinned_agent"},
        endpoint="responses",
        single_agent=False,
    )

    assert result["output_text"] == "[pinned_agent] chat-mock"
    assert captured["allowed_agent_ids"] == {"pinned_agent"}


def test_exhausted_budget_skips_extra_realtime_judge_call_but_keeps_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exhausted budget skips the extra judge call, never the already-good answer.

    Devin review (PR #1032): this purely observation-only call's own spend
    must never discard the already-decided response above. Unlike
    ``batch_route``'s pre-call gate (which blocks a not-yet-incurred worker
    call before the caller has anything), this call happens after the
    response is fully decided -- an exhausted budget skips it outright
    instead of raising and losing an already-good answer.

    The budget here is never spent by a previous run: the whole allowance is
    consumed by *this* request's own not-yet-persisted workflow + synthesis
    spend, which is exactly the case ``budget_status()`` alone cannot see
    (Devin review on #1032).
    """
    agent = ModelAgent("worker_agent", "mock", tags=("reasoning",))
    orchestrator = TaskOrchestrator([agent])
    orchestrator.conduct = lambda *args, **kwargs: dict(_STUB_CONDUCT)  # type: ignore[method-assign]
    orchestrator.budget_max_output_tokens = 1
    assert orchestrator.budget_status()["exceeded"] is False

    def _explode(*args: object, **kwargs: object) -> dict[str, Any]:
        raise AssertionError("realtime judge must be skipped once budget is already exceeded")

    monkeypatch.setattr(orchestrator, "_model_judge_verification", _explode)

    result = orchestrator.proxy_completion(
        {"input": "hello world"}, endpoint="responses", single_agent=False
    )

    assert result["output_text"] == "[worker_agent] chat-mock"
    assert orchestrator._quality_router.member_observation_count("worker_agent") == 0
    assert orchestrator._psychometric_router.has_observations() is False


def test_realtime_judge_excludes_agents_this_request_already_proved_unavailable() -> None:
    """A failed-over-away agent must not be picked as this request's judge.

    Devin review (PR #1032): ``request_exclusions`` holds every agent this
    request already proved unavailable. Feeding the judge from
    ``allowed_agent_ids`` alone leaves such an agent eligible; if it fails
    the judge call, the resulting failure records a false-negative quality
    observation against the answer that actually succeeded -- corrupting the
    exact measurement this wiring exists to produce.
    """

    class _FirstAgentAlwaysFails:
        """Fail every call to ``broken_agent``; serve ``healthy_agent`` normally."""

        def proxy_send_once(
            self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]
        ) -> dict[str, Any]:
            """Raise for the broken agent, otherwise return a fixed answer."""
            del endpoint, payload
            if agent.id == "broken_agent":
                raise ProviderUpstreamError(
                    agent_id=agent.id,
                    model=agent.model,
                    error_code="model_not_found",
                    message="provider rejected the request with HTTP 404",
                    client_status=404,
                    provider_status=404,
                    retryable=False,
                    transport="passthrough",
                )
            return {
                "id": "resp_test",
                "object": "response",
                "model": agent.model,
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "served answer"}],
                    }
                ],
            }

        proxy_send = proxy_send_once

    broken = ModelAgent("broken_agent", "mock", tags=("reasoning",), priority=100)
    healthy = ModelAgent("healthy_agent", "mock", tags=("reasoning",), priority=1)
    orchestrator = TaskOrchestrator([broken, healthy], client=_FirstAgentAlwaysFails())
    orchestrator.conduct = lambda *args, **kwargs: dict(_STUB_CONDUCT)  # type: ignore[method-assign]

    captured: dict[str, object] = {}

    def _spy(
        task: str,
        fallback: dict[str, Any],
        *,
        free_only: bool = False,
        allowed_agent_ids: set[str] | None = None,
        excluded_agent_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        captured["excluded_agent_ids"] = excluded_agent_ids
        captured["judge"] = next(
            agent.id
            for agent in orchestrator._ranked_agents(task, "verifier")
            if allowed_agent_ids is None or agent.id in allowed_agent_ids
            if excluded_agent_ids is None or agent.id not in excluded_agent_ids
        )
        return {
            "accepted": True,
            "reason": "stub verdict",
            "verifier_output": fallback.get("verifier_output", ""),
            "judge": "model",
        }

    orchestrator._model_judge_verification = _spy  # type: ignore[method-assign]

    result = orchestrator.proxy_completion(
        {"input": "hello world"}, endpoint="responses", single_agent=False
    )

    assert result["output_text"] == "served answer"
    assert captured["excluded_agent_ids"] == {"broken_agent"}
    # Without the exclusion the higher-priority broken agent wins verifier
    # ranking and would have taken the judge call.
    assert captured["judge"] == "healthy_agent"


def test_realtime_judge_spend_reaches_budget_meter_and_spend_analytics() -> None:
    """The extra judge call's own tokens are metered, not silently free.

    Devin review (PR #1032): ``_realtime_route_judge``'s return value was
    discarded, so a real, already-incurred provider call was invisible to
    both the budget meter that gates *subsequent* requests and buyer-facing
    ``spend_analytics``.
    """
    agent = ModelAgent("worker_agent", "mock-model", tags=("reasoning",))
    client = _ResponsesUsageClient(
        content="final answer",
        usage={"input_tokens": 7, "output_tokens": 13, "total_tokens": 20},
    )
    orchestrator = TaskOrchestrator([agent], client=client)
    orchestrator.conduct = lambda *args, **kwargs: dict(_STUB_CONDUCT)  # type: ignore[method-assign]
    orchestrator._model_judge_verification = lambda task, fallback, **_ignored: {  # type: ignore[method-assign]
        "accepted": True,
        "reason": "stub verdict",
        "verifier_output": fallback.get("verifier_output", ""),
        "judge": "model",
        "judge_agent_id": "worker_agent",
        "judge_model": "mock-model",
        "judge_usage": {"prompt_tokens": 3, "completion_tokens": 29, "total_tokens": 32},
    }

    orchestrator.proxy_completion(
        {"input": "hello world"}, endpoint="responses", single_agent=False
    )

    run = next(iter(orchestrator._workflow_runs.values()))
    assert run["realtime_verification"]["judge_agent_id"] == "worker_agent"
    # The synthesis step reported 13 output tokens; the judge call reported
    # 29 more. Both must land on the meter -- 13 alone is the bug.
    assert orchestrator.budget_status()["spent_output_tokens"] == 13 + 29
    assert orchestrator._run_budget_output_by_model(run) == ({"mock-model": 13 + 29}, True)

    rows = {row["model"]: row for row in orchestrator.spend_analytics()["by_model"]}
    assert rows["mock-model"]["output_tokens"] == 13 + 29


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__]))
