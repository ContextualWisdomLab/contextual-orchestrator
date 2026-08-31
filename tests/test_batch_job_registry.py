"""Durable batch-job registries: Valkey-backed state must survive a restart.

The real defect these tests pin down: batch job registries lived in
per-process dicts, so a server restart between submit and retrieve turned
paid-for work into a 404. With a Valkey-backed registry, a second
coordinator (standing in for the restarted process) sharing the same
Valkey client must see the first coordinator's submitted jobs and serve
their results.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.batch_job_registry import (
    ClaimNotAcquired,
    DEFAULT_RETENTION_SECONDS,
    JobRegistryFactory,
    ValkeyJsonMapping,
    build_job_registry,
)
from contextual_orchestrator.batch_routing import (
    BatchJob,
    BatchRequest,
    BatchResultItem,
    EmbeddingBatchRequest,
    LocalBatchBackend,
    ProviderEmbeddingBatchBackend,
)
from contextual_orchestrator.kv_config import InMemoryConfigStore


class FakeValkeyClient:
    """In-memory stand-in for redis.Redis limited to the hash surface used."""

    def __init__(self) -> None:
        self.hashes: Dict[str, Dict[str, str]] = {}
        self.expirations: Dict[str, int] = {}
        self.execution_extension_attempted = threading.Event()

    class LockNotOwnedError(RuntimeError):
        pass

    class _Lock:
        def __init__(self, client: "FakeValkeyClient", name: str) -> None:
            self._client = client
            self._lose_on_extend = "provider_embedding_job_execution" in name
            self._owned = False

        def acquire(self) -> bool:
            self._owned = True
            return True

        def extend(self, _seconds: float, *, replace_ttl: bool) -> bool:
            assert replace_ttl is True
            if self._lose_on_extend:
                self._owned = False
                self._client.execution_extension_attempted.set()
                return False
            return self._owned

        def owned(self) -> bool:
            return self._owned

        def release(self) -> None:
            if not self._owned:
                raise self._client.LockNotOwnedError("claim no longer owned")
            self._owned = False

    def hget(self, key: str, field: str) -> Any:
        return self.hashes.get(key, {}).get(field)

    def hset(self, key: str, field: str, value: str) -> int:
        self.hashes.setdefault(key, {})[field] = value
        return 1

    def hsetnx(self, key: str, field: str, value: str) -> int:
        bucket = self.hashes.setdefault(key, {})
        if field in bucket:
            return 0
        bucket[field] = value
        return 1

    def hdel(self, key: str, field: str) -> int:
        bucket = self.hashes.get(key, {})
        if field in bucket:
            del bucket[field]
            return 1
        return 0

    def hkeys(self, key: str) -> list:
        return list(self.hashes.get(key, {}))

    def hlen(self, key: str) -> int:
        return len(self.hashes.get(key, {}))

    def expire(self, key: str, seconds: int) -> bool:
        self.expirations[key] = seconds
        return True

    def lock(self, name: str, **_kwargs: Any) -> "FakeValkeyClient._Lock":
        return self._Lock(self, name)


def test_mapping_round_trips_dataclasses_and_plain_values() -> None:
    """Dataclasses, dataclass lists, and JSON scalars all survive the trip."""
    client = FakeValkeyClient()
    jobs = ValkeyJsonMapping(client, "jobs", decode=lambda raw: BatchJob(**raw))
    job = BatchJob(job_id="batch_1", backend="local", status="completed", request_count=2)
    jobs["batch_1"] = job
    assert jobs["batch_1"] == job

    results = ValkeyJsonMapping(client, "results", decode=lambda raw: BatchResultItem(**raw))
    items = [BatchResultItem(custom_id="a", answer="A"), BatchResultItem(custom_id="b", answer="B")]
    results["batch_1"] = items
    assert results["batch_1"] == items

    counts = ValkeyJsonMapping(client, "counts")
    counts["batch_1"] = 7
    assert counts["batch_1"] == 7
    assert counts.get("missing") is None
    assert "batch_1" in counts and len(counts) == 1


def test_mapping_delete_and_iteration_match_dict_semantics() -> None:
    """The registry honors the MutableMapping contract call sites rely on."""
    client = FakeValkeyClient()
    mapping = ValkeyJsonMapping(client, "jobs")
    mapping["one"] = {"n": 1}
    mapping["two"] = {"n": 2}
    assert sorted(mapping) == ["one", "two"]
    del mapping["one"]
    assert "one" not in mapping
    try:
        del mapping["one"]
        raised = False
    except KeyError:
        raised = True
    assert raised


def test_writes_refresh_the_registry_retention_window() -> None:
    """Every write pushes the hash expiry forward so live registries persist."""
    client = FakeValkeyClient()
    mapping = ValkeyJsonMapping(client, "jobs", retention_seconds=123)
    mapping["job"] = {"ok": True}
    assert client.expirations["batch_job_registry:jobs"] == 123


def test_set_if_absent_preserves_the_first_value() -> None:
    client = FakeValkeyClient()
    mapping = ValkeyJsonMapping(client, "jobs", retention_seconds=123)

    assert mapping.set_if_absent("job", {"value": 1}) is True
    assert mapping.set_if_absent("job", {"value": 2}) is False
    assert mapping["job"] == {"value": 1}


def test_factory_without_client_hands_out_plain_dicts() -> None:
    """No Valkey configured -> the historical in-process dict behavior."""
    factory = JobRegistryFactory(None)
    assert factory.durable is False
    mapping = factory.mapping("jobs")
    assert isinstance(mapping, dict)


def test_build_job_registry_defaults_to_in_process_without_the_secret() -> None:
    """An unconfigured store must not change existing deployments."""
    factory = build_job_registry(InMemoryConfigStore())
    assert factory.durable is False


def test_jobs_submitted_before_a_restart_are_retrievable_after_it() -> None:
    """Two backends sharing one Valkey client model a process restart."""
    client = FakeValkeyClient()

    def runner(messages, mode, model):
        return {"answer": messages[-1]["content"].upper(), "mode": mode}

    first = LocalBatchBackend(runner=runner, job_registry=JobRegistryFactory(client))
    job = first.submit([BatchRequest(messages=[{"role": "user", "content": "hi"}])])

    restarted = LocalBatchBackend(runner=runner, job_registry=JobRegistryFactory(client))
    items = restarted.retrieve(job)
    assert [item.answer for item in items] == ["HI"]


def test_default_retention_is_a_week() -> None:
    """Documented default: abandoned jobs expire after seven days."""
    assert DEFAULT_RETENTION_SECONDS == 7 * 24 * 3600


def test_renewal_loss_is_visible_to_the_claim_holder() -> None:
    """A failed CAS renewal fences the worker instead of becoming background noise."""
    client = FakeValkeyClient()
    factory = JobRegistryFactory(client)
    with factory.lock(
        "provider_embedding_job_execution",
        "job",
        lease_seconds=0.15,
        renew_until_epoch=time.time() + 1,
    ) as claim:
        assert client.execution_extension_attempted.wait(timeout=1)
        with pytest.raises(ClaimNotAcquired, match="ownership was lost"):
            claim.ensure_owned()


def test_provider_result_is_not_published_after_claim_renewal_loss() -> None:
    """A stale provider worker leaves recovery state for the succeeding claimant."""
    client = FakeValkeyClient()
    registry = JobRegistryFactory(client, retention_seconds=2)

    def runner(_requests):
        assert client.execution_extension_attempted.wait(timeout=1)
        return [[1.0]], 1

    backend = ProviderEmbeddingBatchBackend(
        runner,
        job_registry=registry,
        claim_lease_seconds=0.15,
    )
    job = backend.submit(
        [EmbeddingBatchRequest(input_text="synthetic", model="synthetic-model")]
    )

    assert backend.wait(job, timeout=1)["status"] == "running"
    assert backend.retrieve(job) == []
    assert backend.usage(job) == {}
    backend.close()


if __name__ == "__main__":
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()
    print("test_batch_job_registry: all direct-run checks passed")
