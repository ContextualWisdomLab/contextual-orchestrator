"""Behavior tests for deterministic tenant model-group fallback."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from contextual_orchestrator.credentials import InMemoryCredentialBackend, set_backend
from contextual_orchestrator.model_group import ModelGroupExecutor, ModelGroupUnavailable
from contextual_orchestrator.tenant_registry import InMemoryTenantRegistry


@dataclass
class _Outcome:
    value: object
    usage: dict[str, int] | None = None


class _FakeClient:
    def __init__(self, outcomes: dict[str, _Outcome]) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []
        self._usage: dict[str, int] | None = None

    def chat(self, agent, messages, temperature=0.2):
        del messages, temperature
        self.calls.append(agent.id)
        outcome = self.outcomes[agent.id]
        self._usage = outcome.usage
        if isinstance(outcome.value, BaseException):
            raise outcome.value
        return outcome.value

    def take_usage(self):
        usage = self._usage
        self._usage = None
        return usage


def _configured_registry() -> InMemoryTenantRegistry:
    backend = InMemoryCredentialBackend()
    set_backend(backend)
    registry = InMemoryTenantRegistry(credential_backend=backend)
    registry.create_tenant("acme_corporation", "ACME Corporation")

    first_key = registry.register_provider_credential(
        "acme_corporation", "openrouter_provider", "openrouter_primary_key", "secret-one"
    )
    second_key = registry.register_provider_credential(
        "acme_corporation", "nvidia_provider", "nvidia_secondary_key", "secret-two"
    )
    outside_key = registry.register_provider_credential(
        "acme_corporation", "bytez_provider", "bytez_outside_key", "secret-three"
    )

    group = registry.create_model_group("acme_corporation", "general_chat_group")
    first_endpoint = registry.create_model_endpoint(
        "acme_corporation",
        "openrouter_primary_endpoint",
        "openrouter_provider",
        "openrouter-model-id",
        "mock://openrouter",
        first_key.credential_id,
    )
    second_endpoint = registry.create_model_endpoint(
        "acme_corporation",
        "nvidia_secondary_endpoint",
        "nvidia_provider",
        "nvidia-model-id",
        "mock://nvidia",
        second_key.credential_id,
    )
    registry.create_model_endpoint(
        "acme_corporation",
        "bytez_outside_endpoint",
        "bytez_provider",
        "bytez-model-id",
        "mock://bytez",
        outside_key.credential_id,
    )
    registry.add_group_membership(
        "acme_corporation", group.group_id, first_endpoint.endpoint_id, fallback_order=10
    )
    registry.add_group_membership(
        "acme_corporation", group.group_id, second_endpoint.endpoint_id, fallback_order=20
    )
    return registry


def teardown_function() -> None:
    """Reset the process credential backend after each test."""
    set_backend(None)


def test_first_failure_falls_back_to_second_complete_response() -> None:
    registry = _configured_registry()
    client = _FakeClient(
        {
            "openrouter_primary_endpoint": _Outcome(TimeoutError("provider timeout")),
            "nvidia_secondary_endpoint": _Outcome(
                "verified response", {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
            ),
            "bytez_outside_endpoint": _Outcome("must not run"),
        }
    )

    result = ModelGroupExecutor(registry, client).complete(
        "acme_corporation",
        "general_chat_group",
        [{"role": "user", "content": "hello"}],
    )

    assert result.content == "verified response"
    assert result.served_endpoint_name == "nvidia_secondary_endpoint"
    assert result.served_model == "nvidia-model-id"
    assert result.usage == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    assert client.calls == ["openrouter_primary_endpoint", "nvidia_secondary_endpoint"]
    assert [attempt.outcome for attempt in result.attempts] == ["failed", "succeeded"]
    assert "provider timeout" not in repr(result.attempts)
    assert "bytez_outside_endpoint" not in client.calls


def test_empty_or_non_string_completion_is_not_a_winner() -> None:
    registry = _configured_registry()
    for invalid in ("", "   ", None, {"content": "not a string"}):
        client = _FakeClient(
            {
                "openrouter_primary_endpoint": _Outcome(invalid),
                "nvidia_secondary_endpoint": _Outcome("second endpoint wins"),
                "bytez_outside_endpoint": _Outcome("must not run"),
            }
        )
        result = ModelGroupExecutor(registry, client).complete(
            "acme_corporation",
            "general_chat_group",
            [{"role": "user", "content": "hello"}],
        )
        assert result.content == "second endpoint wins"
        assert [attempt.error_code for attempt in result.attempts] == [
            "invalid_completion",
            None,
        ]


def test_all_failed_error_is_stable_and_secret_free() -> None:
    registry = _configured_registry()
    client = _FakeClient(
        {
            "openrouter_primary_endpoint": _Outcome(RuntimeError("secret-one leaked here")),
            "nvidia_secondary_endpoint": _Outcome(RuntimeError("secret-two leaked here")),
            "bytez_outside_endpoint": _Outcome("must not run"),
        }
    )

    with pytest.raises(ModelGroupUnavailable) as captured:
        ModelGroupExecutor(registry, client).complete(
            "acme_corporation",
            "general_chat_group",
            [{"role": "user", "content": "hello"}],
        )

    error = captured.value
    assert str(error) == "model group is unavailable"
    assert [attempt.endpoint_name for attempt in error.attempts] == [
        "openrouter_primary_endpoint",
        "nvidia_secondary_endpoint",
    ]
    assert all(attempt.error_code == "provider_failed" for attempt in error.attempts)
    assert "secret-one" not in repr(error.attempts)
    assert "secret-two" not in repr(error.attempts)
    assert client.calls == ["openrouter_primary_endpoint", "nvidia_secondary_endpoint"]
