"""mode/orchestration_mode casefold auto|route|conduct over HTTP."""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.server import SecurityConfig, build_server

_TEST_AUTH_TOKEN = "mode_casefold_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing", "embedding"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
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


def test_http_chat_accepts_mode_casefold_route_conduct_auto() -> None:
    server, thread, port = _server()
    try:
        for key, val in (
            ("mode", "ROUTE"),
            ("mode", " Conduct "),
            ("mode", "AuTo"),
            ("orchestration_mode", "ROUTE"),
            ("orchestration", "CONDUCT"),
        ):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"{key}={val}"}],
                    key: val,
                },
            )
            assert status == 200, (key, val, body)
            assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_mode_cascade() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "cascade"}],
                "mode": "CASCADE",
            },
        )
        assert status == 400, body
        assert "invalid_mode" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_dimensions_digit_string_still_named_reject() -> None:
    """Digit-string dimensions coerce then fail closed (not applied)."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            # embeddings path via wrong helper? use urllib for embeddings
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "skip"}],
            },
        )
        # chat baseline smoke so server is warm
        assert status == 200, body
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/embeddings",
            data=json.dumps(
                {"model": "mock-planner", "input": "hello", "dimensions": "8"}
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status2 = response.status
                body2 = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            status2 = exc.code
            body2 = json.loads(exc.read().decode("utf-8"))
        assert status2 == 400, body2
        assert "invalid_dimensions" in json.dumps(body2)
        assert "not supported" in json.dumps(body2)

        # Whole-float dimensions also coerce then fail closed.
        request_f = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/embeddings",
            data=json.dumps(
                {"model": "mock-planner", "input": "hello", "dimensions": 8.0}
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request_f, timeout=10) as response:
                status3 = response.status
                body3 = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            status3 = exc.code
            body3 = json.loads(exc.read().decode("utf-8"))
        assert status3 == 400, body3
        assert "invalid_dimensions" in json.dumps(body3)
        assert "not supported" in json.dumps(body3)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_mode_casefold_route_conduct_auto()
    test_http_chat_still_rejects_mode_cascade()
    test_http_embeddings_dimensions_digit_string_still_named_reject()
    print("ok")
