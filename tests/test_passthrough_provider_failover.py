"""Cross-provider failover contracts for raw OpenAI passthrough requests."""

from __future__ import annotations

import io
import json
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
from contextual_orchestrator.orchestrator import (
    ModelClient,
    ProviderRequestTooLargeError,
)


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


def _tool_description_too_long_error() -> urllib.error.HTTPError:
    """Build the provider's bounded tool-description rejection."""
    return urllib.error.HTTPError(
        "https://provider.example/v1",
        400,
        "invalid tools",
        None,
        io.BytesIO(
            json.dumps(
                {
                    "error": {
                        "code": "invalid_tools",
                        "message": (
                            "each tool.function.description must be at most "
                            "1024 characters"
                        ),
                    }
                }
            ).encode()
        ),
    )


def _invalid_tools_error() -> urllib.error.HTTPError:
    """Build a non-size tool validation failure that must remain sticky."""
    return urllib.error.HTTPError(
        "https://provider.example/v1",
        400,
        "invalid tools",
        None,
        io.BytesIO(
            json.dumps(
                {
                    "error": {
                        "code": "invalid_tools",
                        "message": "tool.function.parameters must be an object",
                    }
                }
            ).encode()
        ),
    )


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


@pytest.mark.parametrize("status", [404, 410, 413, 429, 503])
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


def test_virtual_passthrough_advances_on_oversized_tool_description() -> None:
    """A provider-specific tool length cap is eligible for cross-provider failover."""
    client = SequencedProxyClient(
        {
            "primary_agent": _tool_description_too_long_error(),
            "fallback_agent": {"model": "fallback-model", "choices": []},
        }
    )

    orchestrator = _build(client)
    orchestrator.agents = [
        replace(agent, group_name="provider-group") for agent in orchestrator.agents
    ]
    result = orchestrator.proxy_completion(
        {
            "model": TaskOrchestrator.AUTO_MODEL,
            "messages": [{"role": "user", "content": "review code"}],
            "tools": [{"type": "function", "function": {"name": "inspect"}}],
        }
    )

    assert result["model"] == "fallback-model"
    assert [agent_id for agent_id, _ in client.calls] == [
        "primary_agent",
        "fallback_agent",
    ]
    assert "primary_agent" not in orchestrator._circuit
    assert orchestrator._group_router.member_observation_count("primary_agent") == 0


def test_virtual_passthrough_keeps_non_size_tool_errors_sticky() -> None:
    """A generic provider invalid_tools response must not hide a bad request."""
    failure = _invalid_tools_error()
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": {"model": "fallback-model", "choices": []},
        }
    )

    with pytest.raises(urllib.error.HTTPError) as caught:
        _build(client).proxy_completion(
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "messages": [{"role": "user", "content": "review code"}],
                "tools": [{"type": "function", "function": {"name": "inspect"}}],
            }
        )

    assert caught.value is failure
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]


@pytest.mark.parametrize("status", [404, 413, 429])
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


def test_explicit_grouped_model_413_does_not_degrade_provider_health() -> None:
    """Request-size rejection is not provider stability evidence."""
    client = SequencedProxyClient({"primary_agent": _http_error(413)})
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "primary_agent",
                "primary-model",
                provider_name="primary",
                group_name="primary-group",
            )
        ],
        client=client,
    )

    with pytest.raises(urllib.error.HTTPError) as caught:
        orchestrator.proxy_completion(
            {"model": "primary-model", "messages": [{"role": "user", "content": "x"}]}
        )

    assert caught.value.code == 413
    report = orchestrator._group_router.member_report("primary_agent")
    assert report["failure_count"] == 0


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


@pytest.mark.parametrize("model", [TaskOrchestrator.AUTO_MODEL, TaskOrchestrator.FREE_MODEL])
def test_orchestrated_structured_synthesis_advances_on_413(model: str) -> None:
    """Conducted synthesis retains AUTO/FREE eligibility when a provider rejects size."""
    client = SequencedProxyClient(
        {
            "primary_agent": _http_error(413),
            "fallback_agent": {
                "model": "fallback-model",
                "choices": [{"message": {"content": "{}"}}],
            },
        }
    )
    free_tag = ("cost:free",) if model == TaskOrchestrator.FREE_MODEL else ()
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "primary_agent",
                "primary-model",
                priority=10,
                provider_name="primary",
                tags=("response_format", *free_tag),
            ),
            ModelAgent(
                "fallback_agent",
                "fallback-model",
                priority=1,
                provider_name="fallback",
                tags=("response_format", *free_tag),
            ),
        ],
        client=client,
    )
    orchestrator.conduct = lambda *args, **kwargs: {  # type: ignore[method-assign]
        "mode": "conduct",
        "answer": "evidence",
        "trace": [
            {
                "id": 0,
                "role": "worker",
                "agent_id": "primary_agent",
                "subtask": "Evidence",
                "access": [],
                "output": "evidence",
            }
        ],
        "verification": {"accepted": True, "reason": "test", "verifier_output": ""},
    }

    result = orchestrator.proxy_completion(
        {
            "model": model,
            "messages": [{"role": "user", "content": "large structured request"}],
            "response_format": {"type": "json_object"},
        },
        single_agent=False,
    )

    assert result["model"] == "fallback-model"
    assert [agent_id for agent_id, _ in client.calls] == [
        "primary_agent",
        "fallback_agent",
    ]


def test_structured_synthesis_records_non_413_failure_on_actual_provider() -> None:
    """A post-413 provider error must trip the provider that actually failed."""
    client = SequencedProxyClient(
        {
            "primary_agent": _http_error(413),
            "fallback_agent": RuntimeError("fallback unavailable"),
        }
    )
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "primary_agent",
                "primary-model",
                priority=10,
                provider_name="primary",
                tags=("response_format",),
            ),
            ModelAgent(
                "fallback_agent",
                "fallback-model",
                priority=1,
                provider_name="fallback",
                tags=("response_format",),
            ),
        ],
        client=client,
    )
    orchestrator.conduct = lambda *args, **kwargs: {  # type: ignore[method-assign]
        "mode": "conduct",
        "answer": "evidence",
        "trace": [
            {
                "id": 0,
                "role": "worker",
                "agent_id": "primary_agent",
                "subtask": "Evidence",
                "access": [],
                "output": "evidence",
            }
        ],
        "verification": {"accepted": True, "reason": "test", "verifier_output": ""},
    }

    with pytest.raises(RuntimeError, match="fallback unavailable"):
        orchestrator.proxy_completion(
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "messages": [{"role": "user", "content": "large structured request"}],
                "response_format": {"type": "json_object"},
            },
            single_agent=False,
        )

    assert orchestrator._circuit["fallback_agent"]["failures"] == 1.0
    assert "primary_agent" not in orchestrator._circuit


def test_structured_repair_reuses_provider_that_accepted_request() -> None:
    """Repair must not retry a provider that already rejected the request size."""
    class RepairClient(SequencedProxyClient):
        def proxy_send_once(
            self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]
        ) -> dict[str, Any]:
            del endpoint
            self.calls.append((agent.id, deepcopy(payload)))
            if agent.id == "primary_agent":
                raise _http_error(413)
            content = "not json" if len(self.calls) == 2 else "{}"
            return {
                "model": agent.model,
                "choices": [{"message": {"content": content}}],
            }

        proxy_send = proxy_send_once

    client = RepairClient({})
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "primary_agent",
                "primary-model",
                priority=10,
                provider_name="primary",
                tags=("response_format",),
            ),
            ModelAgent(
                "fallback_agent",
                "fallback-model",
                priority=1,
                provider_name="fallback",
                tags=("response_format",),
            ),
        ],
        client=client,
    )
    orchestrator.conduct = lambda *args, **kwargs: {  # type: ignore[method-assign]
        "mode": "conduct",
        "answer": "evidence",
        "trace": [],
        "verification": {"accepted": True, "reason": "test", "verifier_output": ""},
    }

    result = orchestrator.proxy_completion(
        {
            "model": TaskOrchestrator.AUTO_MODEL,
            "messages": [{"role": "user", "content": "large structured request"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"schema": {"type": "object"}},
            },
        },
        single_agent=False,
    )

    assert result["model"] == "fallback-model"
    assert [agent_id for agent_id, _ in client.calls] == [
        "primary_agent",
        "fallback_agent",
        "fallback_agent",
    ]


def test_all_virtual_candidates_rejecting_size_preserves_request_too_large() -> None:
    """Exhausted 413 routing remains a client-visible size error, not HTTP 500."""
    client = SequencedProxyClient(
        {
            "primary_agent": _http_error(413),
            "fallback_agent": _http_error(413),
        }
    )

    with pytest.raises(ProviderRequestTooLargeError, match="every eligible provider"):
        _build(client).proxy_completion(
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "messages": [{"role": "user", "content": "large request"}],
            }
        )


def test_all_oversized_tool_rejections_preserve_request_too_large() -> None:
    """Raw provider-specific size errors retain the all-candidates signal."""
    client = SequencedProxyClient(
        {
            "primary_agent": _tool_description_too_long_error(),
            "fallback_agent": _tool_description_too_long_error(),
        }
    )

    with pytest.raises(ProviderRequestTooLargeError, match="every eligible provider"):
        _build(client).proxy_completion(
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "messages": [{"role": "user", "content": "large tools"}],
            }
        )


def test_mixed_failures_are_not_misreported_as_all_candidates_too_large() -> None:
    """A final 413 cannot erase an earlier provider outage from exhaustion evidence."""
    client = SequencedProxyClient(
        {
            "primary_agent": _http_error(503),
            "fallback_agent": _http_error(413),
        }
    )

    with pytest.raises(RuntimeError, match="all 2 candidate agents failed"):
        _build(client).proxy_completion(
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "messages": [{"role": "user", "content": "large request"}],
            }
        )


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

    with pytest.raises(RuntimeError, match="all 1 candidate agents failed"):
        orchestrator.proxy_completion(
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "x"}],
            }
        )

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

    with pytest.raises(urllib.error.HTTPError) as caught:
        _build(client).proxy_completion({"messages": [{"role": "user", "content": "x"}]})

    assert caught.value is failure
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

    with pytest.raises(RuntimeError, match="all 2 candidate agents failed") as caught:
        orchestrator.proxy_completion({"messages": [{"role": "user", "content": "x"}]})

    assert caught.value.__cause__ is final


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

    with pytest.raises(RuntimeError, match="all 1 candidate agents failed"):
        orchestrator.proxy_completion(
            {"model": orchestrator.AUTO_MODEL, "messages": [{"role": "user", "content": "x"}]}
        )

    assert [agent_id for agent_id, _ in client.calls] == ["first_mock"]
