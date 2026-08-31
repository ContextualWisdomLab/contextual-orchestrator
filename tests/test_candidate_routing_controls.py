"""Stateless candidate pin and exclusion controls across OpenAI chat paths."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.orchestrator import ModelClient
from contextual_orchestrator.server import (
    RequestError,
    SecurityConfig,
    _validate_routing,
    build_server,
)


class _CandidateClient(ModelClient):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def chat(self, agent, messages, effort_profile=None):
        self.calls.append(agent.id)
        if agent.id == "candidate_a":
            raise RuntimeError("candidate a failed")
        if messages and "workflow_required" in str(messages[0].get("content")):
            return '{"workflow_required": false}'
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


def _post_responses(
    port: int, token: str, body: dict, *, stream: bool = False
) -> tuple[int, dict | list[dict]]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/responses",
        data=json.dumps(body).encode(),
        headers={
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
            "connection": "close",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        raw = response.read().decode()
        if stream:
            return response.status, [
                json.loads(line.removeprefix("data: "))
                for line in raw.splitlines()
                if line.startswith("data: {")
            ]
        return response.status, json.loads(raw)


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


def test_candidate_controls_reject_an_unserviceable_worker_pool() -> None:
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "worker_excluded",
                "excluded-model",
                provider_exclusions=("worker",),
            ),
            ModelAgent("worker_agent", "worker-model", tags=("cost:free",)),
        ]
    )

    with pytest.raises(ValueError, match="eligible agent"):
        with orchestrator.candidate_routing_policy(
            {"candidate_id": "worker_excluded"}
        ):
            pass
    with pytest.raises(ValueError, match="leaves no eligible agent"):
        with orchestrator.candidate_routing_policy(
            {"exclude_candidate_ids": ["worker_agent"]},
            model_name="orchestrator/free",
        ):
            pass

    zdr_orchestrator = TaskOrchestrator(
        [
            ModelAgent("plain_agent", "plain-model"),
            ModelAgent("zdr_agent", "zdr-model", tags=("privacy:zdr",)),
        ]
    )
    with zdr_orchestrator.request_policy(True):
        with pytest.raises(ValueError, match="leaves no eligible agent"):
            with zdr_orchestrator.candidate_routing_policy(
                {"exclude_candidate_ids": ["zdr_agent"]}
            ):
                pass


def test_candidate_pin_preflight_checks_conduct_roles_and_required_tags() -> None:
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "worker_only",
                "worker-model",
                provider_exclusions=("verifier",),
            ),
            ModelAgent("vision_agent", "vision-model", tags=("vision",)),
        ]
    )

    with pytest.raises(ValueError, match="eligible agent"):
        with orchestrator.candidate_routing_policy(
            {"candidate_id": "worker_only"},
            required_roles=("thinker", "worker", "verifier", "synthesizer"),
        ):
            pass
    with pytest.raises(ValueError, match="eligible agent"):
        with orchestrator.candidate_routing_policy(
            {"candidate_id": "worker_only"}, required_tags=("vision",)
        ):
            pass
    with pytest.raises(ValueError, match="leaves no eligible agent"):
        with orchestrator.candidate_routing_policy(
            {"exclude_candidate_ids": ["vision_agent"]},
            required_roles=("verifier",),
        ):
            pass


def test_http_conduct_preflight_rejects_role_ineligible_pin() -> None:
    client = _CandidateClient()
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "worker_only",
                "worker-model",
                provider_exclusions=("verifier",),
            )
        ],
        client=client,
    )
    token = "candidate-routing-token"
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=token)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post(
            server.server_address[1],
            token,
            {
                "model": "orchestrator/auto",
                "messages": [{"role": "user", "content": "conduct this"}],
                "mode": "conduct",
                "routing": {"candidate_id": "worker_only"},
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 400
    assert body["error"]["code"] == "invalid_routing"
    assert client.calls == []


def test_response_candidate_evidence_does_not_mutate_workflow_history() -> None:
    client = _CandidateClient()
    orchestrator = TaskOrchestrator(
        [ModelAgent("candidate_b", "model-b", provider_name="provider-b")],
        client=client,
    )
    token = "candidate-routing-token"
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=token)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post(
            server.server_address[1],
            token,
            {
                "model": "orchestrator/auto",
                "messages": [{"role": "user", "content": "conduct this"}],
                "mode": "conduct",
                "routing": {"candidate_id": "candidate_b"},
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200
    assert body["orchestration"]["routing"]["candidate_id"] == "candidate_b"
    assert orchestrator._workflow_runs
    assert all(
        "candidate_routing" not in record
        for record in orchestrator._workflow_runs.values()
    )


def test_generated_planner_uses_only_request_eligible_candidates(monkeypatch) -> None:
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("candidate_a", "model-a"),
            ModelAgent("candidate_b", "model-b"),
        ]
    )
    prompts: list[str] = []

    def plan(_agent, messages, **_kwargs):
        prompts.append(messages[0]["content"])
        return json.dumps(
            {
                "steps": [
                    {
                        "id": 0,
                        "role": "worker",
                        "agent_id": "candidate_a",
                        "subtask": "work",
                        "access": [],
                    },
                    {
                        "id": 1,
                        "role": "synthesizer",
                        "agent_id": "candidate_a",
                        "subtask": "answer",
                        "access": [0],
                    },
                ]
            }
        )

    monkeypatch.setattr(orchestrator.client, "chat", plan)
    with orchestrator.candidate_routing_policy(
        {"exclude_candidate_ids": ["candidate_a"]}
    ):
        steps = orchestrator._plan_generated("plan this")

    assert "candidate_a" not in prompts[0]
    assert "candidate_b" in prompts[0]
    assert {step.agent_id for step in steps} == {"candidate_b"}


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


def test_candidate_pin_is_honored_by_responses_json_and_stream_paths() -> None:
    server, thread, token, client = _serve()
    routing = {"candidate_id": "candidate_b", "exclude_candidate_ids": ["candidate_a"]}
    try:
        json_status, json_body = _post_responses(
            server.server_address[1],
            token,
            {"model": "orchestrator/auto", "input": "short", "routing": routing},
        )
        stream_status, stream_events = _post_responses(
            server.server_address[1],
            token,
            {
                "model": "orchestrator/auto",
                "input": "short",
                "stream": True,
                "routing": routing,
            },
            stream=True,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert json_status == 200
    assert isinstance(json_body, dict)
    assert json_body["orchestration"]["routing"]["served_candidate_id"] == "candidate_b"
    assert stream_status == 200
    assert isinstance(stream_events, list)
    completed = next(event for event in stream_events if event["type"] == "response.completed")
    assert completed["response"]["orchestration"]["routing"]["served_candidate_id"] == "candidate_b"
    assert set(client.calls) == {"candidate_b"}


def test_auto_stream_triage_and_completion_both_honor_the_pin() -> None:
    server, thread, token, client = _serve()
    try:
        status, events = _post_sse(
            server.server_address[1],
            token,
            {
                "model": "orchestrator/auto",
                "messages": [{"role": "user", "content": "auto route"}],
                "stream": True,
                "routing": {
                    "candidate_id": "candidate_b",
                    "exclude_candidate_ids": ["candidate_a"],
                },
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200
    assert events
    assert len(client.calls) >= 2
    assert set(client.calls) == {"candidate_b"}


def test_core_rejects_file_affinity_that_conflicts_with_pin() -> None:
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("candidate_a", "model-a"),
            ModelAgent("candidate_b", "model-b"),
        ]
    )
    with orchestrator.candidate_routing_policy(
        {"candidate_id": "candidate_b"}, model_name="orchestrator/auto"
    ):
        try:
            orchestrator.proxy_completion(
                {
                    "model": "orchestrator/auto",
                    "input": "file request",
                    "_required_agent_id": "candidate_a",
                },
                endpoint="responses",
            )
        except RuntimeError as exc:
            assert "required file provider" in str(exc)
        else:  # pragma: no cover - security regression
            raise AssertionError("conflicting file affinity was accepted")


def test_candidate_keys_are_rejected_on_unsupported_routing_surfaces() -> None:
    with pytest.raises(RequestError) as error:
        _validate_routing({"candidate_id": "candidate_b"})
    assert error.value.code == "invalid_routing"
    assert _validate_routing(
        {"exclude_candidate_ids": []}, allow_candidate_controls=True
    ) == {"exclude_candidate_ids": []}


def test_attempt_evidence_keeps_failed_candidate_before_success() -> None:
    server, thread, token, client = _serve()
    try:
        status, body = _post(
            server.server_address[1],
            token,
            _tool_body({"exclude_candidate_ids": ["disabled_candidate"]}),
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200
    assert client.calls == ["candidate_a", "candidate_b"]
    assert body["orchestration"]["routing"]["attempted_candidate_ids"] == [
        "candidate_a",
        "candidate_b",
    ]
    assert body["orchestration"]["routing"]["served_candidate_id"] == "candidate_b"


def test_cache_hit_reports_no_current_candidate_attempt() -> None:
    client = _CandidateClient()
    orchestrator = TaskOrchestrator(
        [ModelAgent("candidate_b", "model-b", provider_name="provider-b")],
        client=client,
        cache_ttl=60,
    )
    messages = [{"role": "user", "content": "cached candidate request"}]

    with orchestrator.candidate_routing_policy({"candidate_id": "candidate_b"}):
        first = orchestrator.complete(messages, mode="route")
        first_evidence = orchestrator._candidate_routing_evidence(first)
    with orchestrator.candidate_routing_policy({"candidate_id": "candidate_b"}):
        second = orchestrator.complete(messages, mode="route")
        second_evidence = orchestrator._candidate_routing_evidence(second)

    assert first["cache_status"] == "miss"
    assert first_evidence["attempted_candidate_ids"] == ["candidate_b"]
    assert first_evidence["served_candidate_id"] == "candidate_b"
    assert second["cache_status"] == "hit"
    assert second_evidence == {
        "candidate_id": "candidate_b",
        "exclude_candidate_ids": [],
        "attempted_candidate_ids": [],
    }
