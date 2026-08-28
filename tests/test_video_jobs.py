"""Provider-affine video job ownership tests."""

from __future__ import annotations

from email.message import Message
import io
import pytest

from contextual_orchestrator.batch_job_registry import JobRegistryFactory
from contextual_orchestrator.orchestrator import (
    ModelAgent,
    ModelClient,
    ProviderResponseError,
)
from contextual_orchestrator.video_jobs import (
    VideoJobContractError,
    VideoJobOwner,
    VideoJobRecord,
    VideoJobUsage,
    VideoJobRegistry,
    video_agent_affinity_key,
)


class _SharedRegistryFactory(JobRegistryFactory):
    """Expose shared in-memory mappings for a restart-equivalent unit test."""

    def __init__(self) -> None:
        super().__init__(None)
        self._registries: dict[str, dict] = {}

    def mapping(self, name: str, *, decode=None):  # type: ignore[no-untyped-def]
        """Return the same named mapping across registry adapter instances."""
        return self._registries.setdefault(name, {})


def test_provider_followup_read_is_bounded_without_content_length() -> None:
    response = io.BytesIO(b"12345")
    response.headers = Message()  # type: ignore[attr-defined]
    with pytest.raises(ProviderResponseError, match="configured limit"):
        ModelClient._read_bounded_response(response, 4)


def test_register_replaces_provider_id_and_preserves_owner() -> None:
    factory = _SharedRegistryFactory()
    registry = VideoJobRegistry(factory)

    response = registry.register(
        {"id": "provider-job", "status": "queued"}, "declared_video_agent", "principal_one"
    )

    assert response == {"id": response["id"], "status": "queued"}
    assert response["id"].startswith("videojob_")
    owner = VideoJobRegistry(factory).owner(response["id"], "principal_one")
    assert owner.provider_job_id == "provider-job"
    assert owner.agent_id == "declared_video_agent"
    assert owner.gateway_job_id == response["id"]


def test_register_uses_normalized_ownership_and_usage_records() -> None:
    factory = _SharedRegistryFactory()
    registry = VideoJobRegistry(factory)

    response = registry.register(
        {
            "id": "provider-job",
            "usage": {"prompt_tokens": 7, "completion_tokens": 2},
        },
        "declared_video_agent",
        "principal_one",
    )

    record = factory._registries["video_job_records"][response["id"]]
    usage = factory._registries["video_job_usages"][response["id"]]
    assert isinstance(record, VideoJobRecord)
    assert isinstance(usage, VideoJobUsage)
    assert record.owner_id == "principal_one"
    assert usage.prompt_tokens == 7 and usage.completion_tokens == 2
    assert not hasattr(record, "provider_usage")
    assert registry.owner(response["id"], "principal_one").provider_usage == {
        "prompt_tokens": 7,
        "completion_tokens": 2,
    }


def test_stale_owner_observation_cannot_replace_first_complete_usage() -> None:
    factory = _SharedRegistryFactory()
    first = VideoJobRegistry(factory)
    response = first.register(
        {"id": "provider-job"}, "declared_video_agent", "principal_one"
    )
    stale_owner = first.owner(response["id"], "principal_one")
    second = VideoJobRegistry(factory)

    first.observe_provider_result(
        stale_owner, {"usage": {"input_tokens": 7, "output_tokens": 2}}
    )
    second.observe_provider_result(
        stale_owner, {"usage": {"input_tokens": 9, "output_tokens": 3}}
    )

    assert first.owner(response["id"], "principal_one").provider_usage == {
        "prompt_tokens": 7,
        "completion_tokens": 2,
    }


def test_legacy_owner_records_remain_readable_during_normalization() -> None:
    factory = _SharedRegistryFactory()
    legacy = VideoJobOwner(
        gateway_job_id="videojob_legacy",
        provider_job_id="provider-job",
        agent_id="declared_video_agent",
        submitted_at=1,
        owner_id="principal_one",
    )
    factory.mapping("video_job_owners")[legacy.gateway_job_id] = legacy

    assert VideoJobRegistry(factory).owner(
        legacy.gateway_job_id, "principal_one"
    ) == legacy


def test_video_agent_affinity_changes_with_provider_account_routing() -> None:
    original = ModelAgent(
        "video_agent", "video-model", credential_key="ACCOUNT_ONE"
    )
    replacement = ModelAgent(
        "video_agent", "video-model", credential_key="ACCOUNT_TWO"
    )

    assert video_agent_affinity_key(original) != video_agent_affinity_key(replacement)


def test_followup_with_a_different_provider_id_fails_closed() -> None:
    registry = VideoJobRegistry(_SharedRegistryFactory())
    response = registry.register(
        {"id": "provider-job"}, "declared_video_agent", "principal_one"
    )
    owner = registry.owner(response["id"], "principal_one")
    with pytest.raises(VideoJobContractError, match="different job id"):
        registry.public_response({"id": "other-provider-job"}, owner)


def test_public_response_replaces_nested_provider_job_identity() -> None:
    """Provider job ids never escape through nested metadata or URL strings."""
    factory = _SharedRegistryFactory()
    registry = VideoJobRegistry(factory)

    response = registry.register(
        {
            "id": "provider-job",
            "metadata": {
                "job_id": "provider-job",
                "status_url": "https://provider.invalid/videos/provider-job",
                "progress": 5,
            },
            "related": ["provider-job"],
        },
        "declared_video_agent",
        "principal_one",
    )

    gateway_job_id = response["id"]
    assert response == {
        "id": gateway_job_id,
        "metadata": {
            "job_id": gateway_job_id,
            "status_url": f"https://provider.invalid/videos/{gateway_job_id}",
            "progress": 5,
        },
        "related": [gateway_job_id],
    }


@pytest.mark.parametrize("provider_id", [None, "", "   ", 7])
def test_register_rejects_untrackable_provider_result(provider_id: object) -> None:
    registry = VideoJobRegistry(_SharedRegistryFactory())

    with pytest.raises(VideoJobContractError):
        registry.register({"id": provider_id}, "declared_video_agent", "principal_one")


def test_unknown_gateway_job_remains_unknown() -> None:
    registry = VideoJobRegistry(_SharedRegistryFactory())

    with pytest.raises(KeyError):
        registry.owner("videojob_unknown", "principal_one")


def test_foreign_principal_and_unknown_job_are_indistinguishable() -> None:
    registry = VideoJobRegistry(_SharedRegistryFactory())
    response = registry.register({"id": "provider-job"}, "declared_video_agent", "principal_one")
    with pytest.raises(KeyError):
        registry.owner(response["id"], "principal_two")


def test_async_usage_stays_unknown_until_provider_reports_counts() -> None:
    registry = VideoJobRegistry(_SharedRegistryFactory())
    response = registry.register({"id": "provider-job"}, "declared_video_agent", "principal_one")
    owner = registry.owner(response["id"], "principal_one")
    assert owner.usage_measurement_status == "unavailable" and owner.provider_usage is None
    owner = registry.observe_provider_result(owner, {"usage": {"input_tokens": 7, "output_tokens": 2}})
    assert owner.provider_usage == {"prompt_tokens": 7, "completion_tokens": 2}
    revised = registry.observe_provider_result(
        owner, {"usage": {"input_tokens": 9, "output_tokens": 3}}
    )
    assert revised.provider_usage == {"prompt_tokens": 7, "completion_tokens": 2}
