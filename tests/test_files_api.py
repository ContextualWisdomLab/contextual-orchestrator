"""OpenAI-compatible Files boundary and provider-affinity tests."""

from __future__ import annotations

import tempfile
import json
import threading
import urllib.error
import urllib.request

import pytest

from contextual_orchestrator.batch_job_registry import JobRegistryFactory
from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.file_registry import FileRegistry
import contextual_orchestrator.server as server_module
from contextual_orchestrator.server import (
    MAX_BATCH_FILE_BYTES,
    MAX_FILE_UPLOAD_BYTES,
    MAX_FILE_UPLOAD_REQUEST_BYTES,
    RequestError,
    _multipart_upload_metadata,
    _request_body_size,
    SecurityConfig,
    build_server,
)


def _multipart(*, purpose: str = "user_data", filename: str = "sample.png", data: bytes = b"image") -> bytes:
    boundary = "test-boundary"
    return (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\n{purpose}\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()


def test_files_and_batch_boundaries_match_openai_contract_without_large_allocations() -> None:
    """Boundary arithmetic proves 512 MB Files and 200 MB Batch limits."""
    assert MAX_FILE_UPLOAD_REQUEST_BYTES > MAX_FILE_UPLOAD_BYTES
    assert (
        _request_body_size(
            {"content-length": str(MAX_FILE_UPLOAD_REQUEST_BYTES)},
            MAX_FILE_UPLOAD_REQUEST_BYTES,
        )
        == MAX_FILE_UPLOAD_REQUEST_BYTES
    )
    with pytest.raises(RequestError):
        _request_body_size(
            {"content-length": str(MAX_FILE_UPLOAD_REQUEST_BYTES + 1)},
            MAX_FILE_UPLOAD_REQUEST_BYTES,
        )
    assert MAX_BATCH_FILE_BYTES == 200 * 1024 * 1024


def test_multipart_metadata_reads_fields_and_exact_file_size_from_disk() -> None:
    """The parser extracts only metadata while the file remains disk-backed."""
    raw = _multipart(purpose="batch", filename="jobs.jsonl", data=b"{}\n")
    with tempfile.TemporaryFile() as body:
        body.write(raw)
        assert _multipart_upload_metadata(
            body, "multipart/form-data; boundary=test-boundary"
        ) == ("batch", "jobs.jsonl", 3)


def test_files_http_rejects_file_part_over_limit_before_provider_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multipart overhead cannot hide a file part above the 512 MB limit."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("files_agent", "mock-files", tags=("files",))]
    )
    monkeypatch.setattr(
        server_module,
        "_multipart_upload_metadata",
        lambda *_args: ("user_data", "oversized.bin", MAX_FILE_UPLOAD_BYTES + 1),
    )
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token="files-token"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/v1/files",
            data=_multipart(),
            headers={
                "Authorization": "Bearer files-token",
                "Content-Type": "multipart/form-data; boundary=test-boundary",
            },
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        assert caught.value.code == 413
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_file_registry_hides_provider_identity_and_enforces_principal_ownership() -> None:
    """Gateway ids remain opaque and cannot be resolved by another principal."""
    registry = FileRegistry(JobRegistryFactory())
    public = registry.register(
        {"id": "provider-secret-id", "object": "file", "bytes": 4},
        "agent-a",
        "principal-a",
        agent_affinity_key="affinity",
    )
    assert public["id"].startswith("file_")
    assert "provider-secret-id" not in str(public)
    owner = registry.owner(public["id"], "principal-a")
    assert owner.provider_file_id == "provider-secret-id"
    with pytest.raises(KeyError):
        registry.owner(public["id"], "principal-b")

    rewritten, bindings = registry.bind_request(
        {"input": [{"content": [{"type": "input_file", "file_id": public["id"]}]}]},
        "principal-a",
    )
    assert rewritten["input"][0]["content"][0]["file_id"] == public["id"]
    assert bindings[public["id"]]["agent-a"]["provider_file_id"] == "provider-secret-id"


def test_files_http_upload_list_retrieve_content_and_delete() -> None:
    """The public Files lifecycle retains opaque provider affinity end to end."""
    server = build_server(
        TaskOrchestrator([ModelAgent("files_agent", "mock-files", tags=("files",))]),
        port=0,
        security=SecurityConfig(auth_token="files-token"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def request(path: str, *, method: str = "GET", data: bytes | None = None, content_type: str | None = None):
        headers = {"Authorization": "Bearer files-token"}
        if content_type:
            headers["Content-Type"] = content_type
        with urllib.request.urlopen(
            urllib.request.Request(base + path, data=data, headers=headers, method=method)
        ) as response:
            return response.status, response.headers.get_content_type(), response.read()

    try:
        raw = _multipart()
        status, _, payload = request(
            "/v1/files",
            method="POST",
            data=raw,
            content_type="multipart/form-data; boundary=test-boundary",
        )
        assert status == 201
        created = json.loads(payload)
        file_id = created["id"]
        assert file_id.startswith("file_") and "provider_file_" not in payload.decode()

        _, _, payload = request("/v1/files")
        assert [item["id"] for item in json.loads(payload)["data"]] == [file_id]
        _, _, payload = request(f"/v1/files/{file_id}")
        assert json.loads(payload)["id"] == file_id
        _, content_type, payload = request(f"/v1/files/{file_id}/content")
        assert (content_type, payload) == ("video/mp4", b"mock video")
        _, _, payload = request(f"/v1/files/{file_id}", method="DELETE")
        assert json.loads(payload) == {"id": file_id, "object": "file", "deleted": True}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_files_upload_does_not_replicate_to_every_provider() -> None:
    """A default upload discloses the file to only the first eligible provider."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("first_files_agent", "mock-files", tags=("files",)),
            ModelAgent("second_files_agent", "mock-files", tags=("files",)),
        ]
    )
    uploaded_by: list[str] = []

    def proxy_upload(agent, *_args, **_kwargs):
        uploaded_by.append(agent.id)
        return {"id": f"provider_file_{agent.id}", "object": "file", "bytes": 5}

    orchestrator.client.proxy_upload = proxy_upload
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token="files-token"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/v1/files",
            data=_multipart(),
            headers={
                "Authorization": "Bearer files-token",
                "Content-Type": "multipart/form-data; boundary=test-boundary",
            },
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            assert response.status == 201
        assert uploaded_by == ["first_files_agent"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_files_upload_skips_provider_excluded_from_files() -> None:
    """A files tag cannot override the operator's provider exclusion."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "excluded_files_agent",
                "mock-files",
                tags=("files",),
                provider_exclusions=("files",),
            ),
            ModelAgent("eligible_files_agent", "mock-files", tags=("files",)),
        ]
    )
    uploaded_by: list[str] = []
    orchestrator.client.proxy_upload = (  # type: ignore[method-assign]
        lambda agent, *_args, **_kwargs: uploaded_by.append(agent.id)
        or {"id": f"provider_file_{agent.id}", "object": "file", "bytes": 5}
    )
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token="files-token"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/v1/files",
            data=_multipart(),
            headers={
                "Authorization": "Bearer files-token",
                "Content-Type": "multipart/form-data; boundary=test-boundary",
            },
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            assert response.status == 201
        assert uploaded_by == ["eligible_files_agent"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_files_delete_maps_provider_failure_to_retryable_503() -> None:
    """A failed provider deletion remains registered and can be retried."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("files_agent", "mock-files", tags=("files",))]
    )
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token="files-token"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    headers = {"Authorization": "Bearer files-token"}
    try:
        upload = urllib.request.Request(
            base + "/v1/files",
            data=_multipart(),
            headers={
                **headers,
                "Content-Type": "multipart/form-data; boundary=test-boundary",
            },
            method="POST",
        )
        with urllib.request.urlopen(upload) as response:
            file_id = json.loads(response.read())["id"]

        def unavailable(*_args, **_kwargs):
            raise urllib.error.HTTPError("provider", 503, "unavailable", {}, None)

        orchestrator.client.proxy_delete_json = unavailable  # type: ignore[method-assign]
        delete = urllib.request.Request(
            f"{base}/v1/files/{file_id}", headers=headers, method="DELETE"
        )
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(delete)
        assert caught.value.code == 503
        assert json.loads(caught.value.read())["error"]["code"] == "file_provider_unavailable"

        orchestrator.client.proxy_delete_json = (  # type: ignore[method-assign]
            lambda *_args, **_kwargs: {"deleted": True}
        )
        with urllib.request.urlopen(delete) as response:
            assert json.loads(response.read())["deleted"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
