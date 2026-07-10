"""Integration tests for the REAL provider transport (urllib) against a local
OpenAI-compatible HTTP server.

This exercises the network path that the `mock://` path never touches: the actual
POST, JSON parse, usage capture, real `urllib.error.HTTPError` classification, and
retry/backoff recovery. Previously all of `_send` was `# pragma: no cover`.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402


def _completion(content: str, usage: dict | None = None) -> dict:
    body: dict = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    if usage is not None:
        body["usage"] = usage
    return body


class _FakeProvider:
    """Serves a scripted sequence of (status, json_body) at POST /chat/completions."""

    def __init__(self, responses: list[tuple[int, dict]]) -> None:
        self.request_count = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("content-length", 0))
                self.rfile.read(length)
                index = min(outer.request_count, len(responses) - 1)
                outer.request_count += 1
                status, body = responses[index]
                raw = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args: object) -> None:  # silence
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "_FakeProvider":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"


def _agent(base_url: str) -> ModelAgent:
    return ModelAgent("worker_agent", "gpt-x", base_url=base_url, api_key_env="UNSET_KEY_ENV")


def test_send_real_http_round_trip_and_usage_capture() -> None:
    usage = {"prompt_tokens": 11, "completion_tokens": 42, "total_tokens": 53}
    with _FakeProvider([(200, _completion("live answer", usage))]) as provider:
        client = ModelClient()
        client._local.usage = None
        result = client._send(_agent(provider.base_url), {"model": "gpt-x"})
    assert result == "live answer"  # real POST + JSON parse over the wire
    assert client._local.usage == usage  # provider-reported usage captured from a real response


def test_transient_5xx_retries_then_succeeds_over_http() -> None:
    with _FakeProvider([(503, {}), (503, {}), (200, _completion("recovered"))]) as provider:
        client = ModelClient(max_retries=3, retry_backoff=0.0)
        result = client._send_with_retry(_agent(provider.base_url), {"model": "gpt-x"})
        assert result == "recovered"
        assert provider.request_count == 3  # two real 503s (urllib.error.HTTPError) then success


def test_permanent_4xx_is_not_retried_over_http() -> None:
    with _FakeProvider([(400, {"error": "bad request"})]) as provider:
        client = ModelClient(max_retries=5, retry_backoff=0.0)
        raised = False
        try:
            client._send_with_retry(_agent(provider.base_url), {"model": "gpt-x"})
        except RuntimeError:
            raised = True
        assert raised
        assert provider.request_count == 1  # 400 is a real HTTPError classified permanent: one attempt


def test_connection_error_is_transient_and_exhausts() -> None:
    # Point at a port with nothing listening: a real urllib URLError, classified transient.
    client = ModelClient(max_retries=1, retry_backoff=0.0, timeout=2)
    agent = _agent("http://127.0.0.1:1")  # port 1: connection refused
    raised = False
    try:
        client._send_with_retry(agent, {"model": "gpt-x"})
    except RuntimeError as exc:
        raised = True
        assert "worker_agent" in str(exc)
    assert raised


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
