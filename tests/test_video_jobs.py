"""Provider-affine video job ownership tests."""

from __future__ import annotations

import pytest

from contextual_orchestrator.batch_job_registry import JobRegistryFactory
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


def test_register_replaces_provider_id_and_preserves_owner() -> None:
    factory = _SharedRegistryFactory()
    registry = VideoJobRegistry(factory)

    response = registry.register(
        {"id": "provider-job", "status": "queued"}, "declared_video_agent"
    )

    assert response == {"id": response["id"], "status": "queued"}
    assert response["id"].startswith("videojob_")
    owner = VideoJobRegistry(factory).owner(response["id"])
    assert owner.provider_job_id == "provider-job"
    assert owner.agent_id == "declared_video_agent"
    assert owner.gateway_job_id == response["id"]


@pytest.mark.parametrize("provider_id", [None, "", "   ", 7])
def test_register_rejects_untrackable_provider_result(provider_id: object) -> None:
    registry = VideoJobRegistry(_SharedRegistryFactory())

    with pytest.raises(VideoJobContractError):
        registry.register({"id": provider_id}, "declared_video_agent")


def test_unknown_gateway_job_remains_unknown() -> None:
    registry = VideoJobRegistry(_SharedRegistryFactory())

    with pytest.raises(KeyError):
        registry.owner("videojob_unknown")

