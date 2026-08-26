"""Provider-affine video job ownership tests."""

from __future__ import annotations

from email.message import Message
import io
import pytest

from contextual_orchestrator.batch_job_registry import JobRegistryFactory
from contextual_orchestrator.orchestrator import ModelClient, ProviderResponseError
from contextual_orchestrator.video_jobs import (
    VideoJobContractError,
    VideoJobRegistry,
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
