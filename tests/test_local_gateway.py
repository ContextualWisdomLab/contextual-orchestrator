"""Provider-neutral loopback gateway transport without weakening egress rules."""

from __future__ import annotations

import json
import socket
import sys
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator, load_agents  # noqa: E402
from contextual_orchestrator.credentials import NotConfigured  # noqa: E402
from contextual_orchestrator.orchestrator import (  # noqa: E402
    ModelClient,
    _chat_to_responses_payload,
    _is_local_provider_url,
    _responses_to_chat_payload,
    _responses_usage,
)


@pytest.fixture(autouse=True)
def _local_gateway_credentials():
    with patch("contextual_orchestrator.orchestrator.get_credential", return_value="local-secret"):
        yield


def test_local_candidate_registry_keeps_all_discovered_entries() -> None:
    agents = load_agents(str(Path(__file__).resolve().parents[1] / "examples/agents.local.json"))
    orchestrator = TaskOrchestrator(agents)

    assert {agent.model for agent in orchestrator.candidates} >= {
        "contextual-orchestrator",
        "gemma-4-e4b-it",
        "embeddinggemma",
    }
    assert all(not agent.disabled for agent in orchestrator.candidates)
    assert len(orchestrator.candidates) == len(orchestrator.agents)
    assert all(not agent.base_url.startswith("mlx://") for agent in orchestrator.candidates)
    assert any(
        agent.model == "contextual-orchestrator"
        and set(agent.provider_exclusions) == {"thinker", "worker", "verifier", "synthesizer"}
        for agent in orchestrator.candidates
    )


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        import json

        return json.dumps(self.payload).encode("utf-8")


def test_local_gateway_requires_explicit_authentication() -> None:
    with pytest.raises(ValueError, match="local_credential_key"):
        ModelAgent("local_agent", "local-model", base_url="local://127.0.0.1:8080/v1")


def test_authenticated_local_gateway_uses_only_its_explicit_kv_credential() -> None:
    agent = ModelAgent(
        "gateway_agent",
        "local-model",
        base_url="local://127.0.0.1:8080/v1",
        credential_key="OPENAI_API_KEY",
        local_credential_key="LOCAL_GATEWAY_TOKEN",
    )
    client = ModelClient(
        max_retries=0,
        temperature=0.0,
    )
    seen = []

    def open_provider(request, _destination=None):
        seen.append(request)
        return _Response({"choices": [{"message": {"content": "gateway-ok"}}]})

    def credential(name: str) -> str | None:
        return {"LOCAL_GATEWAY_TOKEN": "gateway-secret"}.get(name)

    with patch("contextual_orchestrator.orchestrator.get_credential", side_effect=credential), patch.object(
        client, "_open_provider", side_effect=open_provider
    ):
        assert client.chat(agent, [{"role": "user", "content": "ping"}]) == "gateway-ok"

    assert seen[0].full_url == "http://127.0.0.1:8080/v1/chat/completions"
    assert seen[0].get_header("Authorization") == "Bearer gateway-secret"
    assert "chat_template_kwargs" not in json.loads(seen[0].data)


def test_authenticated_local_gateway_requires_its_kv_credential() -> None:
    agent = ModelAgent(
        "gateway_agent",
        "local-model",
        base_url="local://127.0.0.1:8080/v1",
        local_credential_key="LOCAL_GATEWAY_TOKEN",
    )
    with patch("contextual_orchestrator.orchestrator.get_credential", return_value=None):
        with pytest.raises(NotConfigured, match="LOCAL_GATEWAY_TOKEN"):
            ModelClient(max_retries=0).chat(agent, [{"role": "user", "content": "ping"}])


def test_direct_mlx_provider_scheme_is_rejected() -> None:
    with pytest.raises(ValueError, match="direct mlx:// provider URLs are unsupported"):
        ModelAgent("local_agent", "local-model", base_url="mlx://127.0.0.1:8080/v1")


def test_provider_probe_verifies_registry_then_uses_one_bounded_completion_without_retry() -> None:
    agent = ModelAgent("local_agent", "local-model", base_url="local://127.0.0.1:8080/v1", local_credential_key="LOCAL_GATEWAY_TOKEN")
    client = ModelClient(max_retries=2, local_max_retries=2)
    seen: list[tuple[object, float | None]] = []

    def open_provider(request, _destination=None, *, timeout=None):
        seen.append((request, timeout))
        if request.get_method() == "GET":
            return _Response({"object": "list", "data": [{"id": "local-model"}]})
        return _Response({
            "choices": [{"message": {"content": "OK"}}],
            "usage": {"prompt_tokens": 6, "completion_tokens": 1, "total_tokens": 7},
        })

    with patch.object(client, "_open_provider", side_effect=open_provider):
        report = client.probe(agent, timeout=1.25)

    assert report["status"] == "ready"
    assert report["usage"]["total_tokens"] == 7
    assert len(seen) == 2
    assert seen[0][0].get_method() == "GET"
    assert seen[0][0].full_url == "http://127.0.0.1:8080/v1/models"
    assert seen[1][0].get_method() == "POST"
    assert seen[1][1] == 1.25
    import json

    payload = json.loads(seen[1][0].data)
    assert payload["max_tokens"] == 1
    assert "temperature" not in payload


def test_provider_probe_rejects_a_local_model_registry_mismatch() -> None:
    agent = ModelAgent("local_agent", "requested-model", base_url="local://127.0.0.1:8080/v1", local_credential_key="LOCAL_GATEWAY_TOKEN")
    client = ModelClient(max_retries=0)
    with patch.object(
        client,
        "_open_provider",
        return_value=_Response({"object": "list", "data": [{"id": "other-model"}]}),
    ) as open_provider:
        report = client.probe(agent, timeout=0.5)

    assert report["status"] == "not_ready"
    assert report["error_type"] == "RuntimeError"
    assert report["failure_code"] == "provider_model_not_registered"
    assert "error" not in report
    assert open_provider.call_count == 1


def test_provider_probe_reports_timeout_without_retry() -> None:
    agent = ModelAgent("local_agent", "local-model", base_url="local://127.0.0.1:8080/v1", local_credential_key="LOCAL_GATEWAY_TOKEN")
    client = ModelClient(max_retries=2, local_max_retries=2)
    with patch.object(client, "_open_provider", side_effect=TimeoutError("probe timeout")) as open_provider:
        report = client.probe(agent, timeout=0.5)

    assert report["status"] == "not_ready"
    assert report["error_type"] == "TimeoutError"
    assert report["failure_code"] == "provider_probe_failed"
    assert "error" not in report
    assert open_provider.call_count == 1


def test_provider_probe_does_not_serialize_provider_exception_text() -> None:
    agent = ModelAgent("local_agent", "local-model", base_url="local://127.0.0.1:8080/v1", local_credential_key="LOCAL_GATEWAY_TOKEN")
    client = ModelClient(max_retries=0)
    with patch.object(client, "_open_provider", side_effect=RuntimeError("provider-output-secret")):
        report = client.probe(agent, timeout=0.5)

    serialized = json.dumps(report)
    assert "provider-output-secret" not in serialized
    assert report["error_type"] == "RuntimeError"
    assert report["failure_code"] == "provider_probe_failed"


def test_provider_readiness_report_keeps_liveness_unprobed_until_refresh() -> None:
    client = ModelClient()
    orchestrator = TaskOrchestrator([
        ModelAgent("ready_agent", "ready-model"),
        ModelAgent("disabled_agent", "disabled-model", disabled=True),
    ], client=client)
    with patch.object(client, "probe", return_value={"status": "ready", "agent_id": "ready_agent", "model": "ready-model"}) as probe:
        unprobed = orchestrator.provider_readiness_report()
        refreshed = orchestrator.provider_readiness_report(refresh=True, timeout=2.0)

    assert unprobed["status"] == "unprobed"
    assert unprobed["items"][0]["status"] == "unprobed"
    assert refreshed["status"] == "ready"
    assert refreshed["ready_agent_count"] == 1
    assert refreshed["items"][1]["status"] == "disabled"
    probe.assert_called_once_with(orchestrator.agents[0], timeout=2.0)


def test_provider_readiness_refresh_serializes_concurrent_probes() -> None:
    import threading

    client = ModelClient()
    orchestrator = TaskOrchestrator([ModelAgent("ready_agent", "ready-model")], client=client)
    entered = threading.Event()
    release = threading.Event()
    counters = {"active": 0, "max_active": 0}
    counter_lock = threading.Lock()

    def probe(_agent, *, timeout):
        del timeout
        with counter_lock:
            counters["active"] += 1
            counters["max_active"] = max(counters["max_active"], counters["active"])
        entered.set()
        release.wait(timeout=2)
        with counter_lock:
            counters["active"] -= 1
        return {"status": "ready", "agent_id": "ready_agent", "model": "ready-model"}

    with patch.object(client, "probe", side_effect=probe):
        first = threading.Thread(target=lambda: orchestrator.provider_readiness_report(refresh=True))
        second = threading.Thread(target=lambda: orchestrator.provider_readiness_report(refresh=True))
        first.start()
        assert entered.wait(timeout=2)
        second.start()
        release.set()
        first.join(timeout=2)
        second.join(timeout=2)

    assert counters["max_active"] == 1


def test_local_provider_serializes_model_switches_and_bounds_waiters() -> None:
    import threading

    first_agent = ModelAgent("first_agent", "model-a", base_url="local://127.0.0.1:8080/v1", local_credential_key="LOCAL_GATEWAY_TOKEN")
    second_agent = ModelAgent("second_agent", "model-b", base_url="local://127.0.0.1:8080/v1", local_credential_key="LOCAL_GATEWAY_TOKEN")
    first_client = ModelClient(max_retries=0, timeout=1.0)
    second_client = ModelClient(max_retries=0, timeout=0.05)
    entered = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []
    active = 0
    max_active = 0
    counter_lock = threading.Lock()

    def slow_open(_request, _destination=None):
        nonlocal active, max_active
        with counter_lock:
            active += 1
            max_active = max(max_active, active)
        entered.set()
        release.wait(timeout=2)
        with counter_lock:
            active -= 1
        return _Response({"choices": [{"message": {"content": "OK"}}]})

    def call(client, agent):
        try:
            client.chat(agent, [{"role": "user", "content": "ping"}])
        except BaseException as exc:  # noqa: BLE001 - thread result is asserted below
            errors.append(exc)

    with patch.object(first_client, "_open_provider", side_effect=slow_open), patch.object(
        second_client, "_open_provider", side_effect=slow_open
    ):
        first = threading.Thread(target=call, args=(first_client, first_agent))
        second = threading.Thread(target=call, args=(second_client, second_agent))
        first.start()
        assert entered.wait(timeout=1)
        second.start()
        second.join(timeout=1)
        release.set()
        first.join(timeout=1)

    assert not first.is_alive()
    assert not second.is_alive()
    assert max_active == 1
    assert len(errors) == 1
    assert isinstance(errors[0], TimeoutError)


def test_reasoning_only_response_explains_missing_content() -> None:
    agent = ModelAgent("local_agent", "local-model", base_url="local://127.0.0.1:8080/v1", local_credential_key="LOCAL_GATEWAY_TOKEN")
    client = ModelClient(max_retries=0)
    with patch.object(
        client,
        "_open_provider",
        return_value=_Response({"choices": [{"message": {"reasoning": "still thinking"}}]}),
    ):
        try:
            client.chat(agent, [{"role": "user", "content": "ping"}])
        except RuntimeError as exc:
            assert "assistant content" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("reasoning-only provider response must fail clearly")


def test_response_without_content_or_reasoning_fails_clearly() -> None:
    agent = ModelAgent("local_agent", "local-model", base_url="local://127.0.0.1:8080/v1", local_credential_key="LOCAL_GATEWAY_TOKEN")
    with pytest.raises(RuntimeError, match="assistant content"):
        ModelClient()._response_content(agent, {"choices": [{"message": {}}]})


def test_local_responses_passthrough_adapts_to_chat_transport() -> None:
    agent = ModelAgent("local_agent", "local-model", base_url="local://127.0.0.1:8080/v1", local_credential_key="LOCAL_GATEWAY_TOKEN")
    client = ModelClient(max_retries=0)
    with patch.object(client, "_validate_provider", return_value=None), patch.object(
        client,
        "_send_raw_with_retry",
        return_value={
            "id": "chatcmpl-local",
            "model": "local-model",
            "created": 123,
            "choices": [{
                "message": {"role": "assistant", "content": "OK"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        },
    ) as send:
        response = client.proxy_send(
            agent,
            "responses",
            {
                "model": "local-model",
                "instructions": "Be concise.",
                "input": [{
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "ping"}],
                }],
                "stream": True,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "result_shape",
                        "schema": {"type": "object"},
                    }
                },
                "tools": [{
                    "type": "function",
                    "name": "lookup",
                    "parameters": {"type": "object"},
                }],
            },
        )
    assert response["object"] == "response"
    assert response["output_text"] == "OK"
    forwarded = send.call_args.args[2]
    assert forwarded["messages"] == [
        {"role": "system", "content": "Be concise."},
        {"role": "user", "content": "ping"},
    ]
    assert forwarded["tools"] == [{
        "type": "function",
        "function": {"name": "lookup", "parameters": {"type": "object"}},
    }]
    assert forwarded["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "result_shape",
            "schema": {"type": "object"},
        },
    }


def test_local_responses_passthrough_has_no_provider_specific_fields() -> None:
    agent = ModelAgent("local_agent", "local-model", base_url="local://127.0.0.1:8080/v1", local_credential_key="LOCAL_GATEWAY_TOKEN")
    client = ModelClient()
    with patch.object(client, "_validate_provider", return_value=None), patch.object(
        client,
        "_send_raw_with_retry",
        return_value={"choices": [{"message": {"content": "OK"}}]},
    ) as send:
        client.proxy_send(agent, "responses", {"input": "ping"})

    assert "chat_template_kwargs" not in send.call_args.args[2]


def test_local_chat_passthrough_applies_bounded_controls_for_final_synthesis() -> None:
    agent = ModelAgent(
        "local_agent",
        "local-model",
        base_url="local://127.0.0.1:8080/v1",
        local_credential_key="LOCAL_GATEWAY_TOKEN",
    )
    client = ModelClient(max_output_tokens=321)
    with patch.object(client, "_validate_provider", return_value=None), patch.object(
        client,
        "_send_raw_with_retry",
        return_value={"choices": [{"message": {"content": "OK"}}]},
    ) as send:
        client.proxy_send(
            agent,
            "chat/completions",
            {
                "model": "local-model",
                "messages": [{"role": "user", "content": "final synthesis"}],
                "response_format": {"type": "json_object"},
            },
        )

    forwarded = send.call_args.args[2]
    assert forwarded["max_tokens"] == 321
    assert "chat_template_kwargs" not in forwarded


def test_local_chat_passthrough_preserves_explicit_max_tokens() -> None:
    agent = ModelAgent(
        "local_agent",
        "local-model",
        base_url="local://127.0.0.1:8080/v1",
        local_credential_key="LOCAL_GATEWAY_TOKEN",
    )
    client = ModelClient(max_output_tokens=321)
    with patch.object(client, "_validate_provider", return_value=None), patch.object(
        client,
        "_send_raw_with_retry",
        return_value={"choices": [{"message": {"content": "OK"}}]},
    ) as send:
        client.proxy_send(
            agent,
            "chat/completions",
            {
                "model": "local-model",
                "messages": [{"role": "user", "content": "final synthesis"}],
                "max_tokens": 64,
            },
        )

    assert send.call_args.args[2]["max_tokens"] == 64


def test_local_responses_adapter_preserves_supported_items_and_controls() -> None:
    payload = _responses_to_chat_payload(
        {
            "model": "local-model",
            "instructions": [
                {"type": "input_text", "text": "system"},
                {"type": "ignored", "text": 17},
                " rules",
            ],
            "input": [
                "plain input",
                {"type": "message", "role": "developer", "content": "developer note"},
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "prior answer"}],
                },
                {"type": "message", "role": "user", "content": []},
                {
                    "type": "function_call_output",
                    "call_id": "call_1",
                    "output": [{"type": "output_text", "text": "tool result"}],
                },
                {
                    "type": "function_call",
                    "call_id": "call_2",
                    "name": "lookup",
                    "arguments": '{"q":"x"}',
                },
                {"type": "reasoning", "id": "reasoning_1"},
                {"type": "item_reference", "id": "item_1"},
            ],
            "max_output_tokens": 99,
            "temperature": 0.1,
            "tools": [
                {"type": "file_search"},
                {"type": "function", "name": "lookup", "parameters": {"type": "object"}},
            ],
            "tool_choice": {"type": "function", "name": "lookup", "extra": "ignored"},
        }
    )

    assert payload["messages"] == [
        {"role": "system", "content": "system rules"},
        {"role": "user", "content": "plain input"},
        {"role": "system", "content": "developer note"},
        {"role": "assistant", "content": "prior answer"},
        {"role": "tool", "tool_call_id": "call_1", "content": "tool result"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_2",
                "type": "function",
                "function": {"name": "lookup", "arguments": '{"q":"x"}'},
            }],
        },
    ]
    assert payload["max_tokens"] == 99
    assert payload["temperature"] == 0.1
    assert payload["tools"] == [{
        "type": "function",
        "function": {"name": "lookup", "parameters": {"type": "object"}},
    }]
    assert payload["tool_choice"] == {"type": "function", "function": {"name": "lookup"}}


def test_local_responses_adapter_preserves_json_schema_contract() -> None:
    payload = _responses_to_chat_payload(
        {
            "model": "local-model",
            "input": "extract the region",
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "region_result",
                    "description": "A bounded region result",
                    "schema": {"type": "object", "properties": {"label": {"type": "string"}}},
                    "strict": True,
                }
            },
        }
    )

    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "region_result",
            "description": "A bounded region result",
            "schema": {"type": "object", "properties": {"label": {"type": "string"}}},
            "strict": True,
        },
    }


def test_local_responses_adapter_prefers_translated_text_format_contract() -> None:
    payload = _responses_to_chat_payload(
        {
            "input": "prefer the Responses contract",
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "responses_shape",
                    "schema": {"type": "object"},
                }
            },
            "response_format": {"type": "json_object"},
        }
    )

    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "responses_shape",
            "schema": {"type": "object"},
        },
    }


def test_responses_usage_normalizes_chat_aliases() -> None:
    assert _responses_usage(
        {"prompt_tokens": 4, "completion_tokens": 5, "total_tokens": 9}
    ) == {"input_tokens": 4, "output_tokens": 5, "total_tokens": 9}


def test_local_responses_adapter_preserves_bounded_metadata_for_provider() -> None:
    payload = _responses_to_chat_payload(
        {
            "input": "use the supplied context",
            "metadata": {"pu": "PU_TEST", "corp_code": "CORP_TEST", "author_id": "AUTHOR_TEST"},
        }
    )

    assert payload["metadata"] == {
        "pu": "PU_TEST",
        "corp_code": "CORP_TEST",
        "author_id": "AUTHOR_TEST",
    }


def test_local_responses_adapter_rejects_non_string_input() -> None:
    with pytest.raises(ValueError, match="string or item list"):
        _responses_to_chat_payload({"input": {"unexpected": "mapping"}})


@pytest.mark.parametrize(
    "item",
    [
        17,
        {"type": "message", "role": "moderator", "content": "unsupported role"},
        {"type": "unknown"},
    ],
)
def test_local_responses_adapter_rejects_unsupported_items(item: object) -> None:
    with pytest.raises(ValueError):
        _responses_to_chat_payload({"input": [item]})


def test_local_responses_adapter_accepts_string_input() -> None:
    payload = _responses_to_chat_payload({"input": "plain text"})
    assert payload["messages"] == [{"role": "user", "content": "plain text"}]


def test_local_responses_response_maps_reasoning_and_tool_calls() -> None:
    response = _chat_to_responses_payload(
        {
            "id": "chatcmpl-1",
            "model": "local-model",
            "created": 123,
            "choices": [{
                "message": {
                    "reasoning": "internal reasoning",
                    "tool_calls": [
                        "malformed",
                        {"id": "call_1", "function": {"name": "lookup", "arguments": "{}"}},
                    ],
                },
                "finish_reason": "length",
            }],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        },
        {"model": "local-model", "metadata": {"trace": "test"}},
    )

    assert response["status"] == "incomplete"
    assert response["output_text"] == "internal reasoning"
    assert response["usage"] == {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5}
    assert response["metadata"] == {"trace": "test"}
    assert response["output"][-1] == {
        "id": "fc_call_1",
        "type": "function_call",
        "status": "completed",
        "call_id": "call_1",
        "name": "lookup",
        "arguments": "{}",
    }

    tool_only = _chat_to_responses_payload(
        {"choices": [{"message": {"content": "", "tool_calls": [{"id": "call_2", "function": {}}]}}]},
        {},
    )
    assert tool_only["output"][0]["type"] == "function_call"


def test_local_provider_scheme_validation_rejects_remote_and_malformed_ports() -> None:
    assert _is_local_provider_url("local://127.0.0.1:8080/v1")
    assert not _is_local_provider_url("mlx://example.com:8080/v1")
    assert not _is_local_provider_url("mlx://127.0.0.1:8080/v1")
    assert not _is_local_provider_url("local://127.0.0.1:not-a-port/v1")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_retries": -1},
        {"max_retries": True},
        {"local_max_retries": -1},
        {"local_max_retries": True},
        {"local_concurrency": 0},
        {"local_concurrency": False},
        {"local_concurrency": 1.5},
        {"local_concurrency": 65},
    ],
)
def test_local_transport_limits_reject_invalid_values(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ModelClient(**kwargs)


def test_provider_transport_rejects_invalid_port_and_resolution_failures() -> None:
    client = ModelClient()
    with pytest.raises(RuntimeError, match="invalid port"):
        client._open_provider(urllib.request.Request("http://127.0.0.1:not-a-port/v1"))

    with patch("contextual_orchestrator.orchestrator.socket.getaddrinfo", side_effect=socket.gaierror):
        with pytest.raises(RuntimeError, match="could not be resolved"):
            client._resolve_addresses("unresolvable.example", 443)
    with patch("contextual_orchestrator.orchestrator.socket.getaddrinfo", return_value=[]):
        with pytest.raises(RuntimeError, match="no stream address"):
            client._resolve_addresses("empty.example", 443)


@pytest.mark.parametrize(
    "userinfo_url",
    [
        "https://@provider.example/v1/chat/completions",
        "https://:secret@provider.example/v1/chat/completions",
    ],
)
def test_provider_transport_rejects_empty_userinfo(userinfo_url: str) -> None:
    """The low-level transport must reject empty userinfo before opening a socket."""
    with pytest.raises(RuntimeError, match="without userinfo"):
        ModelClient()._open_provider(urllib.request.Request(userinfo_url))


def test_https_provider_uses_verifying_connection_and_resolved_destination() -> None:
    class FakeResponse:
        status = 200

    class FakeConnection:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.request_args = None

        def request(self, *args, **kwargs):
            self.request_args = (args, kwargs)

        def getresponse(self):
            return FakeResponse()

        def close(self):
            return None

    client = ModelClient()
    connection = FakeConnection()
    request = urllib.request.Request("https://provider.example/v1/chat/completions", method="POST")
    with patch(
        "contextual_orchestrator.orchestrator.http.client.HTTPSConnection",
        return_value=connection,
    ) as https_connection:
        response = client._open_provider(
            request,
            (socket.AF_INET, ("127.0.0.1", 443)),
        )

    assert response.status == 200
    https_connection.assert_called_once_with(
        "provider.example", 443, timeout=client.timeout, context=client._ssl_context
    )
    assert connection.request_args[0][0] == "POST"


def test_validated_connect_binds_source_address() -> None:
    class FakeSocket:
        def __init__(self):
            self.bound = None
            self.connected = None
            self.timeout = None
            self.closed = False

        def settimeout(self, value):
            self.timeout = value

        def bind(self, address):
            self.bound = address

        def connect(self, address):
            self.connected = address

        def close(self):
            self.closed = True

    fake = FakeSocket()
    with patch("contextual_orchestrator.orchestrator.socket.socket", return_value=fake) as socket_factory:
        result = ModelClient._connect_validated(
            (socket.AF_INET, ("127.0.0.1", 443)),
            2.0,
            ("127.0.0.1", 0),
        )

    assert result is fake
    socket_factory.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
    assert fake.timeout == 2.0
    assert fake.bound == ("127.0.0.1", 0)
    assert fake.connected == ("127.0.0.1", 443)


def test_local_provider_url_rejects_query_data_at_transport_boundary() -> None:
    agent = ModelAgent("local_agent", "local-model", base_url="local://127.0.0.1:8080/v1?unsafe=1", local_credential_key="LOCAL_GATEWAY_TOKEN")
    with pytest.raises(RuntimeError, match="query data"):
        ModelClient()._provider_url(agent, "/chat/completions")
    with pytest.raises(RuntimeError, match="query data"):
        ModelClient()._validate_provider(agent)


def test_provider_url_rejects_non_http_scheme_at_builder_boundary() -> None:
    agent = ModelAgent("bad_agent", "bad-model", base_url="file:///tmp/provider")
    with pytest.raises(RuntimeError, match=r"http\(s\) provider URL"):
        ModelClient()._provider_url(agent, "/chat/completions")


def test_provider_validation_rejects_non_loopback_and_remote_query_data() -> None:
    client = ModelClient()
    local = ModelAgent("local_agent", "local-model", base_url="local://127.0.0.1:8080/v1", local_credential_key="LOCAL_GATEWAY_TOKEN")
    with patch.object(client, "_resolve_addresses", return_value=[(socket.AF_INET, ("192.0.2.1", 8080))]):
        with pytest.raises(RuntimeError, match="non-loopback"):
            client._validate_provider(local)

    remote_query = ModelAgent(
        "remote_agent",
        "remote-model",
        base_url="https://provider.example/v1?unsafe=1",
        credential_key="remote-key",
    )
    remote = ModelAgent(
        "remote_agent",
        "remote-model",
        base_url="https://provider.example/v1",
        credential_key="remote-key",
    )
    with patch("contextual_orchestrator.orchestrator.get_credential", return_value="secret"):
        with pytest.raises(RuntimeError, match="query data"):
            client._validate_provider(remote_query)
        with patch.object(
            client,
            "_resolve_addresses",
            return_value=[(socket.AF_INET, ("93.184.216.34", 443))],
        ):
            assert client._validate_provider(remote) == (socket.AF_INET, ("93.184.216.34", 443))


def test_remote_transport_uses_kv_credential_for_chat_and_stream() -> None:
    agent = ModelAgent(
        "remote_agent",
        "remote-model",
        base_url="https://provider.example/v1",
        credential_key="remote-key",
    )

    class StreamingResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            return iter([b'data: {"choices":[{"delta":{"content":"delta"}}]}\n', b"data: [DONE]\n"])

    client = ModelClient()
    with patch("contextual_orchestrator.orchestrator.get_credential", return_value="remote-secret"), patch.object(
        client,
        "_open_provider",
        side_effect=[
            _Response({"choices": [{"message": {"content": "chat"}}]}),
            StreamingResponse(),
        ],
    ) as open_provider:
        assert client._send(agent, {"model": agent.model}) == "chat"
        assert list(client._stream_send(agent, {"model": agent.model, "stream": True})) == ["delta"]

    for call in open_provider.call_args_list:
        assert call.args[0].get_header("Authorization") == "Bearer remote-secret"


def test_remote_http_is_still_rejected() -> None:
    agent = ModelAgent("remote_agent", "remote-model", base_url="http://127.0.0.1:8080/v1")
    try:
        with patch("contextual_orchestrator.orchestrator.get_credential", return_value="local"):
            ModelClient(max_retries=0).chat(agent, [{"role": "user", "content": "ping"}])
    except RuntimeError as exc:
        assert "https" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("plain http provider must remain rejected")


def test_provider_transport_rejects_non_http_url_before_io() -> None:
    client = ModelClient(max_retries=0)
    request = urllib.request.Request("file:///tmp/not-a-provider", method="GET")
    try:
        client._open_provider(request)
    except RuntimeError as exc:
        assert "HTTP(S) URL" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("non-HTTP provider URL must be rejected")


def test_local_batch_preserves_ids_and_usage() -> None:
    agent = ModelAgent("local_agent", "local-model", base_url="local://127.0.0.1:8080/v1", local_credential_key="LOCAL_GATEWAY_TOKEN")
    client = ModelClient(max_retries=0, local_concurrency=2)
    calls = []

    def fake_chat(_agent, messages, temperature=None):
        calls.append((messages[0]["content"], temperature))
        client._local.usage = {"completion_tokens": 1}
        return messages[0]["content"]

    with patch.object(client, "chat", side_effect=fake_chat):
        result = client.batch_chat(
            agent,
            {"one": [{"role": "user", "content": "1"}], "two": [{"role": "user", "content": "2"}]},
            temperature=0.0,
        )
    assert {key: value["content"] for key, value in result.items()} == {"one": "1", "two": "2"}
    assert all(value["usage"] == {"completion_tokens": 1} for value in result.values())
    assert sorted(calls) == [("1", 0.0), ("2", 0.0)]


def test_local_batch_default_uses_sequential_path() -> None:
    agent = ModelAgent("local_agent", "local-model", base_url="local://127.0.0.1:8080/v1", local_credential_key="LOCAL_GATEWAY_TOKEN")
    client = ModelClient()
    with patch.object(client, "chat", side_effect=lambda _agent, messages, temperature=None: messages[0]["content"]):
        result = client.batch_chat(
            agent,
            {"one": [{"role": "user", "content": "1"}], "two": [{"role": "user", "content": "2"}]},
        )

    assert {key: value["content"] for key, value in result.items()} == {"one": "1", "two": "2"}


def test_patch_agent_rejects_disabling_last_enabled_agent() -> None:
    orchestrator = TaskOrchestrator([ModelAgent("only_agent", "mock-only")])
    with pytest.raises(ValueError, match="last enabled"):
        orchestrator.patch_agent("default", "only_agent", {"status": "disabled"})


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
