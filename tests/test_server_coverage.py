"""Behavioural coverage for HTTP validation, admin surfaces, and operator CRUD."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
import contextual_orchestrator.server as server_module  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    RequestError,
    SecurityConfig,
    _coerce_json,
    _embeddings_attribution,
    _response_payload,
    _validate_attribution,
    _validate_batch_requests,
    _validate_embeddings_inputs,
    _validate_messages,
    _validate_mode,
    _validate_routing,
    build_server,
)

TOKEN = "coverage-token"


def _build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing", "planning", "research")),
            ModelAgent("review_agent", "mock-reviewer", tags=("verification", "security", "review")),
        ]
    )


@contextlib.contextmanager
def _running_server(orchestrator: TaskOrchestrator, **security_kwargs):
    security = SecurityConfig(auth_token=TOKEN, rate_limit_requests=1000, **security_kwargs)
    server = build_server(orchestrator, port=0, security=security)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _request(
    base_url: str,
    method: str,
    path: str,
    payload: object | None = None,
    *,
    token: str | None = TOKEN,
    content_type: str = "application/json",
    raw_body: bytes | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, object, dict[str, str]]:
    headers = {"connection": "close"}
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    if payload is not None or raw_body is not None:
        headers["content-type"] = content_type
    if extra_headers:
        headers.update(extra_headers)
    data = raw_body if raw_body is not None else (json.dumps(payload).encode("utf-8") if payload is not None else None)
    request = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read()
            parsed: object
            if response.headers.get("content-type", "").startswith("application/json"):
                parsed = json.loads(body.decode("utf-8"))
            else:
                parsed = body.decode("utf-8")
            return response.status, parsed, dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        parsed = json.loads(body.decode("utf-8")) if body else {}
        return exc.code, parsed, dict(exc.headers.items())


def test_security_and_validation_branches_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Validation helpers reject malformed security, request, and attribution shapes."""
    with pytest.raises(ValueError):
        SecurityConfig(admin_token="admin-only")

    assert SecurityConfig(auth_token="shared").readiness_profile()["auth_mode"] == "single_token"
    assert SecurityConfig(admin_token="a", inference_token="i").readiness_profile()["auth_mode"] == "split_token"
    assert SecurityConfig().readiness_profile()["auth_mode"] == "auth_not_configured"

    security = SecurityConfig(auth_token="shared", rate_limit_requests=2, rate_limit_window_seconds=1)
    security._rate_buckets["client"] = (2, time.monotonic() - 1)
    security.check_rate_limit("client")
    assert security._rate_buckets["client"][0] == 1

    assert _validate_mode("route") == "route"
    for invalid in (None, 1, "invalid"):
        with pytest.raises(RequestError):
            _validate_mode(invalid)

    with pytest.raises(RequestError):
        _validate_messages([])
    with pytest.raises(RequestError):
        _validate_messages(["not-an-object"])
    with pytest.raises(RequestError):
        _validate_messages([{"role": "owner", "content": "hello"}])
    assert _validate_messages([{"role": "user", "content": "hello", "ignored": True}]) == [
        {"role": "user", "content": "hello"}
    ]

    assert _validate_attribution(None) is None
    with pytest.raises(RequestError):
        _validate_attribution("team-a")
    with pytest.raises(RequestError):
        _validate_attribution({"unknown_dimension": "x"})
    assert _validate_attribution({"team": 7, "provider": "mock"}) == {"team": "7", "provider": "mock"}

    assert _validate_routing(None) is None
    with pytest.raises(RequestError):
        _validate_routing("batch")
    with pytest.raises(RequestError):
        _validate_routing({"unexpected": True})
    with pytest.raises(RequestError):
        _validate_routing({"channel": "async"})
    assert _validate_routing({"channel": "batch", "priority": "low"}) == {"channel": "batch", "priority": "low"}

    with pytest.raises(RequestError):
        _coerce_json(b"[]")
    assert _coerce_json(b'{"ok": true}') == {"ok": True}

    with pytest.raises(RequestError):
        _validate_embeddings_inputs({})
    with pytest.raises(RequestError):
        _validate_embeddings_inputs({"input": ["ok", 3]})
    assert _validate_embeddings_inputs({"input": "one"}) == ["one"]

    with pytest.raises(RequestError):
        _embeddings_attribution({"metadata": "bad"})
    assert _embeddings_attribution(
        {
            "metadata": {"team": "metadata-team", "source": "ignored", "company": "acme", "group": ""},
            "attribution": {"team": "explicit-team"},
        }
    ) == {"team": "explicit-team", "company": "acme"}

    with pytest.raises(RequestError):
        _validate_batch_requests({}, False)
    with pytest.raises(RequestError):
        _validate_batch_requests({"requests": ["bad"]}, False)
    batch = _validate_batch_requests(
        {
            "model": "default-model",
            "attribution": {"company": "acme"},
            "requests": [
                {
                    "messages": [{"role": "user", "content": "hello"}],
                    "model": "child-model",
                    "attribution": {"team": "alpha"},
                    "mode": "conduct",
                }
            ],
        },
        False,
    )
    assert batch[0].model == "child-model"
    assert batch[0].attribution == {"company": "acme", "team": "alpha"}
    assert batch[0].mode == "conduct"

    safe = _response_payload({"trace": [{"secret": "Bearer abcdefghijklmnopqrstuvwxyz"}], "nested": [{"trace": [1]}]}, False)
    assert "trace" not in safe


def test_admin_get_matrix_covers_commercial_and_resource_routes() -> None:
    """Authenticated admin GETs expose every buyer packet and resource outcome."""
    orchestrator = _build()
    workflow = orchestrator.run([{"role": "user", "content": "build and verify the buyer packet"}], mode="route")
    workflow_run_id = workflow["workflow_run_id"]
    evaluation = orchestrator.run_evaluation(["replay buyer readiness"], mode="route")
    evaluation_run_id = evaluation["evaluation_run_id"]

    commercial_paths = [
        "/api/v1/sales_readiness/latest",
        "/api/v1/commercial_readiness/latest",
        "/api/v1/buyer_evidence_manifests/latest",
        "/api/v1/buyer_handoff_bundles/latest",
        "/api/v1/saleability_decisions/latest",
        "/api/v1/commercial_evidence_exports/latest",
        "/api/v1/commercial_acceptance_checks/latest",
        "/api/v1/commercial_release_candidates/latest",
        "/api/v1/commercial_gap_registers/latest",
        "/api/v1/commercial_procurement_readiness/latest",
        "/api/v1/commercial_contract_readiness/latest",
        "/api/v1/commercial_onboarding_readiness/latest",
        "/api/v1/commercial_operations_readiness/latest",
        "/api/v1/commercial_security_attestations/latest",
        "/api/v1/commercial_value_readiness/latest",
        "/api/v1/commercial_close_readiness/latest",
        "/api/v1/commercial_go_to_market_readiness/latest",
        "/api/v1/commercial_launch_readiness/latest",
        "/api/v1/commercial_completion_scorecards/latest",
        "/api/v1/commercial_buyer_acceptance_workflows/latest",
        "/api/v1/commercial_demo_scenarios/latest",
        "/api/v1/commercial_proposal_packets/latest",
        "/api/v1/commercial_purchase_approval_packets/latest",
        "/api/v1/commercial_due_diligence_rooms/latest",
        "/api/v1/commercial_investment_committee_memos/latest",
    ]

    with _running_server(orchestrator) as base_url:
        for path in commercial_paths:
            status, body, _headers = _request(base_url, "GET", path)
            assert status == 200, (path, body)
            assert isinstance(body, dict)

        success_paths = [
            "/api/v1/cost_attribution_dimensions",
            "/api/v1/cost_reports/rollup?dimension=model_name",
            "/api/v1/llm_usage_records?page_number=1&page_size=10",
            "/api/v1/agent_pools?page_number=1&page_size=10",
            "/api/v1/orchestration_policies/default_policy",
            "/api/v1/analytics_snapshots/latest",
            "/api/v1/spend_analytics/latest",
            "/admin/state",
            "/api/v1/workflow_runs?page_number=1&page_size=10",
            f"/api/v1/workflow_runs/{workflow_run_id}",
            f"/api/v1/access_reports/{workflow_run_id}",
            f"/api/v1/evaluation_runs/{evaluation_run_id}",
            "/api/v1/agent_pools/default_pool/worker_agents/general_agent",
            "/api/v1/locale_bundles/en",
        ]
        for path in success_paths:
            status, body, _headers = _request(base_url, "GET", path)
            assert status == 200, (path, body)

        error_cases = [
            ("/api/v1/cost_reports/rollup?dimension=not-a-dimension", 400, "invalid_dimension"),
            ("/api/v1/llm_usage_records?start=not-an-int", 400, "invalid_request"),
            ("/api/v1/agent_pools?page_number=0", 400, "invalid_request"),
            ("/api/v1/agent_pools?page_size=101", 400, "invalid_request"),
            ("/api/v1/workflow_runs/missing", 404, "workflow_run_not_found"),
            ("/api/v1/access_reports/missing", 404, "workflow_run_not_found"),
            ("/api/v1/evaluation_runs/missing", 404, "evaluation_run_not_found"),
            ("/api/v1/agent_pools/default_pool/worker_agents/missing", 404, "agent_not_found"),
            ("/api/v1/agent_pools/default_pool/not_worker/missing", 400, "bad_path"),
            ("/api/v1/locale_bundles/not-a-locale", 404, "locale_not_found"),
            ("/api/v1/not-a-route", 404, "route_not_found"),
            ("/api/v1/batch_routing_jobs/missing", 404, "batch_job_not_found"),
        ]
        for path, expected_status, expected_code in error_cases:
            status, body, _headers = _request(base_url, "GET", path)
            assert status == expected_status, (path, body)
            assert isinstance(body, dict)
            assert body["error"]["code"] == expected_code


def test_agent_crud_batch_and_post_error_matrix() -> None:
    """POST/PATCH/DELETE cover operator CRUD, batch surfaces, and HTTP-safe failures."""
    orchestrator = _build()
    with _running_server(orchestrator, max_body_bytes=1024) as base_url:
        create_payload = {
            "id": "coverage_agent",
            "model": "mock-coverage",
            "base_url": "mock://coverage",
            "tags": ["reasoning"],
            "priority": 5,
        }
        status, body, _ = _request(base_url, "POST", "/api/v1/agent_pools/default_pool/worker_agents", create_payload)
        assert status == 201
        assert body["id"] == "coverage_agent"

        status, body, _ = _request(
            base_url,
            "PATCH",
            "/api/v1/agent_pools/default_pool/worker_agents/coverage_agent",
            {"priority": 9, "tags": ["reasoning", "review"]},
        )
        assert status == 200
        assert body["priority"] == 9

        status, body, _ = _request(base_url, "DELETE", "/api/v1/agent_pools/default_pool/worker_agents/coverage_agent")
        assert status == 200

        status, body, _ = _request(
            base_url,
            "PATCH",
            "/api/v1/agent_pools/default_pool/worker_agents/missing",
            {"priority": 2},
        )
        assert status == 404
        assert body["error"]["code"] == "resource_not_found"

        status, body, _ = _request(base_url, "DELETE", "/api/v1/agent_pools/default_pool/worker_agents/missing")
        assert status == 404
        assert body["error"]["code"] == "resource_not_found"

        for method, path in [
            ("PATCH", "/api/v1/agent_pools/default_pool/extra/worker_agents/missing"),
            ("DELETE", "/api/v1/agent_pools/default_pool/extra/worker_agents/missing"),
        ]:
            status, body, _ = _request(base_url, method, path, {} if method == "PATCH" else None)
            assert status == 400
            assert body["error"]["code"] == "bad_path"

        status, body, _ = _request(
            base_url,
            "PATCH",
            "/api/v1/agent_pools/default_pool/worker_agents/general_agent",
            {"unknown": True},
        )
        assert status == 400
        assert body["error"]["code"] == "unknown_fields"

        status, body, _ = _request(
            base_url,
            "POST",
            "/api/v1/agent_pools/default_pool/extra/worker_agents",
            create_payload,
        )
        assert status == 400
        assert body["error"]["code"] == "bad_path"

        status, body, _ = _request(base_url, "POST", "/admin/simulate", {"prompt": 3})
        assert status == 400
        assert body["error"]["code"] == "invalid_request"

        status, body, _ = _request(base_url, "POST", "/admin/simulate", {"prompt": "simulate", "mode": "route"})
        assert status == 200
        assert isinstance(body, dict)

        status, body, _ = _request(base_url, "POST", "/api/v1/workflow_runs", {"prompt_text": "run this", "run_mode": "route"})
        assert status == 201
        assert body["mode"] == "route"

        status, body, _ = _request(base_url, "POST", "/api/v1/workflow_runs", {"prompt_text": ""})
        assert status == 400
        assert body["error"]["code"] == "invalid_request"

        status, body, _ = _request(base_url, "POST", "/api/v1/evaluation_runs", {"prompt_text": "evaluate this", "run_mode": "route"})
        assert status == 201
        assert body["prompt_count"] == 1

        status, body, _ = _request(base_url, "POST", "/api/v1/evaluation_runs", {"prompts": []})
        assert status == 400
        assert body["error"]["code"] == "invalid_request"

        status, body, _ = _request(
            base_url,
            "POST",
            "/v1/batch/embeddings",
            {"model": "mock-embedding", "input": ["alpha", "beta"], "metadata": {"team": "coverage"}},
        )
        assert status in {200, 202}
        assert isinstance(body, dict)
        batch_id = body["batch_id"]
        poll_status, poll_body, _ = _request(base_url, "GET", f"/v1/batch/embeddings/{batch_id}")
        assert poll_status == 200
        assert poll_body["batch_id"] == batch_id

        status, body, _ = _request(base_url, "GET", "/v1/batch/embeddings/missing")
        assert status == 404
        assert body["error"]["code"] == "embeddings_batch_not_found"

        status, body, _ = _request(
            base_url,
            "POST",
            "/api/v1/batch_routing_jobs",
            {
                "model": "mock-generalist",
                "requests": [
                    {"messages": [{"role": "user", "content": "batch hello"}], "mode": "route"}
                ],
            },
        )
        assert status == 201
        job_id = body["job_id"]

        status, body, _ = _request(base_url, "GET", f"/api/v1/batch_routing_jobs/{job_id}")
        assert status == 200
        assert body["job_id"] == job_id

        status, body, _ = _request(base_url, "POST", f"/api/v1/batch_routing_jobs/{job_id}/results", {})
        assert status == 200
        assert isinstance(body, dict)

        status, body, _ = _request(base_url, "POST", "/api/v1/batch_routing_jobs/missing/results", {})
        assert status == 404
        assert body["error"]["code"] == "batch_job_not_found"

        status, body, _ = _request(base_url, "POST", "/v1/responses", {"model": "mock-generalist", "input": "respond"})
        assert status == 200
        assert isinstance(body, dict)

        status, body, _ = _request(base_url, "POST", "/not-a-route", {})
        assert status == 404
        assert body["error"]["code"] == "route_not_found"

        status, body, _ = _request(base_url, "POST", "/admin/simulate", raw_body=b"{not-json")
        assert status == 400
        assert body["error"]["code"] == "invalid_json"

        status, body, _ = _request(
            base_url,
            "POST",
            "/admin/simulate",
            {"prompt": "text"},
            content_type="text/plain",
        )
        assert status == 415
        assert body["error"]["code"] == "unsupported_media_type"

        status, body, _ = _request(
            base_url,
            "POST",
            "/admin/simulate",
            raw_body=b"x" * 1025,
            extra_headers={"content-type": "application/json"},
        )
        assert status == 413
        assert body["error"]["code"] == "request_too_large"


def test_document_surfaces_and_buffered_stream_preserve_content_types() -> None:
    """OpenAPI, admin HTML, and buffered SSE return their public wire formats."""
    orchestrator = _build()
    with _running_server(orchestrator) as base_url:
        status, body, headers = _request(base_url, "GET", "/openapi.json", token=None)
        assert status == 200
        assert isinstance(body, dict)
        assert body["info"]["title"] == "Contextual Orchestrator API"
        assert headers["content-type"].startswith("application/json")

        status, body, headers = _request(base_url, "GET", "/admin")
        assert status == 200
        assert "Contextual Orchestrator" in body
        assert headers["content-type"] == "text/html; charset=utf-8"

        status, body, headers = _request(
            base_url,
            "POST",
            "/v1/chat/completions",
            {
                "model": "contextual-orchestrator",
                "messages": [{"role": "user", "content": "plan, implement, and verify this change"}],
                "mode": "conduct",
                "stream": True,
            },
        )
        assert status == 200
        assert headers["content-type"] == "text/event-stream; charset=utf-8"
        assert '"object": "chat.completion.chunk"' in body
        assert body.endswith("data: [DONE]\n\n")


def test_live_stream_reports_a_terminal_error_after_headers_are_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A route stream failure terminates with an error frame and releases the slot."""
    orchestrator = _build()

    def failing_stream(_messages, workflow_run_id=None):
        yield "partial"
        raise RuntimeError("provider disconnected")

    monkeypatch.setattr(orchestrator, "stream_route", failing_stream)
    with _running_server(orchestrator) as base_url:
        status, body, headers = _request(
            base_url,
            "POST",
            "/v1/chat/completions",
            {
                "messages": [{"role": "user", "content": "stream this answer"}],
                "mode": "route",
                "stream": True,
            },
        )

    assert status == 200
    assert headers["content-type"] == "text/event-stream; charset=utf-8"
    assert '"content": "partial"' in body
    assert '"finish_reason": "error"' in body
    assert body.endswith("data: [DONE]\n\n")


def test_http_method_error_boundaries_return_stable_statuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PATCH, DELETE, GET, and POST convert domain and unexpected failures safely."""
    orchestrator = _build()
    with _running_server(orchestrator) as base_url:
        status, body, _ = _request(base_url, "PATCH", "/api/v1/not-a-route", {})
        assert status == 404
        assert body["error"]["code"] == "route_not_found"

        status, body, _ = _request(base_url, "DELETE", "/api/v1/not-a-route")
        assert status == 404
        assert body["error"]["code"] == "route_not_found"

        status, body, _ = _request(
            base_url,
            "PATCH",
            "/api/v1/agent_pools/default_pool/worker_agents/general_agent",
            {"status": "not-a-status"},
        )
        assert status == 400
        assert body["error"]["code"] == "invalid_request"

        monkeypatch.setattr(orchestrator, "remove_agent", lambda *_args: (_ for _ in ()).throw(ValueError("last agent")))
        status, body, _ = _request(
            base_url,
            "DELETE",
            "/api/v1/agent_pools/default_pool/worker_agents/general_agent",
        )
        assert status == 400
        assert body["error"]["code"] == "invalid_request"

        failure_cases = [
            ("admin_state", "GET", "/admin/state", None),
            (
                "patch_agent",
                "PATCH",
                "/api/v1/agent_pools/default_pool/worker_agents/general_agent",
                {"priority": 3},
            ),
            (
                "remove_agent",
                "DELETE",
                "/api/v1/agent_pools/default_pool/worker_agents/general_agent",
                None,
            ),
            (
                "add_agent",
                "POST",
                "/api/v1/agent_pools/default_pool/worker_agents",
                {"id": "new_agent", "model": "mock-new", "base_url": "mock://new"},
            ),
        ]
        for method_name, http_method, path, payload in failure_cases:
            monkeypatch.setattr(
                orchestrator,
                method_name,
                lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unexpected failure")),
            )
            status, body, _ = _request(base_url, http_method, path, payload)
            assert status == 500, (method_name, body)
            assert body["error"]["code"] == "internal_error"


def test_serve_starts_the_built_server(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The blocking serve entrypoint announces its address and starts serving."""
    started: list[bool] = []

    class FakeServer:
        def serve_forever(self) -> None:
            started.append(True)

    monkeypatch.setattr(server_module, "build_server", lambda *_args, **_kwargs: FakeServer())
    server_module.serve(_build(), host="127.0.0.1", port=8765)

    assert started == [True]
    assert capsys.readouterr().out == "listening on http://127.0.0.1:8765\n"
