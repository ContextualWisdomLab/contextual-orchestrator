"""Regression tests for asynchronous video ownership and usage atomicity."""

from __future__ import annotations

import threading
from typing import Any

from contextual_orchestrator.batch_job_registry import JobRegistryFactory
from contextual_orchestrator.video_jobs import (
    VideoJobOwner,
    VideoJobRegistry,
    VideoJobUsage,
)


class _AtomicUsageMapping(dict[str, Any]):
    """Model one shared durable mapping with atomic first-write-wins semantics."""

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._preferred_first_write = threading.Event()

    def set_if_absent(self, key: str, value: Any) -> bool:
        """Store the seven-token report before the competing stale report."""
        if isinstance(value, VideoJobUsage) and value.prompt_tokens == 9:
            assert self._preferred_first_write.wait(timeout=5)
        with self._lock:
            if key in self:
                return False
            super().__setitem__(key, value)
            if isinstance(value, VideoJobUsage) and value.prompt_tokens == 7:
                self._preferred_first_write.set()
            return True


class _RacingLegacyMapping(dict[str, VideoJobOwner]):
    """Force two registry instances to read the same stale legacy owner."""

    def __init__(self) -> None:
        super().__init__()
        self.race_enabled = False
        self._read_barrier = threading.Barrier(2)
        self._first_write = threading.Event()

    def __getitem__(self, key: str) -> VideoJobOwner:
        value = super().__getitem__(key)
        if self.race_enabled:
            self._read_barrier.wait(timeout=5)
        return value

    def __setitem__(self, key: str, value: VideoJobOwner) -> None:
        usage = value.provider_usage or {}
        prompt_tokens = usage.get("prompt_tokens")
        if self.race_enabled and prompt_tokens == 9:
            assert self._first_write.wait(timeout=5)
        super().__setitem__(key, value)
        if self.race_enabled and prompt_tokens == 7:
            self._first_write.set()


class _DurableStyleFactory(JobRegistryFactory):
    """Share durable-style named mappings across independent registries."""

    def __init__(self) -> None:
        super().__init__(None)
        self.records: dict[str, Any] = {}
        self.usages = _AtomicUsageMapping()
        self.legacy = _RacingLegacyMapping()

    def mapping(self, name: str, *, decode=None):  # type: ignore[no-untyped-def]
        """Return the shared mapping for one registry namespace."""
        del decode
        return {
            "video_job_records": self.records,
            "video_job_usages": self.usages,
            "video_job_owners": self.legacy,
        }[name]


class _FailingUsageMapping(dict[str, Any]):
    """Fail the companion usage write after ownership has persisted."""

    def set_if_absent(self, key: str, value: Any) -> bool:
        """Simulate a registry outage during the usage write."""
        del key, value
        raise RuntimeError("usage registry unavailable")


class _PartialFailureFactory(JobRegistryFactory):
    """Expose a healthy owner mapping and a failing usage mapping."""

    def __init__(self) -> None:
        super().__init__(None)
        self.records: dict[str, Any] = {}
        self.usages = _FailingUsageMapping()
        self.legacy: dict[str, Any] = {}

    def mapping(self, name: str, *, decode=None):  # type: ignore[no-untyped-def]
        """Return the injected mapping for one registry namespace."""
        del decode
        return {
            "video_job_records": self.records,
            "video_job_usages": self.usages,
            "video_job_owners": self.legacy,
        }[name]


def test_legacy_usage_is_first_write_wins_across_registry_instances() -> None:
    """Two replicas must not overwrite the first complete legacy usage report."""
    factory = _DurableStyleFactory()
    legacy = VideoJobOwner(
        gateway_job_id="videojob_legacy",
        provider_job_id="provider-job",
        agent_id="declared_video_agent",
        submitted_at=1,
        owner_id="principal_one",
    )
    factory.legacy[legacy.gateway_job_id] = legacy
    first = VideoJobRegistry(factory)
    second = VideoJobRegistry(factory)
    first_owner = first.owner(legacy.gateway_job_id, "principal_one")
    second_owner = second.owner(legacy.gateway_job_id, "principal_one")
    factory.legacy.race_enabled = True
    errors: list[BaseException] = []

    def observe(
        registry: VideoJobRegistry,
        owner: VideoJobOwner,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        try:
            registry.observe_provider_result(
                owner,
                {
                    "usage": {
                        "input_tokens": prompt_tokens,
                        "output_tokens": completion_tokens,
                    }
                },
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    preferred = threading.Thread(target=observe, args=(first, first_owner, 7, 2))
    stale = threading.Thread(target=observe, args=(second, second_owner, 9, 3))
    preferred.start()
    stale.start()
    preferred.join(timeout=10)
    stale.join(timeout=10)
    factory.legacy.race_enabled = False

    assert not preferred.is_alive() and not stale.is_alive()
    assert errors == []
    assert first.owner(legacy.gateway_job_id, "principal_one").provider_usage == {
        "prompt_tokens": 7,
        "completion_tokens": 2,
    }


def test_register_returns_gateway_id_after_companion_usage_write_failure() -> None:
    """A persisted owner remains discoverable when immediate usage persistence fails."""
    factory = _PartialFailureFactory()
    registry = VideoJobRegistry(factory)

    response = registry.register(
        {
            "id": "provider-job",
            "status": "queued",
            "usage": {"prompt_tokens": 7, "completion_tokens": 2},
        },
        "declared_video_agent",
        "principal_one",
    )

    assert response["id"].startswith("videojob_")
    assert response["usage"] == {"prompt_tokens": 7, "completion_tokens": 2}
    owner = registry.owner(response["id"], "principal_one")
    assert owner.gateway_job_id == response["id"]
    assert owner.usage_measurement_status == "unavailable"
    assert owner.provider_usage is None
