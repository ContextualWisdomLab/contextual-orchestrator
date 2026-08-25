"""A disconnected client during response write must not crash the handler thread."""

from __future__ import annotations

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


if __name__ == "__main__":
    test_write_response_swallows_a_broken_pipe_from_a_disconnected_client()
    test_write_response_still_propagates_unrelated_errors()
    print("ok")
