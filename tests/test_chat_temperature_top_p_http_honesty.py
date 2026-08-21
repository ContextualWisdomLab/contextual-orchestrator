"""Chat/Completions temperature and top_p sampling honesty over HTTP."""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "chat_temperature_top_p_http_honesty_token"  # noqa: S105


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
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server():
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_accepts_temperature_and_top_p_in_range() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "sample in range"}],
                "temperature": 0.7,
                "top_p": 0.9,
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_temperature_above_two() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "hot"}],
                "temperature": 2.5,
            },
        )
        assert status == 400, body
        assert "invalid_temperature" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_temperature_negative() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "cold"}],
                "temperature": -0.1,
            },
        )
        assert status == 400, body
        assert "invalid_temperature" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_temperature_bool() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "bool temp"}],
                "temperature": True,
            },
        )
        assert status == 400, body
        assert "invalid_temperature" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_top_p_zero() -> None:
    """top_p must be in (0, 1]; zero is not a valid nucleus mass."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "top_p zero"}],
                "top_p": 0,
            },
        )
        assert status == 400, body
        assert "invalid_top_p" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_top_p_above_one() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "top_p high"}],
                "top_p": 1.1,
            },
        )
        assert status == 400, body
        assert "invalid_top_p" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_temperature_bounds() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {
                "model": "mock-planner",
                "prompt": "legacy temp bounds",
                "temperature": 0,
                "top_p": 1,
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_sampling_omitted() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "defaults"}],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_concurrent_http_sampling_is_request_scoped() -> None:
    """An explicit temperature must not leak into a concurrent omitted request."""
    barrier = threading.Barrier(2)
    observed: dict[str, float | None] = {}

    class ConcurrentClient(ModelClient):
        """Hold two provider calls together so their HTTP request scopes overlap."""

        def chat(
            self,
            agent: ModelAgent,
            messages: list[dict],
            temperature: float | None = None,
            top_p: float | None = None,
        ) -> str:
            barrier.wait(timeout=5)
            prompt = str(messages[-1]["content"])
            observed[prompt] = self._effective_temperature(temperature)
            return f"[{agent.id}] answer"

    client = ConcurrentClient()
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))],
        client=client,
    )
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        explicit = {
            "model": "mock-planner",
            "messages": [{"role": "user", "content": "explicit"}],
            "temperature": 0.2,
        }
        omitted = {
            "model": "mock-planner",
            "messages": [{"role": "user", "content": "omitted"}],
        }
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda payload: _post(port, "/v1/chat/completions", payload),
                    (explicit, omitted),
                )
            )
        assert all(status == 200 for status, _body in results), results
        assert observed == {"explicit": 0.2, "omitted": None}
        assert client.default_temperature is None
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_temperature_and_top_p_in_range()
    test_http_chat_rejects_temperature_above_two()
    test_http_chat_rejects_temperature_negative()
    test_http_chat_rejects_temperature_bool()
    test_http_chat_rejects_top_p_zero()
    test_http_chat_rejects_top_p_above_one()
    test_http_completions_accepts_temperature_bounds()
    test_http_chat_accepts_sampling_omitted()
    test_concurrent_http_sampling_is_request_scoped()
    print("ok")
