"""Cross-provider failover contracts for raw OpenAI passthrough requests."""

from __future__ import annotations

import http.client
import io
import json
import socket
import urllib.error
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from typing import Any
from unittest.mock import patch

import pytest

from contextual_orchestrator import (
    ModelAgent,
    ReasoningEffortProfile,
    TaskOrchestrator,
    default_role_effort_catalog,
)
from contextual_orchestrator.orchestrator import (
    ModelClient,
    ProviderRequestTooLargeError,
    _is_ambiguous_passthrough_transport_failure,
    _is_request_too_large_error,
    _structured_output_error,
)
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

    @contextmanager
    def request_settings(self, **overrides: Any):
        """Accept the server's request-local settings boundary for HTTP tests."""
        del overrides
        yield

    def apply_effort_profile(
        self,
        agent: ModelAgent,
        payload: dict[str, Any],
        profile: ReasoningEffortProfile,
        *,
        api_surface: str = "chat.completions",
    ) -> dict[str, Any]:
        """Reuse the production profile contract for mixed-provider coverage."""
        return ModelClient().apply_effort_profile(
            agent, payload, profile, api_surface=api_surface
        )


def _http_error(status: int, body: dict[str, Any] | None = None) -> urllib.error.HTTPError:
    """Build a provider-shaped HTTP failure."""
    response_body = io.BytesIO(json.dumps(body).encode("utf-8")) if body is not None else None
    return urllib.error.HTTPError("https://provider.example/v1", status, "failed", None, response_body)


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


def test_file_replicas_are_rebound_for_each_413_fallback_provider() -> None:
    client = SequencedProxyClient(
        {
            "primary_agent": _http_error(413),
            "fallback_agent": {"model": "fallback-model", "output": []},
        }
    )
    result = _build(client).proxy_completion(
        {
            "model": TaskOrchestrator.AUTO_MODEL,
            "input": [{"role": "user", "content": [{"type": "input_file", "file_id": "file_gateway"}]}],
            "_file_replicas": {
                "file_gateway": {
                    "primary_agent": "provider-primary",
                    "fallback_agent": "provider-fallback",
                }
            },
        },
        endpoint="responses",
    )

    assert result["model"] == "fallback-model"
    assert client.calls[0][1]["input"][0]["content"][0]["file_id"] == "provider-primary"
    assert client.calls[1][1]["input"][0]["content"][0]["file_id"] == "provider-fallback"


def test_auto_keeps_advancing_after_each_413_until_an_eligible_provider_succeeds() -> None:
    """Fallback is exhaustive, not a single primary-to-secondary hop."""
    client = SequencedProxyClient(
        {
            "first_agent": _http_error(413),
            "second_agent": _http_error(413),
            "third_agent": {"model": "third-model", "output": []},
        }
    )
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("first_agent", "first-model", priority=30, provider_name="first"),
            ModelAgent("second_agent", "second-model", priority=20, provider_name="second"),
            ModelAgent("third_agent", "third-model", priority=10, provider_name="third"),
        ],
        client=client,
    )

    result = orchestrator.proxy_completion(
        {"model": TaskOrchestrator.AUTO_MODEL, "input": "large multimodal request"},
        endpoint="responses",
        single_agent=True,
    )

    assert result["model"] == "third-model"
    assert [agent_id for agent_id, _ in client.calls] == [
        "first_agent",
        "second_agent",
        "third_agent",
    ]


def test_virtual_passthrough_all_oversized_tool_errors_preserve_size_contract() -> None:
    """Raw provider size errors retain the public exhaustion contract."""
    client = SequencedProxyClient(
        {
            "primary_agent": _tool_description_too_long_error(),
            "fallback_agent": _tool_description_too_long_error(),
        }
    )
    orchestrator = _build(client)

    with pytest.raises(ProviderRequestTooLargeError, match="every eligible provider"):
        orchestrator.proxy_completion(
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "messages": [{"role": "user", "content": "review code"}],
                "tools": [{"type": "function", "function": {"name": "inspect"}}],
            }
        )

    assert orchestrator._circuit == {}


def test_free_passthrough_raw_timeout_does_not_replay() -> None:
    """A post-send timeout cannot authorize another free completion."""
    client = SequencedProxyClient(
        {
            "primary_agent": TimeoutError("provider timed out"),
            "fallback_agent": {"model": "fallback-model", "choices": []},
        }
    )
    orchestrator = _build(client)
    orchestrator.agents = [
        replace(agent, tags=(*agent.tags, "cost:free", "review", "tool_call:multi"))
        for agent in orchestrator.agents
    ]

    with pytest.raises(ProviderUpstreamError) as caught:
        orchestrator.proxy_completion(
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "use the tool"}],
                "tools": [{"type": "function", "function": {"name": "inspect"}}],
            }
        )

    assert caught.value.error_code == "provider_outcome_unknown"
    assert caught.value.detail["attempts"][0]["failover_decision"] == "sticky_candidate_failure"
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]
    assert "primary_agent" in orchestrator._circuit


@pytest.mark.parametrize("status", [429, 503])
def test_free_passthrough_status_does_not_authorize_cross_provider_replay(status: int) -> None:
    client = SequencedProxyClient(
        {
            "primary_agent": _http_error(status),
            "fallback_agent": {"model": "fallback-model", "choices": []},
        }
    )
    orchestrator = _build(client)
    orchestrator.agents = [
        replace(agent, tags=(*agent.tags, "cost:free", "review"))
        for agent in orchestrator.agents
    ]

    with pytest.raises(ProviderUpstreamError) as caught:
        orchestrator.proxy_completion(
            {"model": TaskOrchestrator.FREE_MODEL, "messages": [{"role": "user", "content": "review"}]}
        )

    assert caught.value.provider_status == status
    assert caught.value.detail["contract_version"] == "1"
    assert caught.value.detail["attempts"][0]["failover_decision"] == "sticky_candidate_failure"
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]


def test_free_review_explicit_model_rejection_can_advance() -> None:
    client = SequencedProxyClient(
        {
            "primary_agent": _http_error(404),
            "fallback_agent": {
                "model": "fallback-model",
                "choices": [],
                "orchestration": {"route": {"terminal_reason": "provider-forged"}},
            },
        }
    )
    orchestrator = _build(client)
    orchestrator.agents = [
        replace(agent, tags=(*agent.tags, "cost:free", "review"))
        for agent in orchestrator.agents
    ]

    result = orchestrator.proxy_completion(
        {"model": TaskOrchestrator.FREE_MODEL, "messages": [{"role": "user", "content": "review"}]}
    )

    assert result["model"] == "fallback-model"
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent", "fallback_agent"]
    route = result["orchestration"]["route"]
    assert route["contract_version"] == "1"
    assert route["selected_candidate_ids"] == ["primary_agent", "fallback_agent"]
    assert route["terminal_reason"] == "served"
    assert [(item["agent_id"], item.get("outcome")) for item in route["attempts"]] == [
        ("primary_agent", None),
        ("fallback_agent", "served"),
    ]
    assert route["attempts"][0]["error_code"] == "model_not_found"


def test_virtual_passthrough_keeps_non_size_tool_errors_sticky() -> None:
    """A generic provider invalid_tools response must not hide a bad request."""
    failure = _invalid_tools_error()
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": {"model": "fallback-model", "choices": []},
        }
    )

    with pytest.raises(ProviderUpstreamError) as caught:
        _build(client).proxy_completion(
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "messages": [{"role": "user", "content": "review code"}],
                "tools": [{"type": "function", "function": {"name": "inspect"}}],
            }
        )

    assert caught.value.provider_status == 400
    assert caught.value.error_code == "invalid_request_error"
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]


def test_provider_affine_file_request_does_not_escape_to_another_provider() -> None:
    """A gateway file id pins its rewritten request to the owning provider."""
    client = SequencedProxyClient(
        {
            "primary_agent": {"model": "primary-model", "output": []},
            "fallback_agent": {"model": "fallback-model", "output": []},
        }
    )
    result = _build(client).proxy_completion(
        {
            "model": TaskOrchestrator.AUTO_MODEL,
            "input": [{"role": "user", "content": [{"type": "input_file", "file_id": "provider-file"}]}],
            "_required_agent_id": "fallback_agent",
        },
        endpoint="responses",
        single_agent=True,
    )

    assert result["model"] == "fallback-model"
    assert [agent_id for agent_id, _ in client.calls] == ["fallback_agent"]
    assert "_required_agent_id" not in client.calls[0][1]


def test_zdr_only_rejects_a_non_zdr_required_file_provider() -> None:
    client = SequencedProxyClient({"paid_agent": {"model": "paid-model"}})
    orchestrator = TaskOrchestrator(
        [ModelAgent("paid_agent", "paid-model")],
        client=client,
    )

    with orchestrator.request_policy(True), pytest.raises(
        RuntimeError, match="required file provider is unavailable"
    ):
        orchestrator.proxy_completion(
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "messages": [{"role": "user", "content": "private"}],
                "_required_agent_id": "paid_agent",
            }
        )
    assert client.calls == []


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


@pytest.mark.parametrize(
    "model",
    [
        TaskOrchestrator.GATEWAY_DEFAULT_MODEL,
        TaskOrchestrator.AUTO_MODEL,
        TaskOrchestrator.FREE_MODEL,
    ],
)
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


@pytest.mark.parametrize("status", [429, 503])
def test_review_free_structured_synthesis_does_not_replay_on_http_status(
    status: int,
) -> None:
    """A status alone cannot prove a review completion was never applied."""
    client = SequencedProxyClient(
        {
            "primary_agent": _http_error(status),
            "fallback_agent": {"model": "fallback-model"},
        }
    )
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("primary_agent", "primary-model", priority=10,
                       tags=("cost:free", "review", "response_format")),
            ModelAgent("fallback_agent", "fallback-model", priority=1,
                       tags=("cost:free", "review", "response_format")),
        ],
        client=client,
    )
    with patch.object(orchestrator, "conduct", return_value=_structured_workflow()):
        with pytest.raises(ProviderUpstreamError) as caught:
            orchestrator.proxy_completion(
                {
                    "model": TaskOrchestrator.FREE_MODEL,
                    "messages": [{"role": "user", "content": "review"}],
                    "response_format": {"type": "json_object"},
                },
                single_agent=False,
            )

    assert caught.value.provider_status == status
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]


def test_review_free_structured_synthesis_timeout_has_unknown_outcome() -> None:
    """An ambiguous synthesis timeout stops before another free send."""
    client = SequencedProxyClient(
        {
            "primary_agent": TimeoutError("read timed out"),
            "fallback_agent": {"model": "fallback-model"},
        }
    )
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("primary_agent", "primary-model", priority=10,
                       tags=("cost:free", "review", "response_format")),
            ModelAgent("fallback_agent", "fallback-model", priority=1,
                       tags=("cost:free", "review", "response_format")),
        ],
        client=client,
    )
    with patch.object(orchestrator, "conduct", return_value=_structured_workflow()):
        with pytest.raises(ProviderUpstreamError) as caught:
            orchestrator.proxy_completion(
                {
                    "model": TaskOrchestrator.FREE_MODEL,
                    "messages": [{"role": "user", "content": "review"}],
                    "response_format": {"type": "json_object"},
                },
                single_agent=False,
            )

    assert caught.value.error_code == "provider_outcome_unknown"
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]


def test_review_free_conduct_requires_tool_evidence_before_any_send() -> None:
    """Conduct must receive the same request-shaped pool as synthesis."""
    client = SequencedProxyClient({"unknown_agent": {"model": "unknown-model"}})
    orchestrator = TaskOrchestrator(
        [ModelAgent("unknown_agent", "unknown-model", tags=("cost:free", "review"))],
        client=client,
    )
    with patch.object(orchestrator, "conduct") as conduct:
        with pytest.raises(ProviderUpstreamError) as caught:
            orchestrator.proxy_completion(
                {
                    "model": TaskOrchestrator.FREE_MODEL,
                    "messages": [{"role": "user", "content": "review"}],
                    "tools": [{"type": "function", "function": {"name": "inspect"}}],
                },
                single_agent=False,
            )

    assert caught.value.error_code == "request_capability_unavailable"
    conduct.assert_not_called()
    assert client.calls == []


def test_review_free_conduct_receives_request_admitted_candidates() -> None:
    """Unknown tool support cannot enter an earlier conduct role."""
    client = SequencedProxyClient(
        {
            "known_agent": {
                "model": "known-model",
                "choices": [{"message": {"content": "{}"}}],
            },
        }
    )
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("unknown_agent", "unknown-model", priority=10,
                       tags=("cost:free", "review")),
            ModelAgent("known_agent", "known-model", priority=1,
                       tags=("cost:free", "review", "tool_call:single")),
        ],
        client=client,
    )
    with patch.object(orchestrator, "conduct", return_value=_structured_workflow()) as conduct:
        orchestrator.proxy_completion(
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "review"}],
                "tools": [{"type": "function", "function": {"name": "inspect"}}],
            },
            single_agent=False,
        )

    assert conduct.call_args.kwargs["_allowed_agent_ids"] == {"known_agent"}
    assert [agent_id for agent_id, _ in client.calls] == ["known_agent"]


def test_conduct_limits_every_free_role_to_admitted_candidates() -> None:
    """The first conduct role cannot send through an excluded free model."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("unknown_agent", "unknown-model", priority=10,
                       tags=("cost:free", "review")),
            ModelAgent("known_agent", "known-model", priority=1,
                       tags=("cost:free", "review", "tool_call:single")),
        ]
    )
    with patch.object(
        orchestrator, "_invoke_with_rate_limit_recovery", side_effect=RuntimeError("stop")
    ) as invoke:
        with pytest.raises(RuntimeError, match="stop"):
            orchestrator.conduct(
                [{"role": "user", "content": "review"}],
                model_name=TaskOrchestrator.FREE_MODEL,
                _allowed_agent_ids={"known_agent"},
            )

    assert invoke.call_args.kwargs["allowed_agent_ids"] == {"known_agent"}


@pytest.mark.parametrize("status", [429, 502, 503])
def test_review_free_conduct_does_not_replay_upstream_failure(status: int) -> None:
    """Conduct's own role calls obey the review completion replay boundary."""
    first = ModelAgent("first_agent", "first-model", priority=10,
                       tags=("cost:free", "review"))
    second = ModelAgent("second_agent", "second-model", priority=1,
                        tags=("cost:free", "review"))

    class ChatClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def chat(self, agent: ModelAgent, _messages: list[dict[str, Any]]) -> str:
            self.calls.append(agent.id)
            if agent.id == first.id:
                raise ProviderUpstreamError(
                    agent_id=first.id,
                    model=first.model,
                    error_code="api_error",
                    message="provider failed",
                    client_status=status,
                    provider_status=status,
                    retryable=True,
                    transport="chat",
                )
            return "answer"

    client = ChatClient()
    orchestrator = TaskOrchestrator([first, second], client=client)
    with pytest.raises(ProviderUpstreamError) as caught:
        orchestrator.conduct(
            [{"role": "user", "content": "review"}],
            model_name=TaskOrchestrator.FREE_MODEL,
            _allowed_agent_ids={first.id, second.id},
            _review_no_replay=True,
        )

    assert caught.value.provider_status == status
    assert client.calls == [first.id]


def test_explicit_structured_synthesis_normalizes_413() -> None:
    """A sticky explicit model still exposes request-size rejection as 413 authority."""
    client = SequencedProxyClient({"primary_agent": _http_error(413)})
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "primary_agent",
                "primary-model",
                provider_name="primary",
                tags=("response_format",),
            )
        ],
        client=client,
    )
    orchestrator.conduct = lambda *args, **kwargs: {  # type: ignore[method-assign]
        "mode": "conduct",
        "answer": "evidence",
        "trace": [],
        "verification": {"accepted": True, "reason": "test", "verifier_output": ""},
    }

    with pytest.raises(ProviderRequestTooLargeError, match="provider limit"):
        orchestrator.proxy_completion(
            {
                "model": "primary-model",
                "messages": [{"role": "user", "content": "large structured request"}],
                "response_format": {"type": "json_object"},
            },
            single_agent=False,
        )


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

    with pytest.raises(ProviderUpstreamError) as exc_info:
        orchestrator.proxy_completion(
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "messages": [{"role": "user", "content": "large structured request"}],
                "response_format": {"type": "json_object"},
            },
            single_agent=False,
        )

    assert exc_info.value.agent_id == "fallback_agent"
    assert exc_info.value.error_code == "api_error"
    assert "fallback unavailable" not in str(exc_info.value)
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


def test_stale_model_then_size_failure_preserves_request_too_large() -> None:
    client = SequencedProxyClient(
        {
            "primary_agent": _http_error(404),
            "fallback_agent": _http_error(413),
        }
    )

    orchestrator = _build(client)
    orchestrator.conduct = lambda *args, **kwargs: {  # type: ignore[method-assign]
        "mode": "conduct",
        "answer": "evidence",
        "trace": [],
        "verification": {"accepted": True, "reason": "test", "verifier_output": ""},
    }

    with pytest.raises(ProviderRequestTooLargeError, match="every eligible provider"):
        orchestrator.proxy_completion(
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "messages": [{"role": "user", "content": "large request"}],
                "response_format": {"type": "json_object"},
            },
            single_agent=False,
        )


def test_mixed_failures_surface_the_final_classified_provider_failure() -> None:
    """Mixed exhaustion keeps the final provider's actionable typed failure."""
    client = SequencedProxyClient(
        {
            "primary_agent": _http_error(503),
            "fallback_agent": _http_error(413),
        }
    )

    with pytest.raises(ProviderUpstreamError) as caught:
        _build(client).proxy_completion(
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "messages": [{"role": "user", "content": "large request"}],
            }
        )

    assert caught.value.provider_status == 413
    assert caught.value.error_code == "request_too_large"


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
    # 500 here (not 429): this test is about the free/paid selection
    # boundary, not rate-limiting -- a bare 429 with no Retry-After now
    # assumes a short quota cooldown and waits/retries the single free
    # candidate, which would make this test slow and flaky on call count
    # instead of exercising the boundary it actually tests.
    client = SequencedProxyClient(
        {
            "free_agent": _http_error(500),
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


def test_virtual_passthrough_fails_over_on_provider_tool_description_limit() -> None:
    """A provider-only tool limit advances the caller's request to the next provider."""
    failure = _http_error(
        400,
        {
            "error": {
                "code": "invalid_tools",
                "message": "each tool.function.description must be at most 1024 characters",
            }
        },
    )
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": {"model": "fallback-model"},
        }
    )
    orchestrator = _build(client)
    orchestrator.agents = [
        replace(agent, tags=(*agent.tags, "cost:free")) for agent in orchestrator.agents
    ]

    result = orchestrator.proxy_completion(
        {
            "model": TaskOrchestrator.FREE_MODEL,
            "messages": [{"role": "user", "content": "use the tool"}],
            "tools": [{"type": "function", "function": {"name": "inspect", "description": "x" * 1025}}],
        }
    )

    assert result["model"] == "fallback-model"
    assert [agent_id for agent_id, _ in client.calls] == [
        "primary_agent",
        "fallback_agent",
    ]


def test_virtual_passthrough_fails_over_on_single_tool_call_limit() -> None:
    """A model that rejects multi-tool-call turns advances to the next provider.

    Reproduces the exact NVIDIA NIM litellm error shape observed live (Strix
    scan, ContextualWisdomLab/naruon#1486, 2026-09-01): a generic
    ``invalid_request_error`` code (not ``invalid_tools``) with the model's
    own capability-limit sentence embedded in a longer, agent-prefixed
    message. Recognizing this is what stops that single-tool-call-only model
    from ending an entire scan instead of the orchestrator just moving on to
    a capability-matched agent.
    """
    failure = _http_error(
        400,
        {
            "error": {
                "code": "invalid_request_error",
                "message": (
                    "Model 'meta/llama-3.2-11b-vision-instruct' via agent "
                    "'nvidia_nim_meta_llama_3_2_11b_vision_instruct': This "
                    "model only supports single tool-calls at once! This "
                    "model only supports single tool-calls at once!. Adjust "
                    "the request parameters and retry."
                ),
            }
        },
    )
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": {"model": "fallback-model"},
        }
    )
    orchestrator = _build(client)
    orchestrator.agents = [
        replace(agent, tags=(*agent.tags, "cost:free")) for agent in orchestrator.agents
    ]

    result = orchestrator.proxy_completion(
        {
            "model": TaskOrchestrator.FREE_MODEL,
            "messages": [{"role": "user", "content": "use two tools at once"}],
            "tools": [
                {"type": "function", "function": {"name": "inspect", "description": "x"}},
                {"type": "function", "function": {"name": "scan", "description": "y"}},
            ],
        }
    )

    assert result["model"] == "fallback-model"
    assert [agent_id for agent_id, _ in client.calls] == [
        "primary_agent",
        "fallback_agent",
    ]


def _free_pool_with_tool_call_evidence(
    client: SequencedProxyClient, primary_tags: tuple[str, ...]
) -> TaskOrchestrator:
    """Build a free pool whose primary agent carries the given discovery evidence."""
    orchestrator = _build(client)
    orchestrator.agents = [
        replace(
            agent,
            tags=(
                *agent.tags,
                "cost:free",
                "review",
                *(primary_tags if agent.id == "primary_agent" else ("tool_call:multi",)),
            ),
        )
        for agent in orchestrator.agents
    ]
    return orchestrator


def _two_tool_request(**extra: Any) -> dict[str, Any]:
    """Return the request shape the discovery probe proved a single-call model rejects."""
    return {
        "model": TaskOrchestrator.FREE_MODEL,
        "messages": [{"role": "user", "content": "use two tools at once"}],
        "tools": [
            {"type": "function", "function": {"name": "inspect", "description": "x"}},
            {"type": "function", "function": {"name": "scan", "description": "y"}},
        ],
        **extra,
    }


def _one_tool_request(**extra: Any) -> dict[str, Any]:
    """Return a single-tool request no provider evidence shows to be rejected."""
    return {
        "model": TaskOrchestrator.FREE_MODEL,
        "messages": [{"role": "user", "content": "use one tool"}],
        "tools": [
            {"type": "function", "function": {"name": "inspect", "description": "x"}},
        ],
        **extra,
    }


def test_free_pool_skips_single_tool_call_agent_for_multi_tool_request() -> None:
    """Positive single-call evidence removes an agent before the request is sent.

    Issue #940: discovery already records ``tool_call:single`` when a provider
    rejected the probe's two-tool ``parallel_tool_calls: true`` request, and
    the passthrough path already fails over on that 400. Selection must use
    the same evidence so the doomed provider round-trip never happens.
    """
    client = SequencedProxyClient(
        {
            "primary_agent": {"model": "primary-model"},
            "fallback_agent": {"model": "fallback-model"},
        }
    )
    orchestrator = _free_pool_with_tool_call_evidence(client, ("tool_call:single",))

    result = orchestrator.proxy_completion(_two_tool_request())

    assert result["model"] == "fallback-model"
    assert [agent_id for agent_id, _ in client.calls] == ["fallback_agent"]
    assert result["orchestration"]["route"]["selected_candidate_ids"] == ["fallback_agent"]
    assert result["orchestration"]["route"]["attempts"][0]["outcome"] == "served"


def test_free_pool_skips_single_tool_call_agent_when_parallel_calls_requested() -> None:
    """An explicit ``parallel_tool_calls: true`` needs multi-call capability even with one tool."""
    client = SequencedProxyClient(
        {
            "primary_agent": {"model": "primary-model"},
            "fallback_agent": {"model": "fallback-model"},
        }
    )
    orchestrator = _free_pool_with_tool_call_evidence(client, ("tool_call:single",))

    result = orchestrator.proxy_completion(_one_tool_request(parallel_tool_calls=True))

    assert result["model"] == "fallback-model"
    assert [agent_id for agent_id, _ in client.calls] == ["fallback_agent"]


@pytest.mark.parametrize(
    "body",
    [
        _one_tool_request(),
        _two_tool_request(parallel_tool_calls=False),
    ],
    ids=["single_tool_without_flag", "parallel_calls_disabled"],
)
def test_free_pool_keeps_single_tool_call_agent_for_single_call_shapes(
    body: dict[str, Any],
) -> None:
    """Shapes no provider evidence rejects keep the single-call agent eligible."""
    client = SequencedProxyClient(
        {
            "primary_agent": {"model": "primary-model"},
            "fallback_agent": {"model": "fallback-model"},
        }
    )
    orchestrator = _free_pool_with_tool_call_evidence(client, ("tool_call:single",))

    result = orchestrator.proxy_completion(body)

    assert result["model"] == "primary-model"
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]


@pytest.mark.parametrize("tools", [None, []], ids=["no_tools_key", "empty_tools"])
def test_free_pool_keeps_single_tool_call_agent_for_requests_without_tools(tools) -> None:
    """A request that carries no tools never triggers the single-call exclusion."""
    client = SequencedProxyClient(
        {
            "primary_agent": {"model": "primary-model"},
            "fallback_agent": {"model": "fallback-model"},
        }
    )
    orchestrator = _free_pool_with_tool_call_evidence(client, ("tool_call:single",))
    body = {
        "model": TaskOrchestrator.FREE_MODEL,
        "messages": [{"role": "user", "content": "plain text"}],
    }
    if tools is not None:
        body["tools"] = tools

    result = orchestrator.proxy_completion(body)

    assert result["model"] == "primary-model"
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]


def test_free_pool_requires_tool_call_evidence_for_tool_request() -> None:
    """A plain-chat candidate cannot be admitted for an unproven tool shape."""
    client = SequencedProxyClient(
        {
            "primary_agent": {"model": "primary-model"},
            "fallback_agent": {"model": "fallback-model"},
        }
    )
    orchestrator = _free_pool_with_tool_call_evidence(client, ())

    result = orchestrator.proxy_completion(_two_tool_request())

    assert result["model"] == "fallback-model"
    assert [agent_id for agent_id, _ in client.calls] == ["fallback_agent"]
    assert orchestrator.proxy_completion(
        {"model": TaskOrchestrator.FREE_MODEL, "messages": [{"role": "user", "content": "chat"}]}
    )["model"] == "primary-model"


def test_free_pool_without_tool_evidence_fails_before_provider_send() -> None:
    client = SequencedProxyClient({"primary_agent": {"model": "primary-model"}})
    orchestrator = _free_pool_with_tool_call_evidence(client, ())
    orchestrator.agents = [orchestrator.agents[0]]

    with pytest.raises(ProviderUpstreamError) as caught:
        orchestrator.proxy_completion(_one_tool_request())

    assert caught.value.error_code == "request_capability_unavailable"
    assert caught.value.client_status == 503
    assert caught.value.detail["capability"] == "tool_call"
    assert client.calls == []


@pytest.mark.parametrize(
    "failure",
    [
        _http_error(
            400,
            {
                "error": {
                    "code": "invalid_tools",
                    "message": "each tool.function.description must be at most 1024 characters",
                }
            },
        ),
        _http_error(
            400,
            {
                "error": {
                    "code": "invalid_request_error",
                    "message": "This model only supports single tool-calls at once!",
                }
            },
        ),
    ],
    ids=["provider_tool_description_limit", "single_tool_call_limit"],
)
def test_capability_mismatch_failover_does_not_penalize_the_model(
    failure: urllib.error.HTTPError,
) -> None:
    """A structural capability mismatch must not trip the circuit breaker.

    Codex Review (ContextualWisdomLab/contextual-orchestrator#986): a model
    rejecting a request shape it can never support (too many tool
    descriptions, more than one tool call per turn) says nothing about that
    model's health for a differently-shaped future request. Unlike a
    reliability failure, this must not count as a failed stability
    observation -- otherwise an ordinary, differently-shaped future request
    to the same model could be wrongly deprioritized or circuit-broken.
    """
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": {"model": "fallback-model"},
        }
    )
    orchestrator = _build(client)

    result = orchestrator.proxy_completion(
        {
            "model": "contextual-orchestrator",
            "messages": [{"role": "user", "content": "use two tools at once"}],
            "tools": [
                {"type": "function", "function": {"name": "inspect", "description": "x"}},
                {"type": "function", "function": {"name": "scan", "description": "y"}},
            ],
        }
    )

    assert result["model"] == "fallback-model"
    assert orchestrator._circuit.get("primary_agent") in (None, {"failures": 0.0, "opened_at": 0.0})


@pytest.mark.parametrize(
    "provider_error",
    [
        "each tool.function.description must be at most 1024 characters",
        "Bytez rejected the request: each tool.function.description must be at most 1024 characters",
    ],
)
def test_virtual_passthrough_fails_over_on_string_tool_description_limit(
    provider_error: str,
) -> None:
    """Provider APIs that encode ``error`` as text still prove capability mismatch."""
    failure = _http_error(400, {"error": provider_error})
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": {"model": "fallback-model"},
        }
    )
    orchestrator = _build(client)
    orchestrator.agents = [
        replace(agent, tags=(*agent.tags, "cost:free")) for agent in orchestrator.agents
    ]

    result = orchestrator.proxy_completion(
        {
            "model": TaskOrchestrator.FREE_MODEL,
            "messages": [{"role": "user", "content": "use the tool"}],
            "tools": [{"type": "function", "function": {"name": "inspect"}}],
        }
    )

    assert result["model"] == "fallback-model"
    assert [agent_id for agent_id, _ in client.calls] == [
        "primary_agent",
        "fallback_agent",
    ]


@pytest.mark.parametrize(
    "provider_error",
    [
        "each tool.function.description must be at most 1024 characters",
        "Bytez rejected the request: each tool.function.description must be at most 1024 characters",
    ],
)
def test_exhausted_string_tool_description_limit_returns_413_without_penalty(
    provider_error: str,
) -> None:
    """A string-form capability limit is request-size neutral for provider health."""
    failure = _http_error(400, {"error": provider_error})
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": _http_error(400, {"error": provider_error}),
        }
    )
    orchestrator = _build(client)
    orchestrator.agents = [
        replace(agent, tags=(*agent.tags, "cost:free")) for agent in orchestrator.agents
    ]

    with pytest.raises(ProviderRequestTooLargeError, match="every eligible provider"):
        orchestrator.proxy_completion(
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "use the tool"}],
                "tools": [{"type": "function", "function": {"name": "inspect"}}],
            }
        )

    assert orchestrator._circuit == {}
    assert orchestrator._group_router.member_observation_count("primary_agent") == 0
    assert orchestrator._group_router.member_observation_count("fallback_agent") == 0


def test_model_client_preserves_tool_limit_body_for_failover(monkeypatch) -> None:
    """The real passthrough transport shares its one-read provider error body."""
    failure = _http_error(
        400,
        {
            "error": {
                "code": "invalid_tools",
                "message": "each tool.function.description must be at most 1024 characters",
            }
        },
    )
    outcomes: list[dict[str, Any] | BaseException] = [
        failure,
        {"model": "fallback-model"},
    ]
    client = ModelClient()

    def _send_raw(*_args: object, **_kwargs: object) -> dict[str, Any]:
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(
        client,
        "_validate_provider",
        lambda _agent: (socket.AF_INET, ("127.0.0.1", 80)),
    )
    monkeypatch.setattr(client, "_send_raw", _send_raw)
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "primary_agent",
                "primary-model",
                base_url="https://primary.example/v1",
                provider_name="primary",
            ),
            ModelAgent(
                "fallback_agent",
                "fallback-model",
                base_url="https://fallback.example/v1",
                provider_name="fallback",
            ),
        ],
        client=client,
    )

    result = orchestrator.proxy_completion(
        {
            "model": TaskOrchestrator.AUTO_MODEL,
            "messages": [{"role": "user", "content": "use the tool"}],
            "tools": [{"type": "function", "function": {"name": "inspect"}}],
        }
    )

    assert result["model"] == "fallback-model"
    assert outcomes == []


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


def test_proxy_send_only_client_preserves_classified_failover_signal() -> None:
    """Virtual passthrough still fails over when only classified proxy_send exists."""

    class ProxySendOnlyClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def proxy_send(
            self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]
        ) -> dict[str, Any]:
            del endpoint
            self.calls.append((agent.id, deepcopy(payload)))
            if agent.id == "primary_agent":
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
            return {"model": "fallback-model", "choices": []}

        def apply_effort_profile(
            self,
            agent: ModelAgent,
            payload: dict[str, Any],
            profile: ReasoningEffortProfile,
        ) -> dict[str, Any]:
            return ModelClient().apply_effort_profile(agent, payload, profile)

    client = ProxySendOnlyClient()

    assert _build(client).proxy_completion(
        {"model": TaskOrchestrator.AUTO_MODEL, "messages": [{"role": "user", "content": "x"}]}
    )["model"] == "fallback-model"
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent", "fallback_agent"]


def test_classified_ambiguous_connection_error_does_not_fail_over() -> None:
    """A retryable connection error without status must not replay passthrough."""
    failure = ProviderUpstreamError(
        agent_id="primary_agent",
        model="primary-model",
        error_code="provider_connection_error",
        message="the provider primary_agent connection failed or did not finish in time",
        client_status=502,
        provider_status=None,
        retryable=True,
        transport="passthrough",
    )
    client = SequencedProxyClient(
        {"primary_agent": failure, "fallback_agent": {"model": "fallback-model"}}
    )

    with pytest.raises(ProviderUpstreamError) as caught:
        _build(client).proxy_completion(
            {"model": TaskOrchestrator.AUTO_MODEL, "messages": [{"role": "user", "content": "x"}]}
        )

    assert caught.value is failure
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]


def test_free_virtual_model_keeps_ambiguous_transport_502_sticky() -> None:
    """A classified ambiguous transport failure must not replay a free request."""
    failure = ProviderUpstreamError(
        agent_id="primary_agent",
        model="primary-model",
        error_code="provider_connection_error",
        message="the provider primary_agent connection failed or did not finish in time",
        client_status=502,
        provider_status=None,
        retryable=True,
        transport="passthrough",
    )
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": {"model": "fallback-model"},
        }
    )
    orchestrator = _build(client)
    orchestrator.agents = [
        replace(agent, tags=(*agent.tags, "cost:free")) for agent in orchestrator.agents
    ]

    with pytest.raises(ProviderUpstreamError) as caught:
        orchestrator.proxy_completion(
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "use the tool"}],
                "tools": [{"type": "function", "function": {"name": "inspect"}}],
            }
        )

    assert caught.value.detail["attempts"][0]["phase"] == "transport"
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]



@pytest.mark.parametrize("status", [500, 502, 504, 529])
def test_free_virtual_model_keeps_ambiguous_http_failure_sticky(status: int) -> None:
    """Ambiguous HTTP failures do not prove non-acceptance and cannot replay."""
    client = SequencedProxyClient(
        {
            "primary_agent": _http_error(status),
            "fallback_agent": {"model": "fallback-model"},
        }
    )
    orchestrator = _build(client)
    orchestrator.agents = [
        replace(agent, tags=(*agent.tags, "cost:free")) for agent in orchestrator.agents
    ]

    with pytest.raises(ProviderUpstreamError) as caught:
        orchestrator.proxy_completion(
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "use the tool"}],
                "tools": [{"type": "function", "function": {"name": "inspect"}}],
            }
        )

    assert caught.value.provider_status == status
    assert caught.value.detail["terminal_reason"] == "terminal_provider_failure"
    assert caught.value.detail["attempts"][0]["failover_decision"] == (
        "sticky_candidate_failure"
    )
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]


def test_free_virtual_model_stops_after_a_rejection_then_ambiguous_failure() -> None:
    """One proved rejection may advance, but an ambiguous next failure is sticky."""
    client = SequencedProxyClient(
        {"primary_agent": _http_error(429), "fallback_agent": _http_error(500)}
    )
    orchestrator = _build(client)
    orchestrator.agents = [
        replace(
            agent,
            base_url=f"mock://{agent.id}",
            provider_name="",
            tags=(*agent.tags, "cost:free"),
        )
        for agent in orchestrator.agents
    ]

    with pytest.raises(ProviderUpstreamError) as caught:
        orchestrator.proxy_completion(
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "use the tool"}],
                "tools": [{"type": "function", "function": {"name": "inspect"}}],
            }
        )

    assert caught.value.agent_id == "fallback_agent"
    assert caught.value.detail["terminal_reason"] == "terminal_provider_failure"
    assert caught.value.detail["selected_candidate_ids"] == [
        "primary_agent",
        "fallback_agent",
    ]
    assert caught.value.detail["attempts"] == [
        {
            "agent_id": "primary_agent",
            "model": "primary-model",
            "provider_name": "unreported",
            "attempt_number": 1,
            "error_code": "rate_limit_exceeded",
            "client_status": 429,
            "provider_status": 429,
            "retryable": True,
            "transport": "passthrough",
            "phase": "provider_response",
            "failover_decision": "advance_to_next_candidate",
        },
        {
            "agent_id": "fallback_agent",
            "model": "fallback-model",
            "provider_name": "unreported",
            "attempt_number": 2,
            "error_code": "api_error",
            "client_status": 502,
            "provider_status": 500,
            "retryable": True,
            "transport": "passthrough",
            "phase": "provider_response",
            "failover_decision": "sticky_candidate_failure",
        },
    ]
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent", "fallback_agent"]


def test_explicit_model_classified_transport_502_remains_sticky() -> None:
    """A concrete model id keeps single-provider stickiness for retryable transport failures."""
    failure = ProviderUpstreamError(
        agent_id="primary_agent",
        model="primary-model",
        error_code="provider_connection_error",
        message="the provider primary_agent connection failed or did not finish in time",
        client_status=502,
        provider_status=None,
        retryable=True,
        transport="passthrough",
    )
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": {"model": "fallback-model"},
        }
    )

    with pytest.raises(ProviderUpstreamError) as caught:
        _build(client).proxy_completion(
            {"model": "primary-model", "messages": [{"role": "user", "content": "x"}]}
        )

    assert caught.value is failure
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]


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

    with pytest.raises(ProviderUpstreamError) as caught:
        _build(client).proxy_completion({"messages": [{"role": "user", "content": "x"}]})

    assert caught.value.error_code == "api_error"
    assert caught.value.detail["terminal_reason"] == "terminal_provider_failure"
    assert caught.value.detail["attempts"] == [
        {
            "agent_id": "primary_agent",
            "model": "primary-model",
            "provider_name": "primary",
            "attempt_number": 1,
            "error_code": "api_error",
            "client_status": 502,
            "provider_status": None,
            "retryable": False,
            "transport": "passthrough",
            "phase": "provider_response",
            "failover_decision": "sticky_candidate_failure",
        }
    ]
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]


def test_all_candidates_chain_the_last_failure() -> None:
    """Exhaustion reports one stable gateway error with the final provider cause."""
    final = _http_error(503)
    # 408 here (not 429 or 500): 429 can enter the rate-limit-storm wait path,
    # and 500/502/504/529 stay sticky under the RFC-bounded rejection set from
    # #1049. A proved request rejection (408) may advance, then the final 503
    # is reported on exhaustion without waiting.
    orchestrator = _build(
        SequencedProxyClient({"primary_agent": _http_error(408), "fallback_agent": final})
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
        with pytest.raises(ProviderUpstreamError) as caught:
            _build(client).proxy_completion({"messages": [{"role": "user", "content": "x"}]})
        assert caught.value.error_code == "provider_connection_error"
        assert caught.value.detail["terminal_reason"] == "terminal_provider_failure"
        assert caught.value.detail["attempts"] == [
            {
                "agent_id": "primary_agent",
                "model": "primary-model",
                "provider_name": "primary",
                "attempt_number": 1,
                "error_code": "provider_connection_error",
                "client_status": 502,
                "provider_status": None,
                "retryable": False,
                "transport": "passthrough",
                "phase": "transport",
                "failover_decision": "sticky_candidate_failure",
            }
        ]


@pytest.mark.parametrize("error_type", [TimeoutError, ConnectionError])
def test_ambiguous_timeout_on_explicit_model_is_not_replayed(error_type) -> None:
    """An explicit concrete model still fails closed after exactly one call."""
    failure = error_type("provider outcome unknown token=private_test_value")
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": {"model": "fallback-model"},
        }
    )
    orchestrator = _build(client)

    with pytest.raises(ProviderUpstreamError) as raised:
        orchestrator.proxy_completion(
            {
                "model": "primary-model",
                "messages": [{"role": "user", "content": "x"}],
            }
        )

    assert raised.value.error_code == "provider_outcome_unknown"
    assert raised.value.client_status == 502
    assert raised.value.provider_status is None
    assert raised.value.retryable is False
    assert raised.value.transport == "passthrough"
    assert "private_test_value" not in str(raised.value)
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]
    assert "primary_agent" in orchestrator._circuit


@pytest.mark.parametrize(
    "model",
    [None, TaskOrchestrator.AUTO_MODEL],
    ids=["default_model", "auto_model"],
)
def test_ambiguous_timeout_on_virtual_selector_advances_to_next_candidate(
    model: str | None,
) -> None:
    """A virtual selector may advance past one candidate's ambiguous timeout."""
    failure = TimeoutError("provider outcome unknown")
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": {"model": "fallback-model"},
        }
    )
    orchestrator = _build(client)
    body: dict[str, Any] = {"messages": [{"role": "user", "content": "x"}]}
    if model is not None:
        body["model"] = model

    result = orchestrator.proxy_completion(body)

    assert result["model"] == "fallback-model"
    assert [agent_id for agent_id, _ in client.calls] == [
        "primary_agent",
        "fallback_agent",
    ]
    assert "primary_agent" in orchestrator._circuit


def test_ambiguous_timeout_on_free_model_advances_to_next_free_candidate() -> None:
    """``FREE_MODEL`` advances past an ambiguous timeout with admitted free candidates."""
    failure = TimeoutError("provider outcome unknown")
    client = SequencedProxyClient(
        {
            "free_primary_agent": failure,
            "free_fallback_agent": {"model": "free-fallback-model"},
        }
    )
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "free_primary_agent",
                "free-primary-model",
                priority=10,
                provider_name="free_primary",
                tags=("cost:free",),
            ),
            ModelAgent(
                "free_fallback_agent",
                "free-fallback-model",
                priority=1,
                provider_name="free_fallback",
                tags=("cost:free",),
            ),
        ],
        client=client,
    )

    result = orchestrator.proxy_completion(
        {
            "model": TaskOrchestrator.FREE_MODEL,
            "messages": [{"role": "user", "content": "x"}],
        }
    )

    assert result["model"] == "free-fallback-model"
    assert [agent_id for agent_id, _ in client.calls] == [
        "free_primary_agent",
        "free_fallback_agent",
    ]
    assert "free_primary_agent" in orchestrator._circuit


def test_ambiguous_timeout_on_virtual_selector_exhausts_to_classified_502() -> None:
    """When every virtual-selector candidate times out, the request still fails classified 502."""
    failure = TimeoutError("provider outcome unknown")
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": TimeoutError("provider outcome unknown"),
        }
    )
    orchestrator = _build(client)

    with pytest.raises(ProviderUpstreamError) as caught:
        orchestrator.proxy_completion({"messages": [{"role": "user", "content": "x"}]})

    assert caught.value.client_status == 502
    assert caught.value.error_code == "provider_connection_error"
    assert caught.value.retryable is True
    assert caught.value.transport == "passthrough"
    assert caught.value.agent_id == "fallback_agent"
    assert caught.value.__cause__ is None
    assert [agent_id for agent_id, _ in client.calls] == [
        "primary_agent",
        "fallback_agent",
    ]
    assert "primary_agent" in orchestrator._circuit
    assert "fallback_agent" in orchestrator._circuit


@pytest.mark.parametrize("wrapper_type", [RuntimeError, TimeoutError])
def test_wrapped_admission_timeout_does_not_authorize_replay(wrapper_type) -> None:
    """Only the direct pre-send exception carries the local admission proof."""
    from contextual_orchestrator.orchestrator import (
        _LocalProviderAdmissionTimeout,
        _is_passthrough_failover_error,
    )

    wrapped = wrapper_type("unknown outer operation")
    wrapped.__cause__ = _LocalProviderAdmissionTimeout("earlier slot failure")
    assert not _is_passthrough_failover_error(wrapped)


@pytest.mark.parametrize("after_send", [False, True])
def test_local_admission_timeout_preserves_send_boundary(monkeypatch, after_send: bool) -> None:
    """Only a failed slot acquisition may advance without replaying a sent request."""
    from contextlib import nullcontext
    from contextual_orchestrator.orchestrator import _local_provider_slot

    client = ModelClient(timeout=0.001)
    router = _build(client)
    router.agents[0] = replace(
        router.agents[0], base_url="local://127.0.0.1:19441/v1"
    )
    router.agents[1] = replace(
        router.agents[1], base_url="local://127.0.0.1:19442/v1"
    )
    sent = []

    def raw_send(agent, *args, **kwargs):
        sent.append(agent.id)
        if after_send and agent.id == "primary_agent":
            raise TimeoutError("response not received after transport invocation")
        return {"model": agent.model, "choices": []}

    monkeypatch.setattr(client, "_send_raw_with_retry", raw_send)
    slot = nullcontext() if after_send else _local_provider_slot(router.agents[0], 1, None)
    with slot:
        if after_send:
            # Virtual selector owns failover across an ambiguous post-send
            # timeout (#1166/#1176); the failed candidate is still recorded.
            result = router.proxy_completion({"messages": [{"role": "user", "content": "x"}]})
            assert result["model"] == "fallback-model"
            assert sent == ["primary_agent", "fallback_agent"]
            assert "primary_agent" in router._circuit
        else:
            result = router.proxy_completion({"messages": [{"role": "user", "content": "x"}]})
            assert result["model"] == "fallback-model"
            assert sent == ["fallback_agent"]


@pytest.mark.parametrize("after_send", [False, True])
def test_review_free_replay_requires_direct_local_slot_proof(monkeypatch, after_send: bool) -> None:
    """Count actual transport calls across the local slot and provider boundary."""
    from contextlib import nullcontext
    from contextual_orchestrator.orchestrator import _local_provider_slot

    client = ModelClient(timeout=0.001)
    router = _build(client)
    router.agents = [
        replace(
            agent,
            base_url=f"local://127.0.0.1:{19451 + index}/v1",
            tags=(*agent.tags, "cost:free", "review"),
        )
        for index, agent in enumerate(router.agents)
    ]
    sent: list[str] = []

    def raw_send(agent, *args, **kwargs):
        sent.append(agent.id)
        if after_send and agent.id == "primary_agent":
            raise TimeoutError("response lost after send")
        return {"model": agent.model, "choices": []}

    monkeypatch.setattr(client, "_send_raw_with_retry", raw_send)
    slot = nullcontext() if after_send else _local_provider_slot(router.agents[0], 1, None)
    with slot:
        request = {"model": TaskOrchestrator.FREE_MODEL, "messages": [{"role": "user", "content": "x"}]}
        if after_send:
            with pytest.raises(ProviderUpstreamError) as caught:
                router.proxy_completion(request)
            assert caught.value.error_code == "provider_outcome_unknown"
            assert sent == ["primary_agent"]
        else:
            assert router.proxy_completion(request)["model"] == "fallback-model"
            assert sent == ["fallback_agent"]


@pytest.mark.parametrize("mode", ["route", "conduct"])
def test_review_free_http_tool_request_uses_proven_provider(monkeypatch, mode: str) -> None:
    """The virtual-tool HTTP route excludes an unproven higher-priority model."""
    import threading
    import urllib.request
    from contextual_orchestrator.server import SecurityConfig, build_server

    client = ModelClient()
    sent: list[str] = []

    def chat(agent, messages, **_kwargs):
        sent.append(agent.id)
        scoped_tools = client.request_settings_snapshot().get("tools")
        if messages and isinstance(messages[0].get("content"), str) and "Role: worker" in messages[0]["content"]:
            assert scoped_tools
        return "answer"

    monkeypatch.setattr(client, "chat", chat)
    router = TaskOrchestrator([
        ModelAgent("unknown_agent", "unknown-model", priority=10,
                   tags=("cost:free", "review")),
        ModelAgent("known_agent", "known-model", priority=1,
                   tags=("cost:free", "review", "tool_call:single")),
    ], client=client)
    monkeypatch.setattr(router, "_realtime_route_judge", lambda **_kwargs: {
        "accepted": True, "reason": "test", "verifier_output": "answer"
    })
    server = build_server(router, port=0, security=SecurityConfig(auth_token="local_test_only"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
            data=json.dumps({
                "model": TaskOrchestrator.FREE_MODEL,
                "mode": mode,
                "messages": [{"role": "user", "content": "review"}],
                "tools": [{"type": "function", "function": {
                    "name": "inspect", "parameters": {"type": "object"}
                }}],
            }).encode(),
            headers={"Authorization": "Bearer local_test_only", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.load(response)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert payload["choices"][0]["message"]["content"]
    assert sent and set(sent) == {"known_agent"}
    route = payload["orchestration"]["route"]
    assert route["contract_version"] == "1"
    assert route["admitted_agent_ids"] == ["known_agent"]
    assert route["terminal_reason"] == "response_returned"
    assert route["served_steps"] and {step["agent_id"] for step in route["served_steps"]} == {"known_agent"}
    if mode == "route":
        assert sent == ["known_agent"]


@pytest.mark.parametrize("mode", ["route", "conduct"])
def test_review_free_http_tool_request_fails_before_unknown_provider_send(
    monkeypatch, mode: str
) -> None:
    """The actual virtual-tool HTTP path enforces the same admission contract."""
    import threading
    import urllib.request
    from contextual_orchestrator.server import SecurityConfig, build_server

    client = ModelClient()
    sent: list[str] = []

    def chat(agent, *_args, **_kwargs):
        sent.append(agent.id)
        raise AssertionError("provider must not be called")

    monkeypatch.setattr(client, "chat", chat)
    router = TaskOrchestrator([
        ModelAgent("unknown_agent", "unknown-model", tags=("cost:free", "review"))
    ], client=client)
    server = build_server(router, port=0, security=SecurityConfig(auth_token="local_test_only"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
            data=json.dumps({
                "model": TaskOrchestrator.FREE_MODEL,
                "mode": mode,
                "messages": [{"role": "user", "content": "review"}],
                "tools": [{"type": "function", "function": {
                    "name": "inspect", "parameters": {"type": "object"}
                }}],
            }).encode(),
            headers={"Authorization": "Bearer local_test_only", "Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        with caught.value as response:
            payload = json.load(response)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert caught.value.code == 503
    assert payload["error"]["code"] == "request_capability_unavailable"
    assert payload["error"]["detail"]["contract_version"] == "1"
    assert payload["error"]["detail"]["admitted_agent_ids"] == []
    assert sent == []


def test_review_free_http_tool_request_does_not_replay_rate_limit(monkeypatch) -> None:
    """A live virtual-tool route does not send a second completion after 429."""
    import threading
    import urllib.request
    from contextual_orchestrator.server import SecurityConfig, build_server

    client = ModelClient()
    sent: list[str] = []

    def chat(agent, *_args, **_kwargs):
        sent.append(agent.id)
        if agent.id == "primary_agent":
            raise ProviderUpstreamError(
                agent_id=agent.id,
                model=agent.model,
                error_code="rate_limit_exceeded",
                message="rate limited",
                client_status=429,
                provider_status=429,
                retryable=True,
            )
        return "unexpected fallback"

    monkeypatch.setattr(client, "chat", chat)
    router = TaskOrchestrator([
        ModelAgent("primary_agent", "primary-model", priority=10,
                   tags=("cost:free", "review", "tool_call:single")),
        ModelAgent("fallback_agent", "fallback-model", priority=1,
                   tags=("cost:free", "review", "tool_call:single")),
    ], client=client, rate_limit_wait_seconds=0)
    server = build_server(router, port=0, security=SecurityConfig(auth_token="local_test_only"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
            data=json.dumps({
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "review"}],
                "tools": [{"type": "function", "function": {
                    "name": "inspect", "parameters": {"type": "object"}
                }}],
            }).encode(),
            headers={"Authorization": "Bearer local_test_only", "Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        with caught.value as response:
            payload = json.load(response)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert caught.value.code == 429
    assert payload["error"]["code"] == "rate_limit_exceeded"
    assert payload["error"]["detail"]["terminal_reason"] == "fail_closed"
    assert payload["error"]["detail"]["admitted_agent_ids"] == [
        "primary_agent", "fallback_agent"
    ]
    assert sent == ["primary_agent"]


def test_sdk_passthrough_unknown_outcome_never_replays() -> None:
    """Exact SDK to real HTTP to passthrough preserves one unknown-outcome attempt."""
    import asyncio
    import threading
    from contextual_orchestrator.server import SecurityConfig, build_server

    import openai as sdk
    assert sdk.__version__ == "2.54.0"
    transport = SequencedProxyClient({
        "primary_agent": TimeoutError("token=private_test_value"),
        "fallback_agent": {"model": "fallback-model"},
    })
    server = build_server(_build(transport), port=0, security=SecurityConfig(auth_token="local_test_only"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    async def request_completion():
        async with sdk.AsyncOpenAI(
            api_key="local_test_only", base_url=f"http://127.0.0.1:{server.server_address[1]}/v1",
        ) as client:
            with pytest.raises(sdk.APIStatusError) as raised:
                await client.chat.completions.create(
                    model="primary-model",
                    messages=[{"role": "user", "content": "inspect locally"}],
                    tools=[{"type": "function", "function": {"name": "inspect", "parameters": {"type": "object"}}}],
                )
            assert raised.value.status_code == 502
            assert raised.value.body["code"] == "provider_outcome_unknown"
            assert raised.value.body["detail"]["retryable"] is False
            assert raised.value.response.headers["x-should-retry"] == "false"
            assert "private_test_value" not in str(raised.value)

    try:
        asyncio.run(request_completion())
        assert [agent_id for agent_id, _ in transport.calls] == ["primary_agent"]
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


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


def test_explicit_omit_profile_overrides_fail_closed_catalog_ranking() -> None:
    """A request override may intentionally use an unsupported provider."""
    client = SequencedProxyClient(
        {
            "unsupported_agent": {"model": "unsupported-model"},
            "supported_agent": {"model": "supported-model"},
        }
    )
    unsupported = ModelAgent(
        "unsupported_agent",
        "unsupported-model",
        base_url="https://unsupported.example/v1",
        priority=10,
        provider_name="unsupported",
        reasoning_effort_supported=False,
    )
    supported = ModelAgent(
        "supported_agent",
        "supported-model",
        base_url="https://supported.example/v1",
        priority=1,
        provider_name="supported",
        reasoning_effort_supported=True,
    )
    orchestrator = TaskOrchestrator(
        [unsupported, supported],
        client=client,
        role_effort_catalog=default_role_effort_catalog(),
    )

    result = orchestrator.proxy_completion(
        {"messages": [{"role": "user", "content": "x"}]},
        effort_profile=ReasoningEffortProfile(unsupported_provider_fallback="omit"),
    )

    assert result["model"] == "unsupported-model"
    assert [agent_id for agent_id, _ in client.calls] == ["unsupported_agent"]


def test_passthrough_with_no_ranked_provider_fails_cleanly(monkeypatch) -> None:
    """An empty filtered pool reports unavailability instead of reading stale state."""
    client = SequencedProxyClient({"primary_agent": {"model": "primary-model"}})
    orchestrator = _build(client)
    monkeypatch.setattr(orchestrator, "_failover_candidates", lambda *args, **kwargs: [])

    with pytest.raises(RuntimeError, match="no eligible provider candidate"):
        orchestrator.proxy_completion({"messages": [{"role": "user", "content": "x"}]})

    assert client.calls == []


def test_virtual_responses_effort_profile_uses_responses_wire_shape() -> None:
    """Responses passthrough maps effort and output tokens to its native fields."""
    client = SequencedProxyClient({"primary_agent": {"model": "primary-model"}})
    orchestrator = _build(client)
    profile = ReasoningEffortProfile(
        reasoning_effort="medium",
        max_output_tokens=321,
        unsupported_provider_fallback="error",
    )

    result = orchestrator.proxy_completion(
        {"model": "primary-model", "input": "x"},
        endpoint="responses",
        effort_profile=profile,
    )

    assert result["model"] == "primary-model"
    payload = client.calls[0][1]
    assert payload["max_output_tokens"] == 321
    assert payload["reasoning"] == {"effort": "medium"}
    assert "max_tokens" not in payload
    assert "reasoning_effort" not in payload


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


def test_virtual_structured_synthesis_skips_reasoning_only_model_on_same_endpoint() -> None:
    """A contentless virtual candidate cannot terminate same-endpoint synthesis."""
    endpoint = "https://synthetic.invalid/v1"
    client = SequencedProxyClient(
        {
            "reasoning_only": {
                "choices": [{"message": {"content": None, "reasoning": "bounded"}}]
            },
            "structured_live": {
                "model": "structured-model",
                "choices": [{"message": {"content": '{"status":"synthetic_ok"}'}}]
            },
        }
    )
    first = ModelAgent(
        "reasoning_only", "reasoning-model", endpoint, priority=10,
        tags=("response_format",),
    )
    second = ModelAgent(
        "structured_live", "structured-model", endpoint, priority=1,
        tags=("response_format",),
    )
    orchestrator = TaskOrchestrator([first, second], client=client)
    orchestrator.conduct = lambda *args, **kwargs: {  # type: ignore[method-assign]
        "mode": "conduct",
        "answer": "evidence",
        "trace": [],
        "verification": {"accepted": True},
    }

    result = orchestrator.proxy_completion(
        {
            "model": TaskOrchestrator.AUTO_MODEL,
            "messages": [{"role": "user", "content": "synthetic structured request"}],
            "response_format": {"type": "json_object"},
        },
        single_agent=False,
    )

    assert result["model"] == "structured-model"
    assert result["choices"][0]["message"]["content"] == '{"status":"synthetic_ok"}'
    assert [agent_id for agent_id, _ in client.calls] == [
        "reasoning_only",
        "structured_live",
    ]


def test_json_object_contract_rejects_non_json_and_non_object_values() -> None:
    """json_object validation cannot accept provider prose or JSON scalars."""
    response_format = {"type": "json_object"}

    assert _structured_output_error("not json", response_format) == "invalid_json"
    assert _structured_output_error("[]", response_format) == "invalid_json_object"
    assert _structured_output_error('{"status":"synthetic_ok"}', response_format) is None


def _wrapped_url_error(cause: OSError) -> urllib.error.URLError:
    """Raise ``cause`` the way urllib does, so it becomes the URLError's context."""
    try:
        raise cause
    except OSError as err:
        try:
            raise urllib.error.URLError(err)
        except urllib.error.URLError as wrapped:
            return wrapped


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError("read timed out"),
        ConnectionResetError(104, "connection reset by peer"),
        http.client.IncompleteRead(b""),
        http.client.RemoteDisconnected("remote end closed connection"),
        _wrapped_url_error(TimeoutError("connect timed out")),
    ],
    ids=["read-timeout", "reset", "incomplete-read", "remote-disconnected", "connect-timeout"],
)
def test_ambiguous_transport_failure_is_classified_and_recorded(failure: BaseException) -> None:
    """Explicit-model ambiguous failures fail closed: classified, recorded, not replayed."""
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": {"model": "fallback-model"},
        }
    )
    orchestrator = _build(client)

    with pytest.raises(ProviderUpstreamError) as caught:
        orchestrator.proxy_completion(
            {
                "model": "primary-model",
                "messages": [{"role": "user", "content": "use the tool"}],
                "tools": [{"type": "function", "function": {"name": "inspect"}}],
            }
        )

    assert caught.value.client_status == 502
    assert caught.value.error_code == "provider_outcome_unknown"
    assert caught.value.retryable is False
    assert caught.value.__cause__ is None
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]
    assert "primary_agent" in orchestrator._circuit
    assert _is_ambiguous_passthrough_transport_failure(failure)


def test_ambiguous_transport_predicate_excludes_status_and_dns_failures() -> None:
    """HTTP statuses and DNS failures are not ambiguous: nothing reached the provider or a status came back."""
    assert _is_ambiguous_passthrough_transport_failure(_http_error(401)) is False
    assert _is_ambiguous_passthrough_transport_failure(_http_error(503)) is False
    dns = _wrapped_url_error(socket.gaierror(socket.EAI_NONAME, "name not known"))
    assert _is_ambiguous_passthrough_transport_failure(dns) is False
    assert _is_ambiguous_passthrough_transport_failure(ValueError("bad body")) is False


def test_ambiguous_transport_failure_is_observed_by_the_group_router() -> None:
    """A grouped candidate's ambiguous failure reaches its group's stability record too."""
    client = SequencedProxyClient(
        {
            "primary_agent": TimeoutError("read timed out"),
            "fallback_agent": {"model": "fallback-model"},
        }
    )
    orchestrator = _build(client)
    orchestrator.agents = [
        replace(agent, group_name="provider-group") for agent in orchestrator.agents
    ]

    result = orchestrator.proxy_completion({"messages": [{"role": "user", "content": "x"}]})

    assert result["model"] == "fallback-model"
    assert orchestrator._group_router.member_observation_count("primary_agent") == 1
    assert [agent_id for agent_id, _ in client.calls] == [
        "primary_agent",
        "fallback_agent",
    ]


def test_ambiguous_transport_predicate_stops_at_the_chain_limit() -> None:
    """A chain deeper than the walk limit with no transport failure inside is not ambiguous."""
    error: BaseException = ValueError("layer 0")
    for depth in range(1, 12):
        try:
            raise error
        except ValueError as inner:
            try:
                raise ValueError(f"layer {depth}") from inner
            except ValueError as outer:
                error = outer
    assert _is_ambiguous_passthrough_transport_failure(error) is False


def _tool_call_choice(call_id: str) -> dict[str, Any]:
    """Build a chat-completions-shaped provider response carrying one tool call."""
    return {
        "model": "fallback-model",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": "inspect", "arguments": "{}"},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }


def _plain_choice(model: str) -> dict[str, Any]:
    """Build a chat-completions-shaped provider response with plain text content."""
    return {
        "model": model,
        "choices": [
            {"message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}
        ],
    }


def _tool_result_followup(
    tools_body: dict[str, Any], call_id: str, *, model: str
) -> dict[str, Any]:
    """Build a follow-up chat/completions body carrying one tool result."""
    return {
        "model": model,
        "messages": [
            *tools_body["messages"],
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": "inspect", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": call_id, "content": "42"},
        ],
        "tools": tools_body["tools"],
    }


def test_tool_loop_follow_up_returns_to_the_emitting_agent() -> None:
    """A tool-result follow-up is served by the agent that emitted the call, not the top-ranked one."""
    client = SequencedProxyClient(
        {
            "primary_agent": _http_error(503),
            "fallback_agent": _tool_call_choice("call_1"),
        }
    )
    orchestrator = _build(client)
    body = {
        "model": TaskOrchestrator.AUTO_MODEL,
        "messages": [{"role": "user", "content": "review code"}],
        "tools": [{"type": "function", "function": {"name": "inspect"}}],
    }

    first = orchestrator.proxy_completion(body)

    assert first["model"] == "fallback-model"
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent", "fallback_agent"]
    assert orchestrator._tool_loop_memory["call_1"] == "fallback_agent"

    client.calls.clear()
    client.outcomes["fallback_agent"] = _plain_choice("fallback-model")
    follow_up = _tool_result_followup(body, "call_1", model=TaskOrchestrator.AUTO_MODEL)

    result = orchestrator.proxy_completion(follow_up)

    # The top-ranked primary_agent is never attempted: the follow-up goes
    # straight to the agent that emitted call_1.
    assert [agent_id for agent_id, _ in client.calls] == ["fallback_agent"]
    assert result["orchestration"]["tool_loop_route"] == "emitting_agent"
    assert result["orchestration"]["tool_loop_agent_id"] == "fallback_agent"


def test_tool_loop_falls_back_when_emitting_agent_circuit_is_open() -> None:
    """A circuit-open emitting agent is skipped; routing falls back and says so."""
    client = SequencedProxyClient(
        {
            "primary_agent": _http_error(503),
            "fallback_agent": _tool_call_choice("call_2"),
        }
    )
    orchestrator = _build(client)
    body = {
        "model": TaskOrchestrator.AUTO_MODEL,
        "messages": [{"role": "user", "content": "review code"}],
        "tools": [{"type": "function", "function": {"name": "inspect"}}],
    }
    orchestrator.proxy_completion(body)
    assert orchestrator._tool_loop_memory["call_2"] == "fallback_agent"

    for _ in range(orchestrator.circuit_failure_threshold):
        orchestrator._record_failure("fallback_agent")
    assert orchestrator._circuit_open("fallback_agent") is True

    client.calls.clear()
    client.outcomes["primary_agent"] = _plain_choice("primary-model")
    follow_up = _tool_result_followup(body, "call_2", model=TaskOrchestrator.AUTO_MODEL)

    result = orchestrator.proxy_completion(follow_up)

    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]
    assert result["orchestration"]["tool_loop_route"] == "fallback"
    assert result["orchestration"]["tool_loop_agent_id"] == "fallback_agent"


def test_explicit_concrete_model_ignores_tool_loop_memory() -> None:
    """An explicit concrete model is never re-ranked toward a remembered emitting agent."""
    client = SequencedProxyClient(
        {
            "primary_agent": _http_error(503),
            "fallback_agent": _tool_call_choice("call_3"),
        }
    )
    orchestrator = _build(client)
    body = {
        "model": TaskOrchestrator.AUTO_MODEL,
        "messages": [{"role": "user", "content": "review code"}],
        "tools": [{"type": "function", "function": {"name": "inspect"}}],
    }
    orchestrator.proxy_completion(body)
    assert orchestrator._tool_loop_memory["call_3"] == "fallback_agent"

    client.calls.clear()
    client.outcomes["primary_agent"] = _plain_choice("primary-model")
    follow_up = _tool_result_followup(body, "call_3", model="primary-model")

    result = orchestrator.proxy_completion(follow_up)

    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]
    assert "orchestration" not in result


def test_explicit_model_responses_passthrough_records_the_serving_agent() -> None:
    """Explicit-model /v1/responses passthrough remembers a served function_call's
    agent (recording only -- an explicit concrete model is still never reordered
    or given tool-loop evidence)."""
    client = SequencedProxyClient(
        {"primary_agent": _responses_function_call("resp_call_5", "primary-model")}
    )
    orchestrator = _build(client)

    result = orchestrator.proxy_completion(
        {"model": "primary-model", "input": "call the tool"},
        endpoint="responses",
    )

    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]
    assert orchestrator._tool_loop_memory["resp_call_5"] == "primary_agent"
    assert "orchestration" not in result


def test_free_model_follow_up_never_routes_to_a_non_free_emitting_agent() -> None:
    """orchestrator/free never returns to a paid emitting agent, even when remembered."""
    client = SequencedProxyClient(
        {
            "primary_agent": _tool_call_choice("call_4"),
            "fallback_agent": _plain_choice("fallback-model"),
        }
    )
    orchestrator = _build(client)
    orchestrator.agents = [
        replace(agent, tags=(*agent.tags, "cost:free"))
        if agent.id == "fallback_agent"
        else agent
        for agent in orchestrator.agents
    ]
    body = {
        "model": TaskOrchestrator.AUTO_MODEL,
        "messages": [{"role": "user", "content": "review code"}],
        "tools": [{"type": "function", "function": {"name": "inspect"}}],
    }

    orchestrator.proxy_completion(body)
    assert orchestrator._tool_loop_memory["call_4"] == "primary_agent"

    client.calls.clear()
    follow_up = _tool_result_followup(body, "call_4", model=TaskOrchestrator.FREE_MODEL)

    result = orchestrator.proxy_completion(follow_up)

    assert [agent_id for agent_id, _ in client.calls] == ["fallback_agent"]
    assert result["orchestration"]["tool_loop_route"] == "fallback"
    assert result["orchestration"]["tool_loop_agent_id"] == "primary_agent"


def _structured_workflow() -> dict[str, Any]:
    """Return bounded pre-synthesis evidence for _orchestrated_provider_completion tests."""
    return {
        "mode": "conduct",
        "answer": "evidence",
        "trace": [],
        "verification": {},
        "plan_source": "template",
    }


def _retryable_upstream_error(agent: ModelAgent) -> ProviderUpstreamError:
    """Build a retryable structured-synthesis transport failure for one agent."""
    return ProviderUpstreamError(
        agent_id=agent.id,
        model=agent.model,
        error_code="api_error",
        message="synthetic upstream failure",
        client_status=502,
        provider_status=502,
        retryable=True,
        transport="structured_synthesis",
    )


def _responses_function_call(call_id: str, model: str) -> dict[str, Any]:
    """Build a Responses-shaped provider response carrying one function_call."""
    return {
        "model": model,
        "output_text": "calling tool",
        "output": [
            {
                "type": "function_call",
                "call_id": call_id,
                "name": "inspect",
                "arguments": "{}",
            }
        ],
    }


def _responses_plain_output(model: str, text: str) -> dict[str, Any]:
    """Build a Responses-shaped provider response with no tool call."""
    return {"model": model, "output_text": text, "output": []}


def test_orchestrated_responses_function_call_records_the_serving_agent() -> None:
    """A served Responses ``function_call`` remembers call_id -> serving agent."""
    first = ModelAgent("first_agent", "first-model", "mock://first")
    second = ModelAgent("second_agent", "second-model", "mock://second")
    orchestrator = TaskOrchestrator([first, second])

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, Any]):
        if agent.id == first.id:
            raise _retryable_upstream_error(first)
        return _responses_function_call("resp_call_1", second.model)

    with (
        patch.object(orchestrator, "conduct", return_value=_structured_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=first),
        patch.object(orchestrator, "_ranked_agents", return_value=[first, second]),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
    ):
        orchestrator.proxy_completion(
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "input": "call the tool",
                "tools": [{"type": "function", "function": {"name": "inspect"}}],
            },
            endpoint="responses",
            single_agent=False,
        )

    assert orchestrator._tool_loop_memory["resp_call_1"] == "second_agent"


def test_orchestrated_responses_follow_up_routes_to_the_emitting_agent() -> None:
    """A Responses ``function_call_output`` follow-up returns to the emitting agent."""
    first = ModelAgent("first_agent", "first-model", "mock://first")
    second = ModelAgent("second_agent", "second-model", "mock://second")
    orchestrator = TaskOrchestrator([first, second])
    orchestrator._tool_loop_memory["resp_call_2"] = "second_agent"

    calls: list[str] = []

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, Any]):
        calls.append(agent.id)
        return _responses_plain_output(agent.model, "done")

    with (
        patch.object(orchestrator, "conduct", return_value=_structured_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=first),
        patch.object(orchestrator, "_ranked_agents", return_value=[first, second]),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
    ):
        result = orchestrator.proxy_completion(
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "input": [
                    {
                        "type": "function_call",
                        "call_id": "resp_call_2",
                        "name": "inspect",
                        "arguments": "{}",
                    },
                    {
                        "type": "function_call_output",
                        "call_id": "resp_call_2",
                        "output": "42",
                    },
                ],
            },
            endpoint="responses",
            single_agent=False,
        )

    # The top-ranked first_agent is never attempted: the follow-up goes
    # straight to the agent that emitted resp_call_2.
    assert calls == ["second_agent"]
    assert result["orchestration"]["tool_loop_route"] == "emitting_agent"
    assert result["orchestration"]["tool_loop_agent_id"] == "second_agent"


def test_explicit_concrete_model_on_responses_path_ignores_tool_loop_memory() -> None:
    """An explicit concrete model on the Responses surface is never re-ranked."""
    first = ModelAgent("first_agent", "first-model", "mock://first")
    second = ModelAgent("second_agent", "second-model", "mock://second")
    orchestrator = TaskOrchestrator([first, second])
    orchestrator._tool_loop_memory["resp_call_3"] = "second_agent"

    calls: list[str] = []

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, Any]):
        calls.append(agent.id)
        return _responses_plain_output(agent.model, "done")

    with (
        patch.object(orchestrator, "conduct", return_value=_structured_workflow()),
        patch.object(orchestrator.client, "proxy_send", side_effect=send),
    ):
        result = orchestrator.proxy_completion(
            {
                "model": "first-model",
                "input": [
                    {
                        "type": "function_call_output",
                        "call_id": "resp_call_3",
                        "output": "42",
                    },
                ],
            },
            endpoint="responses",
            single_agent=False,
        )

    assert calls == ["first_agent"]
    orchestration = result.get("orchestration") or {}
    assert "tool_loop_route" not in orchestration
    assert "tool_loop_agent_id" not in orchestration


def test_response_format_chat_passthrough_follow_up_routes_to_the_emitting_agent() -> None:
    """response_format-only chat passthrough (the other _orchestrated_provider_completion
    caller) also returns a tool-loop follow-up to the emitting agent."""
    first = ModelAgent("first_agent", "first-model", "mock://first")
    second = ModelAgent("second_agent", "second-model", "mock://second")
    orchestrator = TaskOrchestrator([first, second])
    body = {
        "model": TaskOrchestrator.AUTO_MODEL,
        "messages": [{"role": "user", "content": "classify and maybe call a tool"}],
        "response_format": {"type": "json_object"},
        "tools": [{"type": "function", "function": {"name": "inspect"}}],
    }
    calls: list[str] = []

    def send(agent: ModelAgent, _endpoint: str, _payload: dict[str, Any]):
        calls.append(agent.id)
        if agent.id == first.id:
            raise _retryable_upstream_error(first)
        # Content satisfies the requested json_object contract *and* the
        # message carries a tool call, so this is accepted without a repair
        # round while still exercising tool-loop recording.
        return {
            "model": second.model,
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": '{"status":"pending"}',
                        "tool_calls": [
                            {
                                "id": "chat_call_1",
                                "type": "function",
                                "function": {"name": "inspect", "arguments": "{}"},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }

    with (
        patch.object(orchestrator, "conduct", return_value=_structured_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=first),
        patch.object(orchestrator, "_ranked_agents", return_value=[first, second]),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=send),
    ):
        orchestrator.proxy_completion(body, single_agent=False)

    assert calls == ["first_agent", "second_agent"]
    assert orchestrator._tool_loop_memory["chat_call_1"] == "second_agent"

    calls.clear()
    follow_up = {
        **_tool_result_followup(body, "chat_call_1", model=TaskOrchestrator.AUTO_MODEL),
        "response_format": {"type": "json_object"},
    }

    def follow_up_send(agent: ModelAgent, _endpoint: str, _payload: dict[str, Any]):
        calls.append(agent.id)
        return {
            "model": agent.model,
            "choices": [
                {
                    "message": {"role": "assistant", "content": '{"status":"ok"}'},
                    "finish_reason": "stop",
                }
            ],
        }

    with (
        patch.object(orchestrator, "conduct", return_value=_structured_workflow()),
        patch.object(orchestrator, "_select_agent", return_value=first),
        patch.object(orchestrator, "_ranked_agents", return_value=[first, second]),
        patch.object(orchestrator.client, "proxy_send_once", side_effect=follow_up_send),
    ):
        result = orchestrator.proxy_completion(follow_up, single_agent=False)

    assert calls == ["second_agent"]
    assert result["orchestration"]["tool_loop_route"] == "emitting_agent"
    assert result["orchestration"]["tool_loop_agent_id"] == "second_agent"


def test_tool_loop_memory_evicts_the_oldest_entry_past_its_bound() -> None:
    """The bounded tool_loop_memory map is an LRU, not a growing log."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("solo_agent", "solo-model")],
        client=SequencedProxyClient({}),
        tool_loop_memory_max_entries=1,
    )

    orchestrator._record_tool_loop_agents(
        [{"id": "call_old", "type": "function"}], "agent_x"
    )
    orchestrator._record_tool_loop_agents(
        [{"id": "call_new", "type": "function"}], "agent_y"
    )

    assert dict(orchestrator._tool_loop_memory) == {"call_new": "agent_y"}


def test_route_once_explicit_model_carries_no_tool_loop_evidence() -> None:
    """``route_once`` with a pinned concrete model emits no tool-loop evidence.

    The remembered emitting agent differs from the pinned one, so an unguarded
    call would have produced ``tool_loop_route: "fallback"`` for a request the
    gateway never re-ranked (CodeRabbit review on PR #1177).
    """
    agents = [
        ModelAgent("primary_agent", "primary-model", base_url="mock://primary", priority=10),
        ModelAgent("fallback_agent", "fallback-model", base_url="mock://fallback", priority=5),
    ]
    orchestrator = TaskOrchestrator(agents)
    called: list[str] = []

    def chat(agent: ModelAgent, _messages: list[dict], **_kwargs: object) -> str:
        called.append(agent.id)
        return f"served by {agent.id}"

    orchestrator.client.chat = chat  # type: ignore[method-assign]
    orchestrator._record_tool_loop_agents([{"id": "call_9"}], "fallback_agent")
    messages = [
        {"role": "user", "content": "inspect"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_9", "type": "function", "function": {"name": "inspect", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call_9", "content": "ok"},
    ]

    pinned = orchestrator.route_once(messages, model_name="primary-model")
    assert called == ["primary_agent"]
    assert "tool_loop_route" not in pinned
    assert "tool_loop_agent_id" not in pinned

    called.clear()
    virtual = orchestrator.route_once(messages, model_name=TaskOrchestrator.AUTO_MODEL)
    assert called[0] == "fallback_agent"
    assert virtual["tool_loop_route"] == "emitting_agent"
    assert virtual["tool_loop_agent_id"] == "fallback_agent"

@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (
            400,
            {"error": {"code": "context_length_exceeded", "message": "nope"}},
            True,
        ),
        (
            400,
            {
                "error": {
                    "message": (
                        "This model's maximum context length is 8192 tokens. "
                        "However, you requested 9001 tokens ..."
                    )
                }
            },
            True,
        ),
        (
            400,
            {"error": "context length 8192 exceeded: 9001 tokens requested"},
            True,
        ),
        (
            400,
            {
                "error": {
                    "type": "invalid_request_error",
                    "message": "prompt is too long: 9001 tokens > 8192 maximum",
                }
            },
            True,
        ),
        (
            400,
            {"error": {"type": "invalid_request_error", "message": "missing required field 'model'"}},
            False,
        ),
        (
            500,
            {
                "error": {
                    "code": "context_length_exceeded",
                    "message": "This model's maximum context length is 8192 tokens.",
                }
            },
            False,
        ),
    ],
    ids=[
        "openai_structured_code",
        "maximum_context_length_message",
        "context_length_and_tokens_string_body",
        "anthropic_prompt_too_long",
        "generic_400_unrelated_message",
        "same_message_wrong_status",
    ],
)
def test_is_request_too_large_error_recognizes_context_length_exceeded(
    status: int, body: dict[str, Any], expected: bool
) -> None:
    """Context-window overflow is a request-size rejection like 413, only at status 400."""
    assert _is_request_too_large_error(_http_error(status, body)) is expected


def test_context_length_exceeded_fails_over_without_penalizing_provider_health() -> None:
    """A context-window overflow fails over to the next agent and is health-neutral.

    Mirrors ``test_explicit_grouped_model_413_does_not_degrade_provider_health``:
    consumers (noema, opencode) must not see this as a hard 400, and the
    rejecting agent's stability record must not be debited for a prompt that
    simply did not fit its context window.
    """
    failure = _http_error(
        400,
        {
            "error": {
                "code": "context_length_exceeded",
                "message": (
                    "This model's maximum context length is 8192 tokens. "
                    "However, you requested 9001 tokens ..."
                ),
            }
        },
    )
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": {"model": "fallback-model"},
        }
    )
    orchestrator = _build(client)

    result = orchestrator.proxy_completion(
        {"model": TaskOrchestrator.AUTO_MODEL, "messages": [{"role": "user", "content": "x" * 40000}]}
    )

    assert result["model"] == "fallback-model"
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent", "fallback_agent"]
    assert orchestrator._circuit.get("primary_agent") in (None, {"failures": 0.0, "opened_at": 0.0})


def _context_window_body(char_count: int, *, model: str = "contextual-orchestrator") -> dict[str, Any]:
    """Build a virtual-selector chat body whose prompt is ``char_count`` characters."""
    return {
        "model": model,
        "messages": [{"role": "user", "content": ("ab " * (char_count // 3 + 1))[:char_count]}],
    }


def test_context_window_filter_skips_too_small_known_window_and_serves_next() -> None:
    """A provably-too-small known context window is skipped; the next candidate serves."""
    client = SequencedProxyClient(
        {
            "small_window_agent": {"model": "small-window-model"},
            "unknown_window_agent": {"model": "unknown-window-model"},
        }
    )
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "small_window_agent",
                "small-window-model",
                priority=10,
                provider_name="small",
                context_window=1000,
            ),
            ModelAgent(
                "unknown_window_agent",
                "unknown-window-model",
                priority=1,
                provider_name="unknown",
                context_window=None,
            ),
        ],
        client=client,
    )

    # 8000 chars -> lower-bound estimate of 8000 // 7 == 1142 tokens, provably
    # larger than small_window_agent's 1000-token known window.
    result = orchestrator.proxy_completion(_context_window_body(8000))

    assert result["model"] == "unknown-window-model"
    assert [agent_id for agent_id, _ in client.calls] == ["unknown_window_agent"]
    evidence = result["orchestration"]
    assert evidence["context_window_excluded"] == ["small_window_agent"]
    assert evidence["prompt_token_lower_bound"] >= 1001
    assert evidence["prompt_token_bound_source"] in ("exact", "estimate_lower_bound")


def test_context_window_filter_never_excludes_an_unknown_window() -> None:
    """A candidate with ``context_window=None`` is never excluded, however large the prompt."""
    client = SequencedProxyClient({"unknown_window_agent": {"model": "unknown-window-model"}})
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "unknown_window_agent",
                "unknown-window-model",
                provider_name="unknown",
                context_window=None,
            ),
        ],
        client=client,
    )

    result = orchestrator.proxy_completion(_context_window_body(50_000))

    assert result["model"] == "unknown-window-model"
    assert [agent_id for agent_id, _ in client.calls] == ["unknown_window_agent"]
    # Nothing was excluded, so no orchestration evidence is attached -- the
    # plain passthrough shape is unchanged (mirrors other evidence fields
    # like served_agent_id/failover_from that are only present when notable).
    assert "orchestration" not in result


def test_context_window_filter_raises_request_too_large_when_every_window_is_too_small() -> None:
    """Every known window too small raises the honest 413 request-too-large contract."""
    client = SequencedProxyClient({})
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "first_agent", "first-model", priority=10, provider_name="first", context_window=500,
            ),
            ModelAgent(
                "second_agent", "second-model", priority=1, provider_name="second", context_window=200,
            ),
        ],
        client=client,
    )

    with pytest.raises(ProviderRequestTooLargeError) as caught:
        orchestrator.proxy_completion(_context_window_body(8000))

    message = str(caught.value)
    assert "200" in message  # smallest known window
    assert not client.calls


def test_context_window_filter_does_not_apply_to_an_explicit_model_request() -> None:
    """An explicitly requested concrete model is never pre-filtered by context window."""
    client = SequencedProxyClient({"tiny_window_agent": {"model": "tiny-window-model"}})
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "tiny_window_agent",
                "tiny-window-model",
                provider_name="tiny",
                context_window=1,
            ),
        ],
        client=client,
    )

    # An enormous prompt whose lower bound provably exceeds the 1-token window --
    # if the filter applied here, this would raise ProviderRequestTooLargeError
    # instead of reaching the provider.
    result = orchestrator.proxy_completion(_context_window_body(50_000, model="tiny-window-model"))

    assert result["model"] == "tiny-window-model"
    assert [agent_id for agent_id, _ in client.calls] == ["tiny_window_agent"]
    assert "orchestration" not in result
