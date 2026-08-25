"""Regression coverage for mounted provider-secret normalization."""

from __future__ import annotations

from pathlib import Path

import pytest

from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    get_credential,
    set_backend,
)
from contextual_orchestrator.provider_bootstrap import (
    PROVIDER_CREDENTIAL_NAMES,
    collect_provider_credentials,
    register_provider_credentials_atomically,
)


@pytest.fixture(autouse=True)
def isolated_credential_backend():
    """Give each test a fresh process-local credential registry."""
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


def _complete_environment() -> dict[str, str]:
    """Return a complete mounted-secret inventory."""
    return {name: f"secret-for-{name.lower()}\n" for name in PROVIDER_CREDENTIAL_NAMES}


def test_collection_removes_only_mounted_line_endings() -> None:
    """Do not silently rewrite other credential bytes while removing CR/LF mounts."""
    environment = _complete_environment()
    environment["OPENAI_API_KEY"] = "  edge-sensitive-secret  \r\n"

    collected = collect_provider_credentials(environment)

    assert collected["OPENAI_API_KEY"] == "  edge-sensitive-secret  "
    assert collected["BYTEZ_API_KEY"] == "secret-for-bytez_api_key"


def test_atomic_registration_preserves_normalized_secret_bytes() -> None:
    """The atomic backend write must not perform a second broad whitespace trim."""
    credentials = {
        name: f"secret-for-{name.lower()}"
        for name in PROVIDER_CREDENTIAL_NAMES
    }
    credentials["OPENROUTER_API_KEY"] = "  edge-sensitive-router-secret  "

    register_provider_credentials_atomically(credentials)

    assert get_credential("OPENROUTER_API_KEY") == "  edge-sensitive-router-secret  "


def test_catalog_sync_leak_guard_matches_secret_normalization() -> None:
    """The workflow checks the exact credential bytes that bootstrap handles."""
    workflow = Path(".github/workflows/provider-catalog-sync.yml").read_text(
        encoding="utf-8"
    )

    assert "os.environ[name].rstrip('\\r\\n')" in workflow
    assert "os.environ[name] and os.environ[name] in report" not in workflow


def test_catalog_sync_has_postgres_fallback_when_durable_kv_is_unconfigured() -> None:
    """Scheduled discovery must run without falsely claiming durable storage."""
    workflow = Path(".github/workflows/provider-catalog-sync.yml").read_text(
        encoding="utf-8"
    )

    assert "image: postgres:17.6-alpine" in workflow
    assert "CATALOG_STORAGE_SCOPE=run-scoped" in workflow
    assert "KV DSN and passphrase must be configured together" in workflow


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
