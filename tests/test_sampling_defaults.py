"""Sampling defaults must not disable providers with narrower capabilities."""

from __future__ import annotations

from unittest.mock import patch

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.orchestrator import ModelClient, _FastMLSIJudgeAdapter


def _remote_agent() -> ModelAgent:
    return ModelAgent(
        "reasoning_agent",
        "reasoning-model",
        base_url="https://provider.example/v1",
        credential_key="TEST_PROVIDER_API_KEY",
    )


def test_chat_omits_temperature_when_caller_does_not_provide_one() -> None:
    client = ModelClient()
    captured: list[dict] = []

    def send(_agent, payload, _destination):
        captured.append(payload)
        return "answer"

    with (
        patch.object(client, "_validate_provider", return_value=object()),
        patch("contextual_orchestrator.orchestrator._provider_credential", return_value="secret"),
        patch.object(client, "_send_with_retry", side_effect=send),
    ):
        assert client.chat(_remote_agent(), [{"role": "user", "content": "hello"}]) == "answer"

    assert "temperature" not in captured[0]


def test_chat_forwards_an_explicit_temperature() -> None:
    client = ModelClient()
    captured: list[dict] = []

    def send(_agent, payload, _destination):
        captured.append(payload)
        return "answer"

    with (
        patch.object(client, "_validate_provider", return_value=object()),
        patch("contextual_orchestrator.orchestrator._provider_credential", return_value="secret"),
        patch.object(client, "_send_with_retry", side_effect=send),
    ):
        client.chat(
            _remote_agent(),
            [{"role": "user", "content": "hello"}],
            temperature=0.2,
        )

    assert captured[0]["temperature"] == 0.2


def test_chat_uses_request_scoped_temperature_before_constructor_value() -> None:
    client = ModelClient(temperature=0.4)
    captured: list[dict] = []

    def send(_agent, payload, _destination):
        captured.append(payload)
        return "answer"

    with (
        patch.object(client, "_validate_provider", return_value=object()),
        patch("contextual_orchestrator.orchestrator._provider_credential", return_value="secret"),
        patch.object(client, "_send_with_retry", side_effect=send),
    ):
        client.chat(
            _remote_agent(),
            [{"role": "user", "content": "hello"}],
            temperature=0.3,
        )

    assert captured[0]["temperature"] == 0.3


def test_chat_uses_constructor_temperature_when_request_scope_is_unset() -> None:
    client = ModelClient(temperature=0.4)
    captured: list[dict] = []

    def send(_agent, payload, _destination):
        captured.append(payload)
        return "answer"

    with (
        patch.object(client, "_validate_provider", return_value=object()),
        patch("contextual_orchestrator.orchestrator._provider_credential", return_value="secret"),
        patch.object(client, "_send_with_retry", side_effect=send),
    ):
        client.chat(_remote_agent(), [{"role": "user", "content": "hello"}])

    assert captured[0]["temperature"] == 0.4


def test_stream_chat_uses_request_temperature_before_constructor_value() -> None:
    """Forward a request-scoped temperature on streamed route completions."""
    client = ModelClient(temperature=0.4)
    captured: list[dict] = []

    def stream_send(_agent, payload, _destination):
        captured.append(payload)
        yield "answer"

    with (
        patch.object(client, "_validate_provider", return_value=object()),
        patch.object(client, "_stream_send", side_effect=stream_send),
    ):
        with client.request_options(
            max_output_tokens=64,
            top_p=0.9,
            presence_penalty=0.1,
            frequency_penalty=0.2,
        ):
            assert list(
                client.stream_chat(
                    _remote_agent(),
                    [{"role": "user", "content": "hello"}],
                    temperature=0.3,
                )
            ) == ["answer"]

    assert captured[0]["temperature"] == 0.3
    assert captured[0]["max_tokens"] == 64
    assert captured[0]["top_p"] == 0.9
    assert captured[0]["presence_penalty"] == 0.1
    assert captured[0]["frequency_penalty"] == 0.2


def test_nested_request_options_restore_thread_local_values() -> None:
    """Nested request scopes restore the outer value and then the client default."""
    client = ModelClient()

    with client.request_options(temperature=0.4):
        assert client._effective_temperature() == 0.4
        with client.request_options(max_output_tokens=73, temperature=0.2):
            assert client._effective_max_output_tokens() == 73
            assert client._effective_temperature() == 0.2
        assert client._effective_temperature() == 0.4

    assert client._effective_max_output_tokens() == client.max_output_tokens
    assert client._effective_temperature() is None


def test_structured_completion_omits_an_unset_temperature() -> None:
    """Do not turn an omitted structured sampling value into JSON null."""
    orchestrator = TaskOrchestrator([_remote_agent()], client=ModelClient())
    adapter = _FastMLSIJudgeAdapter(
        orchestrator=orchestrator,
        text="judge this answer",
        judge="reasoning_agent",
    )
    captured: list[dict] = []

    def proxy(payload):
        captured.append(payload)
        return {
            "choices": [{"message": {"content": '{"decision":"ACCEPT","reason":"ok"}'}}]
        }

    with (
        orchestrator.client.request_options(max_output_tokens=73),
        patch.object(orchestrator, "proxy_completion", side_effect=proxy),
    ):
        result = adapter.complete_structured(
            [{"role": "user", "content": "judge"}],
            response_format={"type": "json_object"},
        )

    assert result["answer"].startswith("{")
    assert captured[0]["max_tokens"] == 73
    assert "temperature" not in captured[0]


def test_structured_completion_forwards_an_explicit_client_temperature() -> None:
    """Preserve an explicitly configured sampling value for structured output."""
    orchestrator = TaskOrchestrator(
        [_remote_agent()],
        client=ModelClient(temperature=0.3),
    )
    adapter = _FastMLSIJudgeAdapter(
        orchestrator=orchestrator,
        text="judge this answer",
        judge="reasoning_agent",
    )
    captured: list[dict] = []

    def proxy(payload):
        captured.append(payload)
        return {
            "choices": [{"message": {"content": '{"decision":"ACCEPT","reason":"ok"}'}}]
        }

    with patch.object(orchestrator, "proxy_completion", side_effect=proxy):
        adapter.complete_structured(
            [{"role": "user", "content": "judge"}],
            response_format={"type": "json_object"},
        )

    assert captured[0]["temperature"] == 0.3
