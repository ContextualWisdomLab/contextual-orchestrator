"""Credential-array contracts for the trusted review gateway."""

from __future__ import annotations

import pytest

from contextual_orchestrator.credentials import InMemoryCredentialBackend, get_credential, set_backend
from contextual_orchestrator import review_gateway


@pytest.fixture(autouse=True)
def _fresh_credential_backend():
    """Keep credential-array tests isolated from the process credential registry."""
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


def test_register_review_credentials_uses_only_requested_array() -> None:
    """A surrounding OpenAI secret is not detected when the free pool excludes it."""
    environment = {
        "BYTEZ_API_KEY": "bytez-secret",
        "NVIDIA_NIM_API_KEY": "nim-secret",
        "NVIDIA_NIM_API_KEY_SUB": "nim-sub-secret",
        "OPENROUTER_API_KEY": "router-secret",
        "OPENAI_API_KEY": "must-not-be-seen",
    }
    requested = [
        "BYTEZ_API_KEY",
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "OPENROUTER_API_KEY",
    ]

    registered = review_gateway.register_review_credentials(
        environment, credential_names=requested
    )

    assert registered == tuple(requested)
    assert get_credential("OPENAI_API_KEY") is None
    assert all(get_credential(name) == environment[name] for name in requested)


def test_register_review_credentials_rejects_duplicate_array_entries() -> None:
    """Duplicate credential specifications fail closed instead of hiding policy drift."""
    with pytest.raises(ValueError, match="duplicate credential"):
        review_gateway.register_review_credentials(
            {"BYTEZ_API_KEY": "secret"},
            credential_names=["BYTEZ_API_KEY", "BYTEZ_API_KEY"],
        )


def test_register_review_credentials_rejects_unknown_array_entries() -> None:
    """Only credential names declared by provider sources are accepted."""
    with pytest.raises(ValueError, match="unknown credential"):
        review_gateway.register_review_credentials(
            {"UNDECLARED_API_KEY": "secret"},
            credential_names=["UNDECLARED_API_KEY"],
        )
