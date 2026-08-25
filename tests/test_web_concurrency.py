"""End-to-end concurrency checks for slow web inference requests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import socket
import threading
import urllib.error
import urllib.request

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.orchestrator import ModelClient
from contextual_orchestrator.server import SecurityConfig, build_server


class BlockingModelClient(ModelClient):
    """Hold provider calls until the test has checked liveness isolation."""

    def __init__(self, expected_calls: int) -> None:
        super().__init__(max_retries=0)
        self.expected_calls = expected_calls
        self.entered_calls = 0
        self.all_entered = threading.Event()
        self.release_calls = threading.Event()
        self._lock = threading.Lock()

    def chat(
        self,
        agent: ModelAgent,
        messages: list[dict[str, object]],
        temperature: float | None = None,
    ) -> str:
        """Signal provider entry and wait for the deterministic release gate."""
        del agent, messages, temperature
        with self._lock:
            self.entered_calls += 1
            if self.entered_calls == self.expected_calls:
                self.all_entered.set()
        if not self.release_calls.wait(timeout=5):
            raise TimeoutError("synthetic provider release was not signalled")
        return "synthetic-concurrent-response"


def _post(port: int) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(
            {
                "model": "synthetic-slow-model",
                "mode": "route",
                "messages": [{"role": "user", "content": "synthetic request"}],
            }
        ).encode("utf-8"),
        headers={"authorization": "Bearer synthetic-token", "content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_slow_provider_calls_do_not_block_liveness_or_overload_rejection() -> None:
    """Keep liveness responsive and reject excess work while all run slots wait."""
    concurrent_runs = 8
    client = BlockingModelClient(concurrent_runs)
    server = build_server(
        TaskOrchestrator(
            [ModelAgent("synthetic_slow_agent", "synthetic-slow-model", tags=("reasoning",))],
            client=client,
        ),
        port=0,
        security=SecurityConfig(
            auth_token="synthetic-token",
            rate_limit_requests=100,
            max_concurrent_runs=concurrent_runs,
        ),
    )
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    port = server.server_address[1]
    executor = ThreadPoolExecutor(max_workers=concurrent_runs + 2)
    blocked = [executor.submit(_post, port) for _ in range(concurrent_runs)]
    try:
        assert client.all_entered.wait(timeout=2)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as response:
            assert response.status == 200
        rejected_status, rejected_body = executor.submit(_post, port).result(timeout=1)
        assert rejected_status == 503
        assert rejected_body["error_code"] == "concurrency_limit_exceeded"
        assert server.request_queue_size == socket.SOMAXCONN
    finally:
        client.release_calls.set()
        assert [future.result(timeout=6)[0] for future in blocked] == [200] * concurrent_runs
        executor.shutdown(wait=True)
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
