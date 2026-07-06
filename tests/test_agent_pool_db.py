"""DB-backed model-group (agent pool) management.

The pool was seed-file + in-memory only: runtime add/patch/remove evaporated on
restart. With agents_db, operator changes persist: stored rows overlay the seed at
startup, removal writes a disabled tombstone so even seed agents stay removed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


def _seed() -> list[ModelAgent]:
    return [ModelAgent("general_agent", "seed-model", tags=("reasoning", "writing"))]


NEW_AGENT = {
    "id": "coding_agent",
    "model": "gpt-5.5",
    "base_url": "https://api.openai.com/v1",
    "api_key_env": "OPENAI_API_KEY",
    "tags": ["coding", "reasoning"],
    "priority": 2,
}


def test_add_patch_remove_survive_restart() -> None:
    with tempfile.TemporaryDirectory() as directory:
        db = os.path.join(directory, "pool.db")

        first = TaskOrchestrator(_seed(), agents_db=db)
        first.add_agent("default", NEW_AGENT)
        first.patch_agent("default", "general_agent", {"priority": 9})
        assert {a.id for a in first.agents} == {"general_agent", "coding_agent"}

        second = TaskOrchestrator(_seed(), agents_db=db)  # restart with the same seed file
        by_id = {a.id: a for a in second.agents}
        assert set(by_id) == {"general_agent", "coding_agent"}  # added agent restored
        assert by_id["general_agent"].priority == 9  # patch restored over the seed
        assert by_id["coding_agent"].model == "gpt-5.5"

        second.remove_agent("default", "coding_agent")
        third = TaskOrchestrator(_seed(), agents_db=db)
        assert {a.id for a in third.agents} == {"general_agent"}  # removal survived restart


def test_seed_agent_removal_tombstones_across_restart() -> None:
    with tempfile.TemporaryDirectory() as directory:
        db = os.path.join(directory, "pool.db")
        seed = [
            ModelAgent("general_agent", "seed-model", tags=("reasoning",)),
            ModelAgent("backup_worker", "seed-model", tags=("reasoning",)),
        ]
        first = TaskOrchestrator(list(seed), agents_db=db)
        first.remove_agent("default", "backup_worker")

        second = TaskOrchestrator(list(seed), agents_db=db)  # seed still lists backup_worker
        assert {a.id for a in second.agents} == {"general_agent"}  # tombstone wins over seed


def test_add_agent_validations() -> None:
    orchestrator = TaskOrchestrator(_seed())
    for bad, why in [
        ({"model": "m"}, "missing id"),
        ({"id": "general_agent", "model": "m"}, "duplicate id"),
        ({"id": "http_agent", "model": "m", "base_url": "http://x.example/v1", "api_key_env": "K"}, "http base_url"),
        ({"id": "nokey_agent", "model": "m", "base_url": "https://x.example/v1"}, "missing api_key_env"),
    ]:
        raised = False
        try:
            orchestrator.add_agent("default", bad)
        except ValueError:
            raised = True
        assert raised, why


def test_remove_last_enabled_agent_refused() -> None:
    orchestrator = TaskOrchestrator(_seed())
    raised = False
    try:
        orchestrator.remove_agent("default", "general_agent")
    except ValueError as exc:
        raised = True
        assert "last enabled" in str(exc)
    assert raised


def test_default_stays_in_memory() -> None:
    orchestrator = TaskOrchestrator(_seed())
    assert orchestrator._pool_store is None
    orchestrator.add_agent("default", {"id": "mock_worker", "model": "m2"})
    assert {a.id for a in TaskOrchestrator(_seed()).agents} == {"general_agent"}  # nothing persisted


def _call(url: str, method: str, token: str, payload: dict | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"content-type": "application/json", "authorization": f"Bearer {token}", "connection": "close"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_http_create_and_delete_worker_agents() -> None:
    token = "pool_token"
    orchestrator = TaskOrchestrator(_seed())
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}/api/v1/agent_pools/default/worker_agents"
    try:
        status, created = _call(base, "POST", token, NEW_AGENT)
        assert status == 201 and created["id"] == "coding_agent" and created["status"] == "active"

        status, dup = _call(base, "POST", token, NEW_AGENT)
        assert status == 400  # duplicate rejected

        status, unknown = _call(base, "POST", token, {**NEW_AGENT, "id": "extra_agent", "surprise": 1})
        assert status == 400 and unknown["error"]["code"] == "unknown_fields"

        status, removed = _call(f"{base}/coding_agent", "DELETE", token)
        assert status == 200 and removed["removed"] == "coding_agent"

        status, _ = _call(f"{base}/ghost_agent", "DELETE", token)
        assert status == 404
    finally:
        server.shutdown()
    assert {a.id for a in orchestrator.agents} == {"general_agent"}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
