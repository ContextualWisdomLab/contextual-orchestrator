"""KV-backed provider host allowlist (runtime purity)."""

from __future__ import annotations

import os
from pathlib import Path
import sys

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
    set_runtime_config_store(InMemoryConfigStore())
    previous = os.environ.get(ALLOWED_PROVIDER_HOSTS_ENV)
    os.environ[ALLOWED_PROVIDER_HOSTS_ENV] = "seeded.example.com"
    try:
        hosts = allowed_provider_hosts()
        assert hosts == {"seeded.example.com"}
        # After seed, store is authority: clear env and still see seeded value.
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


if __name__ == "__main__":
    test_allowed_hosts_read_from_kv_not_live_env_mutation()
    test_bootstrap_env_seeds_kv_once()
    test_empty_env_bootstrap_locks_out_later_env_injection()
    test_validate_provider_uses_kv_allowlist()
    print("ok")
