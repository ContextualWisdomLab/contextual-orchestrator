"""HTTP honesty: OpenAI embeddings ``user`` maps to cost-ledger account rollup."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import (  # noqa: E402
    CostRoutingCoordinator,
    InMemoryConfigStore,
    ModelAgent,
    PriceBook,
    TaskOrchestrator,
)
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "embeddings_user_account_rollup_token"  # noqa: S105


def _serve():
    agents = [
        ModelAgent(
            id="mock_worker",
            model="mock-a",
            base_url="mock://a",
            provider_name="mock",
            tags=("reasoning", "coding", "writing"),
            priority=1,
        )
    ]
    orchestrator = TaskOrchestrator(agents)
    coordinator = CostRoutingCoordinator(
        orchestrator, InMemoryConfigStore(), price_book=PriceBook(InMemoryConfigStore())
    )
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN),
        coordinator=coordinator,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1], coordinator


def _post_embeddings(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/embeddings",
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


def _get_json(port: int, path: str) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        headers={
            "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
            "connection": "close",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_http_embeddings_user_maps_to_account_records() -> None:
    server, thread, port, _coordinator = _serve()
    try:
        status, body = _post_embeddings(
            port,
            {
                "model": "text-embedding-test",
                "input": "buyer invoice line for cost rollup",
                "user": "embed-end-user-42",
            },
        )
        assert status == 200, body
        assert body.get("object") == "list", body
        st, payload = _get_json(port, "/api/v1/llm_usage_records")
        assert st == 200, payload
        items = payload.get("items") or []
        assert any(
            (row.get("account_name") or row.get("account")) == "embed-end-user-42"
            for row in items
        ), payload
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_user_appears_in_account_rollup() -> None:
    server, thread, port, _coordinator = _serve()
    try:
        status, body = _post_embeddings(
            port,
            {
                "model": "text-embedding-test",
                "input": "rollup dimension check",
                "user": "rollup-account-7",
            },
        )
        assert status == 200, body
        st, report = _get_json(port, "/api/v1/cost_reports/rollup?dimension=account")
        assert st == 200, report
        assert report.get("dimension") == "account", report
        items = report.get("items") or []
        assert any(
            (row.get("dimension_value") or row.get("account") or row.get("value"))
            == "rollup-account-7"
            for row in items
        ), report
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_explicit_attribution_account_wins() -> None:
    server, thread, port, _coordinator = _serve()
    try:
        status, body = _post_embeddings(
            port,
            {
                "model": "text-embedding-test",
                "input": "explicit attribution beats user",
                "user": "from-user-field",
                "attribution": {"account": "explicit-embed-account"},
            },
        )
        assert status == 200, body
        st, payload = _get_json(port, "/api/v1/llm_usage_records")
        assert st == 200, payload
        items = payload.get("items") or []
        assert any(
            (row.get("account_name") or row.get("account")) == "explicit-embed-account"
            for row in items
        ), payload
        assert not any(
            (row.get("account_name") or row.get("account")) == "from-user-field"
            for row in items
        ), payload
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_omit_user_is_unattributed_account() -> None:
    server, thread, port, _coordinator = _serve()
    try:
        status, body = _post_embeddings(
            port,
            {
                "model": "text-embedding-test",
                "input": "no user field on request",
            },
        )
        assert status == 200, body
        st, payload = _get_json(port, "/api/v1/llm_usage_records")
        assert st == 200, payload
        items = payload.get("items") or []
        assert items, payload
        assert all(
            (row.get("account_name") or row.get("account") or "unattributed")
            == "unattributed"
            for row in items
        ), payload
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_rejects_empty_user() -> None:
    server, thread, port, _coordinator = _serve()
    try:
        status, body = _post_embeddings(
            port,
            {
                "model": "text-embedding-test",
                "input": "empty user must fail closed",
                "user": "  ",
            },
        )
        assert status == 400, body
        assert body.get("error", {}).get("code") == "invalid_user", body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_embeddings_user_maps_to_account_records()
    test_http_embeddings_user_appears_in_account_rollup()
    test_http_embeddings_explicit_attribution_account_wins()
    test_http_embeddings_omit_user_is_unattributed_account()
    test_http_embeddings_rejects_empty_user()
    print("ok")
