"""Regression contract for semantically specific credential-registry identifiers."""

from __future__ import annotations

from inspect import Parameter, signature

import pytest

from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    delete_credential,
    get_backend,
    get_credential,
    register_credential,
    set_backend,
)
from contextual_orchestrator.provider_bootstrap import (
    PROVIDER_ACCEPTED_CREDENTIAL_NAMES,
    register_provider_credentials_atomically,
)


@pytest.fixture(autouse=True)
def _fresh_credential_backend() -> None:
    """Isolate credential naming tests from process-global backend state."""
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


def test_public_credential_helpers_expose_semantic_identifier_names() -> None:
    """Require public signatures to name the credential concepts they carry."""
    get_parameters = signature(get_credential).parameters
    register_parameters = signature(register_credential).parameters
    delete_parameters = signature(delete_credential).parameters
    backend_parameters = signature(set_backend).parameters

    assert tuple(get_parameters) == ("credential_name",)
    assert tuple(register_parameters) == ("credential_name", "credential_value")
    assert tuple(delete_parameters) == ("credential_name",)
    assert tuple(backend_parameters) == ("credential_backend",)
    assert get_parameters["credential_name"].default is Parameter.empty
    assert register_parameters["credential_name"].default is Parameter.empty
    assert register_parameters["credential_value"].default is Parameter.empty
    assert backend_parameters["credential_backend"].default is Parameter.empty


def test_semantic_keyword_calls_roundtrip_through_active_backend() -> None:
    """Allow callers to use the bounded-context names as ordinary keywords."""
    register_credential(credential_name="OPENAI_API_KEY", credential_value="semantic-secret")

    assert get_credential(credential_name="OPENAI_API_KEY") == "semantic-secret"

    delete_credential(credential_name="OPENAI_API_KEY")
    assert get_credential(credential_name="OPENAI_API_KEY") is None


def test_legacy_generic_keywords_remain_bounded_compatibility_aliases() -> None:
    """Preserve historical keyword callers without keeping generic public metadata."""
    legacy_backend = InMemoryCredentialBackend()
    set_backend(backend=legacy_backend)
    assert get_backend() is legacy_backend

    register_credential(name="OPENAI_API_KEY", value="legacy-secret")
    assert get_credential(name="OPENAI_API_KEY") == "legacy-secret"

    delete_credential(name="OPENAI_API_KEY")
    assert get_credential(credential_name="OPENAI_API_KEY") is None


def test_semantic_and_legacy_keywords_cannot_compete_for_authority() -> None:
    """Reject duplicate semantic and compatibility aliases instead of guessing."""
    with pytest.raises(TypeError, match="credential_name"):
        get_credential(credential_name="OPENAI_API_KEY", name="BYTEZ_API_KEY")

    with pytest.raises(TypeError, match="credential_value"):
        register_credential(
            credential_name="OPENAI_API_KEY",
            credential_value="semantic-secret",
            value="legacy-secret",
        )

    with pytest.raises(TypeError, match="credential_backend"):
        set_backend(credential_backend=InMemoryCredentialBackend(), backend=None)


def test_unknown_credential_keywords_fail_closed() -> None:
    """Reject arbitrary compatibility kwargs at the public registry boundary."""
    with pytest.raises(TypeError, match="unexpected"):
        get_credential(credential_name="OPENAI_API_KEY", alias="OTHER_API_KEY")


def test_atomic_memory_bootstrap_survives_public_naming_repair() -> None:
    """Keep package-level single-lock batch registration working after public renames."""
    credential_name = PROVIDER_ACCEPTED_CREDENTIAL_NAMES[0]

    registered_names = register_provider_credentials_atomically(
        {credential_name: "atomic-secret"}
    )

    assert registered_names == (credential_name,)
    assert get_credential(credential_name=credential_name) == "atomic-secret"
