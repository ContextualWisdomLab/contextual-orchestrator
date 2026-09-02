"""Stateless candidate pin and exclusion controls across OpenAI chat paths."""

from __future__ import annotations

import dataclasses
import json
import threading
import urllib.error
import urllib.request

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.cost_router import CostRoutingCoordinator
from contextual_orchestrator.orchestrator import ModelClient, WorkflowStep
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
                    "message": {
                        "role": "assistant",
                        "content": (
                            '{"answer": "candidate b"}'
                            if isinstance(payload.get("response_format"), dict)
                            else "candidate b"
                        ),
                    },
                    "finish_reason": "stop",
                }
            ],
        }

    proxy_send = proxy_send_once


class _ConductTriageClient(_CandidateClient):
    def chat(self, agent, messages, effort_profile=None):
        self.calls.append(agent.id)
        if messages and "workflow_required" in str(messages[0].get("content")):
            return '{"workflow_required": true}'
        return "candidate b"


class _DivergentTriageClient(ModelClient):
    """Route-forcing triage reply from whichever agent is asked -- used to make
    the free-only triage pool and the full worker pool resolve to two
    genuinely different agents (see #983 finding 2)."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def chat(self, agent, messages, temperature=None, top_p=None, effort_profile=None):
        self.calls.append(agent.id)
        if messages and "workflow_required" in str(messages[0].get("content")):
            return '{"workflow_required": false}'
        return "unexpected chat() call"  # pragma: no cover - triage-only client

    def stream_chat(self, agent, messages, **kwargs):
        self.calls.append(agent.id)
        yield "streamed worker output"


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
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            raw = response.read().decode()
            if stream:
                return response.status, [
                    json.loads(line.removeprefix("data: "))
                    for line in raw.splitlines()
                    if line.startswith("data: {")
                ]
            return response.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


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


def test_candidate_routing_policy_rejects_present_but_falsy_malformed_controls() -> None:
    """A direct Python-API caller who passes a present-but-falsy malformed
    control (empty string, False, explicit None, an empty mapping) must get
    a loud ValueError, not a silent "no control" no-op -- the HTTP layer's
    own ``_validate_routing`` already rejects these shapes with a 400
    before candidate_routing_policy ever sees them, but a caller who talks
    to the orchestrator directly has no such gate (#983 finding 2)."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("candidate_a", "model-a"),
            ModelAgent("candidate_b", "model-b"),
        ]
    )

    malformed_exclude_candidate_ids = ("", False, None, {})
    for value in malformed_exclude_candidate_ids:
        with pytest.raises(ValueError, match="exclude_candidate_ids"):
            with orchestrator.candidate_routing_policy(
                {"exclude_candidate_ids": value}
            ):
                pass

    # candidate_id=None must raise exactly like every other malformed-falsy
    # shape (CodeRabbit finding on #983: the prior `candidate_id is not
    # None` guard let an explicit None silently reach the no-op branch
    # below instead of surfacing the caller bug, unlike
    # exclude_candidate_ids=None above which already raised correctly).
    for value in (False, 0, 1.5, [], {}, None):
        with pytest.raises(ValueError, match="candidate_id"):
            with orchestrator.candidate_routing_policy({"candidate_id": value}):
                pass

    # Absent fields, an explicit None routing mapping, and an explicit
    # empty list/tuple exclude_candidate_ids all remain no-ops -- the
    # existing contract for "no control requested". An *absent*
    # candidate_id key is the only candidate_id shape that is a no-op; an
    # explicitly present candidate_id=None is not (see the loop above).
    with orchestrator.candidate_routing_policy(None):
        pass
    with orchestrator.candidate_routing_policy({}):
        pass
    with orchestrator.candidate_routing_policy({"exclude_candidate_ids": []}):
        pass
    with orchestrator.candidate_routing_policy({"exclude_candidate_ids": ()}):
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
        responses = [
            _post(
                server.server_address[1],
                token,
                {
                    "model": "orchestrator/auto",
                    "messages": [{"role": "user", "content": "conduct this"}],
                    "mode": mode,
                    "routing": {"candidate_id": "worker_only"},
                },
            )
            for mode in ("conduct", "auto")
        ]
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert all(status == 400 for status, _body in responses)
    assert all(
        body["error"]["code"] == "invalid_routing" for _status, body in responses
    )
    assert client.calls == []


def test_http_auto_preflight_accepts_worker_only_pin_when_free_model_always_routes() -> None:
    """``orchestrator/free`` auto mode never needs a live triage call to prove
    the direct route: ``TaskOrchestrator.would_route`` short-circuits to
    True from ``model_name`` alone for FREE_MODEL, so preflight can safely
    require only the worker role -- unlike GATEWAY_DEFAULT_MODEL/AUTO_MODEL
    auto requests (see ``test_http_conduct_preflight_rejects_role_ineligible_pin``),
    where the route-vs-conduct decision genuinely requires a pin-scoped
    triage provider call and preflight stays conservative instead of risking
    it. Covers both /v1/chat/completions and non-streamed/streamed
    /v1/responses so every auto-mode preflight site shares the contract.
    """
    client = _CandidateClient()
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "worker_only",
                "worker-model",
                tags=("cost:free",),
                provider_exclusions=("thinker", "verifier", "synthesizer"),
            )
        ],
        client=client,
    )
    token = "candidate-routing-free-token"
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=token)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        chat_status, chat_body = _post(
            server.server_address[1],
            token,
            {
                "model": "orchestrator/free",
                "messages": [{"role": "user", "content": "hello"}],
                "mode": "auto",
                "routing": {"candidate_id": "worker_only"},
            },
        )
        responses_status, responses_body = _post_responses(
            server.server_address[1],
            token,
            {
                "model": "orchestrator/free",
                "input": "hello",
                "routing": {"candidate_id": "worker_only"},
            },
        )
        stream_status, stream_events = _post_responses(
            server.server_address[1],
            token,
            {
                "model": "orchestrator/free",
                "input": "hello",
                "stream": True,
                "routing": {"candidate_id": "worker_only"},
            },
            stream=True,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert chat_status == 200
    assert chat_body["choices"][0]["message"]["content"] == "candidate b"
    assert chat_body["orchestration"]["mode"] == "route"
    assert chat_body["orchestration"]["routing"]["served_candidate_id"] == "worker_only"

    assert responses_status == 200
    assert isinstance(responses_body, dict)
    assert responses_body["output"][-1]["content"][0]["text"] == "candidate b"

    assert stream_status == 200
    assert isinstance(stream_events, list) and stream_events

    assert client.calls == ["worker_only", "worker_only", "worker_only"]


def test_coordinator_malformed_candidate_id_none_is_not_dropped_by_batch_routing() -> None:
    """A direct ``CostRoutingCoordinator.complete`` caller (the Python API,
    not HTTP -- ``server.py``'s own ``_validate_routing`` already normalizes
    an explicit ``candidate_id: None`` to "missing" before this layer ever
    sees it) who passes a malformed ``candidate_id: None`` alongside a batch
    channel request must still get the loud ``ValueError`` from
    ``candidate_routing_policy``, not a silently-accepted batch job envelope
    that drops the malformed control entirely. ``has_candidate_controls``
    previously used truthiness (``bool(hints.get("candidate_id") or ...)``),
    so ``candidate_id: None`` was indistinguishable from an absent key and
    let the request take the early batch-channel return path before
    validation ever ran (CodeRabbit finding on #983: "direct Python API
    callers can lose or bypass routing validation")."""
    orchestrator = TaskOrchestrator([ModelAgent("candidate_a", "model-a")])

    with pytest.raises(ValueError, match="candidate_id"):
        CostRoutingCoordinator(orchestrator).complete(
            [{"role": "user", "content": "hello"}],
            mode="auto",
            model_name=TaskOrchestrator.AUTO_MODEL,
            hints={"candidate_id": None, "channel": "batch"},
        )


def test_coordinator_explicit_empty_exclusion_still_takes_the_batch_path() -> None:
    """Mirror/regression guard for the fix above: an explicit empty
    ``exclude_candidate_ids: []`` remains a genuine no-op (not a malformed
    value), so it must still be free to take the batch channel exactly as
    it did before -- this is the earlier #983 fix ("빈 제외 목록을 후보
    제어로 처리하지 마십시오") that the presence-based ``candidate_id``
    check above must not regress."""
    orchestrator = TaskOrchestrator([ModelAgent("candidate_a", "model-a")])

    result = CostRoutingCoordinator(orchestrator).complete(
        [{"role": "user", "content": "hello"}],
        mode="auto",
        model_name=TaskOrchestrator.AUTO_MODEL,
        hints={"exclude_candidate_ids": [], "channel": "batch"},
    )

    assert result["channel"] == "batch"


def test_coordinator_auto_route_only_pin_succeeds_for_free_model() -> None:
    """Direct ``CostRoutingCoordinator.complete`` callers get the same
    provable-route carve-out as HTTP callers (see
    ``test_http_auto_preflight_accepts_worker_only_pin_when_free_model_always_routes``):
    FREE_MODEL's auto-mode decision is provider-free, so a worker-only pin
    must not be rejected the way the GATEWAY_DEFAULT_MODEL/AUTO_MODEL case
    still is in ``test_coordinator_auto_preflights_conduct_roles_before_triage``.
    """
    client = _CandidateClient()
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "worker_only",
                "worker-model",
                tags=("cost:free",),
                provider_exclusions=("thinker", "verifier", "synthesizer"),
            )
        ],
        client=client,
    )

    result = CostRoutingCoordinator(orchestrator).complete(
        [{"role": "user", "content": "hello"}],
        mode="auto",
        model_name="orchestrator/free",
        hints={"candidate_id": "worker_only"},
    )

    assert result["mode"] == "route"
    assert result["candidate_routing"]["served_candidate_id"] == "worker_only"
    assert client.calls == ["worker_only"]


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


def test_structured_chat_with_active_candidate_pin_normalizes_batch_channel_to_sync() -> None:
    """An active candidate_id pin forces sync execution instead of the flat
    "batch routing is not supported" rejection, matching
    CostRoutingCoordinator.complete's own has_candidate_controls precedence
    (#983 finding 1)."""
    server, thread, token, client = _serve()
    try:
        status, body = _post(
            server.server_address[1],
            token,
            {
                "model": "orchestrator/auto",
                "messages": [{"role": "user", "content": "structured"}],
                "response_format": {"type": "json_object"},
                "routing": {
                    "candidate_id": "candidate_b",
                    "exclude_candidate_ids": ["candidate_a"],
                    "channel": "batch",
                },
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200, body
    assert "job_id" not in body
    assert body["orchestration"]["routing"]["served_candidate_id"] == "candidate_b"
    assert set(client.calls) == {"candidate_b"}


def test_structured_chat_with_active_candidate_exclusion_normalizes_latency_tolerant_to_sync() -> None:
    """An active exclude_candidate_ids control forces sync execution instead
    of rejecting routing.latency_tolerant=true outright (#983 finding 1)."""
    server, thread, token, client = _serve()
    try:
        status, body = _post(
            server.server_address[1],
            token,
            {
                "model": "orchestrator/auto",
                "messages": [{"role": "user", "content": "structured"}],
                "response_format": {"type": "json_object"},
                "routing": {
                    "exclude_candidate_ids": ["candidate_a"],
                    "latency_tolerant": True,
                },
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200, body
    assert "job_id" not in body
    assert body["orchestration"]["routing"]["served_candidate_id"] == "candidate_b"
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


def test_responses_with_active_candidate_pin_normalizes_batch_channel_to_sync() -> None:
    """An active candidate_id pin forces sync execution instead of the flat
    "routing.channel=batch is not supported on /v1/responses" rejection, for
    both the JSON and streaming Responses paths -- matching the same
    precedence already applied to structured chat (#983 finding 1)."""
    server, thread, token, client = _serve()
    routing = {
        "candidate_id": "candidate_b",
        "exclude_candidate_ids": ["candidate_a"],
        "channel": "batch",
    }
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

    assert json_status == 200, json_body
    assert isinstance(json_body, dict)
    assert "job_id" not in json_body
    assert json_body["orchestration"]["routing"]["served_candidate_id"] == "candidate_b"
    assert stream_status == 200
    assert isinstance(stream_events, list)
    completed = next(event for event in stream_events if event["type"] == "response.completed")
    assert completed["response"]["orchestration"]["routing"]["served_candidate_id"] == "candidate_b"
    assert set(client.calls) == {"candidate_b"}


def test_responses_with_active_candidate_exclusion_normalizes_latency_tolerant_to_sync() -> None:
    """An active exclude_candidate_ids control forces sync execution instead
    of rejecting routing.latency_tolerant=true outright, for both the JSON
    and streaming Responses paths (#983 finding 1)."""
    server, thread, token, client = _serve()
    routing = {"exclude_candidate_ids": ["candidate_a"], "latency_tolerant": True}
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

    assert json_status == 200, json_body
    assert isinstance(json_body, dict)
    assert "job_id" not in json_body
    assert json_body["orchestration"]["routing"]["served_candidate_id"] == "candidate_b"
    assert stream_status == 200
    assert isinstance(stream_events, list)
    completed = next(event for event in stream_events if event["type"] == "response.completed")
    assert completed["response"]["orchestration"]["routing"]["served_candidate_id"] == "candidate_b"
    assert set(client.calls) == {"candidate_b"}


def test_responses_preflight_rejects_conduct_ineligible_pin_before_provider_calls() -> None:
    client = _ConductTriageClient()
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
        responses = [
            _post_responses(
                server.server_address[1],
                token,
                {
                    "model": "orchestrator/auto",
                    "input": "conduct this",
                    "stream": stream,
                    "routing": {"candidate_id": "worker_only"},
                },
                stream=stream,
            )
            for stream in (False, True)
        ]
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert all(status == 400 for status, _body in responses)
    assert all(
        isinstance(body, dict) and body["error"]["code"] == "invalid_routing"
        for _status, body in responses
    )
    assert client.calls == []


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


def test_auto_stream_shares_candidate_scope_with_triage_when_triage_and_worker_differ() -> None:
    """The would_route triage decision and the streamed worker call must
    share one candidate-routing scope so the free triage agent's attempt is
    not discarded from terminal streamed evidence (#983 finding 2).

    The free-only triage pool contains only ``triage_agent`` while the full
    worker pool ranks ``worker_agent`` first (higher operator priority), so
    the agent the triage call attempts and the agent that actually streams
    the answer are genuinely different -- a shape
    test_auto_stream_triage_and_completion_both_honor_the_pin cannot
    exercise, since a candidate_id pin forces both calls onto one agent.
    """
    client = _DivergentTriageClient()
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("triage_agent", "model-triage", tags=("cost:free",), priority=10),
            ModelAgent("worker_agent", "model-worker", priority=20),
            ModelAgent("excluded_agent", "model-excluded"),
        ],
        client=client,
    )
    token = "divergent-triage-token"
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=token)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, events = _post_sse(
            server.server_address[1],
            token,
            {
                "model": "orchestrator/auto",
                "messages": [{"role": "user", "content": "short auto request"}],
                "stream": True,
                "routing": {"exclude_candidate_ids": ["excluded_agent"]},
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200
    assert set(client.calls) == {"triage_agent", "worker_agent"}
    terminal = next(
        event
        for event in events
        if event.get("choices", [{}])[0].get("finish_reason") == "stop"
    )
    routing_evidence = terminal["orchestration"]["routing"]
    assert routing_evidence["served_candidate_id"] == "worker_agent"
    assert set(routing_evidence["attempted_candidate_ids"]) == {
        "triage_agent",
        "worker_agent",
    }


class _StreamedConductTriageClient(ModelClient):
    """Triage reports "needs conduct"; every subsequent conduct-step call
    returns text distinguishable by agent id."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def chat(self, agent, messages, temperature=None, top_p=None, effort_profile=None):
        self.calls.append(agent.id)
        if messages and "workflow_required" in str(messages[0].get("content")):
            return '{"workflow_required": true}'
        return f"{agent.id} output"


def test_auto_stream_shares_candidate_scope_with_triage_when_conducting() -> None:
    """When a streamed auto-mode request's triage decides it needs the
    conduct workflow (not the direct route), server.py falls through past
    the ``with orchestrator.candidate_routing_policy(...)`` block that ran
    the triage call and into ``CostRoutingCoordinator.complete()`` -- which,
    absent ``candidate_scope_open=True``, would open its own independent
    scope and silently discard the triage agent's already-recorded attempt.
    This mirrors test_auto_stream_shares_candidate_scope_with_triage_when_triage_and_worker_differ
    above, but for the conduct branch instead of the route branch (#983,
    "Conducted streams omit triage attempts")."""
    client = _StreamedConductTriageClient()
    orchestrator = TaskOrchestrator(
        [
            # Lower priority than every conduct-role agent below, so the
            # free-only triage ranking picks it (it's the only free_only
            # candidate) while the general (non-free) ranking used for
            # every conduct role always prefers the higher-priority agents
            # instead -- otherwise triage_agent could win a conduct role
            # too and appear in attempted_candidate_ids regardless of
            # whether the scope-sharing fix under test is applied.
            ModelAgent("triage_agent", "model-triage", tags=("cost:free",), priority=10),
            ModelAgent("thinker_agent", "model-thinker", priority=20),
            ModelAgent("worker_agent", "model-worker", priority=20),
            ModelAgent("verifier_agent", "model-verifier", priority=20),
            ModelAgent("synth_agent", "model-synth", priority=20),
            ModelAgent("excluded_agent", "model-excluded", priority=20),
        ],
        client=client,
    )
    token = "conduct-triage-scope-token"
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=token)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, events = _post_sse(
            server.server_address[1],
            token,
            {
                "model": "orchestrator/auto",
                "messages": [{"role": "user", "content": "please conduct this"}],
                "stream": True,
                "routing": {"exclude_candidate_ids": ["excluded_agent"]},
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200
    assert "triage_agent" in client.calls
    terminal = next(
        event
        for event in events
        if event.get("choices", [{}])[0].get("finish_reason") == "stop"
    )
    routing_evidence = terminal["orchestration"]["routing"]
    assert "triage_agent" in routing_evidence["attempted_candidate_ids"]


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
    for routing in (
        {"candidate_id": " candidate_b"},
        {"exclude_candidate_ids": ["candidate_a", " candidate_a"]},
    ):
        with pytest.raises(RequestError) as exact_id_error:
            _validate_routing(routing, allow_candidate_controls=True)
        assert exact_id_error.value.code == "invalid_routing"


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


def test_conduct_pin_rejects_candidate_excluded_from_required_role() -> None:
    client = _CandidateClient()
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("worker_only", "model-worker", provider_exclusions=("verifier",)),
            ModelAgent("all_roles", "model-all"),
        ],
        client=client,
    )
    token = "candidate-conduct-token"
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post(
            server.server_address[1],
            token,
            {
                "model": "orchestrator/auto",
                "orchestration": "conduct",
                "messages": [{"role": "user", "content": "conduct this"}],
                "routing": {"candidate_id": "worker_only"},
            },
        )
        route_status, _ = _post(
            server.server_address[1],
            token,
            {
                "model": "orchestrator/auto",
                "orchestration": "route",
                "messages": [{"role": "user", "content": "route this"}],
                "routing": {"candidate_id": "worker_only"},
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 400
    assert body["error"]["code"] == "invalid_routing"
    assert route_status == 200
    assert client.calls and set(client.calls) == {"worker_only"}


def test_response_routing_evidence_is_not_persisted_in_workflow_history() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent("candidate_b", "model-b")], client=_CandidateClient()
    )
    response = CostRoutingCoordinator(orchestrator).complete(
        [{"role": "user", "content": "route this"}],
        mode="route",
        model_name="orchestrator/auto",
        workflow_run_id="run_candidate_evidence",
        hints={"candidate_id": "candidate_b"},
    )

    assert response["candidate_routing"]["candidate_id"] == "candidate_b"
    assert "candidate_routing" not in orchestrator.get_workflow_run(
        "run_candidate_evidence"
    )


def test_coordinator_auto_preflights_conduct_roles_before_triage() -> None:
    """Direct coordinator callers get the same provider-free auto preflight
    as HTTP callers: auto may select conduct, so a pin must satisfy every
    conduct role before model-backed triage is allowed to run.
    """
    client = _ConductTriageClient()
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

    with pytest.raises(ValueError, match="eligible agent"):
        CostRoutingCoordinator(orchestrator).complete(
            [{"role": "user", "content": "conduct this"}],
            mode="auto",
            model_name="orchestrator/auto",
            hints={"candidate_id": "worker_only"},
        )

    assert client.calls == []


def test_coordinator_plain_proxy_preflights_only_worker_role() -> None:
    """Plain provider requests must not require conduct-only role eligibility."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "worker_only",
                "worker-model",
                provider_exclusions=("verifier",),
            )
        ],
        client=_CandidateClient(),
    )
    observed: list[bool] = []

    def proxy_completion(*_args, **_kwargs):
        observed.append(orchestrator._request_candidate_allowed(orchestrator.agents[0]))
        return {
            "model": "worker-model",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            "orchestration": {"workflow_run_id": "run_plain_candidate"},
        }

    orchestrator.proxy_completion = proxy_completion  # type: ignore[method-assign]
    orchestrator.get_workflow_run = lambda _run_id: {  # type: ignore[method-assign]
        "workflow_run_id": "run_plain_candidate",
        "mode": "route",
        "answer": "worker answer",
        "trace": [],
    }

    result = CostRoutingCoordinator(orchestrator).complete(
        [{"role": "user", "content": "plain proxy"}],
        mode="auto",
        model_name="orchestrator/auto",
        hints={"candidate_id": "worker_only"},
        provider_request={
            "model": "orchestrator/auto",
            "messages": [{"role": "user", "content": "plain proxy"}],
        },
    )

    assert observed == [True]
    assert result["orchestration"]["workflow_run_id"] == "run_plain_candidate"


def test_coordinator_never_republishes_provider_supplied_candidate_routing_without_active_controls() -> None:
    """A raw provider response that happens to already contain a
    ``_candidate_routing`` key (an unrelated/coincidental or adversarial
    provider extension sharing the gateway's own internal sentinel field
    name) must never be republished as gateway-computed
    ``orchestration.routing`` evidence when this request had no active
    candidate control. ``TaskOrchestrator.proxy_completion`` only ever sets
    that key itself when ``_candidate_routing_evidence`` actually ran and
    returned non-None (which requires an active control), so observing the
    key here with no active control can only mean it arrived on the
    provider's own untrusted response body (#983 Devin finding: "Provider
    fields forge routing evidence")."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("worker_only", "worker-model")],
        client=_CandidateClient(),
    )

    def proxy_completion(*_args, **_kwargs):
        return {
            "model": "worker-model",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            "orchestration": {"workflow_run_id": "run_forged_evidence"},
            # An adversarial/coincidental provider-supplied field sharing
            # the gateway's own internal sentinel name.
            "_candidate_routing": {
                "served_candidate_id": "attacker_controlled_agent",
                "attempted_candidate_ids": ["attacker_controlled_agent"],
                "exclude_candidate_ids": [],
            },
        }

    orchestrator.proxy_completion = proxy_completion  # type: ignore[method-assign]
    orchestrator.get_workflow_run = lambda _run_id: {  # type: ignore[method-assign]
        "workflow_run_id": "run_forged_evidence",
        "mode": "route",
        "answer": "worker answer",
        "trace": [],
    }

    result = CostRoutingCoordinator(orchestrator).complete(
        [{"role": "user", "content": "plain proxy"}],
        mode="auto",
        model_name="orchestrator/auto",
        provider_request={
            "model": "orchestrator/auto",
            "messages": [{"role": "user", "content": "plain proxy"}],
        },
    )

    assert "routing" not in result["orchestration"]


def test_http_tool_loop_never_republishes_provider_supplied_candidate_routing_or_crashes() -> None:
    """Mirror of the coordinator-level forging test above, but for the HTTP
    single-agent tool-loop passthrough (server.py's ``proxy_tool_request``),
    which additionally must not crash when the provider's own
    "orchestration" field (if any) is not a mapping -- both are untrusted
    provider response content the gateway must never trust or blindly merge
    into (#983 Devin findings: "Provider fields forge routing evidence" and
    "Provider metadata crashes tool responses")."""

    class _ForgedProviderEvidenceClient(_CandidateClient):
        def proxy_send_once(self, agent, endpoint, payload):
            response = super().proxy_send_once(agent, endpoint, payload)
            # Adversarial/coincidental provider fields sharing the
            # gateway's own internal sentinel names.
            response["_candidate_routing"] = {
                "served_candidate_id": "attacker_controlled_agent",
                "attempted_candidate_ids": ["attacker_controlled_agent"],
                "exclude_candidate_ids": [],
            }
            response["orchestration"] = "not-a-mapping"
            return response

        proxy_send = proxy_send_once

    client = _ForgedProviderEvidenceClient()
    orchestrator = TaskOrchestrator(
        [ModelAgent("worker_only", "worker-model")],
        client=client,
    )
    token = "forged-evidence-token"
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=token)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post(server.server_address[1], token, _tool_body())
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200, body
    # No active candidate control was requested, so the gateway must never
    # have touched the provider's own (malformed) "orchestration" field --
    # not crashed on it, and not overwritten it with forged evidence.
    assert body.get("orchestration") == "not-a-mapping"
    assert "attacker_controlled_agent" not in json.dumps(body)


def test_endpoint_scoped_preflight_rejects_pin_and_exclusion_conflicts() -> None:
    """routing.endpoint plus a candidate_id/exclude_candidate_ids naming an
    agent configured on a *different* endpoint must fail the same 400
    invalid_routing preflight as any other ineligible pin -- never pass
    preflight and only then blow up as a selection RuntimeError/500."""
    client = _CandidateClient()
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("candidate_a", "model-a", base_url="https://a.example/v1"),
            ModelAgent("candidate_b", "model-b", base_url="https://b.example/v1"),
        ],
        client=client,
    )
    token = "candidate-endpoint-token"
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=token)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for routing in (
            # candidate_b is not reachable on endpoint A: a pin conflict.
            {"endpoint": "https://a.example", "candidate_id": "candidate_b"},
            # candidate_a is the only agent reachable on endpoint A: excluding
            # it leaves nothing selection could actually serve from A.
            {"endpoint": "https://a.example", "exclude_candidate_ids": ["candidate_a"]},
        ):
            chat_status, chat_body = _post(
                server.server_address[1],
                token,
                {
                    "model": "orchestrator/auto",
                    "messages": [{"role": "user", "content": "hi"}],
                    "routing": routing,
                },
            )
            assert chat_status == 400, chat_body
            assert chat_body["error"]["code"] == "invalid_routing", chat_body

            responses_status, responses_body = _post_responses(
                server.server_address[1],
                token,
                {"model": "orchestrator/auto", "input": "hi", "routing": routing},
            )
            assert responses_status == 400, responses_body
            assert (
                responses_body["error"]["code"] == "invalid_routing"
            ), responses_body
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert client.calls == []


def test_generated_planner_attempt_is_recorded_even_when_unused_by_steps() -> None:
    """The generated planner call is itself a real provider call; routing
    evidence must include that candidate even when the plan it returns never
    reassigns it to a later role."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("planner_agent", "model-planner"),
            ModelAgent(
                "worker_agent", "model-worker", provider_exclusions=("thinker",)
            ),
            ModelAgent("excluded_agent", "model-excluded"),
        ]
    )

    def plan(_agent, _messages, **_kwargs):
        return json.dumps(
            {
                "steps": [
                    {
                        "id": 0,
                        "role": "worker",
                        "agent_id": "worker_agent",
                        "subtask": "work",
                        "access": [],
                    },
                    {
                        "id": 1,
                        "role": "synthesizer",
                        "agent_id": "worker_agent",
                        "subtask": "answer",
                        "access": [0],
                    },
                ]
            }
        )

    orchestrator.client.chat = plan  # type: ignore[method-assign]
    with orchestrator.candidate_routing_policy(
        {"exclude_candidate_ids": ["excluded_agent"]}
    ):
        steps = orchestrator._plan_generated("plan this")
        evidence = orchestrator._candidate_routing_evidence({"trace": []})

    # worker_agent is the only agent eligible for "thinker" once
    # worker_agent's own provider_exclusions rule it out, so planner_agent
    # is deterministically the planner -- and never appears in a step.
    assert {step.agent_id for step in steps} == {"worker_agent"}
    assert evidence["attempted_candidate_ids"] == ["planner_agent"]


def test_served_candidate_id_matches_verifier_rejected_worker_fallback(
    monkeypatch,
) -> None:
    """conduct() (template plan) can serve the worker's output -- not the
    synthesizer's -- when a required verifier rejects the synthesized
    result. Every step's provider call still lands in the trace, so routing
    evidence must report whichever candidate actually produced ``answer``,
    not whichever step happened to execute last."""

    class _AgentIdClient(ModelClient):
        def chat(self, agent, messages, effort_profile=None):
            return f"{agent.id} output"

    orchestrator = TaskOrchestrator(
        [
            ModelAgent("thinker_agent", "model-thinker"),
            ModelAgent("worker_agent", "model-worker"),
            ModelAgent("verifier_agent", "model-verifier"),
            ModelAgent("synth_agent", "model-synth"),
            ModelAgent("excluded_agent", "model-excluded"),
        ],
        client=_AgentIdClient(),
    )
    monkeypatch.setattr(
        orchestrator,
        "_plan",
        lambda task, *, model_name=TaskOrchestrator.GATEWAY_DEFAULT_MODEL: [
            WorkflowStep(0, "thinker", "thinker_agent", "decompose"),
            WorkflowStep(1, "worker", "worker_agent", "work", (0,)),
            WorkflowStep(2, "verifier", "verifier_agent", "verify", (0, 1)),
            WorkflowStep(3, "synthesizer", "synth_agent", "synthesize", (0, 1, 2)),
        ],
    )
    monkeypatch.setattr(
        orchestrator,
        "_model_judge_verification",
        lambda *args, **kwargs: {
            "accepted": False,
            "reason": "test forces rejection",
            "verifier_output": "verifier_agent output",
            "judge": "model",
        },
    )

    with orchestrator.candidate_routing_policy(
        {"exclude_candidate_ids": ["excluded_agent"]}
    ):
        result = orchestrator.conduct([{"role": "user", "content": "task"}])
        evidence = orchestrator._candidate_routing_evidence(result)

    assert [row["agent_id"] for row in result["trace"]] == [
        "thinker_agent",
        "worker_agent",
        "verifier_agent",
        "synth_agent",
    ]
    assert result["answer"] == "worker_agent output"
    assert evidence["served_candidate_id"] == "worker_agent"


def test_served_candidate_id_matches_generated_worker_fallback(monkeypatch) -> None:
    """Same fallback identity guarantee as the template-plan case above, but
    for a generated plan whose final step is a synthesizer distinct from the
    worker whose output actually gets served on rejection."""

    class _AgentIdClient(ModelClient):
        def chat(self, agent, messages, effort_profile=None):
            return f"{agent.id} output"

    orchestrator = TaskOrchestrator(
        [
            ModelAgent("worker_agent", "model-worker"),
            ModelAgent("verifier_agent", "model-verifier"),
            ModelAgent("synth_agent", "model-synth"),
            ModelAgent("excluded_agent", "model-excluded"),
        ],
        client=_AgentIdClient(),
    )
    orchestrator.policy = dataclasses.replace(
        orchestrator.policy, workflow_planning="generated"
    )
    monkeypatch.setattr(
        orchestrator,
        "_plan_generated",
        lambda task: [
            WorkflowStep(0, "worker", "worker_agent", "work"),
            WorkflowStep(1, "verifier", "verifier_agent", "verify", (0,)),
            WorkflowStep(2, "synthesizer", "synth_agent", "synthesize", (0, 1)),
        ],
    )
    monkeypatch.setattr(
        orchestrator,
        "_model_judge_verification",
        lambda *args, **kwargs: {
            "accepted": False,
            "reason": "test forces rejection",
            "verifier_output": "verifier_agent output",
            "judge": "model",
        },
    )

    with orchestrator.candidate_routing_policy(
        {"exclude_candidate_ids": ["excluded_agent"]}
    ):
        result = orchestrator.conduct([{"role": "user", "content": "task"}])
        evidence = orchestrator._candidate_routing_evidence(result)

    assert result["plan_source"] == "generated"
    assert [row["agent_id"] for row in result["trace"]] == [
        "worker_agent",
        "verifier_agent",
        "synth_agent",
    ]
    assert result["answer"] == "worker_agent output"
    assert evidence["served_candidate_id"] == "worker_agent"


def test_served_candidate_id_prefers_earliest_row_on_duplicate_fallback_text(
    monkeypatch,
) -> None:
    """When a *later* synthesizer step happens to emit byte-identical text to
    the worker's already-served fallback answer, routing evidence must still
    name the worker (the candidate actually served) and not the synthesizer,
    whose trace row merely duplicates the text after the fact. The fallback
    worker step always runs -- and is recorded in the trace -- strictly
    before any step whose output could coincidentally match it, so preferring
    the earliest text match is safe (#983 finding 3, the minimal fix: the
    prior ``reversed()`` walk preferred the *latest* text match and could
    misidentify a coincidental duplicate as the served candidate)."""

    class _CollidingClient(ModelClient):
        def chat(self, agent, messages, effort_profile=None):
            if agent.id == "synth_agent":
                # Deliberately duplicate the worker's fallback text so two
                # trace rows share the exact same "output" as `answer`.
                return "worker_agent output"
            return f"{agent.id} output"

    orchestrator = TaskOrchestrator(
        [
            ModelAgent("thinker_agent", "model-thinker"),
            ModelAgent("worker_agent", "model-worker"),
            ModelAgent("verifier_agent", "model-verifier"),
            ModelAgent("synth_agent", "model-synth"),
            ModelAgent("excluded_agent", "model-excluded"),
        ],
        client=_CollidingClient(),
    )
    monkeypatch.setattr(
        orchestrator,
        "_plan",
        lambda task, *, model_name=TaskOrchestrator.GATEWAY_DEFAULT_MODEL: [
            WorkflowStep(0, "thinker", "thinker_agent", "decompose"),
            WorkflowStep(1, "worker", "worker_agent", "work", (0,)),
            WorkflowStep(2, "verifier", "verifier_agent", "verify", (0, 1)),
            WorkflowStep(3, "synthesizer", "synth_agent", "synthesize", (0, 1, 2)),
        ],
    )
    monkeypatch.setattr(
        orchestrator,
        "_model_judge_verification",
        lambda *args, **kwargs: {
            "accepted": False,
            "reason": "test forces rejection",
            "verifier_output": "verifier_agent output",
            "judge": "model",
        },
    )

    with orchestrator.candidate_routing_policy(
        {"exclude_candidate_ids": ["excluded_agent"]}
    ):
        result = orchestrator.conduct([{"role": "user", "content": "task"}])
        evidence = orchestrator._candidate_routing_evidence(result)

    assert [row["agent_id"] for row in result["trace"]] == [
        "thinker_agent",
        "worker_agent",
        "verifier_agent",
        "synth_agent",
    ]
    # Both the worker row (index 1) and the synthesizer row (index 3) now
    # carry output == "worker_agent output" -- the fallback answer -- but
    # only the worker was actually served.
    assert result["trace"][1]["output"] == "worker_agent output"
    assert result["trace"][3]["output"] == "worker_agent output"
    assert result["answer"] == "worker_agent output"
    assert evidence["served_candidate_id"] == "worker_agent"


def test_served_candidate_id_matches_later_step_on_duplicate_accepted_text(
    monkeypatch,
) -> None:
    """Mirror image of the fallback-duplicate case above: here the verifier
    *accepts* the synthesizer's output, so the synthesizer -- not the worker
    -- is the genuinely served candidate, even though the synthesizer's
    output happens to duplicate the worker's earlier text byte-for-byte. No
    earliest/latest ordering over text matches can be correct for both this
    case and the fallback case simultaneously: routing evidence must resolve
    the served row from ``answering_step_id`` (the step conduct() actually
    served), not from which row's text happens to match first (#983,
    "Duplicate outputs misidentify served candidate" -- the exact
    mirror-image of the fallback-duplicate fix above)."""

    class _CollidingClient(ModelClient):
        def chat(self, agent, messages, effort_profile=None):
            if agent.id in ("worker_agent", "synth_agent"):
                # Deliberately duplicate text across an earlier and a later
                # step so two trace rows share the exact same "output".
                return "duplicate output"
            return f"{agent.id} output"

    orchestrator = TaskOrchestrator(
        [
            ModelAgent("thinker_agent", "model-thinker"),
            ModelAgent("worker_agent", "model-worker"),
            ModelAgent("verifier_agent", "model-verifier"),
            ModelAgent("synth_agent", "model-synth"),
            ModelAgent("excluded_agent", "model-excluded"),
        ],
        client=_CollidingClient(),
    )
    monkeypatch.setattr(
        orchestrator,
        "_plan",
        lambda task, *, model_name=TaskOrchestrator.GATEWAY_DEFAULT_MODEL: [
            WorkflowStep(0, "thinker", "thinker_agent", "decompose"),
            WorkflowStep(1, "worker", "worker_agent", "work", (0,)),
            WorkflowStep(2, "verifier", "verifier_agent", "verify", (0, 1)),
            WorkflowStep(3, "synthesizer", "synth_agent", "synthesize", (0, 1, 2)),
        ],
    )
    monkeypatch.setattr(
        orchestrator,
        "_model_judge_verification",
        lambda *args, **kwargs: {
            "accepted": True,
            "reason": "test forces acceptance",
            "verifier_output": "verifier_agent output",
            "judge": "model",
        },
    )

    with orchestrator.candidate_routing_policy(
        {"exclude_candidate_ids": ["excluded_agent"]}
    ):
        result = orchestrator.conduct([{"role": "user", "content": "task"}])
        evidence = orchestrator._candidate_routing_evidence(result)

    assert [row["agent_id"] for row in result["trace"]] == [
        "thinker_agent",
        "worker_agent",
        "verifier_agent",
        "synth_agent",
    ]
    # Both the worker row (index 1) and the synthesizer row (index 3) carry
    # output == "duplicate output" -- the accepted answer -- but only the
    # synthesizer (the later, genuinely served step) actually produced it.
    assert result["trace"][1]["output"] == "duplicate output"
    assert result["trace"][3]["output"] == "duplicate output"
    assert result["answer"] == "duplicate output"
    assert result["answering_step_id"] == 3
    assert evidence["served_candidate_id"] == "synth_agent"


def test_run_persists_answering_step_id_for_candidate_routing_evidence(
    monkeypatch,
) -> None:
    """``TaskOrchestrator.run()`` persists a workflow-run record built from
    ``conduct()``'s result; it must carry ``answering_step_id`` through, or
    every ``run()``-based caller that resolves routing evidence from the
    persisted record -- chiefly ``CostRoutingCoordinator.complete()`` in
    cost_router.py, the coordinator/HTTP ordinary chat and non-streamed
    Responses path -- loses that identity and falls back to the fragile
    text-match heuristic, which can misattribute a duplicate-text answer to
    an earlier step (#983 Devin finding: "Duplicate outputs misidentify
    serving candidate"). This is the same scenario as
    ``test_served_candidate_id_matches_later_step_on_duplicate_accepted_text``
    above, but exercised through ``run()`` -- the exact record-construction
    boundary the finding named -- instead of calling ``conduct()``
    directly."""

    class _CollidingClient(ModelClient):
        def chat(self, agent, messages, effort_profile=None):
            if agent.id in ("worker_agent", "synth_agent"):
                # Deliberately duplicate text across an earlier and a later
                # step so two trace rows share the exact same "output".
                return "duplicate output"
            return f"{agent.id} output"

    orchestrator = TaskOrchestrator(
        [
            ModelAgent("thinker_agent", "model-thinker"),
            ModelAgent("worker_agent", "model-worker"),
            ModelAgent("verifier_agent", "model-verifier"),
            ModelAgent("synth_agent", "model-synth"),
            ModelAgent("excluded_agent", "model-excluded"),
        ],
        client=_CollidingClient(),
    )
    monkeypatch.setattr(
        orchestrator,
        "_plan",
        lambda task, *, model_name=TaskOrchestrator.GATEWAY_DEFAULT_MODEL: [
            WorkflowStep(0, "thinker", "thinker_agent", "decompose"),
            WorkflowStep(1, "worker", "worker_agent", "work", (0,)),
            WorkflowStep(2, "verifier", "verifier_agent", "verify", (0, 1)),
            WorkflowStep(3, "synthesizer", "synth_agent", "synthesize", (0, 1, 2)),
        ],
    )
    monkeypatch.setattr(
        orchestrator,
        "_model_judge_verification",
        lambda *args, **kwargs: {
            "accepted": True,
            "reason": "test forces acceptance",
            "verifier_output": "verifier_agent output",
            "judge": "model",
        },
    )

    with orchestrator.candidate_routing_policy(
        {"exclude_candidate_ids": ["excluded_agent"]}
    ):
        record = orchestrator.run(
            [{"role": "user", "content": "task"}], mode="conduct"
        )
        evidence = orchestrator._candidate_routing_evidence(record)

    assert [row["output"] for row in record["trace"]][1] == "duplicate output"
    assert [row["output"] for row in record["trace"]][3] == "duplicate output"
    assert record["answer"] == "duplicate output"
    assert record["answering_step_id"] == 3
    assert evidence is not None
    assert evidence["served_candidate_id"] == "synth_agent"


def test_candidate_routing_evidence_fails_closed_without_answering_step_id() -> None:
    """A historical workflow without explicit serving identity must not infer one."""

    orchestrator = TaskOrchestrator(
        [
            ModelAgent("worker_agent", "model-worker"),
            ModelAgent("excluded_agent", "model-excluded"),
        ]
    )

    with orchestrator.candidate_routing_policy(
        {"exclude_candidate_ids": ["excluded_agent"]}
    ):
        orchestrator._record_candidate_attempt("worker_agent")
        evidence = orchestrator._candidate_routing_evidence(
            {
                "answer": "worker_agent output",
                "trace": [
                    {"id": 0, "agent_id": "worker_agent", "output": "worker_agent output"},
                ],
            }
        )

    assert evidence is not None
    assert "served_candidate_id" not in evidence


def test_orchestrated_provider_completion_answering_step_id_identifies_synthesis_over_duplicate_internal_step() -> None:
    """The structured/tool-loop path built by ``_orchestrated_provider_completion``
    persists an internal ``conduct()`` workflow plus its own final synthesis
    row. When the synthesizer's output happens to duplicate an earlier
    internal workflow step's text byte-for-byte, routing evidence must still
    resolve to the synthesizer that actually served the response -- not to
    the internal step it duplicates -- by recording ``answering_step_id`` on
    the persisted workflow record, mirroring ``conduct()``'s own fix (#983
    Devin finding: "Repeated output misidentifies served candidate")."""
    agents = [
        ModelAgent("synth_agent", "synth-model", "mock://catalog"),
        ModelAgent("excluded_agent", "excluded-model", "mock://catalog"),
    ]
    orchestrator = TaskOrchestrator(agents)
    orchestrator._select_agent = lambda *_args, **_kwargs: agents[0]  # type: ignore[method-assign]
    orchestrator._failover_candidates = lambda *_args, **_kwargs: [agents[0]]  # type: ignore[method-assign]
    orchestrator.conduct = lambda *_args, **_kwargs: {  # type: ignore[method-assign]
        "trace": [
            {
                "id": 0,
                "role": "worker",
                "agent_id": "internal_worker",
                "output": "duplicate text",
            },
        ],
        "verification": None,
    }

    def send(agent, _endpoint, _payload):
        return {"choices": [{"message": {"content": "duplicate text"}}]}

    orchestrator.client.proxy_send_once = send

    with orchestrator.candidate_routing_policy(
        {"exclude_candidate_ids": ["excluded_agent"]}
    ):
        result = orchestrator._orchestrated_provider_completion(
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "messages": [{"role": "user", "content": "task"}],
            },
            endpoint="chat/completions",
            effort_profile=None,
        )
        workflow_id = result["orchestration"]["workflow_run_id"]
        persisted = orchestrator.get_workflow_run(workflow_id)
        evidence = orchestrator._candidate_routing_evidence(persisted)

    assert [row["output"] for row in persisted["trace"]] == [
        "duplicate text",
        "duplicate text",
    ]
    assert persisted["answer"] == "duplicate text"
    assert persisted["answering_step_id"] == persisted["trace"][1]["id"]
    assert persisted["trace"][1]["agent_id"] == "synth_agent"
    assert evidence is not None
    assert evidence["served_candidate_id"] == "synth_agent"


def test_orchestrated_provider_completion_answering_step_id_identifies_repair_over_duplicate_internal_step() -> None:
    """Mirror of the synthesis-duplicate case above for the repair branch:
    when the caller's ``response_format`` rejects the first synthesis
    attempt and the *repair* retry succeeds with output that duplicates an
    earlier internal workflow step's text, routing evidence must resolve to
    the repair row (the one that actually produced ``answer``), not the
    internal step it duplicates. No earliest/latest text-match ordering can
    be correct for both this case and the synthesis-duplicate case
    simultaneously -- exactly why ``answering_step_id`` must point at the
    repair row here (#983 Devin finding: "Repeated output misidentifies
    served candidate", suggested-fix case: "synthesis and repair output
    duplicate an earlier workflow step")."""
    agents = [
        ModelAgent("synth_agent", "synth-model", "mock://catalog"),
        ModelAgent("excluded_agent", "excluded-model", "mock://catalog"),
    ]
    orchestrator = TaskOrchestrator(agents)
    orchestrator._select_agent = lambda *_args, **_kwargs: agents[0]  # type: ignore[method-assign]
    orchestrator._failover_candidates = lambda *_args, **_kwargs: [agents[0]]  # type: ignore[method-assign]
    orchestrator.conduct = lambda *_args, **_kwargs: {  # type: ignore[method-assign]
        "trace": [
            {
                "id": 0,
                "role": "worker",
                "agent_id": "internal_worker",
                "output": '{"final": "true"}',
            },
        ],
        "verification": None,
    }

    calls: list[str] = []

    def send(agent, _endpoint, _payload):
        calls.append(agent.id)
        if len(calls) == 1:
            return {"choices": [{"message": {"content": "not valid json"}}]}
        return {"choices": [{"message": {"content": '{"final": "true"}'}}]}

    orchestrator.client.proxy_send_once = send

    with orchestrator.candidate_routing_policy(
        {"exclude_candidate_ids": ["excluded_agent"]}
    ):
        result = orchestrator._orchestrated_provider_completion(
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "messages": [{"role": "user", "content": "task"}],
                "response_format": {"type": "json_object"},
            },
            endpoint="chat/completions",
            effort_profile=None,
        )
        workflow_id = result["orchestration"]["workflow_run_id"]
        persisted = orchestrator.get_workflow_run(workflow_id)
        evidence = orchestrator._candidate_routing_evidence(persisted)

    assert calls == ["synth_agent", "synth_agent"]
    assert [row["role"] for row in persisted["trace"]] == [
        "worker",
        "synthesizer",
        "repair",
    ]
    assert persisted["trace"][0]["output"] == '{"final": "true"}'
    assert persisted["trace"][1]["output"] == "not valid json"
    assert persisted["trace"][2]["output"] == '{"final": "true"}'
    assert persisted["answer"] == '{"final": "true"}'
    assert persisted["answering_step_id"] == persisted["trace"][2]["id"]
    assert persisted["trace"][2]["agent_id"] == "synth_agent"
    assert evidence is not None
    assert evidence["served_candidate_id"] == "synth_agent"


def test_http_structured_chat_preflight_rejects_vision_incompatible_pin() -> None:
    """A structured (response_format) chat request that carries an image must
    fail closed with invalid_routing when pinned to a candidate that lacks
    the "vision" tag, the same way the ordinary chat path already does --
    this branch previously validated only roles, so the incompatible pin
    would have surfaced later as a generic execution error instead (#983)."""
    client = _CandidateClient()
    orchestrator = TaskOrchestrator(
        [ModelAgent("worker_only", "worker-model")],
        client=client,
    )
    token = "structured-vision-token"
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
                "routing": {"candidate_id": "worker_only"},
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 400, body
    assert body["error"]["code"] == "invalid_routing"
    assert client.calls == []


def test_http_responses_provider_path_preflight_rejects_vision_incompatible_pin() -> None:
    """The raw single-agent /v1/responses provider passthrough (reached when
    a request is not eligible for orchestrated Responses handling, e.g. it
    carries response_format) must also fail closed with invalid_routing on a
    vision-incompatible pin -- this path previously ran only the early
    role-only preflight (#983)."""
    client = _CandidateClient()
    orchestrator = TaskOrchestrator(
        [ModelAgent("worker_only", "worker-model")],
        client=client,
    )
    token = "responses-vision-token"
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=token)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post_responses(
            server.server_address[1],
            token,
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "inspect"},
                            {
                                "type": "input_image",
                                "image_url": "data:image/png;base64,AA==",
                            },
                        ],
                    }
                ],
                "response_format": {"type": "json_object"},
                "routing": {"candidate_id": "worker_only"},
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 400, body
    assert body["error"]["code"] == "invalid_routing"
    assert client.calls == []
