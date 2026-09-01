"""Request-scoped endpoint routing is exact, isolated, and fail closed."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.orchestrator import EndpointUnavailableError, ModelClient
from contextual_orchestrator.server import (
    RequestError,
    SecurityConfig,
    _validate_routing,
    build_server,
)


class _RecordingClient(ModelClient):
    """Record selected agents while returning deterministic synthetic text."""

    def __init__(self) -> None:
        super().__init__()
        self.agent_ids: list[str] = []

    def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2, **_kwargs) -> str:  # type: ignore[override]
        self.agent_ids.append(agent.id)
        return json.dumps({"workflow_required": False})

    def proxy_send(  # type: ignore[override]
        self, agent: ModelAgent, endpoint: str, payload: dict
    ) -> dict:
        self.agent_ids.append(agent.id)
        if endpoint == "responses":
            return {
                "object": "response",
                "model": payload["model"],
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "synthetic response"}],
                    }
                ],
            }
        return {
            "id": "chatcmpl-endpoint-test",
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "synthetic response"},
                    "finish_reason": "stop",
                }
            ],
        }


def _orchestrator() -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent(
                "agent_a",
                "model-a",
                base_url="https://a.example/v1",
                group_name="shared_reasoning_model",
            ),
            ModelAgent("agent_b", "model-b", base_url="https://b.example/v1"),
        ],
        client=_RecordingClient(),
        cache_ttl=60,
    )


def test_endpoint_scope_filters_every_role_and_does_not_leak() -> None:
    orchestrator = _orchestrator()
    with orchestrator.routing_endpoint_scope("https://a.example", "orchestrator/auto"):
        for role in ("thinker", "worker", "verifier", "judge", "synthesizer"):
            assert [agent.id for agent in orchestrator._ranked_agents("task", role)] == [
                "agent_a"
            ]
    assert {agent.id for agent in orchestrator._ranked_agents("task", "worker")} == {
        "agent_a",
        "agent_b",
    }


def test_endpoint_scope_is_concurrent_and_rejects_model_conflicts() -> None:
    orchestrator = _orchestrator()
    barrier = threading.Barrier(2)

    def select(endpoint: str) -> str:
        with orchestrator.routing_endpoint_scope(endpoint, "orchestrator/auto"):
            barrier.wait()
            return orchestrator._ranked_agents("task", "worker")[0].id

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert set(executor.map(select, ("https://a.example", "https://b.example"))) == {
            "agent_a",
            "agent_b",
        }
    with (
        pytest.raises(EndpointUnavailableError),
        orchestrator.routing_endpoint_scope("https://a.example", "model-b"),
    ):
        pass


def test_endpoint_scope_partitions_response_and_triage_caches() -> None:
    orchestrator = _orchestrator()
    messages = [{"role": "user", "content": "same synthetic prompt"}]
    with orchestrator.routing_endpoint_scope("https://a.example", "orchestrator/auto"):
        cache_a = orchestrator._cache_key(messages, "route")
        orchestrator._triage_workflow_required("same synthetic prompt")
    with orchestrator.routing_endpoint_scope("https://b.example", "orchestrator/auto"):
        cache_b = orchestrator._cache_key(messages, "route")
        orchestrator._triage_workflow_required("same synthetic prompt")
    assert cache_a != cache_b
    assert len(orchestrator._triage_cache) == 2


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://user:secret@a.example",
        "https://a.example?x=1",
        "https://a.example#x",
        "ftp://a.example",
        "https://a.example:bad",
    ],
)
def test_invalid_endpoint_selector_is_rejected(endpoint: str) -> None:
    with pytest.raises(RequestError) as exc_info:
        _validate_routing({"endpoint": endpoint}, allow_endpoint=True)
    assert exc_info.value.code == "endpoint_unavailable"


def test_malformed_ipv6_endpoint_selector_preserves_error_contract() -> None:
    with pytest.raises(RequestError) as exc_info:
        _validate_routing({"endpoint": "https://[::1"}, allow_endpoint=True)
    assert exc_info.value.code == "endpoint_unavailable"


def test_endpoint_capacity_check_performs_no_provider_io() -> None:
    class _ProbeRecordingClient(_RecordingClient):
        def __init__(self) -> None:
            super().__init__()
            self.embed_calls = 0

        def embed(self, agent: ModelAgent, texts: list[str]) -> list[list[float]]:
            self.embed_calls += 1
            return [[0.0] for _text in texts]

    client = _ProbeRecordingClient()
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "chat_agent",
                "chat-model",
                base_url="https://a.example/v1",
            ),
            ModelAgent(
                "embedding_agent",
                "embedding-model",
                base_url="https://a.example/v1",
                tags=("embedding",),
            ),
        ],
        client=client,
    )

    with orchestrator.routing_endpoint_scope(
        "https://a.example", TaskOrchestrator.AUTO_MODEL
    ):
        pass

    assert client.agent_ids == []
    assert client.embed_calls == 0


def test_endpoint_is_limited_to_supported_surfaces_and_forces_sync() -> None:
    with pytest.raises(RequestError) as exc_info:
        _validate_routing({"endpoint": "https://a.example"})
    assert exc_info.value.code == "invalid_routing"
    assert _validate_routing(
        {"endpoint": "https://a.example", "priority": "bulk"},
        allow_endpoint=True,
    ) == {
        "endpoint": "https://a.example",
        "priority": "bulk",
        "channel": "sync",
    }


def _post_json(server: object, path: str, body: dict) -> tuple[int, dict]:
    port = server.server_address[1]  # type: ignore[attr-defined]
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode(),
        headers={
            "authorization": "Bearer endpoint-test-token",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/v1/chat/completions",
            {
                "model": "orchestrator/auto",
                "messages": [{"role": "user", "content": "synthetic answer"}],
            },
        ),
        ("/v1/responses", {"model": "orchestrator/auto", "input": "synthetic answer"}),
    ],
)
def test_http_surfaces_constrain_candidates_and_preserve_envelopes(path: str, payload: dict) -> None:
    orchestrator = _orchestrator()
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token="endpoint-test-token"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload["routing"] = {"endpoint": "https://a.example"}
        status, document = _post_json(server, path, payload)
        assert status == 200, document
        assert document["object"] in {"chat.completion", "response"}
        assert orchestrator.client.agent_ids
        assert set(orchestrator.client.agent_ids) == {"agent_a"}

        payload["routing"] = {"endpoint": "https://missing.example"}
        status, document = _post_json(server, path, payload)
        assert status == 400
        assert document["error"]["code"] == "endpoint_unavailable"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/v1/chat/completions",
            {
                "model": "  model-a  ",
                "messages": [{"role": "user", "content": "synthetic answer"}],
            },
        ),
        ("/v1/responses", {"model": " shared-reasoning-model ", "input": "synthetic answer"}),
    ],
)
def test_http_endpoint_scope_accepts_normalized_models_and_group_aliases(
    path: str, payload: dict
) -> None:
    orchestrator = _orchestrator()
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token="endpoint-test-token"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, document = _post_json(
            server,
            path,
            {**payload, "routing": {"endpoint": "https://a.example"}},
        )
        assert status == 200, document
        assert set(orchestrator.client.agent_ids) == {"agent_a"}
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/v1/chat/completions",
            {
                "messages": [{"role": "user", "content": "synthetic answer"}],
            },
        ),
        (
            "/v1/responses",
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "input": "synthetic answer",
            },
        ),
    ],
)
def test_http_endpoint_scope_rejects_endpoint_without_local_virtual_capacity(
    path: str, payload: dict
) -> None:
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "embedding_only",
                "embedding-model",
                base_url="https://paid.example/v1",
                tags=("embedding",),
            ),
            ModelAgent(
                "free_elsewhere",
                "free-model",
                base_url="https://free.example/v1",
                tags=("cost:free",),
            ),
        ],
        client=_RecordingClient(),
        cache_ttl=60,
    )
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token="endpoint-test-token"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, document = _post_json(
            server,
            path,
            {**payload, "routing": {"endpoint": "https://paid.example"}},
        )
        assert status == 400
        assert document["error"]["code"] == "endpoint_unavailable"
    finally:
        server.shutdown()
        thread.join(timeout=5)
