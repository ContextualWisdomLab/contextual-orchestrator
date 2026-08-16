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
import socket
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent  # noqa: E402
from contextual_orchestrator.credentials import InMemoryCredentialBackend, set_backend  # noqa: E402
from contextual_orchestrator.kv_config import (  # noqa: E402
    InMemoryConfigStore,
    allowed_provider_hosts,
    get_config_store,
    reset_runtime_config_store,
    seed_provider_egress_from_environ,
    set_runtime_config,
    set_runtime_config_store,
)
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402
from fuzz.targets import exercise_host_allowlist  # noqa: E402

_ENV_NAME = "CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS"
_PUBLIC_ADDRINFO = [
    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443)),
]


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
    """Bootstrap may copy env into KV once; a later seed() must not recopy env."""
    previous = os.environ.get(_ENV_NAME)
    reset_runtime_config_store()
    os.environ[_ENV_NAME] = "api.openai.com"
    try:
        seed_provider_egress_from_environ()
        assert allowed_provider_hosts() == frozenset({"api.openai.com"})
        os.environ[_ENV_NAME] = "evil.example"
        seed_provider_egress_from_environ()
        assert allowed_provider_hosts() == frozenset({"api.openai.com"})
        assert "evil.example" not in allowed_provider_hosts()
    finally:
        reset_runtime_config_store()
        _restore_allowlist_env(previous)


def test_seed_treats_whitespace_only_kv_as_empty() -> None:
    """A stored '   ' must not freeze fail-open; bootstrap may still copy env."""
    previous = os.environ.get(_ENV_NAME)
    reset_runtime_config_store()
    set_runtime_config("provider_egress", "allowed_provider_hosts", "   ")
    os.environ[_ENV_NAME] = "api.openai.com"
    try:
        seed_provider_egress_from_environ()
        assert allowed_provider_hosts() == frozenset({"api.openai.com"})
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


def test_validate_provider_ignores_env_only_allowlist() -> None:
    """Env-only example.com must not reject https://api.openai.com when KV is empty.

    The helper ``allowed_provider_hosts()`` already ignores env. This locks the
    request path: ``_validate_provider`` must not fall back to ``os.environ``.
    """
    previous = os.environ.get(_ENV_NAME)
    reset_runtime_config_store()
    os.environ[_ENV_NAME] = "example.com"
    backend = InMemoryCredentialBackend()
    backend.set("MODEL_KEY", "sk-host-check")
    set_backend(backend)
    client = ModelClient()
    public_agent = ModelAgent(
        "public_agent", "gpt-example", "https://api.openai.com/v1", "MODEL_KEY"
    )
    try:
        with patch(
            "contextual_orchestrator.orchestrator.socket.getaddrinfo",
            return_value=_PUBLIC_ADDRINFO,
        ):
            client._validate_provider(public_agent)
    finally:
        set_backend(None)
        reset_runtime_config_store()
        _restore_allowlist_env(previous)


def test_validate_provider_accepts_kv_listed_public_host() -> None:
    """A KV-listed public host must pass the extra hostname filter."""
    previous = _clear_allowlist_env()
    reset_runtime_config_store()
    backend = InMemoryCredentialBackend()
    backend.set("MODEL_KEY", "sk-host-check")
    set_backend(backend)
    set_runtime_config("provider_egress", "allowed_provider_hosts", "api.openai.com")
    client = ModelClient()
    listed_agent = ModelAgent(
        "listed_agent", "gpt-example", "https://api.openai.com/v1", "MODEL_KEY"
    )
    try:
        with patch(
            "contextual_orchestrator.orchestrator.socket.getaddrinfo",
            return_value=_PUBLIC_ADDRINFO,
        ):
            client._validate_provider(listed_agent)
    finally:
        set_backend(None)
        reset_runtime_config_store()
        _restore_allowlist_env(previous)


def test_separate_config_store_is_not_request_source() -> None:
    """Writes to a new get_config_store() must not change request-time egress.

    The process-wide runtime store is InMemoryConfigStore unless the operator
    installs another backend with set_runtime_config_store() at bootstrap.
    """
    previous = _clear_allowlist_env()
    reset_runtime_config_store()
    detached_store = get_config_store()
    detached_store.set("provider_egress", "allowed_provider_hosts", "example.com")
    try:
        assert allowed_provider_hosts() == frozenset()
    finally:
        reset_runtime_config_store()
        _restore_allowlist_env(previous)


def test_parse_host_allowlist_known_shapes() -> None:
    """CSV, sequences, empty, and mixed-case values must parse without crashing."""
    exercise_host_allowlist("Example.COM, api.openai.com")
    exercise_host_allowlist(["API.OpenAI.com", "  ", None])
    exercise_host_allowlist(None)
    exercise_host_allowlist("")
    exercise_host_allowlist({"ignored": "shape"})


def test_installed_runtime_store_is_request_source() -> None:
    """An operator-installed process store is the request-time allowlist source."""
    previous = _clear_allowlist_env()
    reset_runtime_config_store()
    installed_store = InMemoryConfigStore()
    installed_store.set("provider_egress", "allowed_provider_hosts", "example.com")
    set_runtime_config_store(installed_store)
    try:
        assert allowed_provider_hosts() == frozenset({"example.com"})
    finally:
        reset_runtime_config_store()
        _restore_allowlist_env(previous)


if __name__ == "__main__":
    test_allowed_provider_hosts_ignores_process_environment()
    test_allowed_provider_hosts_reads_kv_csv()
    test_allowed_provider_hosts_empty_kv_is_unrestricted()
    test_seed_provider_egress_from_environ_copies_once()
    test_seed_treats_whitespace_only_kv_as_empty()
    test_validate_provider_rejects_unlisted_host_from_kv()
    test_validate_provider_ignores_env_only_allowlist()
    test_validate_provider_accepts_kv_listed_public_host()
    test_separate_config_store_is_not_request_source()
    test_installed_runtime_store_is_request_source()
    test_parse_host_allowlist_known_shapes()
    print("ok")
