"""provider_egress and process_bootstrap survive process restart on the credential KV.

NIST SP 800-53 Rev. 5 CM-2 (Baseline Configuration) and CM-6 require the
authorized settings store to remain the source after a process restart.
ISO/IEC 27001:2022 A.8.9 is the same operator control. The process-wide
``InMemoryConfigStore`` is the request-time cache; the existing credential
backend (Ponytail: no second backend) is the durable copy.

Buyer next action: call ``set_runtime_config`` (or start once with the env
var set) against a retained credential backend. After restart, ``seed_*``
rehydrates those keys. Do not fold gateway Bearer tokens (#621) into this
slice. Do not write only into a detached ``get_config_store(postgres_dsn=...)``.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    get_credential,
    register_credential,
    set_backend,
)
from contextual_orchestrator.kv_config import (  # noqa: E402
    allowed_provider_hosts,
    reset_runtime_config_store,
    resolve_process_bootstrap,
    seed_process_bootstrap_from_environ,
    seed_provider_egress_from_environ,
    set_runtime_config,
)
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402

_STATE_ENV = "CONTEXTUAL_ORCHESTRATOR_STATE_DB"
_HOSTS_ENV = "CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS"
_TOKEN_ENV = "CONTEXTUAL_ORCHESTRATOR_TOKEN"
_PUBLIC_ADDRINFO = [
    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443)),
]


def _retain_backend() -> InMemoryCredentialBackend:
    backend = InMemoryCredentialBackend(retain_runtime_settings=True)
    set_backend(backend)
    return backend


def _snapshot_env() -> dict[str, str | None]:
    names = (_STATE_ENV, _HOSTS_ENV, _TOKEN_ENV)
    return {name: os.environ.get(name) for name in names}


def _restore_env(previous: dict[str, str | None]) -> None:
    for name, value in previous.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _clear_persist_env() -> None:
    for name in (_STATE_ENV, _HOSTS_ENV, _TOKEN_ENV):
        os.environ.pop(name, None)


def _seed_agents() -> list[ModelAgent]:
    return [ModelAgent("general_agent", "mock", tags=("reasoning", "writing"))]


def test_allowlist_survives_process_store_reset_on_retained_backend() -> None:
    """A buyer-seeded allowlist must still constrain egress after process restart."""
    previous = _snapshot_env()
    reset_runtime_config_store()
    _clear_persist_env()
    _retain_backend()
    try:
        set_runtime_config("provider_egress", "allowed_provider_hosts", "api.openai.com")
        assert allowed_provider_hosts() == frozenset({"api.openai.com"})
        reset_runtime_config_store()
        assert allowed_provider_hosts() == frozenset()
        seed_provider_egress_from_environ()
        assert allowed_provider_hosts() == frozenset({"api.openai.com"})
    finally:
        reset_runtime_config_store()
        set_backend(None)
        _restore_env(previous)


def test_state_db_invoice_review_survives_restart_on_retained_backend() -> None:
    """Sqlite path from the credential KV must keep the real invoice prompt."""
    previous = _snapshot_env()
    reset_runtime_config_store()
    _clear_persist_env()
    _retain_backend()
    with tempfile.TemporaryDirectory() as directory:
        db_path = os.path.join(directory, "workflow_state.db")
        set_runtime_config("process_bootstrap", "state_database_path", db_path)
        first = TaskOrchestrator(_seed_agents())
        try:
            record = first.run([{"role": "user", "content": "persist the invoice review"}])
            run_id = record["workflow_run_id"]
        finally:
            first.close()
        reset_runtime_config_store()
        assert resolve_process_bootstrap().state_database_path is None
        seed_process_bootstrap_from_environ()
        second = TaskOrchestrator(_seed_agents())
        try:
            assert second.get_workflow_run(run_id)["prompt_text"] == "persist the invoice review"
        finally:
            second.close()
            reset_runtime_config_store()
            set_backend(None)
            _restore_env(previous)


def test_env_seed_is_copied_onto_retained_backend_for_next_boot() -> None:
    previous = _snapshot_env()
    reset_runtime_config_store()
    _clear_persist_env()
    _retain_backend()
    os.environ[_HOSTS_ENV] = "api.example.com"
    os.environ[_STATE_ENV] = "/tmp/seeded-state.db"
    try:
        seed_provider_egress_from_environ()
        seed_process_bootstrap_from_environ()
        _clear_persist_env()
        reset_runtime_config_store()
        seed_provider_egress_from_environ()
        seed_process_bootstrap_from_environ()
        assert allowed_provider_hosts() == frozenset({"api.example.com"})
        assert resolve_process_bootstrap().state_database_path == "/tmp/seeded-state.db"
    finally:
        reset_runtime_config_store()
        set_backend(None)
        _restore_env(previous)


def test_persist_does_not_write_secrets_or_gateway_tokens() -> None:
    previous = _snapshot_env()
    reset_runtime_config_store()
    _clear_persist_env()
    backend = _retain_backend()
    register_credential("OPENAI_API_KEY", "sk-live-invoice")
    os.environ[_TOKEN_ENV] = "gateway-token-must-stay-on-621"
    try:
        set_runtime_config("provider_egress", "allowed_provider_hosts", "api.openai.com")
        set_runtime_config("process_bootstrap", "state_database_path", "/tmp/state.db")
        set_runtime_config("gateway_auth_token", "serve_token", "gateway-token-must-stay-on-621")
        seed_provider_egress_from_environ()
        seed_process_bootstrap_from_environ()
        assert get_credential("OPENAI_API_KEY") == "sk-live-invoice"
        assert get_credential("process_bootstrap.state_database_path") is None
        assert get_credential("provider_egress.allowed_provider_hosts") is None
        assert backend.get_runtime_setting("gateway_auth_token", "serve_token") is None
        assert "sk-live-invoice" not in [
            value for _, _, value in backend.list_runtime_settings()
        ]
        assert "gateway-token-must-stay-on-621" not in [
            value for _, _, value in backend.list_runtime_settings()
        ]
    finally:
        reset_runtime_config_store()
        set_backend(None)
        _restore_env(previous)


def test_default_backend_reset_does_not_leak_into_later_env_seed() -> None:
    """reset_runtime_config_store must drop ephemeral in-memory persisted keys."""
    previous = _snapshot_env()
    reset_runtime_config_store()
    _clear_persist_env()
    set_backend(InMemoryCredentialBackend())
    try:
        set_runtime_config("provider_egress", "allowed_provider_hosts", "stale.example")
        reset_runtime_config_store()
        os.environ[_HOSTS_ENV] = "api.openai.com"
        seed_provider_egress_from_environ()
        assert allowed_provider_hosts() == frozenset({"api.openai.com"})
    finally:
        reset_runtime_config_store()
        set_backend(None)
        _restore_env(previous)


def test_whitespace_persisted_value_does_not_freeze_fail_open() -> None:
    previous = _snapshot_env()
    reset_runtime_config_store()
    _clear_persist_env()
    backend = _retain_backend()
    try:
        backend.set_runtime_setting("provider_egress", "allowed_provider_hosts", "   ")
        os.environ[_HOSTS_ENV] = "api.openai.com"
        seed_provider_egress_from_environ()
        assert allowed_provider_hosts() == frozenset({"api.openai.com"})
    finally:
        reset_runtime_config_store()
        set_backend(None)
        _restore_env(previous)


def test_model_client_still_reads_allowlist_after_hydrate() -> None:
    previous = _snapshot_env()
    reset_runtime_config_store()
    _clear_persist_env()
    _retain_backend()
    try:
        set_runtime_config("provider_egress", "allowed_provider_hosts", "api.openai.com")
        reset_runtime_config_store()
        seed_provider_egress_from_environ()
        agent = ModelAgent(
            "coding_agent",
            "gpt-5.5",
            "https://api.openai.com/v1",
            credential_key="OPENAI_API_KEY",
            tags=("coding",),
        )
        register_credential("OPENAI_API_KEY", "sk-live-invoice")
        with patch("socket.getaddrinfo", return_value=_PUBLIC_ADDRINFO):
            ModelClient()._validate_provider(agent)
    finally:
        reset_runtime_config_store()
        set_backend(None)
        _restore_env(previous)


if __name__ == "__main__":
    test_allowlist_survives_process_store_reset_on_retained_backend()
    test_state_db_invoice_review_survives_restart_on_retained_backend()
    test_env_seed_is_copied_onto_retained_backend_for_next_boot()
    test_persist_does_not_write_secrets_or_gateway_tokens()
    test_default_backend_reset_does_not_leak_into_later_env_seed()
    test_whitespace_persisted_value_does_not_freeze_fail_open()
    test_model_client_still_reads_allowlist_after_hydrate()
    print("ok")
