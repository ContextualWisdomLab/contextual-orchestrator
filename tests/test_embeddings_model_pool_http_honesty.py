"""Embeddings model must match the agent pool over HTTP (fail-closed)."""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import CostRoutingCoordinator, ModelAgent, TaskOrchestrator
from contextual_orchestrator.server import SecurityConfig, build_server

_TEST_AUTH_TOKEN = "embeddings_model_pool_http_honesty_token"


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing", "embedding"))]
    )


def _post(port: int, path: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server():
    orchestrator = build()
    counter = type("ExactSyntheticCounter", (), {"count_text": lambda self, text, model="": len(text)})()
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN), coordinator=CostRoutingCoordinator(orchestrator, embedding_token_counter=counter))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def _server_without_embedding():
    server = build_server(
        TaskOrchestrator([ModelAgent("general_agent", "mock-planner", tags=("reasoning",))]),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_select_capability_agent_normalizes_and_rejects_empty_capability() -> None:
    """Capability selection normalizes names and rejects an empty capability."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("embedding_agent", "text-embedding-3-large", tags=("embedding",))]
    )
    assert orchestrator.select_capability_agent("  EMBEDDING ").id == "embedding_agent"
    try:
        orchestrator.select_capability_agent(" ")
    except ValueError as exc:
        assert str(exc) == "capability must be a non-empty string"
    else:
        raise AssertionError("empty capability must fail closed")


def test_select_capability_agent_skips_disabled_and_excluded_agents() -> None:
    """Capability selection skips disabled and provider-excluded candidates."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("disabled_embedding", "disabled", tags=("embedding",), disabled=True),
            ModelAgent(
                "excluded_embedding",
                "excluded",
                tags=("embedding",),
                provider_exclusions=("embedding",),
            ),
            ModelAgent("eligible_embedding", "eligible", tags=("embedding",)),
        ]
    )
    assert orchestrator.select_capability_agent("embedding").id == "eligible_embedding"

    unavailable = TaskOrchestrator(
        [
            ModelAgent("disabled_embedding", "disabled", tags=("embedding",), disabled=True),
            ModelAgent("reasoning_agent", "reasoning", tags=("reasoning",)),
        ]
    )
    try:
        unavailable.select_capability_agent("embedding")
    except RuntimeError as exc:
        assert str(exc) == "no enabled agent available for capability=embedding"
    else:
        raise AssertionError("an unavailable capability must fail closed")


def test_embedding_capability_skips_circuit_open_endpoint_until_half_open_probe() -> None:
    """Repeated endpoint failures quarantine one member without losing recovery."""
    first = ModelAgent("first_embedding", "embed-v1", tags=("embedding",))
    second = ModelAgent("second_embedding", "embed-v2", tags=("embedding",))
    orchestrator = TaskOrchestrator([first, second])

    for _ in range(orchestrator.circuit_failure_threshold):
        orchestrator._record_failure(first.id)

    assert [agent.id for agent in orchestrator._capability_agents("embedding")] == [
        second.id
    ]

    for _ in range(orchestrator.circuit_failure_threshold):
        orchestrator._record_failure(second.id)

    try:
        orchestrator._capability_agents("embedding")
    except RuntimeError as exc:
        assert str(exc) == "all enabled agents temporarily unavailable for capability=embedding"
    else:
        raise AssertionError("open embedding circuits must remain quarantined until cooldown")


def test_embedding_request_too_large_does_not_quarantine_endpoint() -> None:
    """A caller-specific 413 remains observable without penalizing endpoint health."""
    agent = ModelAgent("embedding_agent", "embed-v1", tags=("embedding",))
    orchestrator = TaskOrchestrator([agent])

    for _ in range(orchestrator.circuit_failure_threshold + 1):
        orchestrator._record_embedding_failure(
            agent,
            "/v1/embeddings",
            urllib.error.HTTPError("https://provider.invalid", 413, "too large", {}, None),
        )

    assert orchestrator._circuit_open(agent.id) is False
    failures = [
        event
        for event in orchestrator._analytics_events
        if event["event_name"] == "embedding_endpoint_failed"
    ]
    assert all(event["event_detail"]["provider_status"] == 413 for event in failures)


def test_explicit_embedding_model_returns_503_while_all_circuits_are_open() -> None:
    agent = ModelAgent("embedding_agent", "embed-v1", tags=("embedding",))
    orchestrator = TaskOrchestrator([agent])
    for _ in range(orchestrator.circuit_failure_threshold):
        orchestrator._record_failure(agent.id)
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN),
        coordinator=CostRoutingCoordinator(orchestrator),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for path in ("/v1/embeddings", "/v1/batch/embeddings"):
            status, body = _post(
                server.server_address[1],
                path,
                {"model": agent.model, "input": "invoice search chunk"},
            )
            assert status == 503, body
            assert body["error"]["code"] == "embeddings_unavailable"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_quarantines_repeated_400_endpoint_with_safe_evidence() -> None:
    """Stop selecting one repeatedly rejected endpoint and retain safe diagnostics.

    The `/v1/embeddings` failover order is now cost-ordered (see
    `CostRoutingCoordinator._cost_ordered_capability_candidates`): a single
    recorded failure already drops the failing member's measured health
    below the healthy threshold, demoting it behind every still-healthy
    candidate on the very next request -- a strictly faster, price-aware
    replacement for the older fixed `circuit_failure_threshold`-strikes
    breaker this test originally pinned. The endpoint is still quarantined
    (never selected again once a healthy alternative exists) and the
    recorded failure evidence stays exception-message-free either way.
    """
    first = ModelAgent(
        "rejected_embedding", "embed-v1", tags=("embedding",), priority=1
    )
    second = ModelAgent("healthy_embedding", "embed-v1", tags=("embedding",))
    orchestrator = TaskOrchestrator([first, second])
    coordinator = CostRoutingCoordinator(orchestrator)
    attempted: list[str] = []

    def complete_embeddings_batch(_inputs, *, agent_id, **_kwargs):
        attempted.append(agent_id)
        if agent_id == first.id:
            raise urllib.error.HTTPError(
                "https://provider.invalid/embeddings", 400, "Bad Request", {}, None
            )
        return {
            "status": "completed",
            "embeddings": [{"index": 0, "embedding": [0.25]}],
            "total_tokens": 1,
        }

    coordinator.complete_embeddings_batch = complete_embeddings_batch
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN),
        coordinator=coordinator,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for _ in range(orchestrator.circuit_failure_threshold + 1):
            status, body = _post(
                server.server_address[1],
                "/v1/embeddings",
                {"model": "embed-v1", "input": "invoice search chunk"},
            )
            assert status == 200, body

        # The first request attempts the rejected member once (demoting it),
        # then falls back to the healthy member; every later request in this
        # loop selects only the now-healthier member and never retries the
        # quarantined one.
        assert attempted == [first.id] + [second.id] * (orchestrator.circuit_failure_threshold + 1)
        failures = [
            event
            for event in orchestrator._analytics_events
            if event["event_name"] == "embedding_endpoint_failed"
        ]
        assert len(failures) == 1
        assert all(event["event_detail"]["provider_status"] == 400 for event in failures)
        assert all("provider.invalid" not in json.dumps(event) for event in failures)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_batch_embedding_submission_success_clears_prior_endpoint_failures() -> None:
    """An accepted asynchronous job proves the endpoint is responsive."""
    agent = ModelAgent("embedding_agent", "embed-v1", tags=("embedding",))
    orchestrator = TaskOrchestrator([agent])
    orchestrator._record_failure(agent.id)
    coordinator = CostRoutingCoordinator(orchestrator)
    coordinator.complete_embeddings_batch = lambda *_args, **_kwargs: {
        "status": "validating",
        "batch_id": "batch_accepted",
        "backend": "remote",
    }
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN),
        coordinator=coordinator,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post(
            server.server_address[1],
            "/v1/batch/embeddings",
            {"model": "embed-v1", "input": "invoice search chunk"},
        )
        assert status == 202, body
        assert agent.id not in orchestrator._circuit
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_rejects_model_outside_agent_pool() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {"model": "text-embedding-3-not-deployed", "input": "invoice search chunk"},
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_model" in blob
        assert "text-embedding-3-not-deployed" in blob
        assert "agent pool" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_accepts_model_in_agent_pool() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {"model": "mock-planner", "input": "invoice search chunk"},
        )
        assert status == 200, body
        assert body.get("object") == "list"
        assert body.get("model") == "mock-planner"
        assert isinstance(body.get("data"), list) and body["data"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_auto_selects_enabled_embedding_agent() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, "/v1/embeddings", {"input": "invoice search chunk"})
        assert status == 200, body
        assert body.get("model") == "mock-planner"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_null_model_is_rejected() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, "/v1/embeddings", {"model": None, "input": "invoice"})
        assert status == 400, body
        assert "invalid_model" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_auto_selection_fails_when_capability_is_missing() -> None:
    server, thread, port = _server_without_embedding()
    try:
        status, body = _post(port, "/v1/embeddings", {"input": "invoice search chunk"})
        assert status == 503, body
        assert "embedding_unavailable" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_rejects_explicit_model_without_embedding_capability() -> None:
    """An in-pool model without the ``embedding`` tag fails closed on /v1/embeddings.

    Regression: capability gating must also bind when the caller names a pool
    member explicitly; otherwise a reasoning-only deployment would silently
    serve embedding traffic after an operator re-tags the pool.
    """
    server, thread, port = _server_without_embedding()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {"model": "mock-planner", "input": "invoice search chunk"},
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_model" in blob
        assert "agent pool" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_rejects_explicit_excluded_embedding_model() -> None:
    """An explicit model cannot bypass its provider capability exclusion."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "excluded_embedding",
                "excluded",
                tags=("embedding",),
                provider_exclusions=("embedding",),
            )
        ]
    )
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post(
            server.server_address[1],
            "/v1/embeddings",
            {"model": "excluded", "input": "invoice search chunk"},
        )
        assert status == 400, body
        assert "invalid_model" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_rejects_model_outside_agent_pool() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/batch/embeddings",
            {"model": "text-embedding-3-not-deployed", "inputs": ["alpha", "beta"]},
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_model" in blob
        assert "agent pool" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_accepts_model_in_agent_pool() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/batch/embeddings",
            {"model": "mock-planner", "inputs": ["alpha", "beta"]},
        )
        assert status == 200, body
        assert body.get("status") == "completed"
        assert body.get("model") == "mock-planner"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_auto_selects_enabled_embedding_agent() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, "/v1/batch/embeddings", {"inputs": ["alpha", "beta"]})
        assert status == 200, body
        assert body.get("model") == "mock-planner"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_embeddings_rejects_model_outside_agent_pool()
    test_http_embeddings_accepts_model_in_agent_pool()
    test_http_embeddings_auto_selects_enabled_embedding_agent()
    test_http_batch_embeddings_rejects_model_outside_agent_pool()
    test_http_batch_embeddings_accepts_model_in_agent_pool()
    test_http_batch_embeddings_auto_selects_enabled_embedding_agent()
    print("ok")
