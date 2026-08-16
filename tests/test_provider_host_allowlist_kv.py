"""Provider host allowlist is resolved from the KV, never os.getenv at request time.

NIST SP 800-53 Rev. 5 SC-7 (boundary protection) and ISO/IEC 27001:2022
A.8.20 require an explicit network allowlist. This gateway already exposed
``CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS``, but request-time
``os.environ.get`` made the process environment the runtime source. Env is
bootstrap transport into the KV only — operators seed once, then
``ModelClient._validate_provider`` reads ``provider_egress.allowed_provider_hosts``.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent  # noqa: E402
from contextual_orchestrator.credentials import InMemoryCredentialBackend, set_backend  # noqa: E402
from contextual_orchestrator.kv_config import (  # noqa: E402
    allowed_provider_hosts,
    reset_runtime_config_store,
    seed_provider_egress_from_environ,
    set_runtime_config,
)
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402

_ENV_NAME = "CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS"


def _clear_allowlist_env() -> str | None:
    previous = os.environ.get(_ENV_NAME)
    os.environ.pop(_ENV_NAME, None)
    return previous


def _restore_allowlist_env(previous: str | None) -> None:
    if previous is None:
        os.environ.pop(_ENV_NAME, None)
    else:
        os.environ[_ENV_NAME] = previous


def test_allowed_provider_hosts_ignores_process_environment() -> None:
    """A process env allowlist must not constrain egress until it is seeded into KV."""
    previous = os.environ.get(_ENV_NAME)
    reset_runtime_config_store()
    os.environ[_ENV_NAME] = "example.com"
    try:
        assert allowed_provider_hosts() == frozenset()
    finally:
        reset_runtime_config_store()
        _restore_allowlist_env(previous)


def test_allowed_provider_hosts_reads_kv_csv() -> None:
    previous = _clear_allowlist_env()
    reset_runtime_config_store()
    try:
        set_runtime_config("provider_egress", "allowed_provider_hosts", "example.com, api.openai.com")
        assert allowed_provider_hosts() == frozenset({"example.com", "api.openai.com"})
    finally:
        reset_runtime_config_store()
        _restore_allowlist_env(previous)


def test_allowed_provider_hosts_empty_kv_is_unrestricted() -> None:
    previous = _clear_allowlist_env()
    reset_runtime_config_store()
    try:
        assert allowed_provider_hosts() == frozenset()
    finally:
        reset_runtime_config_store()
        _restore_allowlist_env(previous)


def test_seed_provider_egress_from_environ_copies_once() -> None:
    """Bootstrap may copy env into KV once; later env edits must not change the set."""
    previous = os.environ.get(_ENV_NAME)
    reset_runtime_config_store()
    os.environ[_ENV_NAME] = "api.openai.com"
    try:
        seed_provider_egress_from_environ()
        assert allowed_provider_hosts() == frozenset({"api.openai.com"})
        os.environ[_ENV_NAME] = "evil.example"
        assert allowed_provider_hosts() == frozenset({"api.openai.com"})
        assert "evil.example" not in allowed_provider_hosts()
    finally:
        reset_runtime_config_store()
        _restore_allowlist_env(previous)


def test_validate_provider_rejects_unlisted_host_from_kv() -> None:
    """https://api.openai.com is public, but must fail when KV allowlists only example.com."""
    previous = _clear_allowlist_env()
    reset_runtime_config_store()
    backend = InMemoryCredentialBackend()
    backend.set("MODEL_KEY", "sk-host-check")
    set_backend(backend)
    set_runtime_config("provider_egress", "allowed_provider_hosts", "example.com")
    client = ModelClient()
    unlisted_agent = ModelAgent(
        "unlisted_agent", "gpt-example", "https://api.openai.com/v1", "MODEL_KEY"
    )
    try:
        try:
            client._validate_provider(unlisted_agent)
        except RuntimeError as exc:
            assert "allowlisted" in str(exc)
        else:
            raise AssertionError("unlisted provider should fail when KV allowlist excludes it")
    finally:
        set_backend(None)
        reset_runtime_config_store()
        _restore_allowlist_env(previous)


if __name__ == "__main__":
    test_allowed_provider_hosts_ignores_process_environment()
    test_allowed_provider_hosts_reads_kv_csv()
    test_allowed_provider_hosts_empty_kv_is_unrestricted()
    test_seed_provider_egress_from_environ_copies_once()
    test_validate_provider_rejects_unlisted_host_from_kv()
    print("ok")
