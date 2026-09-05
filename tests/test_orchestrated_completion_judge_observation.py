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
  later ranking call, proving the routing gap this wiring closes;
- a request pinned to one explicit model keeps that pin through the judge
  call *and* through the prompt embedding the observation performs, so
  neither can reach a provider the request itself was never allowed to use;
- a budget rejection meters the provider calls this request already made
  instead of forgetting them, an observation-ledger write failure never
  costs the caller an already-generated answer, and a schema-repaired
  answer publishes the repair call's own latency rather than a span that
  also covers the synthesis attempt that was thrown away;
- a model whose structured synthesis *and* repair both failed before a
  different member of the same virtual pool succeeded still reaches every
  accounting path (trace, budget checkpoint, persisted run, spend analytics)
  without polluting the served answer's own latency/usage attribution;
- a routing-evidence cache entry is never reused across a change of
  embedding model, whose vectors live in a different space entirely.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import (  # noqa: E402
    BudgetExceededError,
    EffortProfileError,
    ProviderResponseError,
    ProviderUpstreamError,
    ReasoningEffortProfile,
    _request_eligibility_scope,
    _request_evidence_partition,
)

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


class _EmbeddingSpyClient:
    """Serve a fixed Responses answer and record every embedding provider call."""

    def __init__(self) -> None:
        self.embed_calls: list[str] = []

    def proxy_send_once(
        self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Return one fixed provider-shaped response for any agent."""
        del endpoint, payload
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

    def embed(self, agent: ModelAgent, texts: list[str]) -> list[list[float]]:
        """Record which provider was asked to embed request-derived text."""
        self.embed_calls.append(agent.id)
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_with_usage(
        self, agent: ModelAgent, texts: list[str]
    ) -> tuple[list[list[float]], int | None]:
        """Same fixed vectors; no authoritative usage (mirrors the mock transport)."""
        return self.embed(agent, texts), None


def _pinned_pool() -> tuple[ModelAgent, ModelAgent]:
    """One pinnable chat model plus an embedding deployment on another provider."""
    return (
        ModelAgent(
            "pinned_agent",
            "pinned-model",
            base_url="https://pinned.example/v1",
            tags=("reasoning",),
            priority=1,
        ),
        ModelAgent(
            "unrelated_agent",
            "unrelated-model",
            base_url="https://unrelated.example/v1",
            tags=("reasoning", "embedding"),
            priority=100,
        ),
    )


def test_explicit_structured_model_pin_constrains_realtime_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller-named explicit model pins the judge exactly like ``_required_agent_id``.

    Devin review (PR #1032): the judge's allow-list is derived from
    ``_required_agent_id`` alone, so an explicit structured model request --
    which pins synthesis to that one agent just as hard -- left the judge
    unrestricted and could send the prompt and served answer to an unrelated
    provider.
    """
    pinned, unrelated = _pinned_pool()
    orchestrator = TaskOrchestrator([pinned, unrelated], client=_EmbeddingSpyClient())
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
        captured["judge"] = next(
            (
                agent.id
                for agent in orchestrator._ranked_agents(task, "verifier")
                if allowed_agent_ids is None or agent.id in allowed_agent_ids
            ),
            None,
        )
        return {
            "accepted": True,
            "reason": "stub verdict",
            "verifier_output": fallback.get("verifier_output", ""),
            "judge": "model",
        }

    monkeypatch.setattr(orchestrator, "_model_judge_verification", _spy)

    result = orchestrator.proxy_completion(
        {"input": "hello world", "model": "pinned-model"},
        endpoint="responses",
        single_agent=False,
    )

    assert result["output_text"] == "served answer"
    # No _required_agent_id anywhere -- the pin came from `model` alone.
    assert captured["allowed_agent_ids"] == {"pinned_agent"}
    # Without the pin the higher-priority unrelated provider wins verifier
    # ranking and would have taken the judge call.
    assert captured["judge"] == "pinned_agent"


def test_explicit_structured_model_pin_blocks_ineligible_prompt_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The observation's prompt embedding honors the request's own eligibility.

    Devin review (PR #1032): the contextual observation embeds the prompt for
    routing evidence, and that embedding took no allow-list of its own -- so
    a request pinned to one provider could still hand its prompt to an
    unrelated embedding provider. The pinned request must reach no embedding
    provider at all here; the same pool with an unpinned virtual request
    still does, proving the block is the pin and not a missing deployment.
    """
    pinned, unrelated = _pinned_pool()

    def _accept(
        task: str, fallback: dict[str, Any], **_ignored: object
    ) -> dict[str, Any]:
        """Stand in for the judge verdict so only the embedding path is measured."""
        del task
        return {
            "accepted": True,
            "reason": "stub verdict",
            "verifier_output": fallback.get("verifier_output", ""),
            "judge": "model",
        }

    pinned_client = _EmbeddingSpyClient()
    pinned_orchestrator = TaskOrchestrator([pinned, unrelated], client=pinned_client)
    pinned_orchestrator.conduct = lambda *args, **kwargs: dict(_STUB_CONDUCT)  # type: ignore[method-assign]
    monkeypatch.setattr(pinned_orchestrator, "_model_judge_verification", _accept)

    pinned_orchestrator.proxy_completion(
        {"input": "confidential prompt", "model": "pinned-model"},
        endpoint="responses",
        single_agent=False,
    )
    assert pinned_client.embed_calls == []
    assert pinned_orchestrator._psychometric_router.has_observations() is True

    open_client = _EmbeddingSpyClient()
    open_orchestrator = TaskOrchestrator([pinned, unrelated], client=open_client)
    open_orchestrator.conduct = lambda *args, **kwargs: dict(_STUB_CONDUCT)  # type: ignore[method-assign]
    monkeypatch.setattr(open_orchestrator, "_model_judge_verification", _accept)

    open_orchestrator.proxy_completion(
        {"input": "confidential prompt"}, endpoint="responses", single_agent=False
    )
    assert "unrelated_agent" in open_client.embed_calls


def test_eligibility_scope_narrows_embedding_to_reachable_providers() -> None:
    """Embedding eligibility follows the provider, not the exact model id.

    The narrowing must block an unrelated provider without silently killing
    routing evidence for every restricted request: an embedding deployment
    behind an endpoint the request already reaches stays usable, an empty
    allow-list yields no embedding at all, and no scope keeps the
    unrestricted pick.
    """
    chat = ModelAgent(
        "chat_agent",
        "chat-model",
        base_url="https://same.example/v1",
        tags=("reasoning",),
    )
    same_provider = ModelAgent(
        "same_embedder",
        "embed-model",
        base_url="https://same.example/v1/",
        tags=("embedding",),
    )
    other_provider = ModelAgent(
        "other_embedder",
        "other-embed-model",
        base_url="https://other.example/v1",
        tags=("embedding",),
        priority=100,
    )
    orchestrator = TaskOrchestrator([chat, same_provider, other_provider])

    unrestricted = orchestrator._embedding_agent_id()
    assert unrestricted == "other_embedder"
    with _request_eligibility_scope({"chat_agent"}):
        assert orchestrator._embedding_agent_id() == "same_embedder"
    with _request_eligibility_scope(set()):
        assert orchestrator._embedding_agent_id() is None
    with _request_eligibility_scope(None):
        assert orchestrator._embedding_agent_id() == unrestricted


def test_free_scope_embedding_endpoint_fallback_requires_free_pricing() -> None:
    """A free-scoped eligible set's endpoint fallback must stay free-priced.

    Devin review (PR #1032, round 6): the endpoint-sharing fallback in
    ``_embedding_agent_id`` is privacy-only -- it says nothing about cost.
    ``free_only`` builds an eligible set that is entirely free (see the
    ``allowed_agent_ids`` branch in ``_orchestrated_provider_completion``),
    so admitting a *paid* embedding deployment purely because it shares an
    endpoint with a free eligible agent lets a free request incur real,
    unmetered spend outside every budget check.
    """
    free_chat = ModelAgent(
        "chat_free",
        "chat-free-model",
        base_url="https://shared.example/v1",
        tags=("reasoning", "cost:free"),
    )
    paid_embedder = ModelAgent(
        "paid_embedder",
        "paid-embed-model",
        base_url="https://shared.example/v1/",
        tags=("embedding",),
    )
    orchestrator = TaskOrchestrator([free_chat, paid_embedder])
    with _request_eligibility_scope({free_chat.id}):
        assert orchestrator._embedding_agent_id() is None

    # A genuinely free co-located embedder must still ride along -- the gate
    # excludes the paid sibling, it does not over-block the free scope.
    free_embedder = ModelAgent(
        "free_embedder",
        "free-embed-model",
        base_url="https://shared.example/v1",
        tags=("embedding", "cost:free"),
    )
    orchestrator_with_free = TaskOrchestrator([free_chat, paid_embedder, free_embedder])
    with _request_eligibility_scope({free_chat.id}):
        assert orchestrator_with_free._embedding_agent_id() == free_embedder.id


def test_paid_pin_embedding_endpoint_fallback_stays_privacy_only() -> None:
    """An explicit paid pin's endpoint fallback is unaffected by the cost gate.

    The free-scope gate fires only when the *entire* eligible set is free.
    An explicit paid pin's eligible set is a single paid agent, so its
    endpoint-sharing fallback keeps admitting a co-located deployment
    regardless of price -- the pre-existing privacy-only rationale, unchanged
    by the fix above.
    """
    paid_chat = ModelAgent(
        "chat_paid",
        "chat-paid-model",
        base_url="https://shared.example/v1",
        tags=("reasoning",),
    )
    paid_embedder = ModelAgent(
        "paid_embedder",
        "paid-embed-model",
        base_url="https://shared.example/v1/",
        tags=("embedding",),
    )
    orchestrator = TaskOrchestrator([paid_chat, paid_embedder])
    with _request_eligibility_scope({paid_chat.id}):
        assert orchestrator._embedding_agent_id() == paid_embedder.id


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


def test_conduct_verification_judge_spend_counts_toward_realtime_judge_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """conduct's own verifier judge is current-request spend the gate must see.

    Devin review (PR #1032): ``conduct`` runs its own verifier-role judge and
    records it in ``workflow["verification"]``, never as a trace row. A gate
    built from trace rows plus synthesis/repair therefore missed it, so a
    request whose allowance was already consumed by that first judge fired
    the optional second one anyway.

    The budget here (64 judge tokens + 1) is crossed only by summing *both*
    completed calls: the 13-token synthesis alone stays well inside it, which
    is exactly why counting trace rows alone let the judge through.
    """
    agent = ModelAgent("worker_agent", "mock-model", tags=("reasoning",))
    client = _ResponsesUsageClient(
        content="final answer",
        usage={"input_tokens": 7, "output_tokens": 13, "total_tokens": 20},
    )
    orchestrator = TaskOrchestrator([agent], client=client)
    orchestrator.conduct = lambda *args, **kwargs: {  # type: ignore[method-assign]
        **_STUB_CONDUCT,
        "verification": {
            "accepted": True,
            "reason": "test",
            "verifier_output": "",
            "judge": "model",
            "judge_agent_id": "worker_agent",
            "judge_model": "mock-model",
            "judge_usage": {"prompt_tokens": 3, "completion_tokens": 64, "total_tokens": 67},
        },
    }
    orchestrator.budget_max_output_tokens = 65
    # Nothing is persisted yet: the whole overrun is this request's own
    # in-flight spend, which budget_status() alone cannot see.
    assert orchestrator.budget_status()["exceeded"] is False

    def _explode(*args: object, **kwargs: object) -> dict[str, Any]:
        raise AssertionError("realtime judge must be skipped once budget is already exceeded")

    monkeypatch.setattr(orchestrator, "_model_judge_verification", _explode)

    result = orchestrator.proxy_completion(
        {"input": "hello world"}, endpoint="responses", single_agent=False
    )

    # The already-decided answer is still served; only the optional second
    # judge is skipped.
    assert result["output_text"] == "final answer"
    assert orchestrator._quality_router.member_observation_count("worker_agent") == 0
    run = next(iter(orchestrator._workflow_runs.values()))
    assert run["realtime_verification"] is None


def test_restricted_request_cannot_read_an_incompatible_scopes_cached_evidence() -> None:
    """A cached routing vector never crosses the request-eligibility boundary.

    Devin review (PR #1032): the evidence caches were keyed on text and
    endpoint alone and were read *before* ``_embedding_agent_id`` validated
    anything, so a restricted request hitting a key an earlier unrestricted
    request had filled inherited that ineligible provider's vector -- and the
    routing evidence baked into it -- straight past the isolation boundary
    the scope exists to draw.

    The cache still has to work for the restricted path it exists to make
    cheap, so a second request under the *same* scope must still hit.
    """
    chat = ModelAgent(
        "chat_agent",
        "chat-model",
        base_url="https://chat.example/v1",
        tags=("reasoning",),
    )
    unrelated_embedder = ModelAgent(
        "unrelated_embedder",
        "embed-model",
        base_url="https://unrelated.example/v1",
        tags=("embedding",),
    )
    client = _EmbeddingSpyClient()
    orchestrator = TaskOrchestrator([chat, unrelated_embedder], client=client)

    # An earlier unrestricted request fills the cache from a provider a
    # chat_agent-scoped request may not reach.
    assert orchestrator._embed_cached("confidential prompt") == [0.1, 0.2, 0.3]
    assert orchestrator._descriptor_vector_cached(chat) == [0.1, 0.2, 0.3]
    assert client.embed_calls == ["unrelated_embedder", "unrelated_embedder"]

    with _request_eligibility_scope({"chat_agent"}):
        assert orchestrator._embed_cached("confidential prompt") is None
        assert orchestrator._descriptor_vector_cached(chat) is None
    # No eligible embedder, so no provider call either -- the restricted
    # request degrades to declaration-only evidence, it does not borrow.
    assert client.embed_calls == ["unrelated_embedder", "unrelated_embedder"]

    # Same scope twice still hits the cache: the fix partitions the cache, it
    # does not disable it.
    with _request_eligibility_scope({"chat_agent", "unrelated_embedder"}):
        assert orchestrator._embed_cached("confidential prompt") == [0.1, 0.2, 0.3]
        assert orchestrator._embed_cached("confidential prompt") == [0.1, 0.2, 0.3]
    assert client.embed_calls == [
        "unrelated_embedder",
        "unrelated_embedder",
        "unrelated_embedder",
    ]


_JUDGED_WORKFLOW = {
    "mode": "conduct",
    "answer": "evidence",
    "trace": [
        {
            "id": 0,
            "role": "worker",
            "agent_id": "worker_agent",
            "subtask": "do the work",
            "access": [],
            "output": "worker output",
            "usage": {"prompt_tokens": 5, "completion_tokens": 60, "total_tokens": 65},
        }
    ],
    "verification": {
        "accepted": True,
        "reason": "test",
        "verifier_output": "",
        "judge": "model",
        "judge_agent_id": "worker_agent",
        "judge_model": "mock-model",
        "judge_usage": {"prompt_tokens": 3, "completion_tokens": 45, "total_tokens": 48},
    },
}


def test_budget_rejection_meters_the_spend_conduct_already_incurred() -> None:
    """A rejected request still pays for the provider calls it already made.

    Devin review (PR #1032): ``_replace_workflow_run`` is the only path onto
    the budget meter and this request persists nothing until it succeeds, so
    the post-conduct checkpoint's raise dropped every call ``conduct`` had
    already completed -- its workflow trace *and* its verifier-role judge.
    The next request was then admitted against understated spend, burned the
    same allowance again, and forgot it again, with no bound on the repeat.

    The 100-token cap here is crossed only by the two completed calls
    together (60 worker + 45 judge), which is exactly the spend that used to
    vanish.
    """
    agent = ModelAgent("worker_agent", "mock-model", tags=("reasoning",))
    client = _ResponsesUsageClient(
        content="never served",
        usage={"input_tokens": 7, "output_tokens": 13, "total_tokens": 20},
    )
    orchestrator = TaskOrchestrator([agent], client=client)
    conduct_calls: list[object] = []

    def _conduct(*_args: object, **_kwargs: object) -> dict[str, Any]:
        """Return one already-completed workflow and count the attempt."""
        conduct_calls.append(object())
        return {**_JUDGED_WORKFLOW}

    orchestrator.conduct = _conduct  # type: ignore[method-assign]
    orchestrator.budget_max_output_tokens = 100

    with pytest.raises(BudgetExceededError):
        orchestrator.proxy_completion(
            {"input": "hello world"}, endpoint="responses", single_agent=False
        )

    # The rejection never reached synthesis, but 60 + 45 output tokens had
    # already left the wallet: the meter has to say so.
    assert client.calls == []
    assert orchestrator.budget_status()["spent_output_tokens"] == 60 + 45
    assert orchestrator.budget_status()["exceeded"] is True

    # ...without the failed request ever surfacing as a finished workflow.
    assert orchestrator.count_workflow_runs() == 0
    assert orchestrator.list_recent_runs() == []

    # And the next request is stopped before it can burn the same allowance
    # again -- against a meter that forgot, conduct ran once per request.
    with pytest.raises(BudgetExceededError):
        orchestrator.proxy_completion(
            {"input": "hello again"}, endpoint="responses", single_agent=False
        )
    assert len(conduct_calls) == 1
    assert orchestrator.budget_status()["spent_output_tokens"] == 60 + 45


def test_observation_write_failure_never_discards_a_completed_answer(
    tmp_path: Path,
) -> None:
    """A failed routing-evidence write costs the observation, never the answer.

    Devin review (PR #1032): the observation-only judge runs after synthesis
    has already succeeded but before the response and its workflow run are
    persisted, and ``_observe_contextual_quality`` writes through the state
    store. A store failure there therefore threw away a perfectly good
    answer *and* kept the synthesis and judge spend it had already incurred
    from ever reaching the ledger.
    """
    agent = ModelAgent("worker_agent", "mock-model", tags=("reasoning",))
    client = _ResponsesUsageClient(
        content="final answer",
        usage={"input_tokens": 7, "output_tokens": 13, "total_tokens": 20},
    )
    orchestrator = TaskOrchestrator(
        [agent], client=client, state_db=str(tmp_path / "state.db")
    )
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
    assert orchestrator._store is not None
    healthy_save = orchestrator._store.save

    def _failing_save(
        kind: str, key: str | None, payload: dict[str, Any], **options: Any
    ) -> None:
        """Fail exactly the psychometric write; leave run persistence working."""
        if kind == "psychometric_observation":
            raise sqlite3.OperationalError("disk I/O error")
        healthy_save(kind, key, payload, **options)

    orchestrator._store.save = _failing_save  # type: ignore[method-assign]

    result = orchestrator.proxy_completion(
        {"input": "hello world"}, endpoint="responses", single_agent=False
    )

    assert result["output_text"] == "final answer"
    # Accounting still lands: the completed judge call and the synthesis both
    # reach the run record and the budget meter.
    run = next(iter(orchestrator._workflow_runs.values()))
    assert run["realtime_verification"]["judge_agent_id"] == "worker_agent"
    assert orchestrator.budget_status()["spent_output_tokens"] == 13 + 29
    assert orchestrator._quality_router.member_report("worker_agent")["success_count"] == 1


class _SchemaRepairClient:
    """Answer one slow schema violation, then a fast valid repair."""

    def __init__(self, *, first_delay: float) -> None:
        self.first_delay = first_delay
        self.calls = 0

    def proxy_send(
        self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Return the invalid first synthesis, then the valid repair."""
        del agent, endpoint, payload
        self.calls += 1
        if self.calls == 1:
            time.sleep(self.first_delay)
            return {
                "choices": [{"message": {"content": '{"input_count":6}'}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            }
        return {
            "choices": [{"message": {"content": '{"input_count":10}'}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 4, "total_tokens": 6},
        }

    proxy_send_once = proxy_send


def test_repaired_answer_publishes_only_the_repair_calls_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A repaired answer's throughput sample times the call that produced it.

    Devin review (PR #1032): ``synthesis_started`` precedes the *rejected*
    first synthesis, so the published latency spanned both calls while the
    usage published beside it covered only the repair -- understating the
    serving model's real throughput in the very ledger this observation
    exists to keep honest.
    """
    agent = ModelAgent("worker_agent", "mock-model", tags=("reasoning",))
    client = _SchemaRepairClient(first_delay=0.05)
    orchestrator = TaskOrchestrator([agent], client=client)
    orchestrator.conduct = lambda *args, **kwargs: dict(_STUB_CONDUCT)  # type: ignore[method-assign]
    monkeypatch.setattr(
        orchestrator,
        "_model_judge_verification",
        lambda task, fallback, **_ignored: {
            "accepted": True,
            "reason": "stub verdict",
            "verifier_output": fallback.get("verifier_output", ""),
            "judge": "model",
        },
    )

    captured: dict[str, Any] = {}
    original_judge = TaskOrchestrator._realtime_route_judge

    def _spy(self: TaskOrchestrator, **kwargs: Any) -> dict[str, Any]:
        """Record the observation's arguments and run the real call."""
        captured.update(kwargs)
        return original_judge(self, **kwargs)

    monkeypatch.setattr(TaskOrchestrator, "_realtime_route_judge", _spy)

    result = orchestrator.proxy_completion(
        {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "classify ten items"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "exact_count",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {"input_count": {"const": 10}},
                        "required": ["input_count"],
                        "additionalProperties": False,
                    },
                },
            },
        },
        single_agent=False,
    )

    assert client.calls == 2
    assert result["choices"][0]["message"]["content"] == '{"input_count":10}'
    run = orchestrator.get_workflow_run(result["orchestration"]["workflow_run_id"])
    repair_step = run["trace"][-1]
    assert repair_step["role"] == "repair"
    # The usage published beside the latency is the repair call's own, so the
    # latency has to be the repair call's own too.
    assert captured["usage"]["completion_tokens"] == 4
    assert captured["latency_seconds"] == pytest.approx(repair_step["latency_ms"] / 1000)
    # The thrown-away first synthesis alone took 50ms; it is not folded in.
    assert captured["latency_seconds"] < client.first_delay


_EXACT_TEN = {
    "type": "json_schema",
    "json_schema": {
        "name": "exact_count",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"input_count": {"const": 10}},
            "required": ["input_count"],
            "additionalProperties": False,
        },
    },
}


class _SchemaFailoverClient:
    """Violate the caller's schema on named members, satisfy it on the rest.

    Every response reports usage, and a failing member's synthesis and repair
    report *different* token counts, so each individual attempt is
    identifiable in the budget meter's per-model totals.
    """

    FAILED_SYNTHESIS_TOKENS = 11
    FAILED_REPAIR_TOKENS = 13
    SERVED_TOKENS = 17

    def __init__(self, *failing_agent_ids: str) -> None:
        self._failing_agent_ids = frozenset(failing_agent_ids)
        self.calls: list[str] = []

    def proxy_send_once(
        self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Return a schema-violating answer for the failing members only."""
        del endpoint, payload
        self.calls.append(agent.id)
        if agent.id not in self._failing_agent_ids:
            content, completion = '{"input_count": 10}', self.SERVED_TOKENS
        else:
            content = '{"input_count": 6}'
            completion = (
                self.FAILED_SYNTHESIS_TOKENS
                if self.calls.count(agent.id) == 1
                else self.FAILED_REPAIR_TOKENS
            )
        return {
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {
                "prompt_tokens": 5,
                "completion_tokens": completion,
                "total_tokens": 5 + completion,
            },
        }

    proxy_send = proxy_send_once


def test_failed_schema_attempts_reach_every_spend_accounting_path() -> None:
    """A discarded model's synthesis and repair are metered, not silently free.

    Devin review (PR #1032): in the virtual same-endpoint retry loop
    ``synthesis_step``/``repair_step`` are rebound on every pass, so when one
    model failed structured synthesis *and* its repair before a different
    member of the same pool succeeded, that first model's two completed
    provider calls disappeared from the final trace -- and therefore from the
    budget checkpoint, the persisted run, and buyer-facing spend analytics.
    Genuine provider spend went unmetered.

    Distinct from the rejected-request case an earlier round fixed: these are
    attempts that completed and were *followed* by a successful one, not a
    wholesale request rejection.
    """
    first = ModelAgent(
        "first_agent", "first-model", base_url="mock://pool", tags=("reasoning",)
    )
    second = ModelAgent(
        "second_agent", "second-model", base_url="mock://pool", tags=("reasoning",)
    )
    client = _SchemaFailoverClient(first.id)
    orchestrator = TaskOrchestrator([first, second], client=client)
    # Isolate synthesis accounting: the optional observation-only judge has
    # its own already-covered metering path (test above).
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    orchestrator.conduct = lambda *args, **kwargs: dict(_STUB_CONDUCT)  # type: ignore[method-assign]
    orchestrator._select_agent = lambda *args, **kwargs: first  # type: ignore[method-assign]
    orchestrator._failover_candidates = lambda *args, **kwargs: [first, second]  # type: ignore[method-assign]

    result = orchestrator.proxy_completion(
        {
            "model": TaskOrchestrator.AUTO_MODEL,
            "messages": [{"role": "user", "content": "classify ten items"}],
            "response_format": _EXACT_TEN,
        },
        single_agent=False,
    )

    assert result["choices"][0]["message"]["content"] == '{"input_count": 10}'
    assert client.calls == [first.id, first.id, second.id]

    run = next(iter(orchestrator._workflow_runs.values()))
    trace = run["trace"]
    assert [(step["role"], step["agent_id"]) for step in trace] == [
        ("synthesizer", first.id),
        ("repair", first.id),
        ("synthesizer", second.id),
    ]
    # Unique, contiguous step ids: `access` indexes the trace positionally
    # (see get_access_report), so a rebound id would misattribute evidence.
    assert [step["id"] for step in trace] == [0, 1, 2]
    assert trace[1]["access"] == [0]
    # The discarded attempts are marked, so an auditor reading the persisted
    # run can tell them from the row that actually produced `answer`.
    assert trace[0]["structured_output_error"]
    assert trace[1]["structured_output_error"]
    assert "structured_output_error" not in trace[2]

    # Every completed call reaches the meter and buyer-facing analytics.
    failed_tokens = (
        _SchemaFailoverClient.FAILED_SYNTHESIS_TOKENS
        + _SchemaFailoverClient.FAILED_REPAIR_TOKENS
    )
    assert orchestrator._run_budget_output_by_model(run) == (
        {
            "first-model": failed_tokens,
            "second-model": _SchemaFailoverClient.SERVED_TOKENS,
        },
        True,
    )
    assert orchestrator.budget_status()["spent_output_tokens"] == (
        failed_tokens + _SchemaFailoverClient.SERVED_TOKENS
    )
    rows = {row["model"]: row for row in orchestrator.spend_analytics()["by_model"]}
    assert rows["first-model"]["output_tokens"] == failed_tokens

    # Response-facing attribution stays on the served call alone.
    assert run["answer"] == '{"input_count": 10}'
    assert result["usage"]["completion_tokens"] == _SchemaFailoverClient.SERVED_TOKENS


def test_failed_schema_attempt_spend_gates_the_next_budget_checkpoint() -> None:
    """The discarded attempts count against this request's own in-flight budget.

    The same rebinding hid them from ``_trace_budget_spend``, so a request
    that had already burned its allowance on a failed model kept firing
    further provider calls. Both members violate the schema here, so the
    second one's pre-repair checkpoint is reached with the first one's two
    completed calls behind it: 11 + 13 + 11 = 35 crosses the 34-token
    allowance, while the second member's own synthesis (11) alone does not --
    which is precisely why counting the current attempt alone let it through.
    """
    first = ModelAgent(
        "first_agent", "first-model", base_url="mock://pool", tags=("reasoning",)
    )
    second = ModelAgent(
        "second_agent", "second-model", base_url="mock://pool", tags=("reasoning",)
    )
    client = _SchemaFailoverClient(first.id, second.id)
    orchestrator = TaskOrchestrator([first, second], client=client)
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    orchestrator.conduct = lambda *args, **kwargs: dict(_STUB_CONDUCT)  # type: ignore[method-assign]
    orchestrator._select_agent = lambda *args, **kwargs: first  # type: ignore[method-assign]
    orchestrator._failover_candidates = lambda *args, **kwargs: [first, second]  # type: ignore[method-assign]
    # Nothing persisted yet, so the whole overrun is in-flight spend.
    orchestrator.budget_max_output_tokens = (
        _SchemaFailoverClient.FAILED_SYNTHESIS_TOKENS * 2
        + _SchemaFailoverClient.FAILED_REPAIR_TOKENS
        - 1
    )
    assert orchestrator.budget_status()["exceeded"] is False

    with pytest.raises(BudgetExceededError):
        orchestrator.proxy_completion(
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "messages": [{"role": "user", "content": "classify ten items"}],
                "response_format": _EXACT_TEN,
            },
            single_agent=False,
        )

    # The second member's synthesis ran (the checkpoint is pre-repair), and
    # its repair was refused. Without the fix that fourth call is made.
    assert client.calls == [first.id, first.id, second.id]


def test_pinned_terminal_schema_failure_meters_the_spend_it_already_incurred() -> None:
    """An explicitly pinned model's terminal schema failure still meters spend.

    Devin review (PR #1032, round 6): when synthesis and repair both violate
    the schema on an explicitly pinned model (``virtual_model`` is False,
    ``synthesis_candidates == [final_agent]``), the loop raises
    ``ProviderResponseError`` before ``failed_attempts.extend(...)`` ever
    runs. Those two completed provider calls are real spend, but they never
    reached the trace, the budget meter, or spend_analytics -- and no
    workflow run is ever persisted for a request that never served an
    answer, so ``count_workflow_runs`` must stay unaffected too.
    """
    agent = ModelAgent(
        "pinned_agent", "pinned-model", base_url="mock://pool", tags=("reasoning",)
    )
    client = _SchemaFailoverClient(agent.id)
    orchestrator = TaskOrchestrator([agent], client=client)
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    orchestrator.conduct = lambda *args, **kwargs: dict(_STUB_CONDUCT)  # type: ignore[method-assign]

    with pytest.raises(ProviderResponseError):
        orchestrator.proxy_completion(
            {
                "model": agent.model,
                "messages": [{"role": "user", "content": "classify ten items"}],
                "response_format": _EXACT_TEN,
            },
            single_agent=False,
        )

    assert client.calls == [agent.id, agent.id]
    assert orchestrator.budget_status()["spent_output_tokens"] == (
        _SchemaFailoverClient.FAILED_SYNTHESIS_TOKENS
        + _SchemaFailoverClient.FAILED_REPAIR_TOKENS
    )
    assert orchestrator.count_workflow_runs() == 0


def test_pool_exhausted_schema_failure_meters_the_spend_it_already_incurred() -> None:
    """A virtual pool's same-endpoint exhaustion also meters its spend.

    Devin review (PR #1032, round 6): distinct from the pinned-model case
    above -- this exercises the ``next_agent is None`` exit, reached on a
    virtual/``AUTO_MODEL`` request whose failover candidates yield no other
    agent on the same endpoint. Same silent loss: the raise happened before
    ``failed_attempts.extend(...)``.
    """
    agent = ModelAgent(
        "pool_agent", "pool-model", base_url="mock://pool", tags=("reasoning",)
    )
    client = _SchemaFailoverClient(agent.id)
    orchestrator = TaskOrchestrator([agent], client=client)
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    orchestrator.conduct = lambda *args, **kwargs: dict(_STUB_CONDUCT)  # type: ignore[method-assign]
    orchestrator._select_agent = lambda *args, **kwargs: agent  # type: ignore[method-assign]
    orchestrator._failover_candidates = lambda *args, **kwargs: [agent]  # type: ignore[method-assign]

    with pytest.raises(ProviderResponseError):
        orchestrator.proxy_completion(
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "messages": [{"role": "user", "content": "classify ten items"}],
                "response_format": _EXACT_TEN,
            },
            single_agent=False,
        )

    assert client.calls == [agent.id, agent.id]
    assert orchestrator.budget_status()["spent_output_tokens"] == (
        _SchemaFailoverClient.FAILED_SYNTHESIS_TOKENS
        + _SchemaFailoverClient.FAILED_REPAIR_TOKENS
    )
    assert orchestrator.count_workflow_runs() == 0


class _TransportFailureClient:
    """Every synthesis attempt raises before any provider response exists."""

    def proxy_send_once(
        self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Simulate a transport failure: no response, nothing to meter here."""
        del agent, endpoint, payload
        raise RuntimeError("connection reset by peer")

    proxy_send = proxy_send_once


_TRACED_CONDUCT = {
    "mode": "conduct",
    "answer": "evidence",
    "trace": [
        {
            "id": 0,
            "role": "worker",
            "agent_id": "worker_agent",
            "subtask": "do the work",
            "access": [],
            "output": "worker output",
            "usage": {"prompt_tokens": 2, "completion_tokens": 9, "total_tokens": 11},
        }
    ],
    "verification": {"accepted": True, "reason": "test", "verifier_output": ""},
}


def test_synthesis_transport_failure_meters_the_spend_it_already_incurred() -> None:
    """A transport failure on synthesis still meters ``conduct``'s prior spend.

    Devin review (PR #1032, round 7): distinct from round 6's two
    schema-violation exits below this same ``except Exception`` clause -- a
    transport failure (a raised ``ProviderUpstreamError`` or similar, as
    opposed to a schema-violating response) raises before any
    ``budget_checkpoint`` in this loop ever runs, so ``conduct()``'s
    already-completed workflow trace vanished from the meter exactly like the
    post-conduct checkpoint's own except-clause guards against.
    """
    agent = ModelAgent(
        "pinned_agent", "pinned-model", base_url="mock://pool", tags=("reasoning",)
    )
    client = _TransportFailureClient()
    orchestrator = TaskOrchestrator([agent], client=client)
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    orchestrator.conduct = lambda *args, **kwargs: dict(_TRACED_CONDUCT)  # type: ignore[method-assign]

    with pytest.raises(ProviderUpstreamError):
        orchestrator.proxy_completion(
            {
                "model": agent.model,
                "messages": [{"role": "user", "content": "classify ten items"}],
                "response_format": _EXACT_TEN,
            },
            single_agent=False,
        )

    assert orchestrator.budget_status()["spent_output_tokens"] == 9
    assert orchestrator.count_workflow_runs() == 0


class _RepairTransportFailureClient:
    """Schema-violating synthesis, then a transport failure on the repair."""

    SYNTHESIS_TOKENS = 11

    def __init__(self) -> None:
        self.calls = 0

    def proxy_send_once(
        self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """First call: completed but schema-violating. Second: raises."""
        del endpoint, payload
        self.calls += 1
        if self.calls == 1:
            return {
                "choices": [{"message": {"role": "assistant", "content": '{"input_count": 6}'}}],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": self.SYNTHESIS_TOKENS,
                    "total_tokens": 5 + self.SYNTHESIS_TOKENS,
                },
            }
        del agent
        raise RuntimeError("connection reset by peer")

    proxy_send = proxy_send_once


def test_repair_transport_failure_meters_the_completed_synthesis_spend() -> None:
    """A transport failure on repair still meters the synthesis it repairs.

    Devin review (PR #1032, round 7): ``synthesis_step`` is a real, paid-for
    call that produced the schema-violating output prompting this repair. It
    has not yet reached ``failed_attempts`` (only added once a repair
    response exists to check), so a transport failure on the repair call
    itself dropped it from the meter along with everything else in
    ``workflow["trace"]``/``failed_attempts``.
    """
    agent = ModelAgent(
        "pinned_agent", "pinned-model", base_url="mock://pool", tags=("reasoning",)
    )
    client = _RepairTransportFailureClient()
    orchestrator = TaskOrchestrator([agent], client=client)
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    orchestrator.conduct = lambda *args, **kwargs: dict(_STUB_CONDUCT)  # type: ignore[method-assign]

    with pytest.raises(ProviderUpstreamError):
        orchestrator.proxy_completion(
            {
                "model": agent.model,
                "messages": [{"role": "user", "content": "classify ten items"}],
                "response_format": _EXACT_TEN,
            },
            single_agent=False,
        )

    assert client.calls == 2
    assert (
        orchestrator.budget_status()["spent_output_tokens"]
        == _RepairTransportFailureClient.SYNTHESIS_TOKENS
    )
    assert orchestrator.count_workflow_runs() == 0


class _RepairEffortProfileFailureClient:
    """Schema-violating synthesis, then an unconverted ``EffortProfileError`` on repair.

    ``apply_effort_profile`` runs before ``send_synthesis``'s own inner
    ``try:`` in the structured-synthesis loop, so an ``EffortProfileError`` it
    raises is never passed through ``classify_provider_failure`` -- it leaves
    ``send_synthesis`` as a raw, unconverted exception. ``EffortProfileError``
    does not inherit from ``ProviderUpstreamError``, so the repair call site's
    own ``except ProviderUpstreamError`` could never catch it either
    (CodeRabbit review, PR #1032, round 10).
    """

    SYNTHESIS_TOKENS = 11

    def __init__(self) -> None:
        self.calls = 0
        self.effort_calls = 0

    def apply_effort_profile(
        self,
        agent: ModelAgent,
        payload: dict[str, Any],
        profile: ReasoningEffortProfile | None,
        *,
        api_surface: str = "chat.completions",
    ) -> dict[str, Any]:
        """First call (initial synthesis): pass through. Second (repair): raise."""
        del agent, profile, api_surface
        self.effort_calls += 1
        if self.effort_calls == 1:
            return payload
        raise EffortProfileError("provider reasoning_effort support is unproven")

    def proxy_send_once(
        self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """The only provider call that ever completes: schema-violating synthesis."""
        del agent, endpoint, payload
        self.calls += 1
        return {
            "choices": [{"message": {"role": "assistant", "content": '{"input_count": 6}'}}],
            "usage": {
                "prompt_tokens": 5,
                "completion_tokens": self.SYNTHESIS_TOKENS,
                "total_tokens": 5 + self.SYNTHESIS_TOKENS,
            },
        }

    proxy_send = proxy_send_once


def test_repair_effort_profile_error_still_meters_the_completed_synthesis_spend() -> None:
    """An unconverted ``EffortProfileError`` on repair still meters synthesis spend.

    CodeRabbit review (PR #1032, round 10): the repair call site's
    ``except ProviderUpstreamError`` is narrower than the initial-call site's
    own ``except Exception``, so an ``EffortProfileError`` from the repair
    attempt (raised by ``apply_effort_profile``, which ``send_synthesis`` calls
    before its own ``except Exception`` could ever convert it) skipped both
    the accounting exclusion *and* the ``_meter_unserved_spend`` call entirely
    -- the already-incurred synthesis spend silently vanished, exactly the
    "spend lost" class rounds 4/6/7 already fixed for other exception types.
    A misconfigured effort profile is also not the agent's fault, so it must
    stay excluded from routing penalties exactly like the initial-call site
    already excludes it.
    """
    agent = ModelAgent(
        "pinned_agent",
        "pinned-model",
        base_url="mock://pool",
        tags=("reasoning",),
        group_name="repair_pool",
    )
    client = _RepairEffortProfileFailureClient()
    orchestrator = TaskOrchestrator([agent], client=client)
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    orchestrator.conduct = lambda *args, **kwargs: dict(_STUB_CONDUCT)  # type: ignore[method-assign]
    prior_beta = orchestrator._group_router._members[agent.id]["beta"]

    with pytest.raises(EffortProfileError):
        orchestrator.proxy_completion(
            {
                "model": agent.model,
                "messages": [{"role": "user", "content": "classify ten items"}],
                "response_format": _EXACT_TEN,
            },
            single_agent=False,
            effort_profile=ReasoningEffortProfile(),
        )

    # (a) the EffortProfileError itself propagates -- the fix does not
    # swallow it, it only ensures accounting runs first.
    assert client.calls == 1
    assert client.effort_calls == 2
    # (b) the synthesis call's spend, already incurred before repair failed,
    # reached the budget meter.
    assert (
        orchestrator.budget_status()["spent_output_tokens"]
        == _RepairEffortProfileFailureClient.SYNTHESIS_TOKENS
    )
    assert orchestrator.spend_analytics()["totals"]["output_tokens"] == (
        _RepairEffortProfileFailureClient.SYNTHESIS_TOKENS
    )
    assert orchestrator.count_workflow_runs() == 0
    # (c) neither the circuit breaker nor the group router's stability
    # posterior recorded a failure for this agent.
    assert agent.id not in orchestrator._circuit
    assert orchestrator._group_router._members[agent.id]["beta"] == prior_beta


class _EmbeddingSpaceSpyClient:
    """One distinct unit vector per embedding deployment, every call recorded."""

    VECTORS = {
        "first_embedder": [1.0, 0.0, 0.0],
        "second_embedder": [0.0, 1.0, 0.0],
    }

    def __init__(self) -> None:
        self.embed_calls: list[str] = []

    def embed(self, agent: ModelAgent, texts: list[str]) -> list[list[float]]:
        """Return this deployment's own vector space, recording the caller."""
        self.embed_calls.append(agent.id)
        return [list(self.VECTORS[agent.id]) for _ in texts]

    def embed_with_usage(
        self, agent: ModelAgent, texts: list[str]
    ) -> tuple[list[list[float]], int | None]:
        """Same vector space; no authoritative usage (mirrors the mock transport)."""
        return self.embed(agent, texts), None


def _embedding_space_pool() -> tuple[ModelAgent, ModelAgent, ModelAgent]:
    """One chat model plus two embedding deployments in one eligible set."""
    return (
        ModelAgent(
            "chat_agent", "chat-model", base_url="mock://pool", tags=("reasoning",)
        ),
        ModelAgent(
            "first_embedder",
            "first-embed-model",
            base_url="mock://pool",
            tags=("embedding",),
            priority=10,
        ),
        ModelAgent(
            "second_embedder",
            "second-embed-model",
            base_url="mock://pool",
            tags=("embedding",),
            priority=1,
        ),
    )


def test_evidence_cache_is_not_reused_across_a_change_of_embedding_model() -> None:
    """A cached vector never survives the embedder that produced it changing.

    Devin review (PR #1032): the eligibility partition
    (``_request_evidence_partition``) is keyed on endpoint identity, ZDR mode
    and the sorted allow-list -- the restrictions that *select* an embedder.
    ``_embedding_agent_id`` can still resolve to a different embedding
    model/deployment under an identical restriction shape (an agent-pool
    change, or measured-member reordering inside one eligible group), and the
    two evidence caches persist across that. A hit then returned a vector from
    a different embedding space, and a cosine between two embedding spaces is
    meaningless -- affinity-based routing was silently corrupted rather than
    degraded.

    This is a refinement of the eligibility partitioning, not a duplicate:
    the restriction shape below is *identical* before and after, which is
    exactly why that partition alone cannot catch it.
    """
    chat, first_embedder, second_embedder = _embedding_space_pool()
    client = _EmbeddingSpaceSpyClient()
    orchestrator = TaskOrchestrator([chat, first_embedder, second_embedder], client=client)

    assert orchestrator._embedding_agent_id() == first_embedder.id
    partition_before = _request_evidence_partition()
    assert orchestrator._embed_cached("routing evidence text") == [1.0, 0.0, 0.0]
    assert orchestrator._descriptor_vector_cached(chat) == [1.0, 0.0, 0.0]

    # An operator re-ranks the pool. Same agents, same endpoint, same ZDR
    # mode, no eligibility scope -- so the restriction shape does not move.
    orchestrator.patch_agent("default", second_embedder.id, {"priority": 100})
    assert orchestrator._embedding_agent_id() == second_embedder.id
    assert _request_evidence_partition() == partition_before

    assert orchestrator._embed_cached("routing evidence text") == [0.0, 1.0, 0.0]
    assert orchestrator._descriptor_vector_cached(chat) == [0.0, 1.0, 0.0]
    assert client.embed_calls == [
        first_embedder.id,
        first_embedder.id,
        second_embedder.id,
        second_embedder.id,
    ]

    # The cache still works: a repeat under the current embedder hits.
    assert orchestrator._embed_cached("routing evidence text") == [0.0, 1.0, 0.0]
    assert client.embed_calls[-1] == second_embedder.id
    assert len(client.embed_calls) == 4


def test_one_cosine_never_mixes_two_embedding_spaces() -> None:
    """Both halves of an affinity come from one embedding member, resolved once.

    The task vector and every descriptor vector in a single
    ``_semantic_affinities`` call are pinned to the member resolved at its
    start, so a pool change landing mid-comparison cannot make one cosine
    span two embedding spaces.
    """
    chat, first_embedder, second_embedder = _embedding_space_pool()
    client = _EmbeddingSpaceSpyClient()
    orchestrator = TaskOrchestrator([chat, first_embedder, second_embedder], client=client)

    affinities = orchestrator._semantic_affinities("classify ten items", [chat])
    assert affinities[chat.id] == pytest.approx(1.0)
    assert set(client.embed_calls) == {first_embedder.id}

    orchestrator.patch_agent("default", second_embedder.id, {"priority": 100})
    client.embed_calls.clear()
    affinities = orchestrator._semantic_affinities("classify ten items", [chat])
    assert affinities[chat.id] == pytest.approx(1.0)
    # Not one leftover call to the old embedder: a mixed pair would have
    # yielded a cosine of 0.0 between two orthogonal spaces.
    assert set(client.embed_calls) == {second_embedder.id}


class _PricedEmbeddingClient:
    """An embedder that reports authoritative ``prompt_tokens`` on every call.

    Unlike ``_EmbeddingSpaceSpyClient``/``_EmbeddingSpyClient`` (which mirror
    the ``mock://`` transport's ``prompt_tokens=None``), this fixture stands
    in for a real, usage-reporting provider -- the case
    ``_meter_embedding_spend`` exists to meter.
    """

    def __init__(self, prompt_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.embed_calls: list[str] = []

    def embed_with_usage(
        self, agent: ModelAgent, texts: list[str]
    ) -> tuple[list[list[float]], int | None]:
        self.embed_calls.append(agent.id)
        return [[0.5, 0.5, 0.5] for _ in texts], self.prompt_tokens

    def embed(self, agent: ModelAgent, texts: list[str]) -> list[list[float]]:
        vectors, _prompt_tokens = self.embed_with_usage(agent, texts)
        return vectors


def _paid_embedder() -> ModelAgent:
    return ModelAgent(
        "paid_embedder",
        "paid-embed-model",
        base_url="https://embed.example/v1",
        tags=("embedding",),
    )


def test_cache_miss_with_paid_embedder_is_metered() -> None:
    """A cache-miss embedding call with authoritative usage reaches the budget meter.

    Before this fix, ``_embed_cached`` called ``client.embed()`` (discarding
    usage) and never touched ``_workflow_runs`` at all: real, incurred
    provider spend on routing-evidence embeddings was completely invisible
    to ``spend_analytics``/``budget_status`` (Devin review on #1032).
    """
    embedder = _paid_embedder()
    client = _PricedEmbeddingClient(prompt_tokens=37)
    orchestrator = TaskOrchestrator([embedder], client=client)

    vector = orchestrator._embed_cached("routing text")

    assert vector == [0.5, 0.5, 0.5]
    analytics = orchestrator.spend_analytics()
    assert analytics["totals"]["prompt_tokens"] == 37
    by_model = {row["model"]: row for row in analytics["by_model"]}
    assert by_model["paid-embed-model"]["output_tokens"] == 0
    assert by_model["paid-embed-model"]["step_count"] == 1


def test_cache_hit_is_never_metered_again() -> None:
    """A cache hit reuses the already-metered vector; it must not meter twice.

    This is the fix's core safety property: metering sits strictly on the
    miss branch, after the ``if cached is not None: return cached``
    short-circuit, so a hit is never reachable from it.
    """
    embedder = _paid_embedder()
    client = _PricedEmbeddingClient(prompt_tokens=37)
    orchestrator = TaskOrchestrator([embedder], client=client)

    assert orchestrator._embed_cached("routing text") == [0.5, 0.5, 0.5]
    assert orchestrator._embed_cached("routing text") == [0.5, 0.5, 0.5]

    assert client.embed_calls == [embedder.id]
    assert orchestrator.spend_analytics()["totals"]["prompt_tokens"] == 37

    assert orchestrator._descriptor_vector_cached(embedder) == [0.5, 0.5, 0.5]
    assert orchestrator._descriptor_vector_cached(embedder) == [0.5, 0.5, 0.5]

    assert client.embed_calls == [embedder.id, embedder.id]
    assert orchestrator.spend_analytics()["totals"]["prompt_tokens"] == 74


def test_select_model_group_members_meters_embedding_with_no_live_request() -> None:
    """A request-independent caller still gets its embedding spend metered.

    ``select_model_group_members`` is the confirmed real call site that
    reaches ``_embed_cached``/``_descriptor_vector_cached`` with no
    enclosing task, workflow record, or request-eligibility context at all
    (no ``_request_eligibility_scope`` is entered anywhere in this test) --
    ``_meter_embedding_spend`` must not assume any of those exist.
    """
    chat = ModelAgent(
        "chat_agent", "chat-model", base_url="mock://pool", tags=("reasoning",)
    )
    embedder = _paid_embedder()
    client = _PricedEmbeddingClient(prompt_tokens=11)
    orchestrator = TaskOrchestrator([chat, embedder], client=client)

    selected = orchestrator.select_model_group_members(
        [chat], text="classify ten items"
    )

    assert [agent.id for agent in selected] == [chat.id]
    assert client.embed_calls  # the task text and/or a descriptor were embedded
    expected_prompt_tokens = len(client.embed_calls) * 11
    assert (
        orchestrator.spend_analytics()["totals"]["prompt_tokens"]
        == expected_prompt_tokens
    )


def test_unpriced_embedder_under_cost_budget_does_not_blind_meter() -> None:
    """An unpriced embedder must never flip the whole meter to blocked_unavailable.

    Isolates the exact gap: every *general-chat* model is priced (so
    ``budget_status()``'s own ``candidate_prices_available`` check, which
    only looks at ``_is_general_chat_agent`` models, already passes) but the
    embedder -- structurally unable to need a price before this fix, since
    embedding calls never produced a workflow run at all -- is not.
    ``completion_tokens`` is always ``0`` for an embedding step, which
    satisfies ``_replace_workflow_run``'s *per-step* availability check --
    but its second, independent gate (every model appearing in the run must
    be priced whenever ``budget_max_cost_usd`` is set) still fails on the
    unpriced embedder. Before this guard, that added the synthetic run's id
    to ``_budget_unavailable_run_ids`` and flipped
    ``budget_status()["enforcement_status"]`` to ``"blocked_unavailable"``
    for every request org-wide, even though this run's real contribution to
    spend is mathematically $0 (an embedding call has no completion
    tokens). The guard skips metering in that one case -- true zero-cost
    either way -- instead of writing a row that blinds unrelated requests'
    enforcement.
    """
    chat = ModelAgent(
        "chat_agent", "chat-model", base_url="mock://pool", tags=("reasoning",)
    )
    embedder = _paid_embedder()

    unpriced_client = _PricedEmbeddingClient(prompt_tokens=37)
    unpriced = TaskOrchestrator(
        [chat, embedder],
        client=unpriced_client,
        budget_max_cost_usd=1.0,
        price_per_million={"chat-model": 1.0},
    )
    unpriced._embed_cached("routing text")
    assert unpriced.budget_status()["enforcement_status"] == "within_budget"
    assert unpriced.spend_analytics()["totals"]["prompt_tokens"] == 0

    # Scoped to the unpriced case only: once the embedder is priced too
    # (even at $0), metering proceeds normally and the meter still reads
    # within_budget -- this is not a blanket "budget enabled => never meter".
    priced_client = _PricedEmbeddingClient(prompt_tokens=37)
    priced = TaskOrchestrator(
        [chat, embedder],
        client=priced_client,
        budget_max_cost_usd=1.0,
        price_per_million={"chat-model": 1.0, "paid-embed-model": 0.0},
    )
    priced._embed_cached("routing text")
    assert priced.spend_analytics()["totals"]["prompt_tokens"] == 37
    assert priced.budget_status()["enforcement_status"] == "within_budget"


def test_embedding_spend_persistence_failure_never_aborts_model_selection(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A durable-write failure behind an embedding spend never propagates.

    Devin review (PR #1032, comment 3921362518): ``_meter_embedding_spend``
    ends with an unguarded ``self._store.save("workflow_run", ...)`` -- a
    real sqlite3 write. Any failure there (a state-store outage) propagated
    straight through ``_embed_cached``/``_descriptor_vector_cached``,
    through ``_semantic_affinities``, through every one of
    ``_ranked_agents``'s call sites, and into model selection: a disk
    hiccup on a best-effort routing-evidence row could abort real request
    handling.
    """
    embedder = _paid_embedder()
    client = _PricedEmbeddingClient(prompt_tokens=37)
    orchestrator = TaskOrchestrator(
        [embedder], client=client, state_db=str(tmp_path / "state.db")
    )
    assert orchestrator._store is not None
    healthy_save = orchestrator._store.save

    def _failing_save(
        kind: str, key: str | None, payload: dict[str, Any], **options: Any
    ) -> None:
        """Fail exactly the workflow_run write; leave everything else working."""
        if kind == "workflow_run":
            raise sqlite3.OperationalError("disk I/O error")
        healthy_save(kind, key, payload, **options)

    orchestrator._store.save = _failing_save  # type: ignore[method-assign]

    with caplog.at_level(logging.WARNING):
        vector = orchestrator._embed_cached("routing text")

    # (a) the caller never sees the exception -- it gets its vector back.
    assert vector == [0.5, 0.5, 0.5]

    # (b) the failure doesn't poison the cache: a second call is a cache
    # hit, not a second provider call.
    vector_again = orchestrator._embed_cached("routing text")
    assert vector_again == [0.5, 0.5, 0.5]
    assert client.embed_calls == [embedder.id]

    # (c) the failure isn't silently discarded -- it's logged.
    assert any(
        record.levelno == logging.WARNING and "embedding spend" in record.getMessage()
        for record in caplog.records
    )

    # Caveat 3: the durability failure never blinds the in-memory meter --
    # _replace_workflow_run already ran before the guarded write, so the
    # spend is real and enforcement stays exact, not "unavailable".
    assert orchestrator.spend_analytics()["totals"]["prompt_tokens"] == 37
    status = orchestrator.budget_status()
    assert status["enforcement_status"] == "within_budget"
    assert status["measurement_status"] == "measured"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__]))
