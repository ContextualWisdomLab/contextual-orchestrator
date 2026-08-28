"""Request-scoped configured-endpoint routing is exact, isolated, and fail closed."""

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
    """Record the selected agent while returning deterministic provider text."""

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


def test_origin_selector_matches_configured_v1_and_filters_every_role() -> None:
    """The transport suffix is identity-neutral and every role sees one endpoint."""
    orchestrator = _orchestrator()
    with orchestrator.routing_endpoint_scope("https://a.example", "contextual-orchestrator"):
        for role in ("thinker", "worker", "verifier", "judge", "synthesizer"):
            assert [agent.id for agent in orchestrator._ranked_agents("task", role)] == [
                "agent_a"
            ]


def test_missing_endpoint_and_explicit_model_conflict_fail_closed() -> None:
    orchestrator = _orchestrator()
    with (
        pytest.raises(EndpointUnavailableError),
        orchestrator.routing_endpoint_scope(
            "https://missing.example", "contextual-orchestrator"
        ),
    ):
        pass
    with (
        pytest.raises(EndpointUnavailableError),
        orchestrator.routing_endpoint_scope("https://a.example", "model-b"),
    ):
        pass


@pytest.mark.parametrize(
    "endpoint",
    ["https://user:secret@a.example", "https://a.example?x=1", "https://a.example#x", "ftp://a.example", "https://a.example:bad"],
)
def test_invalid_endpoint_selector_is_rejected(endpoint: str) -> None:
    with pytest.raises(RequestError) as exc_info:
        _validate_routing({"endpoint": endpoint}, allow_endpoint=True)
    assert exc_info.value.code == "endpoint_unavailable"


def test_context_is_concurrent_and_does_not_leak() -> None:
    orchestrator = _orchestrator()
    barrier = threading.Barrier(2)

    def select(endpoint: str) -> str:
        with orchestrator.routing_endpoint_scope(endpoint, "contextual-orchestrator"):
            barrier.wait()
            return orchestrator._ranked_agents("task", "worker")[0].id

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = set(executor.map(select, ("https://a.example", "https://b.example")))
    assert results == {"agent_a", "agent_b"}
    assert {agent.id for agent in orchestrator._ranked_agents("task", "worker")} == {
        "agent_a",
        "agent_b",
    }


def test_cache_and_triage_are_partitioned_by_endpoint() -> None:
    orchestrator = _orchestrator()
    messages = [{"role": "user", "content": "same"}]
    with orchestrator.routing_endpoint_scope("https://a.example", "contextual-orchestrator"):
        cache_a = orchestrator._cache_key(messages, "route")
        orchestrator._triage_workflow_required("same")
    with orchestrator.routing_endpoint_scope("https://b.example", "contextual-orchestrator"):
        cache_b = orchestrator._cache_key(messages, "route")
        orchestrator._triage_workflow_required("same")
    assert cache_a != cache_b
    assert orchestrator.client.agent_ids == ["agent_a", "agent_b"]


def test_generated_plan_cannot_assign_an_agent_outside_endpoint() -> None:
    orchestrator = _orchestrator()
    raw = json.dumps(
        {
            "steps": [
                {"id": 0, "role": "worker", "agent_id": "agent_b", "subtask": "work", "access": []},
                {"id": 1, "role": "synthesizer", "agent_id": "agent_b", "subtask": "answer", "access": [0]},
            ]
        }
    )
    with orchestrator.routing_endpoint_scope("https://a.example", "contextual-orchestrator"):
        assert {step.agent_id for step in orchestrator._parse_workflow_plan(raw)} == {
            "agent_a"
        }


def test_structured_admission_intersects_endpoint_scope() -> None:
    orchestrator = _orchestrator()
    orchestrator._structured_readiness = {
        "agent_a": {"status": "ready", "checked_at": 1.0},
        "agent_b": {"status": "ready", "checked_at": 1.0},
    }
    with orchestrator.routing_endpoint_scope("https://a.example", "contextual-orchestrator"):
        assert orchestrator._structured_admitted_agent_ids() == frozenset({"agent_a"})


def test_routing_object_is_stripped_as_one_provider_control_field() -> None:
    orchestrator = _orchestrator()
    assert "routing" in orchestrator._ORCHESTRATION_ONLY_KEYS


def test_endpoint_is_rejected_on_unrelated_surfaces() -> None:
    with pytest.raises(RequestError) as exc_info:
        _validate_routing({"endpoint": "https://a.example"})
    assert exc_info.value.code == "invalid_routing"


def _post_json(server: object, path: str, body: dict) -> tuple[int, dict]:
    """Post one synthetic OpenAI-compatible request to the in-process server."""
    port = server.server_address[1]  # type: ignore[attr-defined]
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode("utf-8"),
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
                "model": "contextual-orchestrator",
                "messages": [{"role": "user", "content": "answer"}],
            },
        ),
        (
            "/v1/responses",
            {"model": "contextual-orchestrator", "input": "answer"},
        ),
    ],
)
def test_http_surfaces_constrain_candidates_and_preserve_envelopes(
    path: str, payload: dict
) -> None:
    """Both supported OpenAI surfaces apply the endpoint to every provider call."""
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
