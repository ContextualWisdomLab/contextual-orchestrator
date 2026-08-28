"""OpenAI-compatible Files boundary and provider-affinity tests."""

from __future__ import annotations

import tempfile
import json
import threading
import urllib.request

import pytest

from contextual_orchestrator.batch_job_registry import JobRegistryFactory
from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.file_registry import FileRegistry
from contextual_orchestrator.server import (
    MAX_BATCH_FILE_BYTES,
    MAX_FILE_UPLOAD_BYTES,
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
    assert _request_body_size({"content-length": str(MAX_FILE_UPLOAD_BYTES)}, MAX_FILE_UPLOAD_BYTES) == MAX_FILE_UPLOAD_BYTES
    with pytest.raises(RequestError):
        _request_body_size({"content-length": str(MAX_FILE_UPLOAD_BYTES + 1)}, MAX_FILE_UPLOAD_BYTES)
    assert MAX_BATCH_FILE_BYTES == 200 * 1024 * 1024


def test_multipart_metadata_reads_fields_and_exact_file_size_from_disk() -> None:
    """The parser extracts only metadata while the file remains disk-backed."""
    raw = _multipart(purpose="batch", filename="jobs.jsonl", data=b"{}\n")
    with tempfile.TemporaryFile() as body:
        body.write(raw)
        assert _multipart_upload_metadata(
            body, "multipart/form-data; boundary=test-boundary"
        ) == ("batch", "jobs.jsonl", 3)


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
