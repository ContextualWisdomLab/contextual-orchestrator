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


def _orchestrator() -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent("agent_a", "model-a", base_url="https://a.example/v1"),
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
