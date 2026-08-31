"""Stateless candidate pin and exclusion controls across OpenAI chat paths."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.orchestrator import ModelClient
from contextual_orchestrator.server import SecurityConfig, build_server


class _CandidateClient(ModelClient):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def chat(self, agent, messages, effort_profile=None):
        self.calls.append(agent.id)
        if agent.id == "candidate_a":
            raise RuntimeError("candidate a failed")
        return "candidate b"

    def stream_chat(self, agent, messages, **kwargs):
        self.calls.append(agent.id)
        yield "candidate b"

    def proxy_send_once(self, agent, endpoint, payload):
        self.calls.append(agent.id)
        if agent.id == "candidate_a":
            raise urllib.error.HTTPError(
                "https://provider.example/v1", 503, "unavailable", None, None
            )
        return {
            "id": "chatcmpl-candidate-b",
            "object": "chat.completion",
            "created": 1,
            "model": agent.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "candidate b"},
                    "finish_reason": "stop",
                }
            ],
        }

    proxy_send = proxy_send_once


def _post(port: int, token: str, body: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _post_sse(port: int, token: str, body: dict) -> tuple[int, list[dict]]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
            "connection": "close",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        events = [
            json.loads(line.removeprefix("data: "))
            for line in response.read().decode().splitlines()
            if line.startswith("data: {")
        ]
        return response.status, events


def _serve():
    client = _CandidateClient()
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("candidate_a", "model-a", provider_name="provider-a"),
            ModelAgent("candidate_b", "model-b", provider_name="provider-b"),
            ModelAgent("disabled_candidate", "model-disabled", disabled=True),
        ],
        client=client,
    )
    token = "candidate-routing-token"
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=token)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, token, client


def _tool_body(routing: dict | None = None, *, model: str = "orchestrator/auto") -> dict:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "route this request"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    }
    if routing is not None:
        body["routing"] = routing
    return body


def test_failed_pin_then_excluded_candidate_can_be_retried_with_a_new_pin() -> None:
    server, thread, token, client = _serve()
    try:
        failed_status, _ = _post(
            server.server_address[1],
            token,
            _tool_body({"candidate_id": "candidate_a"}),
        )
        succeeded_status, succeeded = _post(
            server.server_address[1],
            token,
            _tool_body(
                {
                    "candidate_id": "candidate_b",
                    "exclude_candidate_ids": ["candidate_a"],
                }
            ),
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert failed_status == 503
    assert succeeded_status == 200
    assert client.calls == ["candidate_a", "candidate_b"]
    assert succeeded["model"] == "model-b"
    assert succeeded["orchestration"]["routing"] == {
        "candidate_id": "candidate_b",
        "exclude_candidate_ids": ["candidate_a"],
        "attempted_candidate_ids": ["candidate_b"],
        "served_candidate_id": "candidate_b",
    }


def test_candidate_controls_fail_closed_and_omission_preserves_response_shape() -> None:
    server, thread, token, _client = _serve()
    try:
        cases = (
            ({"candidate_id": "missing"}, "orchestrator/auto"),
            ({"candidate_id": "disabled_candidate"}, "orchestrator/auto"),
            ({"candidate_id": "candidate_b", "exclude_candidate_ids": ["candidate_b"]}, "orchestrator/auto"),
            ({"exclude_candidate_ids": ["candidate_a", "candidate_a"]}, "orchestrator/auto"),
            ({"candidate_id": "candidate_b"}, "model-b"),
        )
        for routing, model in cases:
            status, body = _post(
                server.server_address[1], token, _tool_body(routing, model=model)
            )
            assert status == 400, body
            assert body["error"]["code"] == "invalid_routing"

        status, body = _post(server.server_address[1], token, _tool_body())
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200
    assert "orchestration" not in body


def test_candidate_pin_is_honored_by_structured_and_streaming_chat_paths() -> None:
    server, thread, token, client = _serve()
    routing = {"candidate_id": "candidate_b", "exclude_candidate_ids": ["candidate_a"]}
    try:
        structured_status, structured = _post(
            server.server_address[1],
            token,
            {
                "model": "orchestrator/auto",
                "messages": [{"role": "user", "content": "structured"}],
                "response_format": {"type": "json_object"},
                "routing": routing,
            },
        )
        stream_status, events = _post_sse(
            server.server_address[1],
            token,
            {
                "model": "orchestrator/auto",
                "messages": [{"role": "user", "content": "short"}],
                "mode": "route",
                "stream": True,
                "routing": routing,
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert structured_status == 200
    assert structured["orchestration"]["routing"]["served_candidate_id"] == "candidate_b"
    assert stream_status == 200
    terminal = next(event for event in events if event.get("choices", [{}])[0].get("finish_reason") == "stop")
    assert terminal["orchestration"]["routing"]["served_candidate_id"] == "candidate_b"
    assert set(client.calls) == {"candidate_b"}
