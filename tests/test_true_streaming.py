"""True token streaming — provider SSE deltas piped through as they arrive.

The prior streaming (#18) computed the whole answer then framed it. This tests the
real streaming path: ModelClient._stream_send parses a provider SSE response over the
wire (local server), and /v1/chat/completions route+stream pipes live deltas out.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


class _FakeSSEProvider:
    """Emits a fixed list of raw SSE frame strings at POST /chat/completions."""

    def __init__(self, frames: list[str]) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("content-length", 0))
                self.rfile.read(length)
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.end_headers()
                for frame in frames:
                    self.wfile.write(frame.encode("utf-8"))
                    self.wfile.flush()

            def log_message(self, *args: object) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "_FakeSSEProvider":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"


def _delta(content: str) -> str:
    return 'data: ' + json.dumps({"choices": [{"delta": {"content": content}}]}) + "\n\n"


def test_stream_send_parses_real_provider_sse() -> None:
    frames = [
        'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n',  # role delta, no content
        _delta("Hello"),
        _delta(" streamed"),
        _delta(" world"),
        "data: [DONE]\n\n",
    ]
    with _FakeSSEProvider(frames) as provider:
        client = ModelClient()
        agent = ModelAgent("worker_agent", "gpt-x", base_url=provider.base_url, api_key_env="UNSET_KEY_ENV")
        deltas = list(client._stream_send(agent, {"model": "gpt-x", "stream": True}))
    assert deltas == ["Hello", " streamed", " world"]  # role delta skipped, [DONE] stops
    assert "".join(deltas) == "Hello streamed world"


def test_stream_chat_mock_yields_chunks() -> None:
    client = ModelClient()
    agent = ModelAgent("general_agent", "mock-model")  # base_url defaults to mock://local
    messages = [{"role": "user", "content": "a reasonably long prompt to force multiple chunks"}]
    deltas = list(client.stream_chat(agent, messages))
    assert len(deltas) >= 2  # chunked, not one blob
    assert "".join(deltas) == client._mock(agent, messages)  # lossless


def test_would_route_true_for_route_false_for_conduct() -> None:
    orchestrator = TaskOrchestrator([ModelAgent("general_agent", "m-model", tags=("reasoning", "writing"))])
    messages = [{"role": "user", "content": "short prompt"}]
    assert orchestrator.would_route(messages, "route") is True
    assert orchestrator.would_route(messages, "conduct") is False


def test_stream_route_yields_and_persists() -> None:
    orchestrator = TaskOrchestrator([ModelAgent("general_agent", "m-model", tags=("reasoning", "writing"))])
    deltas = list(orchestrator.stream_route([{"role": "user", "content": "stream this please"}]))
    answer = "".join(deltas)
    assert answer.startswith("[general_agent:worker]")
    assert len(orchestrator._workflow_runs) == 1  # streamed run still persisted for observability


def test_http_route_stream_pipes_live_deltas() -> None:
    token = "stream_token"
    orchestrator = TaskOrchestrator([ModelAgent("general_agent", "m-model", tags=("reasoning", "writing"))])
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/v1/chat/completions"

    def post(payload: dict) -> tuple[str, str]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json", "authorization": f"Bearer {token}"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.headers.get("content-type", ""), response.read().decode("utf-8")

    try:
        content_type, sse = post({"messages": [{"role": "user", "content": "stream this"}], "mode": "route", "stream": True})
        _, ref = post({"messages": [{"role": "user", "content": "stream this"}], "mode": "route"})
    finally:
        server.shutdown()

    assert content_type.startswith("text/event-stream")
    assert sse.endswith("data: [DONE]\n\n")
    streamed = ""
    for line in sse.split("\n\n"):
        line = line.strip()
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        streamed += json.loads(line[len("data: ") :])["choices"][0]["delta"].get("content", "")
    reference = json.loads(ref)["choices"][0]["message"]["content"]
    assert streamed == reference  # live-streamed deltas equal the non-streamed route answer


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
