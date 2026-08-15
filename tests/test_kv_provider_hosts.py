"""KV-backed provider host allowlist (runtime purity)."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.credentials import InMemoryCredentialBackend, set_backend
from contextual_orchestrator.kv_config import (
    ALLOWED_PROVIDER_HOSTS_ENV,
    InMemoryConfigStore,
    allowed_provider_hosts,
    set_config_value,
    set_runtime_config_store,
)
from contextual_orchestrator.orchestrator import ModelAgent, ModelClient


def test_allowed_hosts_read_from_kv_not_live_env_mutation() -> None:
    """Ignore request-time environment mutations after the KV is installed."""
    set_runtime_config_store(InMemoryConfigStore())
    set_config_value("provider", "allowed_hosts", "api.example.com")
    previous = os.environ.get(ALLOWED_PROVIDER_HOSTS_ENV)
    os.environ[ALLOWED_PROVIDER_HOSTS_ENV] = "evil.example"
    try:
        hosts = allowed_provider_hosts()
        assert hosts == {"api.example.com"}
        assert "evil.example" not in hosts
    finally:
        if previous is None:
            os.environ.pop(ALLOWED_PROVIDER_HOSTS_ENV, None)
        else:
            os.environ[ALLOWED_PROVIDER_HOSTS_ENV] = previous
        set_runtime_config_store(None)


def test_bootstrap_env_seeds_kv_once() -> None:
    """Seed the store once and keep the seeded value after env removal."""
    set_runtime_config_store(InMemoryConfigStore())
    previous = os.environ.get(ALLOWED_PROVIDER_HOSTS_ENV)
    os.environ[ALLOWED_PROVIDER_HOSTS_ENV] = "seeded.example.com"
    try:
        hosts = allowed_provider_hosts()
        assert hosts == {"seeded.example.com"}
        os.environ.pop(ALLOWED_PROVIDER_HOSTS_ENV, None)
        assert allowed_provider_hosts() == {"seeded.example.com"}
    finally:
        if previous is None:
            os.environ.pop(ALLOWED_PROVIDER_HOSTS_ENV, None)
        else:
            os.environ[ALLOWED_PROVIDER_HOSTS_ENV] = previous
        set_runtime_config_store(None)


def test_empty_env_bootstrap_locks_out_later_env_injection() -> None:
    """Empty bootstrap must still seed KV so post-start env cannot inject hosts."""
    set_runtime_config_store(InMemoryConfigStore())
    previous = os.environ.get(ALLOWED_PROVIDER_HOSTS_ENV)
    os.environ.pop(ALLOWED_PROVIDER_HOSTS_ENV, None)
    try:
        assert allowed_provider_hosts() == set()
        os.environ[ALLOWED_PROVIDER_HOSTS_ENV] = "evil.example"
        assert allowed_provider_hosts() == set()
        assert "evil.example" not in allowed_provider_hosts()
    finally:
        if previous is None:
            os.environ.pop(ALLOWED_PROVIDER_HOSTS_ENV, None)
        else:
            os.environ[ALLOWED_PROVIDER_HOSTS_ENV] = previous
        set_runtime_config_store(None)


def test_validate_provider_uses_kv_allowlist() -> None:
    """Reject a credentialed provider whose host is absent from the KV policy."""
    backend = InMemoryCredentialBackend()
    backend.set("MODEL_KEY", "sk-test")
    set_backend(backend)
    set_runtime_config_store(InMemoryConfigStore())
    set_config_value("provider", "allowed_hosts", ["allowed.example"])
    client = ModelClient()
    agent = ModelAgent("remote_agent", "m", "https://other.example/v1", "MODEL_KEY")
    try:
        try:
            client._validate_provider(agent)
        except RuntimeError as exc:
            assert "allowlisted" in str(exc)
        else:
            raise AssertionError("unlisted host should fail")
    finally:
        set_backend(None)
        set_runtime_config_store(None)


def test_serve_installs_runtime_config_store_from_bootstrap() -> None:
    """Install the configured runtime KV before accepting server requests."""
    import contextual_orchestrator.__main__ as cli

    configured_store = InMemoryConfigStore(
        {"provider": {"allowed_hosts": "api.example.com"}}
    )
    argv = [
        "contextual_orchestrator",
        "--serve",
        "--auth-token",
        "test-token",
    ]
    bootstrap_env = {
        "CONTEXTUAL_ORCHESTRATOR_KV_DSN": "postgresql://config.example/db",
        "CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE": "bootstrap-passphrase",
    }
    with patch.object(cli.sys, "argv", argv), patch.dict(
        cli.os.environ, bootstrap_env, clear=False
    ), patch.object(
        cli, "get_config_store", return_value=configured_store
    ) as get_store, patch.object(
        cli, "set_runtime_config_store"
    ) as install_store, patch.object(
        cli, "load_agents", return_value=[]
    ), patch.object(
        cli, "ModelClient", return_value=object()
    ), patch.object(
        cli, "TaskOrchestrator", return_value=object()
    ), patch.object(cli, "serve") as serve_server:
        cli.main()

    get_store.assert_called_once_with(
        "postgresql://config.example/db",
        fernet_key="bootstrap-passphrase",
    )
    install_store.assert_called_once_with(configured_store)
    serve_server.assert_called_once()


if __name__ == "__main__":
    test_allowed_hosts_read_from_kv_not_live_env_mutation()
    test_bootstrap_env_seeds_kv_once()
    test_empty_env_bootstrap_locks_out_later_env_injection()
    test_validate_provider_uses_kv_allowlist()
    test_serve_installs_runtime_config_store_from_bootstrap()
    print("ok")
