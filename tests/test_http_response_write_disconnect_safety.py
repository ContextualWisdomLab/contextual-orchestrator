"""A disconnected client during response write must not crash the handler thread."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "http_response_write_disconnect_safety_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def test_write_response_swallows_a_broken_pipe_from_a_disconnected_client() -> None:
    """``_write_response`` must absorb BrokenPipeError/ConnectionError/OSError.

    A client that gives up waiting on a slow response closes its socket
    before the write completes. Before this guard existed, that exception
    propagated out of do_POST's own `except Exception` handler into a
    second call to the same closed socket, which raised again -- uncaught
    -- and crashed the request-handling thread. The fix point is
    `_write_response`; every `_send*`/`_begin_sse`/`_write_sse` method
    routes through it, so testing it directly covers all of them.
    """
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    try:
        handler_cls = server.RequestHandlerClass

        def _disconnected_write() -> None:
            raise BrokenPipeError("simulated client disconnect mid-write")

        # Must return quietly, not raise -- self is unused by the method,
        # so a dummy stands in for a real connected-handler instance.
        assert handler_cls._write_response(object(), _disconnected_write) is False

        def _reset_by_peer() -> None:
            raise ConnectionResetError("simulated peer reset")

        assert handler_cls._write_response(object(), _reset_by_peer) is False
    finally:
        server.server_close()


def test_stream_stops_consuming_and_releases_slot_after_disconnect() -> None:
    """A dead SSE peer must stop paid upstream work and release concurrency."""
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    yielded: list[str] = []

    class Orchestrator:
        def stream_route(self, messages, workflow_run_id, *, model_name):
            for delta in ("first", "second"):
                yielded.append(delta)
                yield delta

    class Security:
        acquired = 0
        released = 0

        def acquire_run_slot(self):
            self.acquired += 1

        def release_run_slot(self):
            self.released += 1

    class Handler:
        writes = 0

        def _begin_sse(self):
            return True

        def _write_sse(self, _frame):
            self.writes += 1
            return self.writes < 2

    try:
        security = Security()
        handler = Handler()
        server.RequestHandlerClass._stream_route_completion(
            handler, Orchestrator(), security, [], "model-group"
        )
        assert yielded == ["first"]
        assert security.acquired == security.released == 1
    finally:
        server.server_close()


def test_stream_route_emits_provider_usage_when_requested() -> None:
    """A successful live route includes provider usage after its stop frame."""
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    frames: list[str] = []

    class Client:
        def take_usage(self):
            return {"prompt_tokens": 2, "completion_tokens": 4, "total_tokens": 6}

    class Orchestrator:
        client = Client()

        def stream_route(self, messages, workflow_run_id, *, model_name, include_usage=False):
            del messages, workflow_run_id, model_name
            assert include_usage is True
            yield "answer"

    class Security:
        def acquire_run_slot(self):
            return None

        def release_run_slot(self):
            return None

    class Handler:
        def _begin_sse(self):
            return True

        def _write_sse(self, frame):
            frames.append(frame)
            return True

    try:
        server.RequestHandlerClass._stream_route_completion(
            Handler(),
            Orchestrator(),
            Security(),
            [],
            "model-group",
            include_usage=True,
        )
    finally:
        server.server_close()

    payloads = [
        json.loads(frame[6:])
        for frame in frames
        if frame.startswith("data: ") and frame != "data: [DONE]\n\n"
    ]
    usage_frames = [payload for payload in payloads if payload.get("choices") == []]
    assert len(usage_frames) == 1
    assert payloads[-2]["choices"][0]["finish_reason"] == "stop"
    usage_frame = usage_frames[0]
    assert usage_frame["object"] == "chat.completion.chunk"
    assert usage_frame["model"] == "model-group"
    assert usage_frame["choices"] == []
    assert usage_frame["usage"] == {
        "prompt_tokens": 2,
        "completion_tokens": 4,
        "total_tokens": 6,
    }


def test_responses_stream_does_not_start_orchestration_after_header_disconnect() -> None:
    """A dead Responses peer must not trigger any paid provider work."""
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))

    class Orchestrator:
        def would_route(self, *_args, **_kwargs):
            raise AssertionError("orchestration must not start")

    class Security:
        acquired = 0
        released = 0

        def acquire_run_slot(self):
            self.acquired += 1

        def release_run_slot(self):
            self.released += 1

    class Handler:
        def _begin_sse(self):
            return False

    try:
        security = Security()
        result = server.RequestHandlerClass._stream_orchestrated_response(
            Handler(), Orchestrator(), security, [], "orchestrator/auto"
        )
        assert result is False
        assert security.acquired == security.released == 1
    finally:
        server.server_close()


def test_responses_stream_stops_orchestration_after_event_disconnect() -> None:
    """A disconnected reasoning-summary stream must stop later provider work."""
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    continued: list[str] = []

    class Orchestrator:
        def would_route(self, *_args, **_kwargs):
            return False

        def conduct(self, _messages, *, model_name, progress):
            del model_name
            progress("thinker", "started")
            continued.append("after disconnect")
            return {"answer": "must not be returned"}

    class Security:
        acquired = 0
        released = 0

        def acquire_run_slot(self):
            self.acquired += 1

        def release_run_slot(self):
            self.released += 1

    class Handler:
        writes = 0

        def _begin_sse(self):
            return True

        def _write_sse(self, _frame):
            self.writes += 1
            return self.writes < 3

    try:
        security = Security()
        handler = Handler()
        result = server.RequestHandlerClass._stream_orchestrated_response(
            handler, Orchestrator(), security, [], "orchestrator/auto"
        )
        assert result is False
        assert continued == []
        assert handler.writes == 3
        assert security.acquired == security.released == 1
    finally:
        server.server_close()


def test_write_response_still_propagates_unrelated_errors() -> None:
    """Only disconnect-shaped errors are swallowed; real bugs must still surface."""
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    try:
        handler_cls = server.RequestHandlerClass

        def _broken_serializer() -> None:
            raise TypeError("payload was not JSON-serializable")

        try:
            handler_cls._write_response(object(), _broken_serializer)
        except TypeError:
            pass
        else:
            raise AssertionError("expected TypeError to propagate, not be swallowed")
    finally:
        server.server_close()


def test_binary_response_swallows_a_disconnect() -> None:
    """Audio writes use the same disconnect boundary as JSON and SSE writes."""
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    handler_cls = server.RequestHandlerClass

    class DisconnectedHandler:
        wfile = None

        def send_response(self, _status):
            return None

        def send_header(self, _name, _value):
            return None

        def _send_security_headers(self):
            return None

        def end_headers(self):
            return None

        def write(self, _payload):
            raise BrokenPipeError("simulated audio client disconnect")

        _write_response = handler_cls._write_response

    try:
        handler = DisconnectedHandler()
        handler.wfile = handler
        handler_cls._send_bytes(handler, b"audio", "audio/mpeg")
    finally:
        server.server_close()


if __name__ == "__main__":
    test_write_response_swallows_a_broken_pipe_from_a_disconnected_client()
    test_write_response_still_propagates_unrelated_errors()
    print("ok")
