"""Serve sqlite, Clearfolio, and TLS paths resolve from the runtime KV.

NIST SP 800-53 Rev. 5 CM-6 (configuration settings) and ISO/IEC 27001:2022
A.8.9 require configuration to live in a managed baseline, not ambient
process environment. ``CONTEXTUAL_ORCHESTRATOR_STATE_DB``,
``CONTEXTUAL_ORCHESTRATOR_AGENTS_DB``, ``CONTEXTUAL_ORCHESTRATOR_CLEARFOLIO_URL``,
and ``CONTEXTUAL_ORCHESTRATOR_PROVIDER_CA_BUNDLE`` remain bootstrap transport
into ``serve_runtime`` keys. A later env edit must not retarget persistence,
the document viewer, or provider TLS.

Joint Task Force. (2020). *Security and privacy controls for information
systems and organizations* (NIST Special Publication 800-53 Rev. 5).
National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-53r5

International Organization for Standardization. (2022). *Information
security, cybersecurity and privacy protection — Information security
controls* (ISO/IEC 27001:2022). https://www.iso.org/standard/27001
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import urllib.request
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.kv_config import (  # noqa: E402
    AGENTS_DATABASE_PATH_KEY,
    CLEARFOLIO_BASE_URL_KEY,
    PROVIDER_CA_BUNDLE_KEY,
    SERVE_RUNTIME_CATEGORY,
    STATE_DATABASE_PATH_KEY,
    get_runtime_config,
    reset_runtime_config_store,
    resolve_serve_runtime_paths,
    seed_serve_runtime_from_environ,
    set_runtime_config,
)
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402
from contextual_orchestrator.__main__ import serve_runtime_paths  # noqa: E402

_STATE_ENV = "CONTEXTUAL_ORCHESTRATOR_STATE_DB"
_AGENTS_ENV = "CONTEXTUAL_ORCHESTRATOR_AGENTS_DB"
_CLEARFOLIO_ENV = "CONTEXTUAL_ORCHESTRATOR_CLEARFOLIO_URL"
_CA_ENV = "CONTEXTUAL_ORCHESTRATOR_PROVIDER_CA_BUNDLE"


def _restore_env(name: str, previous: str | None) -> None:
    if previous is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = previous


def test_seed_serve_runtime_from_environ_copies_once() -> None:
    """Bootstrap may copy env into KV once; a later seed() must not recopy env."""
    previous = os.environ.get(_STATE_ENV)
    reset_runtime_config_store()
    os.environ[_STATE_ENV] = "/tmp/first_state.db"
    try:
        seed_serve_runtime_from_environ()
        assert get_runtime_config(SERVE_RUNTIME_CATEGORY, STATE_DATABASE_PATH_KEY) == "/tmp/first_state.db"
        os.environ[_STATE_ENV] = "/tmp/evil_rotated_state.db"
        seed_serve_runtime_from_environ()
        assert get_runtime_config(SERVE_RUNTIME_CATEGORY, STATE_DATABASE_PATH_KEY) == "/tmp/first_state.db"
        assert get_runtime_config(SERVE_RUNTIME_CATEGORY, STATE_DATABASE_PATH_KEY) != "/tmp/evil_rotated_state.db"
    finally:
        reset_runtime_config_store()
        _restore_env(_STATE_ENV, previous)


def test_resolve_serve_runtime_paths_ignores_live_environment() -> None:
    """A process env path must not win after the KV already holds the baseline."""
    previous = os.environ.get(_STATE_ENV)
    reset_runtime_config_store()
    try:
        set_runtime_config(SERVE_RUNTIME_CATEGORY, STATE_DATABASE_PATH_KEY, "/tmp/kv_state.db")
        os.environ[_STATE_ENV] = "/tmp/env_only_state.db"
        state_db, agents_db, clearfolio_url, provider_ca_bundle = resolve_serve_runtime_paths()
        assert state_db == "/tmp/kv_state.db"
        assert agents_db is None
        assert clearfolio_url is None
        assert provider_ca_bundle is None
    finally:
        reset_runtime_config_store()
        _restore_env(_STATE_ENV, previous)


def test_explicit_cli_paths_win_over_kv() -> None:
    reset_runtime_config_store()
    try:
        set_runtime_config(SERVE_RUNTIME_CATEGORY, STATE_DATABASE_PATH_KEY, "/tmp/kv_state.db")
        set_runtime_config(SERVE_RUNTIME_CATEGORY, CLEARFOLIO_BASE_URL_KEY, "https://kv.example.com")
        state_db, _, clearfolio_url, _ = resolve_serve_runtime_paths(
            state_db="/tmp/cli_state.db",
            clearfolio_url="https://cli.example.com",
        )
        assert state_db == "/tmp/cli_state.db"
        assert clearfolio_url == "https://cli.example.com"
    finally:
        reset_runtime_config_store()


def test_restart_uses_seeded_state_database_not_later_env() -> None:
    """Buyer next action: seed once, then open the KV sqlite path after restart."""
    previous = os.environ.get(_STATE_ENV)
    reset_runtime_config_store()
    with tempfile.TemporaryDirectory() as directory:
        seeded = os.path.join(directory, "seeded_state.db")
        later = os.path.join(directory, "later_env_state.db")
        os.environ[_STATE_ENV] = seeded
        seed_serve_runtime_from_environ()
        os.environ[_STATE_ENV] = later
        state_db, _, _, _ = resolve_serve_runtime_paths()
        first = TaskOrchestrator(
            [ModelAgent("general_agent", "mock", tags=("reasoning", "writing"))],
            state_db=state_db,
        )
        record = first.run([{"role": "user", "content": "persist invoice INV-9"}])
        run_id = record["workflow_run_id"]
        first.close()
        seeded_restart = TaskOrchestrator(
            [ModelAgent("general_agent", "mock", tags=("reasoning", "writing"))],
            state_db=seeded,
        )
        later_restart = TaskOrchestrator(
            [ModelAgent("general_agent", "mock", tags=("reasoning", "writing"))],
            state_db=later,
        )
        try:
            assert state_db == seeded
            assert run_id in seeded_restart._workflow_runs
            assert seeded_restart.get_workflow_run(run_id)["prompt_text"] == "persist invoice INV-9"
            assert later_restart._workflow_runs == {}
        finally:
            seeded_restart.close()
            later_restart.close()
            reset_runtime_config_store()
            _restore_env(_STATE_ENV, previous)


def test_admin_state_uses_seeded_clearfolio_url_not_later_env() -> None:
    """Buyer next action: seed once, then open the KV Clearfolio URL in Integrations."""
    previous = os.environ.get(_CLEARFOLIO_ENV)
    reset_runtime_config_store()
    os.environ[_CLEARFOLIO_ENV] = "https://seeded-clearfolio.example.com/"
    seed_serve_runtime_from_environ()
    os.environ[_CLEARFOLIO_ENV] = "https://later-env.example.com/"
    _, _, clearfolio_url, _ = resolve_serve_runtime_paths()
    server = build_server(
        TaskOrchestrator([ModelAgent("general_agent", "mock-model", tags=("reasoning",))]),
        port=0,
        security=SecurityConfig(auth_token="t_viewer", rate_limit_requests=10_000),
        clearfolio_url=clearfolio_url,
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
    finally:
        server.shutdown()
        thread.join(timeout=5)
        reset_runtime_config_store()
        _restore_env(_CLEARFOLIO_ENV, previous)
    assert clearfolio_url == "https://seeded-clearfolio.example.com/"
    assert state["document_viewer"] == {
        "provider": "clearfolio",
        "url": "https://seeded-clearfolio.example.com",
    }


def test_serve_runtime_paths_seeds_all_bootstrap_keys() -> None:
    previous = {
        _STATE_ENV: os.environ.get(_STATE_ENV),
        _AGENTS_ENV: os.environ.get(_AGENTS_ENV),
        _CLEARFOLIO_ENV: os.environ.get(_CLEARFOLIO_ENV),
        _CA_ENV: os.environ.get(_CA_ENV),
    }
    reset_runtime_config_store()
    os.environ[_STATE_ENV] = "/tmp/seeded_state.db"
    os.environ[_AGENTS_ENV] = "/tmp/seeded_agents.db"
    os.environ[_CLEARFOLIO_ENV] = "https://seeded-clearfolio.example.com"
    os.environ[_CA_ENV] = "/tmp/seeded_provider.pem"
    try:
        state_db, agents_db, clearfolio_url, provider_ca_bundle = serve_runtime_paths(
            SimpleNamespace(state_db="", agents_db="", clearfolio_url="", provider_ca_bundle="")
        )
        assert state_db == "/tmp/seeded_state.db"
        assert agents_db == "/tmp/seeded_agents.db"
        assert clearfolio_url == "https://seeded-clearfolio.example.com"
        assert provider_ca_bundle == "/tmp/seeded_provider.pem"
        assert get_runtime_config(SERVE_RUNTIME_CATEGORY, AGENTS_DATABASE_PATH_KEY) == "/tmp/seeded_agents.db"
        assert get_runtime_config(SERVE_RUNTIME_CATEGORY, PROVIDER_CA_BUNDLE_KEY) == "/tmp/seeded_provider.pem"
    finally:
        reset_runtime_config_store()
        for name, value in previous.items():
            _restore_env(name, value)


if __name__ == "__main__":
    test_seed_serve_runtime_from_environ_copies_once()
    test_resolve_serve_runtime_paths_ignores_live_environment()
    test_explicit_cli_paths_win_over_kv()
    test_restart_uses_seeded_state_database_not_later_env()
    test_admin_state_uses_seeded_clearfolio_url_not_later_env()
    test_serve_runtime_paths_seeds_all_bootstrap_keys()
    print("ok")
