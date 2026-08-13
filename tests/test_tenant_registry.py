"""Contract tests for tenant-scoped provider and model-group metadata."""

from __future__ import annotations

import re

import pytest

from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    get_credential,
    set_backend,
)
from contextual_orchestrator.tenant_registry import (
    InMemoryTenantRegistry,
    TENANT_SCHEMA_SQL,
    TenantBoundaryError,
    TenantRegistryState,
)


def _registry_pair() -> tuple[InMemoryTenantRegistry, InMemoryTenantRegistry]:
    backend = InMemoryCredentialBackend()
    set_backend(backend)
    state = TenantRegistryState()
    return (
        InMemoryTenantRegistry(state=state, credential_backend=backend),
        InMemoryTenantRegistry(state=state, credential_backend=backend),
    )


def teardown_function() -> None:
    """Reset the process credential backend after every test."""
    set_backend(None)


def test_credential_rotation_is_shared_and_never_disclosed() -> None:
    first, second = _registry_pair()
    first.create_tenant("acme_corporation", "ACME Corporation")

    created = first.register_provider_credential(
        "acme_corporation",
        "openrouter_provider",
        "openrouter_primary_key",
        "first-secret-value",
    )
    listed = second.list_provider_credentials("acme_corporation")

    assert listed == [created]
    assert "first-secret-value" not in repr(created)
    assert "first-secret-value" not in str(created.as_dict())
    assert get_credential(created.credential_key) == "first-secret-value"

    rotated = second.register_provider_credential(
        "acme_corporation",
        "openrouter_provider",
        "openrouter_primary_key",
        "second-secret-value",
    )
    assert rotated.credential_id == created.credential_id
    assert rotated.credential_key == created.credential_key
    assert get_credential(rotated.credential_key) == "second-secret-value"
    assert first.list_provider_credentials("acme_corporation") == [rotated]


def test_cross_tenant_endpoint_reference_fails_closed() -> None:
    registry, _ = _registry_pair()
    registry.create_tenant("acme_corporation", "ACME Corporation")
    registry.create_tenant("beta_corporation", "Beta Corporation")
    credential = registry.register_provider_credential(
        "acme_corporation",
        "nvidia_provider",
        "nvidia_primary_key",
        "nvidia-secret-value",
    )

    with pytest.raises(TenantBoundaryError, match="tenant-owned credential"):
        registry.create_model_endpoint(
            "beta_corporation",
            "nvidia_secondary_endpoint",
            "nvidia_provider",
            "discovered-model-id",
            "https://integrate.api.nvidia.com/v1",
            credential.credential_id,
            priority=20,
        )


def test_group_resolution_is_ordered_scoped_and_disable_aware() -> None:
    registry, _ = _registry_pair()
    registry.create_tenant("acme_corporation", "ACME Corporation")
    registry.create_tenant("beta_corporation", "Beta Corporation")
    openrouter_key = registry.register_provider_credential(
        "acme_corporation",
        "openrouter_provider",
        "openrouter_primary_key",
        "openrouter-secret",
    )
    nvidia_key = registry.register_provider_credential(
        "acme_corporation",
        "nvidia_provider",
        "nvidia_secondary_key",
        "nvidia-secret",
    )
    beta_key = registry.register_provider_credential(
        "beta_corporation",
        "bytez_provider",
        "bytez_primary_key",
        "bytez-secret",
    )

    group = registry.create_model_group("acme_corporation", "general_chat_group")
    first_endpoint = registry.create_model_endpoint(
        "acme_corporation",
        "openrouter_primary_endpoint",
        "openrouter_provider",
        "openrouter-model-id",
        "https://openrouter.ai/api/v1",
        openrouter_key.credential_id,
        priority=50,
    )
    second_endpoint = registry.create_model_endpoint(
        "acme_corporation",
        "nvidia_secondary_endpoint",
        "nvidia_provider",
        "nvidia-model-id",
        "https://integrate.api.nvidia.com/v1",
        nvidia_key.credential_id,
        priority=10,
    )
    beta_endpoint = registry.create_model_endpoint(
        "beta_corporation",
        "bytez_primary_endpoint",
        "bytez_provider",
        "bytez-model-id",
        "https://api.bytez.com/models/v2/openai/v1",
        beta_key.credential_id,
    )

    registry.add_group_membership(
        "acme_corporation", group.group_id, second_endpoint.endpoint_id, fallback_order=20
    )
    registry.add_group_membership(
        "acme_corporation", group.group_id, first_endpoint.endpoint_id, fallback_order=10
    )
    with pytest.raises(TenantBoundaryError, match="same tenant"):
        registry.add_group_membership(
            "acme_corporation", group.group_id, beta_endpoint.endpoint_id, fallback_order=30
        )

    resolved = registry.resolve_model_group("acme_corporation", "general_chat_group")
    assert [item.endpoint_name for item in resolved] == [
        "openrouter_primary_endpoint",
        "nvidia_secondary_endpoint",
    ]
    assert [item.fallback_order for item in resolved] == [10, 20]

    registry.set_model_endpoint_enabled(
        "acme_corporation", first_endpoint.endpoint_id, enabled=False
    )
    resolved_after_disable = registry.resolve_model_group(
        "acme_corporation", "general_chat_group"
    )
    assert [item.endpoint_name for item in resolved_after_disable] == [
        "nvidia_secondary_endpoint"
    ]


def test_database_contract_is_normalized_and_uses_descriptive_names() -> None:
    expected_tables = {
        "provider_credentials",
        "tenant_records",
        "tenant_provider_credentials",
        "tenant_model_groups",
        "tenant_model_endpoints",
        "tenant_group_memberships",
    }
    found_tables = set(re.findall(r"CREATE TABLE IF NOT EXISTS\s+([a-z_]+)", TENANT_SCHEMA_SQL))
    assert expected_tables <= found_tables
    assert all("_" in table_name for table_name in found_tables)
    assert "encrypted_value" in TENANT_SCHEMA_SQL
    assert "UNIQUE (tenant_id, credential_label)" in TENANT_SCHEMA_SQL
    assert "UNIQUE (model_group_id, fallback_order)" in TENANT_SCHEMA_SQL
    assert "REFERENCES tenant_records" in TENANT_SCHEMA_SQL
