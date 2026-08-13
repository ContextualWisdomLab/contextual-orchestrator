"""Completions attribution and routing shape honesty over HTTP.

Mirrors chat/Responses control-plane honesty on the legacy Completions surface:
known dimensions and sync routing are accepted; unknown dimensions, free-form
routing keys, and invalid channel/priority/latency flags fail closed with named
errors (not opaque unknown_fields). Batch routing returns a 202 job handle.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "completions_attribution_routing_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/completions",
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


def _server():
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_completions_accepts_known_attribution_and_sync_routing() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "prompt": "known dims",
                "attribution": {"team": "platform", "company": "acme"},
                "routing": {"channel": "sync", "priority": "interactive"},
            },
        )
        assert status == 200, body
        assert body.get("object") == "text_completion" or "choices" in body
        assert "unknown_fields" not in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_unknown_attribution_dimension() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "prompt": "bad dim",
                "attribution": {"team": "platform", "cost_center": "xyz"},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_attribution" in blob
        assert "unsupported" in blob or "cost_center" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_attribution_non_object() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "prompt": "attr string",
                "attribution": "team=platform",
            },
        )
        assert status == 400, body
        assert "invalid_attribution" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_routing_unknown_key() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "prompt": "routing junk",
                "routing": {"channel": "sync", "region": "us-east"},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_routing" in blob
        assert "unsupported" in blob or "region" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_routing_latency_tolerant_non_boolean() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "prompt": "latency string",
                "routing": {"latency_tolerant": "yes"},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_routing" in blob
        assert "boolean" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_routing_invalid_channel() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "prompt": "channel bad",
                "routing": {"channel": "turbo"},
            },
        )
        assert status == 400, body
        assert "invalid_routing" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_routing_invalid_priority() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "prompt": "priority bad",
                "routing": {"priority": "urgent"},
            },
        )
        assert status == 400, body
        assert "invalid_routing" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_batch_routing_returns_job_handle() -> None:
    """latency_tolerant true / channel=batch should select batch channel (202)."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "prompt": "batch me",
                "routing": {"latency_tolerant": True},
            },
        )
        assert status == 202, body
        assert body.get("channel") == "batch" or "job_id" in body
        assert "unknown_fields" not in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_explicit_batch_channel() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "prompt": "batch channel",
                "routing": {"channel": "batch"},
            },
        )
        assert status == 202, body
        assert body.get("channel") == "batch" or "job_id" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_baseline_without_attribution_routing() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port, {"model": "mock-planner", "prompt": "baseline"}
        )
        assert status == 200, body
        assert body.get("object") == "text_completion" or "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_completions_accepts_known_attribution_and_sync_routing()
    test_http_completions_rejects_unknown_attribution_dimension()
    test_http_completions_rejects_attribution_non_object()
    test_http_completions_rejects_routing_unknown_key()
    test_http_completions_rejects_routing_latency_tolerant_non_boolean()
    test_http_completions_rejects_routing_invalid_channel()
    test_http_completions_rejects_routing_invalid_priority()
    test_http_completions_batch_routing_returns_job_handle()
    test_http_completions_accepts_explicit_batch_channel()
    test_http_completions_baseline_without_attribution_routing()
    print("ok")
