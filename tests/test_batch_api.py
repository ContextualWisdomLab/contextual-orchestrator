"""OpenAI Batch API support — upload, create, poll, parse, over real HTTP.

Batch is the cheap path (~50% provider discount, 24h window) for eval/benchmark
workloads. These drive ModelClient._batch_run against a local fake Batch server:
multipart JSONL upload, batch creation, in_progress -> completed polling, JSONL
result parsing with usage, and terminal-failure handling. Mock path stays sync.

Also covers batch_chat()'s own real-vs-emulated routing gate: only an agent
explicitly declaring ``batch_endpoint_supported=True`` may reach the real
Batch API above; every other remote agent (unproven -- ``None``/``False``)
must fall back to the same per-item emulation local providers already use,
never guess-route into a provider that may not implement /v1/batches at all.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import sys
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402


class _FakeBatchProvider:
    """Implements /files, /batches, /batches/{id}, /files/{id}/content, /chat/completions."""

    def __init__(self, fail_status: str | None = None, polls_before_done: int = 2) -> None:
        outer = self
        self.uploaded_jsonl: bytes = b""
        self.poll_count = 0
        self.batches_post_count = 0
        self.chat_completions_count = 0

        class Handler(BaseHTTPRequestHandler):
            def _json(self, payload: dict, status: int = 200) -> None:
                raw = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("content-length", 0))
                body = self.rfile.read(length)
                if self.path == "/files":
                    outer.uploaded_jsonl = body  # multipart wrapper included; checked via 'in'
                    self._json({"id": "file_input_1"})
                elif self.path == "/batches":
                    outer.batches_post_count += 1
                    self._json({"id": "batch_1", "status": "validating"})
                elif self.path == "/chat/completions":
                    # The emulation fallback's target: one ordinary chat completion
                    # per batch item, echoing the prompt so per-item routing is provable.
                    outer.chat_completions_count += 1
                    payload = json.loads(body)
                    last_user = next(
                        (m["content"] for m in reversed(payload["messages"]) if m.get("role") == "user"),
                        "",
                    )
                    self._json({
                        "choices": [{"message": {"role": "assistant", "content": f"emulated: {last_user}"}}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    })
                else:
                    self._json({"error": "not found"}, 404)

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/batches/batch_1":
                    outer.poll_count += 1
                    if fail_status is not None:
                        self._json({"id": "batch_1", "status": fail_status})
                    elif outer.poll_count >= polls_before_done:
                        self._json({"id": "batch_1", "status": "completed", "output_file_id": "file_out_1"})
                    else:
                        self._json({"id": "batch_1", "status": "in_progress"})
                elif self.path == "/files/file_out_1/content":
                    lines = [
                        {"custom_id": "task_a", "response": {"status_code": 200, "body": {
                            "choices": [{"message": {"role": "assistant", "content": "answer A"}}],
                            "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}}}},
                        {"custom_id": "task_b", "response": {"status_code": 200, "body": {
                            "choices": [{"message": {"role": "assistant", "content": "answer B"}}],
                            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}}}},
                    ]
                    raw = "\n".join(json.dumps(line) for line in lines).encode("utf-8")
                    self.send_response(200)
                    self.send_header("content-type", "application/jsonl")
                    self.send_header("content-length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                else:
                    self._json({"error": "not found"}, 404)

            def log_message(self, *args: object) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "_FakeBatchProvider":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"


def _client() -> ModelClient:
    client = ModelClient()
    client._sleep = lambda _s: None  # no real sleeping between polls in tests
    return client


REQUESTS = {
    "task_a": [{"role": "user", "content": "question A"}],
    "task_b": [{"role": "user", "content": "question B"}],
}


def test_batch_run_full_flow_over_http() -> None:
    with _FakeBatchProvider(polls_before_done=3) as provider:
        agent = ModelAgent("worker_agent", "gpt-x", base_url=provider.base_url, api_key_env="UNSET_KEY_ENV")
        results = _client()._batch_run(agent, REQUESTS, temperature=0.2, poll_interval=0.01, poll_timeout=30)

        assert results["task_a"]["content"] == "answer A"
        assert results["task_b"]["usage"]["completion_tokens"] == 2
        assert provider.poll_count >= 3  # actually polled through in_progress
        # The uploaded multipart body carries the JSONL with our custom ids and model.
        assert b'"custom_id": "task_a"' in provider.uploaded_jsonl
        assert b'"model": "gpt-x"' in provider.uploaded_jsonl
        assert b'name="purpose"' in provider.uploaded_jsonl


def test_batch_terminal_failure_raises() -> None:
    with _FakeBatchProvider(fail_status="failed") as provider:
        agent = ModelAgent("worker_agent", "gpt-x", base_url=provider.base_url, api_key_env="UNSET_KEY_ENV")
        raised = False
        try:
            _client()._batch_run(agent, REQUESTS, temperature=0.2, poll_interval=0.01, poll_timeout=30)
        except RuntimeError as exc:
            raised = True
            assert "failed" in str(exc)
        assert raised


def test_batch_poll_timeout_raises() -> None:
    with _FakeBatchProvider(polls_before_done=10_000) as provider:
        agent = ModelAgent("worker_agent", "gpt-x", base_url=provider.base_url, api_key_env="UNSET_KEY_ENV")
        raised = False
        try:
            _client()._batch_run(agent, REQUESTS, temperature=0.2, poll_interval=0.01, poll_timeout=0.0)
        except TimeoutError:
            raised = True
        assert raised


def test_mock_path_answers_synchronously() -> None:
    agent = ModelAgent("general_agent", "mock-model")  # mock://local
    results = ModelClient().batch_chat(agent, REQUESTS)
    assert set(results) == {"task_a", "task_b"}
    assert results["task_a"]["content"].startswith("[general_agent:")
    assert results["task_a"]["usage"] is None


def _remote_agent(base_url: str, **overrides: object) -> ModelAgent:
    # credential_key="" keeps chat()'s NotConfigured pre-check out of the way
    # (no KV credential is registered in tests); base_url is real HTTP so
    # _validate_provider's https/public-IP checks are bypassed per-test below,
    # exactly like the destination-pinning pattern already proven in
    # test_provider_integration.py::test_open_provider_uses_validated_destination_without_dns_relookup.
    fields: dict[object, object] = {
        "id": "worker_agent",
        "model": "gpt-x",
        "base_url": base_url,
        "credential_key": "",
    }
    fields.update(overrides)
    return ModelAgent(**fields)  # type: ignore[arg-type]


def _pinned_destination(provider: "_FakeBatchProvider") -> tuple[int, tuple[str, int]]:
    return (socket.AF_INET, ("127.0.0.1", provider._server.server_address[1]))


def test_batch_chat_routes_batch_capable_agent_to_real_batch_endpoint() -> None:
    """(a) batch_endpoint_supported=True still takes the real Batch API path."""
    with _FakeBatchProvider(polls_before_done=2) as provider:
        agent = _remote_agent(provider.base_url, batch_endpoint_supported=True)
        client = _client()
        with patch.object(client, "_validate_provider", return_value=_pinned_destination(provider)):
            results = client.batch_chat(agent, REQUESTS, poll_interval=0.01, poll_timeout=30)

        assert results["task_a"]["content"] == "answer A"
        assert results["task_b"]["usage"]["completion_tokens"] == 2
        assert provider.batches_post_count == 1  # the real Batch API was used
        assert provider.chat_completions_count == 0  # emulation never triggered


def test_batch_chat_falls_back_to_emulation_when_batch_endpoint_unproven() -> None:
    """(b) an unproven agent (None/False) still returns a correct aggregated
    result, via emulation -- and (c) that emulation path is real, not stubbed:
    every request actually crosses the wire as one /chat/completions call.
    """
    for unsupported_value in (None, False):
        with _FakeBatchProvider() as provider:
            agent = _remote_agent(provider.base_url, batch_endpoint_supported=unsupported_value)
            client = _client()
            with patch.object(client, "_validate_provider", return_value=_pinned_destination(provider)):
                results = client.batch_chat(agent, REQUESTS)

            assert set(results) == {"task_a", "task_b"}
            assert results["task_a"]["content"] == "emulated: question A"
            assert results["task_b"]["content"] == "emulated: question B"
            assert results["task_a"]["usage"]["completion_tokens"] == 1
            # One real chat completion per request -- the emulation path was
            # actually exercised, not just asserted from a mocked return value.
            assert provider.chat_completions_count == 2
            # The real Batch API was never touched: no misroute, no hard failure.
            assert provider.batches_post_count == 0
            assert provider.uploaded_jsonl == b""


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
