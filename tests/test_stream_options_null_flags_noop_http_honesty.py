"""stream_options null flag values are omit-equivalent no-ops over HTTP."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "stream_options_null_flags_noop_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
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


def _post_raw(port: int, path: str, payload: dict) -> tuple[int, str, str]:
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
            return (
                response.status,
                response.headers.get("content-type", ""),
                response.read().decode("utf-8"),
            )
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("content-type", ""), exc.read().decode("utf-8")


def _server():
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_accepts_stream_options_null_flags_without_stream() -> None:
    """SDK optional null flags must not require stream=true or fail type checks."""
    server, thread, port = _server()
    try:
        for opts in (
            {"include_usage": None},
            {"include_obfuscation": None},
            {"include_usage": None, "include_obfuscation": None},
            {"include_usage": None, "include_obfuscation": False},
            {"include_usage": False, "include_obfuscation": None},
        ):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "null so flags"}],
                    "stream": False,
                    "stream_options": opts,
                },
            )
            assert status == 200, (opts, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_stream_options_null_flags_without_stream() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {
                "model": "mock-planner",
                "prompt": "null so flags",
                "stream": False,
                "stream_options": {
                    "include_usage": None,
                    "include_obfuscation": None,
                },
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_stream_options_null_flags() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "null so flags",
                "stream_options": {
                    "include_usage": None,
                    "include_obfuscation": None,
                },
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_include_usage_true() -> None:
    server, thread, port = _server()
    try:
        status, content_type, sse = _post_raw(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "usage true"}],
                "stream": True,
                "stream_options": {"include_usage": True},
            },
        )
        assert status == 200, sse
        assert content_type.startswith("text/event-stream")
        frames = [
            json.loads(frame[len("data: "):])
            for frame in sse.split("\n\n")
            if frame.startswith("data: ") and frame != "data: [DONE]"
        ]
        assert frames
        assert all(frame.get("usage") is None for frame in frames)
        assert not any(frame.get("choices") == [] for frame in frames)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_streams_include_reported_usage() -> None:
    """Single-agent tools passthrough streams the provider's real reported usage.

    Regression for the 2026-08-30 stream_options/tools incident: this
    combination used to be rejected with a blanket 400 even though the
    upstream call here is always a single non-streaming provider request
    whose real usage field survives untouched into the SSE framing.
    """
    server, thread, port = _server()
    try:
        status, content_type, sse = _post_raw(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "structured usage"}],
                "stream": True,
                "stream_options": {"include_usage": True},
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
            },
        )
        assert status == 200, sse
        assert content_type.startswith("text/event-stream")
        frames = [
            json.loads(frame[len("data: "):])
            for frame in sse.split("\n\n")
            if frame.startswith("data: ") and frame != "data: [DONE]"
        ]
        assert frames
        usage_frames = [frame for frame in frames if frame.get("choices") == []]
        assert len(usage_frames) == 1, frames
        usage = usage_frames[0]["usage"]
        assert usage["usage_source"] == "reported"
        assert usage["prompt_tokens"] == 0
        assert usage["completion_tokens"] == 0
        assert usage["total_tokens"] == 0
    finally:
        server.shutdown()
        thread.join(timeout=5)


class _NoUsageToolProvider:
    """Serves one canned tool-call response over real HTTP with no ``usage`` key.

    ``ModelClient.proxy_send`` returns a provider's JSON body verbatim (see
    ``orchestrator.py::proxy_completion``/``_proxy_send``) -- it never requires
    or synthesizes a ``usage`` field. ``mock://`` agents cannot exercise this:
    ``ModelClient._mock_raw`` always injects a zero-valued ``usage`` dict, so a
    real (if fake) HTTP provider is needed to prove the missing-usage path.
    """

    def __init__(self) -> None:
        body = {
            "id": "chatcmpl_fake_no_usage",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": "{}"},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }
        raw = json.dumps(body).encode("utf-8")

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("content-length", 0))
                self.rfile.read(length)
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args: object) -> None:  # silence
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "_NoUsageToolProvider":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"


def test_http_chat_tools_streams_estimated_usage_when_provider_omits_it() -> None:
    """A tools-capable provider that omits ``usage`` gets an honest estimate, not a fake "reported" label.

    Regression for a Devin finding on #925: the PR's own rationale for
    narrowing the ``stream_options.include_usage`` rejection to exclude
    ``tools`` passthrough assumed the one upstream call "always" carries real
    provider usage. That's the common case, not a guarantee --
    ``ModelClient.proxy_send`` returns the provider's raw JSON verbatim with
    no ``usage`` requirement. ``_chat_response_sse_chunks`` already has a
    fallback for exactly this (the same one already exercised for the
    non-tools streaming path): estimate from the visible content/tool_calls
    and label it ``usage_source: "estimated"`` rather than fabricate
    ``"reported"``. This proves that fallback over a real (if fake) HTTP
    provider response, since ``mock://`` agents always inject usage and can
    never exercise it.
    """
    with _NoUsageToolProvider() as provider:
        # The "local://" scheme is this codebase's sanctioned way to point an
        # agent at a loopback dev/test HTTP server: _validate_provider skips
        # the https-only + public-address checks it enforces for ordinary
        # provider base_urls (SSRF hardening this test must not weaken), and
        # _provider_credential_name treats it as keyless by default.
        local_base_url = provider.base_url.replace("http://", "local://", 1)
        orchestrator = TaskOrchestrator(
            [
                ModelAgent(
                    "general_agent",
                    "gpt-x",
                    base_url=local_base_url,
                    tags=("reasoning", "writing", "tools"),
                )
            ]
        )
        server = build_server(
            orchestrator,
            port=0,
            security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        try:
            status, content_type, sse = _post_raw(
                port,
                "/v1/chat/completions",
                {
                    "model": "gpt-x",
                    "messages": [{"role": "user", "content": "no usage from this provider"}],
                    "stream": True,
                    "stream_options": {"include_usage": True},
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": "lookup",
                                "parameters": {"type": "object", "properties": {}},
                            },
                        }
                    ],
                },
            )
            assert status == 200, sse
            assert content_type.startswith("text/event-stream")
            frames = [
                json.loads(frame[len("data: "):])
                for frame in sse.split("\n\n")
                if frame.startswith("data: ") and frame != "data: [DONE]"
            ]
            usage_frames = [frame for frame in frames if frame.get("choices") == []]
            assert len(usage_frames) == 1, frames
            usage = usage_frames[0]["usage"]
            assert usage["usage_source"] == "estimated", usage
            assert usage["prompt_tokens"] > 0
            assert usage["completion_tokens"] > 0
        finally:
            server.shutdown()
            thread.join(timeout=5)


def test_http_chat_tools_estimated_usage_counts_the_tool_schema() -> None:
    """A larger ``tools`` schema must widen the estimated prompt token count.

    Regression for a Devin finding on #925: the estimated-usage fallback in
    ``_chat_response_sse_chunks`` used to build its prompt-token estimate
    from ``body["messages"]`` alone, excluding ``body["tools"]`` entirely.
    OpenAI-compatible providers count tool definitions (names, descriptions,
    JSON schemas) toward prompt usage, so a request with a large tool schema
    would get a materially understated estimate. Proves the fix by sending
    the identical messages with a tiny tools list vs. a large one and
    asserting the estimated prompt_tokens strictly increases.
    """

    def estimated_prompt_tokens(tools: list[dict]) -> int:
        with _NoUsageToolProvider() as provider:
            local_base_url = provider.base_url.replace("http://", "local://", 1)
            orchestrator = TaskOrchestrator(
                [
                    ModelAgent(
                        "general_agent",
                        "gpt-x",
                        base_url=local_base_url,
                        tags=("reasoning", "writing", "tools"),
                    )
                ]
            )
            server = build_server(
                orchestrator,
                port=0,
                security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_address[1]
            try:
                status, _, sse = _post_raw(
                    port,
                    "/v1/chat/completions",
                    {
                        "model": "gpt-x",
                        "messages": [{"role": "user", "content": "no usage from this provider"}],
                        "stream": True,
                        "stream_options": {"include_usage": True},
                        "tools": tools,
                    },
                )
                assert status == 200, sse
                frames = [
                    json.loads(frame[len("data: "):])
                    for frame in sse.split("\n\n")
                    if frame.startswith("data: ") and frame != "data: [DONE]"
                ]
                usage_frames = [frame for frame in frames if frame.get("choices") == []]
                assert len(usage_frames) == 1, frames
                return usage_frames[0]["usage"]["prompt_tokens"]
            finally:
                server.shutdown()
                thread.join(timeout=5)

    small_tools = [
        {
            "type": "function",
            "function": {"name": "lookup", "parameters": {"type": "object", "properties": {}}},
        }
    ]
    large_tools = [
        {
            "type": "function",
            "function": {
                "name": f"tool_{index}",
                "description": "A moderately verbose tool description. " * 5,
                "parameters": {
                    "type": "object",
                    "properties": {
                        f"field_{field}": {"type": "string", "description": "x" * 40}
                        for field in range(5)
                    },
                },
            },
        }
        for index in range(5)
    ]

    small_estimate = estimated_prompt_tokens(small_tools)
    large_estimate = estimated_prompt_tokens(large_tools)
    assert large_estimate > small_estimate, (small_estimate, large_estimate)


def test_http_chat_response_format_only_streams_still_reject_include_usage() -> None:
    """response_format-only (conduct mode, no tools) keeps failing closed.

    Its usage comes from a multi-step workflow's cost ledger, which may be
    unmeasured -- unlike single-agent tools passthrough, which always has
    the one upstream call's own real, reported usage available.
    """
    server, thread, port = _server()
    try:
        status, _, body = _post_raw(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "structured usage"}],
                "stream": True,
                "stream_options": {"include_usage": True},
                "response_format": {"type": "json_object"},
            },
        )
        assert status == 400, body
        assert "invalid_stream_options" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_non_boolean_non_null_flag() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "bad flag"}],
                "stream": True,
                "stream_options": {"include_usage": "yes"},
            },
        )
        assert status == 400, body
        assert "invalid_stream_options" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_stream_options_null_flags_without_stream()
    test_http_completions_accepts_stream_options_null_flags_without_stream()
    test_http_responses_accepts_stream_options_null_flags()
    test_http_chat_accepts_include_usage_true()
    test_http_chat_tools_streams_include_reported_usage()
    test_http_chat_tools_streams_estimated_usage_when_provider_omits_it()
    test_http_chat_tools_estimated_usage_counts_the_tool_schema()
    test_http_chat_response_format_only_streams_still_reject_include_usage()
    test_http_chat_rejects_non_boolean_non_null_flag()
    print("ok")
