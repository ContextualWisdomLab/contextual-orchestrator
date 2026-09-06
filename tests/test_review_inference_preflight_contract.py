"""Exercise the inference-only review preflight against the actual HTTP server."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import http.client
import json
from pathlib import Path
import threading
import urllib.error

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.orchestrator import ModelClient
from contextual_orchestrator.server import SecurityConfig, build_server


def load_contract() -> dict:
    """Read the versioned consumer request contract."""
    return json.loads(Path("tests/fixtures/review_inference_preflight_v1.json").read_text())


class RecordingClient(ModelClient):
    """Supply deterministic provider replies without provider egress."""

    def __init__(self, reject_calls: bool = False) -> None:
        super().__init__()
        self.reject_calls = reject_calls
        self.provider_calls: list[tuple[str, dict]] = []

    def proxy_send_once(self, agent, endpoint, payload):
        """Capture forwarded capabilities and optionally exhaust the free provider."""
        self.provider_calls.append((agent.id, deepcopy(payload)))
        if self.reject_calls:
            raise urllib.error.HTTPError("https://provider.invalid/v1", 429, "unavailable", {}, None)
        if payload.get("tools"):
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "probe_call", "type": "function", "function": {
                    "name": "review_probe", "arguments": '{"probe_status":"ready"}'},
            }]}
        else:
            message = {"role": "assistant", "content": '{"probe_status":"ready"}'}
        return {"id": "probe_response", "object": "chat.completion", "model": agent.model,
                "choices": [{"index": 0, "message": message, "finish_reason": "stop"}]}

    proxy_send = proxy_send_once


@contextmanager
def serve_gateway(*, free_available=True, zdr_available=True, reject_calls=False):
    """Expose a split-token gateway backed only by synthetic unit-test providers."""
    client = RecordingClient(reject_calls)
    agent_tags = ("cost:free",) + (("privacy:zdr",) if zdr_available else ())
    agents = [ModelAgent("paid_agent", "paid-model", base_url="https://paid.invalid/v1")]
    if free_available:
        agents.insert(0, ModelAgent("free_agent", "free-model", base_url="https://free.invalid/v1", tags=agent_tags))
    server = build_server(TaskOrchestrator(agents, client=client), port=0,
                          security=SecurityConfig(admin_token="fixture_admin", inference_token="fixture_inference"))
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        yield server.server_address[1], client
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)


def request_gateway(port_number, request_path, request_body=None, auth_token="fixture_inference"):
    """Send one local HTTP request with explicit connection cleanup."""
    connection = http.client.HTTPConnection("127.0.0.1", port_number, timeout=5)
    request_headers = {"Content-Type": "application/json", "Connection": "close"}
    if auth_token:
        request_headers["Authorization"] = f"Bearer {auth_token}"
    try:
        connection.request("POST" if request_body is not None else "GET", request_path,
                           body=json.dumps(request_body) if request_body is not None else None,
                           headers=request_headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def test_preflight_discovery_needs_only_inference_scope():
    """Inference discovery succeeds while admin readiness stays protected."""
    contract = load_contract()
    with serve_gateway() as (port_number, _client):
        for auth_token in (None, "wrong_fixture_token"):
            assert request_gateway(port_number, contract["discovery_path"], auth_token=auth_token)[0] == 401
        status_code, response_body = request_gateway(port_number, contract["discovery_path"])
        assert status_code == 200
        assert "orchestrator/free" in {item["id"] for item in response_body["data"]}
        assert request_gateway(port_number, "/readyz")[0] == 401
        assert request_gateway(port_number, "/api/v1/agent_pools")[0] == 401


@pytest.mark.parametrize("probe_name", ["json_object", "json_schema", "tool_call"])
def test_inference_preflight_preserves_capability_requests(probe_name):
    """Tool/schema preflight crosses the real gateway with its free/ZDR policy."""
    contract = load_contract()
    probe_request = contract["probe_requests"][probe_name]
    assert probe_request["model"] == "orchestrator/free"
    assert probe_request["zdr_only"] is True
    with serve_gateway() as (port_number, client):
        status_code, response_body = request_gateway(port_number, contract["inference_path"], probe_request)
        assert status_code == 200, response_body
        assert {agent_id for agent_id, _payload in client.provider_calls} == {"free_agent"}
        forwarded_request = client.provider_calls[-1][1]
        for field_name in ("tools", "tool_choice", "response_format"):
            if field_name in probe_request:
                assert forwarded_request[field_name] == probe_request[field_name]
        message_body = response_body["choices"][0]["message"]
        if probe_name == "tool_call":
            tool_function = message_body["tool_calls"][0]["function"]
            assert tool_function["name"] == "review_probe"
            assert json.loads(tool_function["arguments"]) == {"probe_status": "ready"}
        else:
            assert json.loads(message_body["content"]) == {"probe_status": "ready"}


@pytest.mark.parametrize("gateway_options", [
    {"free_available": False}, {"zdr_available": False}, {"reject_calls": True},
])
def test_preflight_exhaustion_never_reaches_paid_or_non_zdr_routes(gateway_options):
    """No free/ZDR capability or exhausted free providers cannot produce readiness."""
    contract = load_contract()
    with serve_gateway(**gateway_options) as (port_number, client):
        status_code, response_body = request_gateway(port_number, contract["inference_path"], contract["probe_requests"]["json_object"])
        assert status_code >= 400, response_body
        assert "paid_agent" not in {agent_id for agent_id, _payload in client.provider_calls}
        if gateway_options.get("zdr_available") is False:
            assert client.provider_calls == []
