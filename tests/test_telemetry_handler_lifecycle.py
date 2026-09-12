"""Deterministic local HTTP handler teardown reproduction; no provider calls."""
import http.client
import json
import threading
import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.orchestrator import ModelClient
from contextual_orchestrator.server import SecurityConfig, build_server


@pytest.mark.parametrize("daemon_handlers", [True, False])
def test_shutdown_waits_for_final_request_logging(daemon_handlers):
    model_agent = ModelAgent("local_agent", "mock-model")
    model_client = ModelClient(max_retries=0)
    router = TaskOrchestrator([model_agent], client=model_client)

    def reject_send(*args, **kwargs):
        raise RuntimeError("controlled provider failure")

    def fail_completion(*args, **kwargs):
        return model_client._send_with_retry(model_agent, {})

    model_client._send = reject_send
    router.complete = fail_completion
    server = build_server(router, port=0, security=SecurityConfig(auth_token="unit-token"))
    server.daemon_threads = daemon_handlers
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    handler_threads = []
    close_threads = []
    close_started = threading.Event()
    close_finished = threading.Event()
    original_summary = server.RequestHandlerClass._log_request_summary

    def blocked_summary(handler, started):
        handler_threads.append(threading.current_thread())
        entered.set()
        try:
            if not release.wait(10):
                raise AssertionError("test did not release final summary")
            original_summary(handler, started)
        finally:
            finished.set()

    server.RequestHandlerClass._log_request_summary = blocked_summary
    serving_thread = threading.Thread(target=server.serve_forever)
    serving_thread.start()
    connection = http.client.HTTPConnection(*server.server_address, timeout=5)
    try:
        connection.request("POST", "/v1/chat/completions", json.dumps({
            "model": "mock-model", "messages": [{"role": "user", "content": "unit"}],
        }), {"Content-Type": "application/json", "Authorization": "Bearer unit-token",
             "Connection": "close"})
        response = connection.getresponse()
        try:
            assert response.status == 502
            response.read()
        finally:
            response.close()
        assert entered.wait(5), "handler never reached final logging"
        server.shutdown()
        serving_thread.join(5)
        assert not serving_thread.is_alive()
        if daemon_handlers:
            server.server_close()
            assert handler_threads[0].is_alive()
            assert not finished.is_set()
        else:
            # Observe the actual join entry; an observation timeout is not success.
            original_join = handler_threads[0].join

            def observed_join(timeout=None):
                close_started.set()
                return original_join(timeout)

            handler_threads[0].join = observed_join

            def close_server():
                server.server_close()
                close_finished.set()

            close_thread = threading.Thread(target=close_server)
            close_threads.append(close_thread)
            close_thread.start()
            assert close_started.wait(5), "server_close never joined the request handler"
            assert not close_finished.is_set()
            assert not finished.is_set()
            release.set()
            close_thread.join(5)
            assert not close_thread.is_alive()
            assert close_finished.is_set()
            assert finished.is_set()
            assert not handler_threads[0].is_alive()
    finally:
        release.set()
        connection.close()
        server.shutdown()
        serving_thread.join(5)
        server.server_close()
        for close_thread in close_threads:
            close_thread.join(5)
            assert not close_thread.is_alive()
        for handler_thread in handler_threads:
            handler_thread.join(5)
            assert not handler_thread.is_alive()
        router.close()
