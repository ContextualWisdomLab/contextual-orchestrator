"""Cross-provider failover contracts for raw OpenAI passthrough requests."""

from __future__ import annotations

import socket
import urllib.error
from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest

from contextual_orchestrator import (
    ModelAgent,
    ReasoningEffortProfile,
    TaskOrchestrator,
)
from contextual_orchestrator.orchestrator import ModelClient
from contextual_orchestrator.provider_errors import ProviderUpstreamError


class SequencedProxyClient:
    """Return one configured outcome per provider while recording attempts."""

    def __init__(self, outcomes: dict[str, dict[str, Any] | BaseException]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def proxy_send_once(
        self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Perform one deterministic passthrough attempt."""
        del endpoint
        self.calls.append((agent.id, deepcopy(payload)))
        outcome = self.outcomes[agent.id]
        if isinstance(outcome, BaseException):
            raise outcome
        return deepcopy(outcome)

    proxy_send = proxy_send_once

    def apply_effort_profile(
        self,
        agent: ModelAgent,
        payload: dict[str, Any],
        profile: ReasoningEffortProfile,
    ) -> dict[str, Any]:
        """Reuse the production profile contract for mixed-provider coverage."""
        return ModelClient().apply_effort_profile(agent, payload, profile)


def _http_error(status: int) -> urllib.error.HTTPError:
    """Build a provider-shaped HTTP failure."""
    return urllib.error.HTTPError("https://provider.example/v1", status, "failed", None, None)


def _build(client: SequencedProxyClient) -> TaskOrchestrator:
    """Build a two-provider pool with deterministic priority."""
    return TaskOrchestrator(
        [
            ModelAgent(
                "primary_agent", "primary-model", priority=10, provider_name="primary"
            ),
            ModelAgent(
                "fallback_agent", "fallback-model", priority=1, provider_name="fallback"
            ),
        ],
        client=client,
    )


@pytest.mark.parametrize("status", [404, 410, 429, 503])
def test_virtual_passthrough_advances_once_and_preserves_request(status: int) -> None:
    """Adaptive requests advance once on transient or stale-model failures."""
    client = SequencedProxyClient(
        {
            "primary_agent": _http_error(status),
            "fallback_agent": {"model": "fallback-model", "choices": []},
        }
    )
    body = {
        "model": "contextual-orchestrator",
        "messages": [{"role": "user", "content": "review code"}],
        "tools": [{"type": "function", "function": {"name": "inspect"}}],
        "response_format": {"type": "json_object"},
        "stream": True,
    }

    result = _build(client).proxy_completion(body)

    assert result["model"] == "fallback-model"
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent", "fallback_agent"]
    assert client.calls[1][1]["tools"] == body["tools"]
    assert client.calls[1][1]["response_format"] == body["response_format"]
    assert client.calls[1][1]["stream"] is False


@pytest.mark.parametrize("status", [404, 429])
def test_explicit_model_never_fails_over(status: int) -> None:
    """A concrete model selection remains sticky even when its provider fails."""
    failure = _http_error(status)
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": {"model": "fallback-model"},
        }
    )

    with pytest.raises(urllib.error.HTTPError) as caught:
        _build(client).proxy_completion(
            {"model": "primary-model", "messages": [{"role": "user", "content": "x"}]}
        )

    assert caught.value is failure
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]


@pytest.mark.parametrize("model", [TaskOrchestrator.AUTO_MODEL, TaskOrchestrator.FREE_MODEL])
def test_virtual_model_names_use_provider_failover(model: str) -> None:
    """Virtual selectors retain cross-provider failover instead of becoming sticky."""
    client = SequencedProxyClient(
        {
            "primary_agent": _http_error(429),
            "fallback_agent": {"model": "fallback-model"},
        }
    )
    orchestrator = _build(client)
    if model == TaskOrchestrator.FREE_MODEL:
        orchestrator.agents = [
            replace(agent, tags=(*agent.tags, "cost:free"))
            for agent in orchestrator.agents
        ]

    result = orchestrator.proxy_completion(
        {"model": model, "messages": [{"role": "user", "content": "x"}]}
    )

    assert result["model"] == "fallback-model"
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent", "fallback_agent"]


def test_auto_virtual_model_fails_over_across_model_groups() -> None:
    """Global AUTO may cross logical-model groups to reach another provider."""
    client = SequencedProxyClient(
        {
            "primary_agent": _http_error(429),
            "fallback_agent": {"model": "fallback-model"},
        }
    )
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "primary_agent",
                "primary-model",
                priority=10,
                provider_name="primary",
                group_name="primary_group",
            ),
            ModelAgent(
                "fallback_agent",
                "fallback-model",
                priority=1,
                provider_name="fallback",
                group_name="fallback_group",
            ),
        ],
        client=client,
    )

    result = orchestrator.proxy_completion(
        {
            "model": TaskOrchestrator.AUTO_MODEL,
            "messages": [{"role": "user", "content": "x"}],
        }
    )

    assert result["model"] == "fallback-model"
    assert [agent_id for agent_id, _ in client.calls] == [
        "primary_agent",
        "fallback_agent",
    ]


def test_free_virtual_model_never_fails_over_to_a_paid_agent() -> None:
    """The free selector exhausts only explicitly zero-cost providers."""
    client = SequencedProxyClient(
        {
            "free_agent": _http_error(429),
            "paid_agent": {"model": "paid-model"},
        }
    )
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "free_agent", "free-model", tags=("cost:free",), provider_name="free"
            ),
            ModelAgent("paid_agent", "paid-model", provider_name="paid"),
        ],
        client=client,
    )

    with pytest.raises(ProviderUpstreamError) as caught:
        orchestrator.proxy_completion(
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "x"}],
            }
        )

    assert caught.value.agent_id == "free_agent"

    assert [agent_id for agent_id, _ in client.calls] == ["free_agent"]


def test_non_transient_error_is_not_replayed() -> None:
    """Caller errors fail closed instead of duplicating a request across providers."""
    failure = _http_error(400)
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": {"model": "fallback-model"},
        }
    )

    with pytest.raises(ProviderUpstreamError) as caught:
        _build(client).proxy_completion({"messages": [{"role": "user", "content": "x"}]})

    assert caught.value.provider_status == 400
    assert caught.value.__cause__ is None
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]


def test_wrapped_transient_error_can_fail_over() -> None:
    """Provider SDK wrappers retain their causal failover signal."""
    try:
        raise RuntimeError("provider wrapper") from _http_error(429)
    except RuntimeError as wrapped:
        failure = wrapped
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": {"model": "fallback-model"},
        }
    )

    assert _build(client).proxy_completion(
        {"messages": [{"role": "user", "content": "x"}]}
    )["model"] == "fallback-model"


def test_suppressed_transient_context_does_not_authorize_failover() -> None:
    """A deliberately hidden exception context cannot become a routing signal."""
    try:
        raise _http_error(429)
    except urllib.error.HTTPError:
        try:
            raise RuntimeError("terminal wrapper") from None
        except RuntimeError as wrapped:
            failure = wrapped
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": {"model": "fallback-model"},
        }
    )

    with pytest.raises(RuntimeError, match="terminal wrapper") as caught:
        _build(client).proxy_completion({"messages": [{"role": "user", "content": "x"}]})

    assert caught.value is failure
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]


def test_all_candidates_chain_the_last_failure() -> None:
    """Exhaustion reports one stable gateway error with the final provider cause."""
    final = _http_error(503)
    orchestrator = _build(
        SequencedProxyClient({"primary_agent": _http_error(429), "fallback_agent": final})
    )

    with pytest.raises(ProviderUpstreamError) as caught:
        orchestrator.proxy_completion({"messages": [{"role": "user", "content": "x"}]})

    assert caught.value.agent_id == "fallback_agent"
    assert caught.value.provider_status == 503
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    "control",
    [
        {"response_format": {}},
        {"tools": []},
        {"tool_choice": "auto"},
    ],
    ids=["response_format_empty_object", "tools_empty_array", "tool_choice_auto"],
)
def test_omit_equivalent_controls_take_plain_passthrough(control: dict[str, Any]) -> None:
    """Empty SDK-default controls select plain passthrough, not conducted synthesis."""
    client = SequencedProxyClient(
        {"primary_agent": {"model": "primary-model", "choices": []}}
    )
    orchestrator = _build(client)

    def _forbidden_conduct(*args: object, **kwargs: object) -> dict[str, Any]:
        raise AssertionError(
            "conducted-evidence+synthesis must not run for omit-equivalent controls"
        )

    orchestrator.conduct = _forbidden_conduct  # type: ignore[method-assign]
    body = {
        "model": TaskOrchestrator.AUTO_MODEL,
        "messages": [{"role": "user", "content": "x"}],
        **control,
    }

    result = orchestrator.proxy_completion(body, single_agent=False)

    assert result["model"] == "primary-model"
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]
    assert "orchestration" not in result


def test_same_provider_is_attempted_only_once() -> None:
    """Two aliases for one upstream cannot replay a non-idempotent request."""
    client = SequencedProxyClient(
        {
            "primary_agent": _http_error(429),
            "same_provider_agent": {"model": "same-provider-model"},
            "fallback_agent": {"model": "fallback-model"},
        }
    )
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "primary_agent", "primary-model", priority=10, provider_name="shared"
            ),
            ModelAgent(
                "same_provider_agent",
                "same-provider-model",
                priority=5,
                provider_name="shared",
            ),
            ModelAgent(
                "fallback_agent", "fallback-model", priority=1, provider_name="fallback"
            ),
        ],
        client=client,
    )

    assert orchestrator.proxy_completion(
        {"messages": [{"role": "user", "content": "x"}], "tools": []}
    )["model"] == "fallback-model"
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent", "fallback_agent"]


@pytest.mark.parametrize(
    ("dns_errno", "should_fail_over"),
    [(socket.EAI_AGAIN, True), (socket.EAI_NONAME, False)],
)
def test_only_temporary_dns_failures_advance(
    dns_errno: int, should_fail_over: bool
) -> None:
    """Temporary DNS resolution can recover elsewhere; permanent DNS errors cannot."""
    try:
        raise RuntimeError("provider resolution failed") from socket.gaierror(
            dns_errno, "dns failure"
        )
    except RuntimeError as wrapped:
        failure = wrapped
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": {"model": "fallback-model"},
        }
    )

    if should_fail_over:
        assert _build(client).proxy_completion(
            {"messages": [{"role": "user", "content": "x"}]}
        )["model"] == "fallback-model"
    else:
        with pytest.raises(RuntimeError, match="provider resolution failed"):
            _build(client).proxy_completion(
                {"messages": [{"role": "user", "content": "x"}]}
            )


def test_ambiguous_timeout_is_not_replayed() -> None:
    """A timeout may follow provider acceptance, so passthrough fails closed."""
    failure = TimeoutError("provider outcome unknown")
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": {"model": "fallback-model"},
        }
    )

    with pytest.raises(TimeoutError, match="outcome unknown"):
        _build(client).proxy_completion({"messages": [{"role": "user", "content": "x"}]})

    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]


def test_virtual_effort_profile_selects_a_supported_provider() -> None:
    """Mixed pools skip unsupported candidates instead of aborting valid routing."""
    client = SequencedProxyClient(
        {
            "unsupported_agent": {"model": "unsupported-model"},
            "supported_agent": {"model": "supported-model"},
        }
    )
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "unsupported_agent",
                "unsupported-model",
                base_url="https://unsupported.example/v1",
                priority=10,
                provider_name="unsupported",
                reasoning_effort_supported=False,
            ),
            ModelAgent(
                "supported_agent",
                "supported-model",
                base_url="https://supported.example/v1",
                priority=1,
                provider_name="supported",
                reasoning_effort_supported=True,
            ),
        ],
        client=client,
    )
    profile = ReasoningEffortProfile(
        reasoning_effort="medium",
        unsupported_provider_fallback="error",
    )

    result = orchestrator.proxy_completion(
        {"messages": [{"role": "user", "content": "x"}]}, effort_profile=profile
    )

    assert result["model"] == "supported-model"
    assert [agent_id for agent_id, _ in client.calls] == ["supported_agent"]


def test_passthrough_with_no_ranked_provider_fails_cleanly(monkeypatch) -> None:
    """An empty filtered pool reports unavailability instead of reading stale state."""
    client = SequencedProxyClient({"primary_agent": {"model": "primary-model"}})
    orchestrator = _build(client)
    monkeypatch.setattr(orchestrator, "_failover_candidates", lambda *args, **kwargs: [])

    with pytest.raises(RuntimeError, match="no eligible provider candidate"):
        orchestrator.proxy_completion({"messages": [{"role": "user", "content": "x"}]})

    assert client.calls == []


def test_effort_support_filter_precedes_same_provider_deduplication() -> None:
    """A lower-ranked supported alias remains eligible for its provider."""
    client = SequencedProxyClient(
        {"supported_alias": {"model": "supported-model"}}
    )
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "unsupported_alias",
                "unsupported-model",
                priority=10,
                provider_name="shared",
                reasoning_effort_supported=False,
            ),
            ModelAgent(
                "supported_alias",
                "supported-model",
                priority=1,
                provider_name="shared",
                reasoning_effort_supported=True,
            ),
        ],
        client=client,
    )

    result = orchestrator.proxy_completion(
        {"messages": [{"role": "user", "content": "x"}]},
        effort_profile=ReasoningEffortProfile(
            reasoning_effort="medium",
            unsupported_provider_fallback="error",
        ),
    )

    assert result["model"] == "supported-model"
    assert [agent_id for agent_id, _ in client.calls] == ["supported_alias"]


def test_default_mock_endpoint_represents_one_fixture_provider() -> None:
    """Default mock agents deduplicate as aliases of one local fixture provider."""
    client = SequencedProxyClient(
        {
            "first_mock": _http_error(503),
            "second_mock": {"model": "second-model"},
        }
    )
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("first_mock", "first-model", priority=10),
            ModelAgent("second_mock", "second-model", priority=1),
        ],
        client=client,
    )

    with pytest.raises(ProviderUpstreamError) as caught:
        orchestrator.proxy_completion(
            {"model": orchestrator.AUTO_MODEL, "messages": [{"role": "user", "content": "x"}]}
        )

    assert caught.value.agent_id == "first_mock"
    assert [agent_id for agent_id, _ in client.calls] == ["first_mock"]
