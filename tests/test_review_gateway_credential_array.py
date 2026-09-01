"""Credential-array and free-pool admission contracts for the review gateway."""

from __future__ import annotations

import pytest

from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    get_credential,
    register_credential,
    set_backend,
)
from contextual_orchestrator.model_discovery import DiscoveredModel
from contextual_orchestrator import review_gateway


@pytest.fixture(autouse=True)
def _fresh_credential_backend():
    """Keep credential-array tests isolated from the process credential registry."""
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


def _discovered(provider: str, credential_name: str, *, is_free: bool = True) -> DiscoveredModel:
    """Build one provider-evidenced free chat row for admission tests."""
    return DiscoveredModel(
        provider_name=provider,
        model_id=f"{provider}-review-model",
        credential_name=credential_name,
        chat_base_url=f"https://{provider}.example/v1",
        auth_scheme="Bearer",
        prompt_price_per_1k=0.0 if is_free else 1.0,
        completion_price_per_1k=0.0 if is_free else 1.0,
        is_free=is_free,
        capabilities=("chat",),
        output_modalities=("text",),
    )


def test_register_review_credentials_accepts_all_five_supplied_credentials() -> None:
    """OpenAI may be registered and globally discovered; admission is separate."""
    environment = {
        "BYTEZ_API_KEY": "bytez-secret",
        "NVIDIA_NIM_API_KEY": "nim-secret",
        "NVIDIA_NIM_API_KEY_SUB": "nim-sub-secret",
        "OPENROUTER_API_KEY": "router-secret",
        "OPENAI_API_KEY": "openai-secret",
    }
    requested = list(environment)

    registered = review_gateway.register_review_credentials(
        environment, credential_names=requested
    )

    assert registered == tuple(requested)
    assert all(get_credential(name) == environment[name] for name in requested)


def test_register_review_credentials_preserves_non_line_ending_bytes() -> None:
    """Mounted CR/LF is normalized without stripping legitimate boundary spaces."""
    registered = review_gateway.register_review_credentials(
        {"OPENAI_API_KEY": "  openai-secret  \r\n"},
        credential_names=["OPENAI_API_KEY"],
    )

    assert registered == ("OPENAI_API_KEY",)
    assert get_credential("OPENAI_API_KEY") == "  openai-secret  "


def test_free_review_candidates_exclude_openai_source_even_when_globally_discovered() -> None:
    """OPENAI_API_KEY discovery never becomes an orchestrator/free candidate."""
    discovered = [
        _discovered("bytez", "BYTEZ_API_KEY"),
        _discovered("nvidia_nim", "NVIDIA_NIM_API_KEY"),
        _discovered("nvidia_nim_sub", "NVIDIA_NIM_API_KEY_SUB"),
        _discovered("openrouter", "OPENROUTER_API_KEY"),
        _discovered("openai", "OPENAI_API_KEY"),
    ]

    admitted = review_gateway._free_review_candidates(discovered)

    assert {model.credential_name for model in admitted} == set(
        review_gateway.REVIEW_FREE_POOL_CREDENTIAL_NAMES
    )
    assert all(model.credential_name != "OPENAI_API_KEY" for model in admitted)


def test_free_review_candidates_require_explicit_zero_cost() -> None:
    """An eligible provider account cannot enter the free pool with nonzero cost."""
    admitted = review_gateway._free_review_candidates(
        [
            _discovered("bytez", "BYTEZ_API_KEY", is_free=False),
            _discovered("openrouter", "OPENROUTER_API_KEY", is_free=True),
        ]
    )

    assert [model.credential_name for model in admitted] == ["OPENROUTER_API_KEY"]


def test_build_review_orchestrator_excludes_preexisting_openai_credential(
    monkeypatch,
) -> None:
    """Stored OpenAI credentials cannot bypass candidate admission."""
    register_credential("OPENAI_API_KEY", "preexisting-openai-secret")
    discovered = [
        _discovered("openai", "OPENAI_API_KEY"),
        _discovered("openrouter", "OPENROUTER_API_KEY"),
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))

    orchestrator = review_gateway.build_review_orchestrator(
        {"OPENROUTER_API_KEY": "router-secret"},
        credential_names=["OPENROUTER_API_KEY"],
    )

    assert get_credential("OPENAI_API_KEY") == "preexisting-openai-secret"
    assert [agent.credential_key for agent in orchestrator.agents] == [
        "OPENROUTER_API_KEY"
    ]


def test_register_review_credentials_rejects_duplicate_array_entries() -> None:
    """Duplicate credential specifications fail closed instead of hiding config drift."""
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


@pytest.mark.parametrize(
    "missing_name",
    [
        "BYTEZ_API_KEY",
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ],
)
def test_register_review_credentials_allows_each_individual_credential_to_be_absent(
    missing_name: str,
) -> None:
    """A missing provider is explicit absence, not permission to fabricate a route."""
    environment = {
        "BYTEZ_API_KEY": "bytez-secret",
        "NVIDIA_NIM_API_KEY": "nim-secret",
        "NVIDIA_NIM_API_KEY_SUB": "nim-sub-secret",
        "OPENROUTER_API_KEY": "router-secret",
        "OPENAI_API_KEY": "openai-secret",
    }
    requested = list(environment)
    environment.pop(missing_name)

    registered = review_gateway.register_review_credentials(
        environment, credential_names=requested
    )

    assert missing_name not in registered
    assert get_credential(missing_name) is None
