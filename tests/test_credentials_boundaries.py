"""Boundary coverage for credential deletion paths."""

from __future__ import annotations

import pytest

from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    delete_credential,
    get_backend,
    get_credential,
    register_credential,
    set_backend,
)


@pytest.fixture(autouse=True)
def _fresh_backend():
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


def test_delete_removes_only_the_named_credential() -> None:
    """Deleting one secret leaves its siblings intact."""
    backend = InMemoryCredentialBackend()
    backend.set("ALPHA_API_KEY", "alpha-secret")
    backend.set("BETA_API_KEY", "beta-secret")

    backend.delete("ALPHA_API_KEY")
    assert backend.get("ALPHA_API_KEY") is None
    assert backend.get("BETA_API_KEY") == "beta-secret"

    # Deleting an unknown name must be a no-op, never a KeyError.
    backend.delete("UNKNOWN_CREDENTIAL_NAME")
    assert backend.get("BETA_API_KEY") == "beta-secret"


def test_delete_credential_resolves_through_the_active_backend() -> None:
    """The module-level helper deletes from the currently registered backend."""
    register_credential("GAMMA_API_KEY", "gamma-secret")
    assert get_credential("GAMMA_API_KEY") == "gamma-secret"

    delete_credential("GAMMA_API_KEY")
    assert get_credential("GAMMA_API_KEY") is None
    # Deleting twice stays safe.
    delete_credential("GAMMA_API_KEY")
    assert get_backend().get("GAMMA_API_KEY") is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
