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
