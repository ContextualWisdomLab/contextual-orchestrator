"""One-shot exact-head repair for PR #909's final review contracts."""

from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    """Replace one reviewed block or fail closed."""
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one replacement in {path}; found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def append_once(path: str, marker: str, addition: str) -> None:
    """Append one regression test only when its marker is absent."""
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if marker in text:
        raise SystemExit(f"{marker} already exists in {path}")
    target.write_text(text + addition, encoding="utf-8")


def main() -> None:
    """Apply exact model, OpenAPI, and already-started SSE error boundaries."""
    replace_once(
        "contextual_orchestrator/cost_router.py",
        '''class BatchModelSelectionError(RuntimeError):
    """Raised when a batch request has no eligible model-group member."""


class CostRoutingCoordinator:
''',
        '''class BatchModelSelectionError(RuntimeError):
    """Raised when a batch request has no eligible model-group member."""


class InvalidBatchModelError(ValueError):
    """Raised only for an unknown client-supplied batch model identity."""


class CostRoutingCoordinator:
''',
    )
    replace_once(
        "contextual_orchestrator/cost_router.py",
        '''        try:
            prepared_requests = [self._resolve_batch_request(request) for request in requests]
        except ValueError:
            raise
        except RuntimeError as exc:
''',
        '''        try:
            prepared_requests = [self._resolve_batch_request(request) for request in requests]
        except ValueError as exc:
            raise InvalidBatchModelError(str(exc)) from exc
        except RuntimeError as exc:
''',
    )
    replace_once(
        "contextual_orchestrator/server.py",
        '''from .cost_router import BatchModelSelectionError, CostRoutingCoordinator
''',
        '''from .cost_router import (
    BatchModelSelectionError,
    CostRoutingCoordinator,
    InvalidBatchModelError,
)
''',
    )
    replace_once(
        "contextual_orchestrator/server.py",
        '''                    except ValueError as exc:
                        raise RequestError(400, "invalid_model", str(exc)) from exc
''',
        '''                    except InvalidBatchModelError as exc:
                        raise RequestError(400, "invalid_model", str(exc)) from exc
''',
    )
    replace_once(
        "contextual_orchestrator/api_contract.py",
        '''                "responses": {"200": {"description": "Batch routing job status"}},
''',
        '''                "responses": {
                    "200": {"description": "Batch routing job status"},
                    "404": {
                        "description": "Batch job is missing or is not owned by the authenticated principal"
                    },
                },
''',
    )
    replace_once(
        "contextual_orchestrator/api_contract.py",
        '''                "responses": {"200": {"description": "Batch results with recorded usage"}},
''',
        '''                "responses": {
                    "200": {"description": "Batch results with recorded usage"},
                    "404": {
                        "description": "Batch job is missing or is not owned by the authenticated principal"
                    },
                },
''',
    )
    replace_once(
        "contextual_orchestrator/server.py",
        '''                if coordinator is not None:
                    result = {
                        **result,
                        **coordinator.record_stream_usage(
                            result=result,
                            attribution=attribution,
                            model_name=model_name,
                        ),
                    }
''',
        '''                if coordinator is not None:
                    try:
                        stream_usage = coordinator.record_stream_usage(
                            result=result,
                            attribution=attribution,
                            model_name=model_name,
                        )
                    except Exception:  # noqa: BLE001 - headers sent; remain inside SSE
                        failed = {
                            **created_response,
                            "status": "failed",
                            "error": {
                                "code": "usage_recording_failed",
                                "message": "Usage evidence could not be recorded for this response.",
                            },
                        }
                        emit("response.failed", response=failed)
                        self._write_sse("data: [DONE]\\n\\n")
                        return False
                    result = {**result, **stream_usage}
''',
    )

    append_once(
        "tests/test_cost_router_boundaries.py",
        "test_batch_model_identity_error_does_not_capture_backend_value_errors",
        '''


def test_batch_model_identity_error_does_not_capture_backend_value_errors() -> None:
    """Only model resolution receives the client-facing invalid-model category."""
    from contextual_orchestrator.batch_routing import BatchRequest
    from contextual_orchestrator.cost_router import InvalidBatchModelError

    class RejectingBackend:
        name = "rejecting-backend"

        def submit(self, requests, metadata=None):  # type: ignore[no-untyped-def]
            del requests, metadata
            raise ValueError("backend payload validation failed")

    coordinator = _coordinator(batch_backend=RejectingBackend())
    with pytest.raises(ValueError, match="backend payload validation failed") as backend_error:
        coordinator.submit_batch([
            BatchRequest(messages=[{"role": "user", "content": "valid"}], model="mock-a")
        ])
    assert type(backend_error.value) is ValueError

    with pytest.raises(InvalidBatchModelError, match="not configured"):
        coordinator.submit_batch([
            BatchRequest(
                messages=[{"role": "user", "content": "private"}],
                model="not-configured",
                zdr_only=True,
            )
        ])
''',
    )
    append_once(
        "tests/test_api_contract.py",
        "test_batch_job_openapi_documents_principal_hiding_404s",
        '''


def test_batch_job_openapi_documents_principal_hiding_404s() -> None:
    """Missing and foreign batch jobs share the documented not-found surface."""
    status = OPENAPI_SPEC["paths"][
        "/api/v1/batch_routing_jobs/{batch_routing_job_id}"
    ]["get"]["responses"]
    results = OPENAPI_SPEC["paths"][
        "/api/v1/batch_routing_jobs/{batch_routing_job_id}/results"
    ]["post"]["responses"]
    assert "404" in status
    assert "not owned" in status["404"]["description"]
    assert results["404"] == status["404"]
''',
    )
    append_once(
        "tests/test_orchestrated_responses_stream.py",
        "test_stream_usage_failure_remains_inside_the_started_sse_protocol",
        '''


def test_stream_usage_failure_remains_inside_the_started_sse_protocol(monkeypatch) -> None:
    """A post-header ledger failure emits Responses failure framing, never JSON HTTP."""
    token = "responses_stream_usage_failure_token"
    orchestrator = TaskOrchestrator([
        ModelAgent("workflow_agent", "mock-model", base_url="mock://provider")
    ])
    coordinator = CostRoutingCoordinator(orchestrator)

    def fail_usage(**_kwargs):
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(coordinator, "record_stream_usage", fail_usage)
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=token),
        coordinator=coordinator,
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        stream = _post(server, token, "orchestrator/auto")
    finally:
        server.shutdown()

    events = [
        json.loads(line[6:])
        for line in stream.splitlines()
        if line.startswith("data: {")
    ]
    assert events[-1]["type"] == "response.failed"
    assert events[-1]["response"]["error"]["code"] == "usage_recording_failed"
    assert all(event["type"] != "response.completed" for event in events)
    assert stream.rstrip().endswith("data: [DONE]")
''',
    )


if __name__ == "__main__":
    main()
