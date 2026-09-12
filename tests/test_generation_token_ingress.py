"""Generation limits remain caller values at the model execution boundary."""

import http.client
import json
import threading

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.orchestrator import ModelClient
from contextual_orchestrator.server import SecurityConfig, build_server


@pytest.mark.parametrize(
    "endpoint_path, budget_field, input_fields",
    [
        ("/v1/completions", "max_tokens", {"prompt": "hello"}),
        ("/v1/completions", "max_completion_tokens", {"prompt": "hello"}),
        ("/v1/chat/completions", "max_tokens", {"messages": [{"role": "user", "content": "hello"}]}),
        ("/v1/chat/completions", "max_completion_tokens", {"messages": [{"role": "user", "content": "hello"}]}),
        ("/v1/responses", "max_tokens", {"input": "hello"}),
        ("/v1/responses", "max_completion_tokens", {"input": "hello"}),
        ("/v1/responses", "max_output_tokens", {"input": "hello"}),
        ("/v1/responses", "max_output_tokens", {"input": "hello", "max_completion_tokens": 32, "max_tokens": 16}),
        ("/v1/responses", "max_completion_tokens", {"input": "hello", "max_output_tokens": None, "max_tokens": 16}),
        ("/v1/responses", "max_tokens", {"input": "hello", "max_output_tokens": None, "max_completion_tokens": None}),
    ],
)
@pytest.mark.parametrize("requested_limit", [64, 1_048_577])
def test_http_preserves_caller_generation_limit(monkeypatch, endpoint_path, budget_field, input_fields, requested_limit):
    """A boundary fixture above the former cap does not claim real model capacity."""
    model_client = ModelClient()
    observed_limits = []
    original_mock = model_client._mock
    original_raw_mock = model_client._mock_raw

    def observe_mock(model_agent, *call_args, **call_kwargs):
        observed_limits.append(model_client.effective_max_output_tokens(model_agent))
        return original_mock(model_agent, *call_args, **call_kwargs)

    def observe_raw_mock(model_agent, provider_endpoint, provider_payload):
        assert provider_endpoint.strip("/") == "responses"
        observed_limits.append(provider_payload.get("max_output_tokens"))
        return original_raw_mock(model_agent, provider_endpoint, provider_payload)

    monkeypatch.setattr(model_client, "_mock", observe_mock)
    monkeypatch.setattr(model_client, "_mock_raw", observe_raw_mock)
    task_orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))],
        client=model_client,
    )
    http_server = build_server(
        task_orchestrator, port=0, security=SecurityConfig(auth_token="fixture-token")
    )
    server_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    server_thread.start()
    http_connection = http.client.HTTPConnection(*http_server.server_address, timeout=10)
    try:
        request_payload = {"model": "mock-planner", **input_fields, budget_field: requested_limit}
        http_connection.request(
            "POST", endpoint_path, json.dumps(request_payload),
            {"Content-Type": "application/json", "Authorization": "Bearer fixture-token"},
        )
        http_response = http_connection.getresponse()
        response_payload = json.loads(http_response.read())
        assert http_response.status == 200, response_payload
        assert observed_limits and all(observed_limit == requested_limit for observed_limit in observed_limits), observed_limits
    finally:
        http_connection.close()
        http_server.shutdown()
        server_thread.join(timeout=5)
        http_server.server_close()
        task_orchestrator.close()
