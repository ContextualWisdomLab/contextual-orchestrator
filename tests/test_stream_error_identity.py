"""Real HTTP streaming errors retain the provider-observed request identity."""

import http.client
import json
import threading

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.provider_errors import ProviderUpstreamError
from contextual_orchestrator.server import SecurityConfig, build_server
from contextual_orchestrator.telemetry import current_request_id
from contextual_orchestrator.tool_fallback import (
    ToolFailureDecision, ToolFailureKind, ToolFallbackAction, ToolFallbackStoppedError,
)


@pytest.mark.parametrize("endpoint,error_kind", [
    ("/v1/chat/completions", "provider"),
    ("/v1/responses", "provider"),
    ("/v1/chat/completions", "tool"),
])
def test_stream_error_preserves_request_identity(endpoint, error_kind, monkeypatch):
    """Typed SSE failures use the same trusted ID as their provider invocation."""
    orchestrator = TaskOrchestrator([ModelAgent("worker_one", "mock/worker")])
    observed_ids = []

    def fail_stream(*args, **kwargs):
        observed_ids.append(current_request_id())
        if error_kind == "tool":
            raise ToolFallbackStoppedError("worker_one", ToolFailureDecision(
                ToolFailureKind.AMBIGUOUS_OUTCOME, ToolFallbackAction.FAIL_CLOSED,
                "ambiguous_outcome", False, False,
            ))
        raise ProviderUpstreamError(
            agent_id="worker_one", model="mock/worker", error_code="unit_failure",
            message="unit failure", client_status=502, transport="stream",
        )

    monkeypatch.setattr(orchestrator.client, "stream_chat", fail_stream)
    monkeypatch.setattr(orchestrator, "would_route", lambda *args, **kwargs: True)
    server = build_server(orchestrator, port=0,
                          security=SecurityConfig(auth_token="unit-token"))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    connection = http.client.HTTPConnection(*server.server_address, timeout=20)
    try:
        body = {"model": "orchestrator/auto", "mode": "route", "stream": True,
                "messages": [{"role": "user", "content": "unit request"}]}
        if endpoint == "/v1/responses":
            body = {"model": "orchestrator/auto", "stream": True, "input": "hello"}
        connection.request("POST", endpoint, json.dumps(body), {
            "Content-Type": "application/json", "Authorization": "Bearer unit-token",
            "X-Request-ID": "untrusted-client-id",
        })
        response = connection.getresponse()
        payload = response.read().decode()
        assert response.status == 200
        events = [json.loads(line[6:]) for line in payload.splitlines()
                  if line.startswith("data: ") and line != "data: [DONE]"]
        errors = [event["error"] for event in events if "error" in event]
        errors += [event["response"]["error"] for event in events
                   if event.get("type") == "response.failed"]
        assert len(observed_ids) == 1
        assert observed_ids[0] and observed_ids[0] != "untrusted-client-id"
        assert len(errors) == 1
        assert errors[0]["detail"]["request_id"] == observed_ids[0]
    finally:
        connection.close()
        server.shutdown()
        worker.join()
        server.server_close()
        orchestrator.close()
