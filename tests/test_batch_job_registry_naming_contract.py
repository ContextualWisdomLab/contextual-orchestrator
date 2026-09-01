"""Naming contracts for the durable batch-job registry public seams."""

from inspect import signature

from contextual_orchestrator.batch_job_registry import JobRegistryFactory, ValkeyJsonMapping


def test_registry_seams_use_bounded_context_names_for_public_parameters() -> None:
    """Reject generic name/key parameters where registry semantics are known."""
    mapping_init_parameters = signature(ValkeyJsonMapping.__init__).parameters
    factory_lock_parameters = signature(JobRegistryFactory.lock).parameters
    factory_mapping_parameters = signature(JobRegistryFactory.mapping).parameters

    assert "registry_name" in mapping_init_parameters
    assert "name" not in mapping_init_parameters

    assert "registry_name" in factory_lock_parameters
    assert "claim_key" in factory_lock_parameters
    assert "name" not in factory_lock_parameters
    assert "key" not in factory_lock_parameters

    assert "registry_name" in factory_mapping_parameters
    assert "name" not in factory_mapping_parameters
