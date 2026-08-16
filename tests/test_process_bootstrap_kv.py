"""Process sqlite/Clearfolio/CA paths resolve from the KV, never os.getenv at init.

NIST SP 800-53 Rev. 5 CM-6 and ISO/IEC 27001:2022 A.8.9 require configuration
from an authorized store. ``CONTEXTUAL_ORCHESTRATOR_STATE_DB``,
``CONTEXTUAL_ORCHESTRATOR_AGENTS_DB``, ``CONTEXTUAL_ORCHESTRATOR_CLEARFOLIO_URL``,
and ``CONTEXTUAL_ORCHESTRATOR_PROVIDER_CA_BUNDLE`` remain bootstrap transport
into ``process_bootstrap.*``. ``TaskOrchestrator``, ``ModelClient``, and
``build_server`` read the process KV when the constructor argument is omitted.
CLI flags still win. Tokens stay on #621 — this slice does not touch them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.kv_config import (  # noqa: E402
    InMemoryConfigStore,
    get_config_store,
    reset_runtime_config_store,
    resolve_process_bootstrap,
    seed_process_bootstrap_from_environ,
    set_runtime_config,
    set_runtime_config_store,
)
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_STATE_ENV = "CONTEXTUAL_ORCHESTRATOR_STATE_DB"
_AGENTS_ENV = "CONTEXTUAL_ORCHESTRATOR_AGENTS_DB"
_CLEARFOLIO_ENV = "CONTEXTUAL_ORCHESTRATOR_CLEARFOLIO_URL"
_CA_ENV = "CONTEXTUAL_ORCHESTRATOR_PROVIDER_CA_BUNDLE"
_BOOTSTRAP_ENV = (_STATE_ENV, _AGENTS_ENV, _CLEARFOLIO_ENV, _CA_ENV)


def _snapshot_env() -> dict[str, str | None]:
    return {name: os.environ.get(name) for name in _BOOTSTRAP_ENV}


def _restore_env(previous: dict[str, str | None]) -> None:
    for name, value in previous.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _clear_bootstrap_env() -> None:
    for name in _BOOTSTRAP_ENV:
        os.environ.pop(name, None)


def _seed_agents() -> list[ModelAgent]:
    return [ModelAgent("general_agent", "mock", tags=("reasoning", "writing"))]


def test_resolve_ignores_process_environment_until_seeded() -> None:
    previous = _snapshot_env()
    reset_runtime_config_store()
    os.environ[_STATE_ENV] = "/tmp/env-only-state.db"
    try:
        settings = resolve_process_bootstrap()
        assert settings.state_database_path is None
    finally:
        reset_runtime_config_store()
        _restore_env(previous)


def test_seed_copies_env_once_and_ignores_later_edit() -> None:
    previous = _snapshot_env()
    reset_runtime_config_store()
    os.environ[_STATE_ENV] = "/tmp/first-state.db"
    os.environ[_AGENTS_ENV] = "/tmp/first-agents.db"
    os.environ[_CLEARFOLIO_ENV] = "https://clearfolio.example.com"
    os.environ[_CA_ENV] = "/tmp/first-ca.pem"
    try:
        seed_process_bootstrap_from_environ()
        first = resolve_process_bootstrap()
        assert first.state_database_path == "/tmp/first-state.db"
        assert first.agents_database_path == "/tmp/first-agents.db"
        assert first.clearfolio_viewer_url == "https://clearfolio.example.com"
        assert first.provider_ca_bundle == "/tmp/first-ca.pem"
        os.environ[_STATE_ENV] = "/tmp/evil-state.db"
        os.environ[_CLEARFOLIO_ENV] = "https://evil.example"
        seed_process_bootstrap_from_environ()
        second = resolve_process_bootstrap()
        assert second.state_database_path == "/tmp/first-state.db"
        assert second.clearfolio_viewer_url == "https://clearfolio.example.com"
    finally:
        reset_runtime_config_store()
        _restore_env(previous)


def test_seed_treats_whitespace_only_kv_as_empty() -> None:
    previous = _snapshot_env()
    reset_runtime_config_store()
    set_runtime_config("process_bootstrap", "state_database_path", "   ")
    os.environ[_STATE_ENV] = "/tmp/after-blank.db"
    try:
        seed_process_bootstrap_from_environ()
        assert resolve_process_bootstrap().state_database_path == "/tmp/after-blank.db"
    finally:
        reset_runtime_config_store()
        _restore_env(previous)


def test_explicit_cli_path_wins_over_kv() -> None:
    previous = _snapshot_env()
    reset_runtime_config_store()
    _clear_bootstrap_env()
    set_runtime_config("process_bootstrap", "state_database_path", "/tmp/kv-state.db")
    try:
        settings = resolve_process_bootstrap(state_database_path="/tmp/cli-state.db")
        assert settings.state_database_path == "/tmp/cli-state.db"
    finally:
        reset_runtime_config_store()
        _restore_env(previous)


def test_detached_config_store_is_not_init_source() -> None:
    previous = _snapshot_env()
    reset_runtime_config_store()
    _clear_bootstrap_env()
    detached_store = get_config_store()
    detached_store.set("process_bootstrap", "state_database_path", "/tmp/detached.db")
    try:
        assert resolve_process_bootstrap().state_database_path is None
    finally:
        reset_runtime_config_store()
        _restore_env(previous)


def test_installed_runtime_store_is_init_source() -> None:
    previous = _snapshot_env()
    reset_runtime_config_store()
    _clear_bootstrap_env()
    installed_store = InMemoryConfigStore()
    installed_store.set("process_bootstrap", "clearfolio_viewer_url", "https://docs.example.com")
    set_runtime_config_store(installed_store)
    try:
        assert resolve_process_bootstrap().clearfolio_viewer_url == "https://docs.example.com"
    finally:
        reset_runtime_config_store()
        _restore_env(previous)


def test_kv_state_db_survives_orchestrator_restart() -> None:
    """A buyer-seeded sqlite path must persist the real prompt across process restart."""
    previous = _snapshot_env()
    reset_runtime_config_store()
    _clear_bootstrap_env()
    with tempfile.TemporaryDirectory() as directory:
        db_path = os.path.join(directory, "workflow_state.db")
        set_runtime_config("process_bootstrap", "state_database_path", db_path)
        first = TaskOrchestrator(_seed_agents())
        try:
            record = first.run([{"role": "user", "content": "persist the invoice review"}])
            run_id = record["workflow_run_id"]
        finally:
            first.close()
        second = TaskOrchestrator(_seed_agents())
        try:
            assert run_id in second._workflow_runs
            assert second.get_workflow_run(run_id)["prompt_text"] == "persist the invoice review"
        finally:
            second.close()
            reset_runtime_config_store()
            _restore_env(previous)


def test_kv_agents_db_keeps_operator_add_across_restart() -> None:
    previous = _snapshot_env()
    reset_runtime_config_store()
    _clear_bootstrap_env()
    with tempfile.TemporaryDirectory() as directory:
        db_path = os.path.join(directory, "agent_pool.db")
        set_runtime_config("process_bootstrap", "agents_database_path", db_path)
        first = TaskOrchestrator(_seed_agents())
        first.add_agent(
            "default",
            {
                "id": "coding_agent",
                "model": "gpt-5.5",
                "base_url": "https://api.openai.com/v1",
                "credential_key": "OPENAI_API_KEY",
                "tags": ["coding", "reasoning"],
            },
        )
        first.close()
        second = TaskOrchestrator(_seed_agents())
        try:
            assert {agent.id for agent in second.agents} == {"general_agent", "coding_agent"}
        finally:
            second.close()
            reset_runtime_config_store()
            _restore_env(previous)


def test_build_server_reads_clearfolio_url_from_kv() -> None:
    previous = _snapshot_env()
    reset_runtime_config_store()
    _clear_bootstrap_env()
    set_runtime_config(
        "process_bootstrap",
        "clearfolio_viewer_url",
        "https://clearfolio.example.com/",
    )
    server = build_server(
        TaskOrchestrator(_seed_agents()),
        port=0,
        security=SecurityConfig(auth_token="t_viewer"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/admin/state",
        headers={"authorization": "Bearer t_viewer", "connection": "close"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            state = json.loads(response.read().decode("utf-8"))
        assert state["document_viewer"] == {
            "provider": "clearfolio",
            "url": "https://clearfolio.example.com",
        }
    finally:
        server.shutdown()
        reset_runtime_config_store()
        _restore_env(previous)


def test_model_client_loads_ca_bundle_from_kv_not_later_env() -> None:
    previous = _snapshot_env()
    reset_runtime_config_store()
    _clear_bootstrap_env()
    with tempfile.TemporaryDirectory() as directory:
        junk_bundle = os.path.join(directory, "not-a-ca.pem")
        Path(junk_bundle).write_text("not-a-certificate\n", encoding="utf-8")
        set_runtime_config("process_bootstrap", "provider_ca_bundle", junk_bundle)
        os.environ[_CA_ENV] = "/tmp/later-env-ca.pem"
        try:
            ModelClient()
        except ValueError as exc:
            assert "provider CA bundle" in str(exc)
            assert "later-env-ca.pem" not in str(exc)
        else:
            raise AssertionError("KV CA bundle must be loaded at ModelClient init")
        reset_runtime_config_store()
        _restore_env(previous)


def test_explicit_ca_bundle_wins_over_kv() -> None:
    previous = _snapshot_env()
    reset_runtime_config_store()
    _clear_bootstrap_env()
    with tempfile.TemporaryDirectory() as directory:
        kv_bundle = os.path.join(directory, "kv-ca.pem")
        cli_bundle = os.path.join(directory, "cli-ca.pem")
        Path(kv_bundle).write_text("kv-not-a-certificate\n", encoding="utf-8")
        Path(cli_bundle).write_text("cli-not-a-certificate\n", encoding="utf-8")
        set_runtime_config("process_bootstrap", "provider_ca_bundle", kv_bundle)
        try:
            ModelClient(ca_bundle=cli_bundle)
        except ValueError as exc:
            assert "cli-ca.pem" in str(exc)
            assert "kv-ca.pem" not in str(exc)
        else:
            raise AssertionError("explicit ca_bundle must win over KV")
        reset_runtime_config_store()
        _restore_env(previous)


if __name__ == "__main__":
    test_resolve_ignores_process_environment_until_seeded()
    test_seed_copies_env_once_and_ignores_later_edit()
    test_seed_treats_whitespace_only_kv_as_empty()
    test_explicit_cli_path_wins_over_kv()
    test_detached_config_store_is_not_init_source()
    test_installed_runtime_store_is_init_source()
    test_kv_state_db_survives_orchestrator_restart()
    test_kv_agents_db_keeps_operator_add_across_restart()
    test_build_server_reads_clearfolio_url_from_kv()
    test_model_client_loads_ca_bundle_from_kv_not_later_env()
    test_explicit_ca_bundle_wins_over_kv()
    print("ok")
