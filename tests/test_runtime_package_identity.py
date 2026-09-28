"""An authenticated deployment receipt must reflect installed package bytes."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import marshal
import py_compile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator import runtime_identity
from contextual_orchestrator.server import SecurityConfig, build_server


def _recorded_file(name: str, content: bytes) -> str:
    class RecordedFile(str):
        hash: SimpleNamespace

    item = RecordedFile(name)
    item.hash = SimpleNamespace(
        mode="sha256",
        value=base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode(),
    )
    return item


def test_runtime_identity_verifies_installed_bytes_and_rejects_mutation(tmp_path, monkeypatch):
    package = tmp_path / "contextual_orchestrator"
    package.mkdir()
    content = b"VALUE = 'expected'\n"
    (package / "__init__.py").write_bytes(b"")
    (package / "worker.py").write_bytes(content)
    (package / "runtime_identity.py").write_bytes(b"identity module\n")
    manifest = {
        "version": "0.2.0",
        "release_tag": "v0.2.0",
        "source_sha": "a" * 40,
        "schema_sha256": runtime_identity.current_schema_sha256(),
    }
    manifest_bytes = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    (package / "_release_identity.json").write_bytes(manifest_bytes)

    class Distribution:
        version = "0.2.0"
        files = [
            _recorded_file("contextual_orchestrator/__init__.py", b""),
            _recorded_file("contextual_orchestrator/worker.py", content),
            _recorded_file("contextual_orchestrator/runtime_identity.py", b"identity module\n"),
            _recorded_file("contextual_orchestrator/_release_identity.json", manifest_bytes),
        ]

        def locate_file(self, path):
            return tmp_path / str(path)

    monkeypatch.setattr(runtime_identity.importlib.metadata, "distribution", lambda _: Distribution())
    monkeypatch.setattr(runtime_identity, "__file__", str(package / "runtime_identity.py"))

    receipt = runtime_identity.verified_runtime_identity()
    assert receipt["source_sha"] == "a" * 40
    assert receipt["package_tree_sha256"] == runtime_identity.package_tree_sha256(
        [(str(item), (tmp_path / str(item)).read_bytes()) for item in Distribution.files]
    )

    cache = Path(importlib.util.cache_from_source(str(package / "worker.py")))
    py_compile.compile(str(package / "worker.py"), doraise=True)
    assert runtime_identity.verified_runtime_identity()["source_sha"] == "a" * 40
    original_cache = cache.read_bytes()
    cache.write_bytes(
        original_cache[:16]
        + marshal.dumps(compile("VALUE = 'modified'\n", str(package / "worker.py"), "exec"))
    )
    with pytest.raises(runtime_identity.RuntimeIdentityUnavailable):
        runtime_identity.verified_runtime_identity()
    cache.write_bytes(original_cache)

    (package / "worker.py").write_bytes(b"altered installed module\n")
    with pytest.raises(runtime_identity.RuntimeIdentityUnavailable):
        runtime_identity.verified_runtime_identity()

    (package / "worker.py").write_bytes(content)
    (package / "injected.txt").write_bytes(b"unrecorded data\n")
    with pytest.raises(runtime_identity.RuntimeIdentityUnavailable):
        runtime_identity.verified_runtime_identity()

    (package / "injected.txt").unlink()
    (package / "worker.py").unlink()
    (package / "worker.py").symlink_to(tmp_path / "worker.py")
    (tmp_path / "worker.py").write_bytes(content)
    with pytest.raises(runtime_identity.RuntimeIdentityUnavailable):
        runtime_identity.verified_runtime_identity()


def test_runtime_identity_endpoint_authenticates_and_fails_closed(monkeypatch):
    orchestrator = TaskOrchestrator([ModelAgent("identity_probe", "mock")])
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(
            admin_token="separate-admin-token",
            inference_token="scoped-inference-token",
        ),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/v1/gateway/identity"

    def request(token: str | None) -> tuple[int, dict]:
        headers = {} if token is None else {"Authorization": f"Bearer {token}"}
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            try:
                return error.code, json.load(error)
            finally:
                error.close()

    try:
        assert request(None)[0] == 401
        monkeypatch.setattr(
            runtime_identity,
            "verified_runtime_identity",
            lambda: (_ for _ in ()).throw(runtime_identity.RuntimeIdentityUnavailable()),
        )
        status, body = request("scoped-inference-token")
        assert status == 503
        assert body["error"]["code"] == "release_identity_unavailable"
        monkeypatch.setattr(runtime_identity, "verified_runtime_identity", lambda: {"source_sha": "a" * 40})
        assert request("scoped-inference-token") == (200, {"source_sha": "a" * 40})
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        orchestrator.close()
