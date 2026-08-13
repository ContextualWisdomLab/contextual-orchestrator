"""Idempotency-Key support for safe POST /v1/chat/completions retries."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import IdempotencyStore, SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "secret_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def post_completion(
    port: int,
    payload: dict[str, object],
    *,
    token: str = _TEST_AUTH_TOKEN,
    idempotency_key: str | None = None,
) -> tuple[int, dict[str, object], dict[str, str]]:
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "connection": "close",
    }
    if idempotency_key is not None:
        headers["idempotency-key"] = idempotency_key
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
            hdrs = {k.lower(): v for k, v in response.headers.items()}
            return response.status, body, hdrs
    except urllib.error.HTTPError as exc:
        body = json.loads(exc.read().decode("utf-8"))
        hdrs = {k.lower(): v for k, v in exc.headers.items()}
        return exc.code, body, hdrs


def test_idempotency_store_conflict_and_replay_helpers() -> None:
    store = IdempotencyStore(ttl_seconds=60, max_entries=8)
    fp_a = IdempotencyStore.fingerprint("/v1/chat/completions", {"messages": [{"role": "user", "content": "a"}]})
    fp_b = IdempotencyStore.fingerprint("/v1/chat/completions", {"messages": [{"role": "user", "content": "b"}]})
    store.store("key-1", fp_a, 200, b'{"ok":true}')
    assert store.lookup("key-1", fp_a) == (200, b'{"ok":true}')
    try:
        store.lookup("key-1", fp_b)
        raise AssertionError("expected conflict")
    except Exception as exc:  # RequestError
        assert getattr(exc, "status") == 409
        assert getattr(exc, "code") == "idempotency_key_conflict"


def test_chat_completions_idempotency_key_replays_same_body() -> None:
    """Buyer path: safe retries with Idempotency-Key return the frozen response."""
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    payload = {"messages": [{"role": "user", "content": "hello idempotency"}], "orchestration": "route"}
    try:
        status1, body1, headers1 = post_completion(port, payload, idempotency_key="client-key-1")
        status2, body2, headers2 = post_completion(port, payload, idempotency_key="client-key-1")
        status3, body3, headers3 = post_completion(
            port,
            {"messages": [{"role": "user", "content": "different"}], "orchestration": "route"},
            idempotency_key="client-key-1",
        )
        status4, body4, _ = post_completion(
            port,
            {**payload, "stream": True},
            idempotency_key="stream-key",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status1 == 200
    assert "choices" in body1
    assert status2 == 200
    assert body2 == body1
    assert headers2.get("idempotent-replayed") == "true"
    assert headers1.get("idempotent-replayed") != "true"
    assert status3 == 409
    assert body3["error"]["code"] == "idempotency_key_conflict"
    assert status4 == 400
    assert body4["error"]["code"] == "idempotency_not_supported"


if __name__ == "__main__":
    test_idempotency_store_conflict_and_replay_helpers()
    test_chat_completions_idempotency_key_replays_same_body()
    print("ok")
