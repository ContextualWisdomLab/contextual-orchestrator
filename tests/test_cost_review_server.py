"""HTTP surface for the cost-review + routing hub: /healthz, rollup, batch routing."""

from __future__ import annotations

from pathlib import Path
import json
import secrets
import threading
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import (  # noqa: E402
    CostRoutingCoordinator,
    InMemoryConfigStore,
    ModelAgent,
    PriceBook,
    PriceEntry,
    TaskOrchestrator,
)
from contextual_orchestrator.server import SecurityConfig, _readiness_payload, build_server  # noqa: E402


def _serve(security=None):
    agents = [ModelAgent(id="mock_worker", model="mock-a", base_url="mock://a", provider_name="mock",
                         tags=("reasoning", "coding", "writing", "embedding"), priority=1)]
    orchestrator = TaskOrchestrator(agents)
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(PriceEntry("mock", "mock-a", prompt_price_per_1k=1.0, completion_price_per_1k=2.0))
    coordinator = CostRoutingCoordinator(orchestrator, config, price_book=price_book)
    token = "cost_token"
    server = build_server(
        orchestrator,
        port=0,
        security=security or SecurityConfig(auth_token=token),
        coordinator=coordinator,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1], token


def _request(method, url, token=None, body=None, status_ok=(200, 201, 202)):
    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:  # pragma: no cover - surfaced in asserts
        return exc.code, json.loads(exc.read())


def test_healthz_is_unauthenticated_and_ok() -> None:
    server, port, _token = _serve()
    try:
        status, body = _request("GET", f"http://127.0.0.1:{port}/healthz")
    finally:
        server.shutdown()
    assert status == 200
    assert body == {"status": "ok", "service": "contextual-orchestrator"}


def test_readyz_requires_admin_and_reports_secret_free_runtime_checks() -> None:
    server, port, token = _serve()
    base = f"http://127.0.0.1:{port}"
    try:
        status, body = _request("GET", f"{base}/readyz")
        assert status == 401
        assert body["error"]["code"] == "unauthorized"

        status, body = _request("GET", f"{base}/readyz", token)
    finally:
        server.shutdown()
    assert status == 200
    assert body["status"] == "ready"
    assert set(body["checks"]) == {"orchestration", "sync_routing", "batch_routing", "embedding_batch"}
    assert body["checks"]["batch_routing"] == {"status": "ready"}
    assert "usage_record_count" not in json.dumps(body)


def test_trace_read_endpoints_require_admin_authentication() -> None:
    """Trace and access-report reads must not become an unauthenticated data leak."""
    server, port, token = _serve()
    base = f"http://127.0.0.1:{port}"
    try:
        for path in (
            "/api/v1/workflow_runs",
            "/api/v1/workflow_runs/missing-run",
            "/api/v1/access_reports/missing-run",
        ):
            status, body = _request("GET", f"{base}{path}")
            assert status == 401
            assert body["error"]["code"] == "unauthorized"

        status, body = _request("GET", f"{base}/api/v1/workflow_runs", token)
        assert status == 200
        assert body["items"] == []
    finally:
        server.shutdown()


def test_trace_read_defaults_cannot_bypass_trace_purpose_authorization() -> None:
    """Default trace exposure still requires the separate trace purpose scope."""
    admin_token = secrets.token_urlsafe(32)
    inference_token = secrets.token_urlsafe(32)
    security = SecurityConfig(
        auth_token="",
        admin_token=admin_token,
        inference_token=inference_token,
        expose_trace_by_default=True,
    )
    server, port, _token = _serve(security)
    try:
        status, body = _request(
            "GET",
            f"http://127.0.0.1:{port}/api/v1/workflow_runs",
            admin_token,
        )
    finally:
        server.shutdown()
    assert status == 401
    assert body["error"]["code"] == "unauthorized"


def test_access_report_requires_trace_purpose_before_resource_lookup() -> None:
    """Hide both owned and missing access reports from a non-trace principal."""
    token = "admin_inference_only"
    security = SecurityConfig(
        bearer_verifier=lambda presented, scope: (
            presented == token and scope in {"admin", "inference"}
        )
    )
    server, port, _ = _serve(security)
    base = f"http://127.0.0.1:{port}"
    try:
        status, created = _request(
            "POST",
            f"{base}/api/v1/workflow_runs",
            token,
            {
                "prompt_text": "owner-bound trace evidence",
                "run_mode": "conduct",
                "include_orchestration_trace": False,
            },
        )
        assert status == 201, created
        for run_id in (created["workflow_run_id"], "missing_run"):
            status, body = _request(
                "GET", f"{base}/api/v1/access_reports/{run_id}", token
            )
            assert status == 401
            assert body["error"]["code"] == "unauthorized"
            assert body["error"]["message"] == "bearer token is invalid for this scope"
    finally:
        server.shutdown()


def test_readiness_never_exposes_backend_identifiers() -> None:
    agents = [ModelAgent(id="mock_worker", model="mock-a", base_url="mock://a")]
    orchestrator = TaskOrchestrator(agents)
    coordinator = CostRoutingCoordinator(orchestrator)

    class Backend:
        name = "https://provider.invalid/api?token=secret"

    coordinator.batch_backend = Backend()
    coordinator.embedding_batch_backend = Backend()
    body, status = _readiness_payload(orchestrator, coordinator)

    assert status == 200
    assert body["checks"]["batch_routing"] == {"status": "ready"}
    assert "provider.invalid" not in json.dumps(body)
    assert "secret" not in json.dumps(body)


def test_readiness_uses_the_current_routed_embedding_backend() -> None:
    agents = [
        ModelAgent(id="mock_worker", model="mock-a", base_url="mock://a"),
        ModelAgent(
            id="embedding_worker",
            model="embedding-model",
            base_url="https://provider.example/v1",
            tags=("embedding",),
        ),
    ]
    orchestrator = TaskOrchestrator(agents)
    coordinator = CostRoutingCoordinator(orchestrator)
    coordinator.embedding_batch_backend = object()

    body, status = _readiness_payload(orchestrator, coordinator)

    assert status == 200
    assert body["checks"]["embedding_batch"] == {"status": "ready"}


def test_readiness_keeps_interactive_service_ready_when_optional_batch_degrades() -> None:
    agents = [ModelAgent(id="mock_worker", model="mock-a", base_url="mock://a")]
    orchestrator = TaskOrchestrator(agents)
    coordinator = CostRoutingCoordinator(orchestrator)
    coordinator.batch_backend = object()

    body, status = _readiness_payload(orchestrator, coordinator)

    assert status == 200
    assert body["status"] == "ready_with_degraded_optional_dependencies"
    assert body["checks"]["batch_routing"] == {"status": "degraded"}


def test_chat_completion_reports_real_usage_and_records_cost() -> None:
    server, port, token = _serve()
    base = f"http://127.0.0.1:{port}"
    try:
        status, body = _request("POST", f"{base}/v1/chat/completions", token,
                                 {"model": "mock-a",
                                  "messages": [{"role": "user", "content": "hello there world"}],
                                  "attribution": {"team": "alpha", "company": "acme"}})
        assert status == 200
        assert body["usage"]["total_tokens"] > 0
        assert body["orchestration"]["channel"] == "sync"

        status, report = _request("GET", f"{base}/api/v1/cost_reports/rollup?dimension=team", token)
        assert status == 200
        values = {item["dimension_value"]: item for item in report["items"]}
        assert "alpha" in values
        assert values["alpha"]["record_count"] == 1
    finally:
        server.shutdown()


def test_chat_completion_fallback_path_labels_estimated_measurement_status() -> None:
    """Provider-unreported usage stays honestly labeled estimated end to end."""
    server, port, token = _serve()
    base = f"http://127.0.0.1:{port}"
    try:
        status, body = _request(
            "POST",
            f"{base}/v1/chat/completions",
            token,
            {
                "model": "mock-a",
                "messages": [{"role": "user", "content": "hello there world"}],
            },
        )
        assert status == 200, body
        # The mock provider reports no usage, so both the completion cost
        # payload and the analytics usage-ledger rows must carry the explicit
        # estimated measurement status instead of claiming provider-measured.
        assert body["orchestration"]["cost"]["measurement_status"] == "estimated"

        status, records = _request("GET", f"{base}/api/v1/llm_usage_records", token)
        assert status == 200, records
        assert records["total_count"] == 1
        assert records["items"][0]["measurement_status"] == "estimated"
    finally:
        server.shutdown()


def test_structured_http_cost_contract_preserves_mixed_currency_components() -> None:
    """HTTP clients receive no implicit cross-currency total or conversion."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("mock_worker", "mock-a", base_url="mock://a")]
    )
    coordinator = CostRoutingCoordinator(orchestrator)
    coordinator.complete = lambda *args, **kwargs: {  # type: ignore[method-assign]
        "id": "chatcmpl_mixed",
        "object": "chat.completion",
        "model": "mock-a",
        "choices": [],
        "cost": {
            "cost_amount": None,
            "currency_code": "MIXED",
            "currency_components": [
                {"currency_code": "EUR", "cost_amount": 2.0},
                {"currency_code": "USD", "cost_amount": 1.0},
            ],
            "measurement_status": "measured",
            "customer_action": (
                "Review each currency component separately. Apply an approved "
                "exchange-rate source before calculating a combined total."
            ),
        },
    }
    token = "cost_token"
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=token),
        coordinator=coordinator,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _request(
            "POST",
            f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
            token,
            {
                "model": "mock-a",
                "messages": [{"role": "user", "content": "return JSON"}],
                "response_format": {"type": "json_object"},
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200
    assert body["cost"]["cost_amount"] is None
    assert body["cost"]["currency_code"] == "MIXED"
    assert body["cost"]["currency_components"] == [
        {"currency_code": "EUR", "cost_amount": 2.0},
        {"currency_code": "USD", "cost_amount": 1.0},
    ]
    assert "approved exchange-rate source" in body["cost"]["customer_action"]


def test_structured_chat_cost_records_keep_service_and_account_attribution() -> None:
    """Structured workflow calls roll up under the same chat dimensions."""
    server, port, token = _serve()
    base = f"http://127.0.0.1:{port}"
    try:
        status, body = _request(
            "POST",
            f"{base}/v1/chat/completions",
            token,
            {
                "model": "mock-a",
                "messages": [{"role": "user", "content": "return JSON"}],
                "response_format": {"type": "json_object"},
                "user": "account_123",
            },
        )
        assert status == 200, body

        for dimension, expected in (
            ("service", "chat_completions_api"),
            ("account", "account_123"),
        ):
            status, report = _request(
                "GET",
                f"{base}/api/v1/cost_reports/rollup?dimension={dimension}",
                token,
            )
            assert status == 200, report
            assert {item["dimension_value"] for item in report["items"]} == {expected}
    finally:
        server.shutdown()


def test_batch_routing_via_chat_completion_and_results_retrieval() -> None:
    server, port, token = _serve()
    base = f"http://127.0.0.1:{port}"
    try:
        status, submitted = _request("POST", f"{base}/v1/chat/completions", token,
                                     {"model": "mock-a",
                                      "messages": [{"role": "user", "content": "batch this"}],
                                      "routing": {"latency_tolerant": True},
                                      "attribution": {"company": "acme"}})
        assert status == 202
        assert submitted["channel"] == "batch"
        job_id = submitted["job_id"]

        status, polled = _request("GET", f"{base}/api/v1/batch_routing_jobs/{job_id}", token)
        assert status == 200
        assert polled["is_complete"] is True

        status, retrieved = _request("POST", f"{base}/api/v1/batch_routing_jobs/{job_id}/results", token)
        assert status == 200
        assert retrieved["result_count"] == 1

        status, report = _request("GET", f"{base}/api/v1/cost_reports/rollup?dimension=company", token)
        assert report["grand_total"]["record_count"] == 1
    finally:
        server.shutdown()


def test_batch_routing_jobs_endpoint_submits_multiple_requests() -> None:
    server, port, token = _serve()
    base = f"http://127.0.0.1:{port}"
    try:
        status, job = _request("POST", f"{base}/api/v1/batch_routing_jobs", token, {
            "attribution": {"company": "acme"},
            "requests": [
                {"messages": [{"role": "user", "content": "one"}]},
                {"messages": [{"role": "user", "content": "two"}], "attribution": {"team": "beta"}},
            ],
        })
        assert status == 201
        assert job["request_count"] == 2

        status, retrieved = _request("POST", f"{base}/api/v1/batch_routing_jobs/{job['job_id']}/results", token)
        assert retrieved["result_count"] == 2

        status, records = _request("GET", f"{base}/api/v1/llm_usage_records", token)
        assert records["total_count"] == 2
    finally:
        server.shutdown()


def test_batch_routing_jobs_are_bound_to_the_authenticated_principal() -> None:
    security = SecurityConfig(
        bearer_verifier=lambda token, _scope: token in {"owner-a", "owner-b"}
    )
    server, port, _token = _serve(security)
    base = f"http://127.0.0.1:{port}"
    try:
        status, job = _request(
            "POST",
            f"{base}/api/v1/batch_routing_jobs",
            "owner-a",
            {"requests": [{"messages": [{"role": "user", "content": "owner-bound"}]}]},
        )
        assert status == 201

        status, body = _request(
            "GET",
            f"{base}/api/v1/batch_routing_jobs/{job['job_id']}",
            "owner-b",
        )
        assert status == 404
        assert body["error"]["code"] == "batch_job_not_found"

        status, polled = _request(
            "GET",
            f"{base}/api/v1/batch_routing_jobs/{job['job_id']}",
            "owner-a",
        )
        assert status == 200
        assert polled["job_id"] == job["job_id"]

        status, body = _request(
            "POST",
            f"{base}/api/v1/batch_routing_jobs/{job['job_id']}/results",
            "owner-b",
        )
        assert status == 404
        assert body["error"]["code"] == "batch_job_not_found"

        status, retrieved = _request(
            "POST",
            f"{base}/api/v1/batch_routing_jobs/{job['job_id']}/results",
            "owner-a",
        )
        assert status == 200
        assert retrieved["result_count"] == 1
    finally:
        server.shutdown()


def test_batch_routing_jobs_round_trip_caller_supplied_custom_ids() -> None:
    """Without caller custom_ids, results cannot be mapped back to requests
    on backends that do not preserve submission order (the OpenAI Batch
    contract does not) -- the submit response never discloses generated ids.
    """
    server, port, token = _serve()
    base = f"http://127.0.0.1:{port}"
    try:
        status, job = _request("POST", f"{base}/api/v1/batch_routing_jobs", token, {
            "requests": [
                {"messages": [{"role": "user", "content": "one"}], "custom_id": "pair-7"},
                {"messages": [{"role": "user", "content": "two"}], "custom_id": "pair-42"},
            ],
        })
        assert status == 201

        status, retrieved = _request(
            "POST", f"{base}/api/v1/batch_routing_jobs/{job['job_id']}/results", token
        )
        assert status == 200
        assert {item["custom_id"] for item in retrieved["results"]} == {"pair-7", "pair-42"}
    finally:
        server.shutdown()


def test_batch_routing_jobs_reject_invalid_custom_ids() -> None:
    server, port, token = _serve()
    base = f"http://127.0.0.1:{port}"
    try:
        for bad_requests in (
            [
                {"messages": [{"role": "user", "content": "a"}], "custom_id": "dup"},
                {"messages": [{"role": "user", "content": "b"}], "custom_id": "dup"},
            ],
            [{"messages": [{"role": "user", "content": "a"}], "custom_id": "  "}],
            [{"messages": [{"role": "user", "content": "a"}], "custom_id": "x" * 65}],
            [{"messages": [{"role": "user", "content": "a"}], "custom_id": 7}],
        ):
            status, body = _request(
                "POST", f"{base}/api/v1/batch_routing_jobs", token,
                {"requests": bad_requests},
            )
            assert status == 400
            assert body["error"]["code"] == "invalid_request"
    finally:
        server.shutdown()


def test_batch_routing_jobs_reject_empty_or_non_string_models() -> None:
    """Reject malformed model identity before a batch reaches its worker."""
    server, port, token = _serve()
    base = f"http://127.0.0.1:{port}"
    try:
        for body in (
            {"model": " ", "requests": [{"messages": [{"role": "user", "content": "a"}]}]},
            {"requests": [{"model": 7, "messages": [{"role": "user", "content": "a"}]}]},
        ):
            status, response = _request(
                "POST", f"{base}/api/v1/batch_routing_jobs", token, body
            )
            assert status == 400
            assert response["error"]["code"] == "invalid_model"
    finally:
        server.shutdown()


def test_cost_report_rejects_unknown_dimension() -> None:
    server, port, token = _serve()
    base = f"http://127.0.0.1:{port}"
    try:
        status, body = _request("GET", f"{base}/api/v1/cost_reports/rollup?dimension=bogus", token)
    finally:
        server.shutdown()
    assert status == 400
    assert body["error"]["code"] == "invalid_dimension"


def test_dimension_catalog_endpoint_lists_all_dimensions() -> None:
    server, port, token = _serve()
    base = f"http://127.0.0.1:{port}"
    try:
        status, body = _request("GET", f"{base}/api/v1/cost_attribution_dimensions", token)
    finally:
        server.shutdown()
    assert status == 200
    assert body["total_count"] == 7


if __name__ == "__main__":  # pragma: no cover
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok {_name}")
    print("ok")
