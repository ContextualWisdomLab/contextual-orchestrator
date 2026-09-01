"""Naming contracts for the durable batch-job registry public seams."""

from inspect import Parameter, signature

import pytest

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


def test_registry_seams_advertise_semantic_identifiers_as_required_non_null_parameters() -> None:
    """Keep signature-driven callers from treating durable identifiers as optional."""
    inspected_parameters = (
        (signature(ValkeyJsonMapping.__init__).parameters, ("registry_name",)),
        (signature(JobRegistryFactory.lock).parameters, ("registry_name", "claim_key")),
        (signature(JobRegistryFactory.mapping).parameters, ("registry_name",)),
    )

    for public_parameters, identifier_names in inspected_parameters:
        for identifier_name in identifier_names:
            semantic_parameter = public_parameters[identifier_name]
            assert semantic_parameter.default is Parameter.empty
            assert semantic_parameter.annotation is str


def test_registry_seams_accept_legacy_keyword_identifiers_at_compatibility_boundary() -> None:
    """Keep previously valid name=/key= calls working while callers migrate."""
    valkey_mapping = ValkeyJsonMapping(object(), name="legacy_jobs")
    assert valkey_mapping._key == "batch_job_registry:legacy_jobs"  # noqa: SLF001

    registry_factory = JobRegistryFactory()
    assert registry_factory.mapping(name="legacy_jobs") == {}
    with registry_factory.lock(name="legacy_jobs", key="job_1"):
        pass


def test_registry_seams_reject_conflicting_specific_and_legacy_identifiers() -> None:
    """Fail closed when old and new keyword forms disagree or duplicate authority."""
    with pytest.raises(TypeError, match="registry_name"):
        ValkeyJsonMapping(object(), "specific_jobs", name="legacy_jobs")

    registry_factory = JobRegistryFactory()
    with pytest.raises(TypeError, match="registry_name"):
        registry_factory.mapping("specific_jobs", name="legacy_jobs")
    with pytest.raises(TypeError, match="claim_key"):
        registry_factory.lock("specific_jobs", "job_1", key="job_2")


def test_registry_seams_reject_unknown_legacy_keywords() -> None:
    """Do not turn the compatibility boundary into an open-ended kwargs sink."""
    with pytest.raises(TypeError, match="unexpected keyword"):
        ValkeyJsonMapping(object(), registry_name="jobs", arbitrary="value")

    registry_factory = JobRegistryFactory()
    with pytest.raises(TypeError, match="unexpected keyword"):
        registry_factory.mapping(registry_name="jobs", arbitrary="value")
    with pytest.raises(TypeError, match="unexpected keyword"):
        registry_factory.lock(registry_name="jobs", claim_key="job_1", arbitrary="value")
