"""Chat Completions response_format honesty over HTTP (structured-output shape)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.provider_errors import ProviderUpstreamError  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "chat_response_format_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server():
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_accepts_response_format_text() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "plain text"}],
                "response_format": {"type": "text"},
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_response_format_json_object() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "json object mode"}],
                "response_format": {"type": "json_object"},
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_structured_synthesis_classifies_upstream_404() -> None:
    """Final synthesis provider rejection is typed and never a raw 500."""
    orchestrator = build()

    def reject_synthesis(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://provider.synthetic.invalid/v1/chat/completions",
            404,
            "not found",
            {},
            None,
        )

    orchestrator.client.proxy_send = reject_synthesis
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post(
            server.server_address[1],
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "json object mode"}],
                "response_format": {"type": "json_object"},
            },
        )
        assert status == 404, body
        assert body["error"]["code"] == "model_not_found"
        assert body["error"]["detail"]["transport"] == "structured_synthesis"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_virtual_structured_synthesis_replaces_stale_model_on_same_endpoint() -> None:
    """Virtual routing retries a missing catalog model without crossing endpoints."""
    agents = [
        ModelAgent("stale_agent", "stale-model", "mock://catalog", tags=("reasoning", "writing")),
        ModelAgent("live_agent", "live-model", "mock://catalog", tags=("reasoning", "writing")),
        ModelAgent("other_agent", "other-model", "mock://other", tags=("reasoning", "writing")),
    ]
    orchestrator = TaskOrchestrator(agents)
    original_select_agent = orchestrator._select_agent
    orchestrator._select_agent = lambda task, role, **kwargs: (
        agents[0] if role == "synthesizer" else original_select_agent(task, role, **kwargs)
    )
    calls = []

    def send(agent, _endpoint, _payload):
        calls.append(agent.id)
        if agent.id == "stale_agent":
            raise urllib.error.HTTPError("https://synthetic.invalid", 404, "missing", {}, None)
        return {"choices": [{"message": {"content": '{"status":"ok"}'}}]}

    orchestrator.client.proxy_send_once = send
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post(
            server.server_address[1],
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "messages": [{"role": "user", "content": "structured"}],
                "response_format": {"type": "json_object"},
                "session_id": "synthetic-session",
            },
        )
        assert status == 200, body
        assert calls == ["stale_agent", "live_agent"]
        assert "other_agent" not in calls
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_virtual_structured_workflow_never_reuses_request_scoped_missing_model() -> None:
    """A model missing in evidence work is excluded from every later role and synthesis."""
    agents = [
        ModelAgent("stale_agent", "stale-model", "mock://catalog", tags=("reasoning", "writing")),
        ModelAgent("live_agent", "live-model", "mock://catalog", tags=("reasoning", "writing")),
    ]
    orchestrator = TaskOrchestrator(agents)
    original_ranked = orchestrator._ranked_agents

    def stale_first(*args, **kwargs):
        ranked = original_ranked(*args, **kwargs)
        return sorted(ranked, key=lambda candidate: candidate.id != "stale_agent")

    orchestrator._ranked_agents = stale_first
    chat_calls: list[str] = []
    synthesis_calls: list[str] = []

    def chat(agent, _messages, **_kwargs):
        chat_calls.append(agent.id)
        if agent.id == "stale_agent":
            raise ProviderUpstreamError(
                agent_id=agent.id,
                model=agent.model,
                error_code="model_not_found",
                message="synthetic missing model",
                client_status=404,
                provider_status=404,
                retryable=False,
            )
        return '{"status":"evidence"}'

    def synthesize(agent, _endpoint, _payload):
        synthesis_calls.append(agent.id)
        return {"choices": [{"message": {"content": '{"status":"ok"}'}}]}

    orchestrator.client.chat = chat
    orchestrator.client.proxy_send_once = synthesize
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post(
            server.server_address[1],
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "messages": [{"role": "user", "content": "structured"}],
                "response_format": {"type": "json_object"},
            },
        )
        assert status == 200, body
        assert chat_calls.count("stale_agent") == 1
        assert synthesis_calls == ["live_agent"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_virtual_structured_workflow_exhausts_each_missing_model_once() -> None:
    """A fully stale virtual pool terminates typed after one attempt per model."""
    agents = [
        ModelAgent("stale_a", "stale-a", "mock://catalog", tags=("reasoning", "writing")),
        ModelAgent("stale_b", "stale-b", "mock://catalog", tags=("reasoning", "writing")),
    ]
    orchestrator = TaskOrchestrator(agents)
    calls: list[str] = []

    def missing(agent, _messages, **_kwargs):
        calls.append(agent.id)
        raise ProviderUpstreamError(
            agent_id=agent.id,
            model=agent.model,
            error_code="model_not_found",
            message="synthetic missing model",
            client_status=404,
            provider_status=404,
            retryable=False,
        )

    orchestrator.client.chat = missing
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post(
            server.server_address[1],
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "messages": [{"role": "user", "content": "structured"}],
                "response_format": {"type": "json_object"},
            },
        )
        assert status == 404, body
        assert body["error"]["code"] == "model_not_found"
        assert sorted(calls) == ["stale_a", "stale_b"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_explicit_structured_model_preserves_model_not_found() -> None:
    """An explicit model pin never switches models after a provider 404."""
    orchestrator = TaskOrchestrator([
        ModelAgent("stale_agent", "stale-model", "mock://catalog", tags=("reasoning", "writing")),
        ModelAgent("live_agent", "live-model", "mock://catalog", tags=("reasoning", "writing")),
    ])
    calls = []

    def send(agent, _endpoint, _payload):
        calls.append(agent.id)
        raise urllib.error.HTTPError("https://synthetic.invalid", 404, "missing", {}, None)

    orchestrator.client.proxy_send = send
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post(
            server.server_address[1],
            {
                "model": "stale-model",
                "messages": [{"role": "user", "content": "structured"}],
                "response_format": {"type": "json_object"},
            },
        )
        assert status == 404
        assert body["error"]["code"] == "model_not_found"
        assert calls == ["stale_agent"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_virtual_missing_models_record_each_circuit_failure_once() -> None:
    """Same-endpoint model replacement does not double-count its final 404."""
    agents = [
        ModelAgent("stale_agent", "stale-model", "mock://catalog", tags=("reasoning", "writing")),
        ModelAgent("live_agent", "live-model", "mock://catalog", tags=("reasoning", "writing")),
    ]
    orchestrator = TaskOrchestrator(agents)
    original_select_agent = orchestrator._select_agent
    orchestrator._select_agent = lambda task, role, **kwargs: (
        agents[0] if role == "synthesizer" else original_select_agent(task, role, **kwargs)
    )
    calls = []

    def send(agent, _endpoint, _payload):
        calls.append(agent.id)
        raise urllib.error.HTTPError("https://synthetic.invalid", 404, "missing", {}, None)

    orchestrator.client.proxy_send_once = send
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post(
            server.server_address[1],
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "messages": [{"role": "user", "content": "structured"}],
                "response_format": {"type": "json_object"},
            },
        )
        assert status == 404, body
        assert calls == ["stale_agent", "live_agent"]
        assert orchestrator._circuit["stale_agent"]["failures"] == 1
        assert orchestrator._circuit["live_agent"]["failures"] == 1
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_structured_chat_rejects_batch_routing() -> None:
    """Provider-native structured synthesis has no batch execution contract."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "json"}],
                "response_format": {"type": "json_object"},
                "routing": {"channel": "batch"},
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_routing"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_structured_chat_applies_sampling_to_evidence_calls() -> None:
    """Conducted evidence and final synthesis share request-scoped sampling."""
    orchestrator = build()
    observed: list[float | None] = []
    original_chat = orchestrator.client.chat

    def observed_chat(agent, messages, **kwargs):
        observed.append(orchestrator.client.request_settings_snapshot()["temperature"])
        return original_chat(agent, messages, **kwargs)

    orchestrator.client.chat = observed_chat
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post(
            server.server_address[1],
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "json"}],
                "response_format": {"type": "json_object"},
                "temperature": 0.25,
            },
        )
        assert status == 200, body
        assert observed and set(observed) == {0.25}
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_structured_image_rejects_text_only_model_as_client_error() -> None:
    """An explicit capability mismatch is a 4xx request error, not a 500."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "inspect"},
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/png;base64,AA=="},
                            },
                        ],
                    }
                ],
                "response_format": {"type": "json_object"},
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_request"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_structured_image_rejects_auto_without_vision_as_client_error() -> None:
    """Automatic routing reports an unavailable image capability as a 4xx error."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "inspect"},
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/png;base64,AA=="},
                            },
                        ],
                    }
                ],
                "response_format": {"type": "json_object"},
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_request"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_fails_closed_when_provider_violates_valid_json_schema() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "structured"}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "receipt_line",
                        "schema": {
                            "type": "object",
                            "properties": {"amount": {"type": "number"}},
                            "required": ["amount"],
                        },
                        "strict": True,
                    },
                },
            },
        )
        assert status == 502, body
        assert body["error"]["code"] == "invalid_structured_output"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_unknown_response_format_type() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "bad type"}],
                "response_format": {"type": "xml"},
            },
        )
        assert status == 400, body
        assert "invalid_response_format" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_json_object_with_sibling_keys() -> None:
    """Buyers must not smuggle extra fields into type-only response_format objects."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "sibling"}],
                "response_format": {"type": "json_object", "strict": True},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_response_format" in blob
        assert "only the type field" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_json_schema_without_schema_body() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "missing schema"}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "receipt_line"},
                },
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_response_format" in blob
        assert "schema must be an object" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_non_object_response_format() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "string fmt"}],
                "response_format": "json",
            },
        )
        assert status == 400, body
        assert "invalid_response_format" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_response_format_omitted() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "no format"}],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_response_format_text()
    test_http_chat_accepts_response_format_json_object()
    test_http_chat_fails_closed_when_provider_violates_valid_json_schema()
    test_http_chat_rejects_unknown_response_format_type()
    test_http_chat_rejects_json_object_with_sibling_keys()
    test_http_chat_rejects_json_schema_without_schema_body()
    test_http_chat_rejects_non_object_response_format()
    test_http_chat_accepts_response_format_omitted()
    print("ok")
