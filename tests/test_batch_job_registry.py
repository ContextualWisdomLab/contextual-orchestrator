"""Durable batch-job registries: Valkey-backed state must survive a restart.

The real defect these tests pin down: batch job registries lived in
per-process dicts, so a server restart between submit and retrieve turned
paid-for work into a 404. With a Valkey-backed registry, a second
coordinator (standing in for the restarted process) sharing the same
Valkey client must see the first coordinator's submitted jobs and serve
their results.
"""

from __future__ import annotations

import gc
import sys
import threading
import time
import weakref
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.batch_job_registry import (
    DEFAULT_RETENTION_SECONDS,
    JobRegistryFactory,
    ValkeyJsonMapping,
    build_job_registry,
)
from contextual_orchestrator.batch_routing import (
    BatchJob,
    BatchRequest,
    BatchResultItem,
    LocalBatchBackend,
    ProviderEmbeddingBatchBackend,
)
from contextual_orchestrator.cost_router import CostRoutingCoordinator
from contextual_orchestrator.kv_config import InMemoryConfigStore
from contextual_orchestrator.orchestrator import ModelAgent, ModelClient, TaskOrchestrator


class FakeValkeyClient:
    """In-memory stand-in for redis.Redis limited to the hash surface used."""

    def __init__(self, *, claim_available: bool = True) -> None:
        self.hashes: Dict[str, Dict[str, str]] = {}
        self.expirations: Dict[str, int] = {}
        self.locks: list[tuple[str, dict[str, int]]] = []
        self.claim_available = claim_available

    class Claim:
        def __init__(self, available: bool) -> None:
            self.available = available

        def acquire(self) -> bool:
            return self.available

        def release(self) -> None:
            return None

    def lock(self, name: str, **kwargs: int) -> object:
        self.locks.append((name, kwargs))
        return self.Claim(self.claim_available)

    def hget(self, key: str, field: str) -> Any:
        return self.hashes.get(key, {}).get(field)

    def hset(self, key: str, field: str, value: str) -> int:
        self.hashes.setdefault(key, {})[field] = value
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


def test_readiness_refresh_is_durable_single_flight_and_explicit() -> None:
    """One declared readiness scope returns immediately and survives restart."""

    client = FakeValkeyClient()
    registry = JobRegistryFactory(client)
    entered = threading.Event()
    release = threading.Event()

    class BlockingProbeClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(timeout=1)

        def probe_structured(self, agent, *, timeout):  # type: ignore[override]
            del timeout
            entered.set()
            release.wait(timeout=2)
            return {"status": "ready", "agent_id": agent.id, "model": agent.model}

    agent = ModelAgent("declared_agent", "mock", tags=("reasoning",))
    orchestrator = TaskOrchestrator([agent], client=BlockingProbeClient())
    first = CostRoutingCoordinator(orchestrator, job_registry=registry)
    submitted = first.submit_provider_readiness_refresh(
        agent_ids=[agent.id],
        capability_code="structured",
        timeout_seconds=1.0,
        deadline_epoch=time.time() + 5.0,
    )
    assert submitted["status"] in {"queued", "running"}
    assert entered.wait(timeout=1)
    duplicate = first.submit_provider_readiness_refresh(
        agent_ids=[agent.id],
        capability_code="structured",
        timeout_seconds=1.0,
        deadline_epoch=time.time() + 5.0,
    )
    assert duplicate["job_id"] == submitted["job_id"]
    release.set()
    for _ in range(100):
        document = first.provider_readiness_refresh_document(submitted["job_id"])
        if document["status"] == "completed":
            break
        time.sleep(0.01)
    assert document["completed_count"] == 1
    assert document["ready_count"] == 1
    execution_claims = [
        kwargs["timeout"]
        for name, kwargs in client.locks
        if "provider_readiness_job_execution" in name
    ]
    assert len(execution_claims) == 1
    assert execution_claims[0] > orchestrator.client.timeout
    restarted_orchestrator = TaskOrchestrator([agent], client=BlockingProbeClient())
    restarted = CostRoutingCoordinator(
        restarted_orchestrator, job_registry=JobRegistryFactory(client)
    )
    assert restarted.provider_readiness_refresh_document(submitted["job_id"])["status"] == "completed"
    assert restarted_orchestrator._structured_readiness[agent.id]["status"] == "ready"


def test_cancelled_readiness_refresh_cannot_publish_late_probe_results() -> None:
    """Cancellation wins before a blocked provider result reaches admission state."""
    entered = threading.Event()
    release = threading.Event()

    class BlockingProbeClient(ModelClient):
        def probe_structured(self, agent, *, timeout):  # type: ignore[override]
            del timeout
            entered.set()
            release.wait(timeout=2)
            return {"status": "ready", "agent_id": agent.id, "model": agent.model}

    agent = ModelAgent("declared_agent", "mock", tags=("reasoning",))
    orchestrator = TaskOrchestrator([agent], client=BlockingProbeClient())
    coordinator = CostRoutingCoordinator(orchestrator)
    submitted = coordinator.submit_provider_readiness_refresh(
        agent_ids=[agent.id],
        capability_code="structured",
        timeout_seconds=1.0,
        deadline_epoch=time.time() + 5.0,
    )
    assert entered.wait(timeout=1)

    cancelled = coordinator.cancel_provider_readiness_refresh(submitted["job_id"])
    release.set()

    assert cancelled["status"] == "cancelled"
    for _ in range(100):
        if coordinator.provider_readiness_refresh_document(submitted["job_id"])[
            "status"
        ] == "cancelled":
            break
        time.sleep(0.01)
    assert orchestrator._structured_readiness == {}


def test_readiness_refresh_rejects_implicit_or_unknown_scope() -> None:
    """The admin job cannot expand an empty or unknown access list."""

    agent = ModelAgent("declared_agent", "mock", tags=("reasoning",))
    coordinator = CostRoutingCoordinator(TaskOrchestrator([agent]))
    for agent_ids in ([], ["unknown_agent"]):
        try:
            coordinator.submit_provider_readiness_refresh(
                agent_ids=agent_ids,
                capability_code="structured",
                timeout_seconds=1.0,
                deadline_epoch=None,
            )
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError("implicit or unknown readiness scope must fail closed")


def test_readiness_refresh_large_explicit_scope_uses_provider_concurrency() -> None:
    """Access-list size is body-bounded; provider calls obey configured concurrency."""

    lock = threading.Lock()
    counters = {"active": 0, "maximum": 0}

    class BoundedProbeClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(local_concurrency=2)

        def probe_structured(self, agent, *, timeout):  # type: ignore[override]
            del timeout
            with lock:
                counters["active"] += 1
                counters["maximum"] = max(counters["maximum"], counters["active"])
            time.sleep(0.001)
            with lock:
                counters["active"] -= 1
            return {"status": "ready", "agent_id": agent.id, "model": agent.model}

    agents = [ModelAgent(f"declared_{index}", "mock") for index in range(65)]
    coordinator = CostRoutingCoordinator(
        TaskOrchestrator(agents, client=BoundedProbeClient())
    )
    job = coordinator.submit_provider_readiness_refresh(
        agent_ids=[agent.id for agent in agents],
        capability_code="structured",
        timeout_seconds=1.0,
        deadline_epoch=time.time() + 5.0,
    )
    for _ in range(200):
        document = coordinator.provider_readiness_refresh_document(job["job_id"])
        if document["status"] == "completed":
            break
        time.sleep(0.01)
    assert document["ready_count"] == len(agents)
    assert counters["maximum"] == 2

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


def test_provider_backend_does_not_duplicate_a_claimed_durable_job() -> None:
    """A second process leaves an in-flight job to the current claim owner."""
    client = FakeValkeyClient(claim_available=False)
    factory = JobRegistryFactory(client)
    factory.mapping("provider_embedding_states")["inflight"] = "queued"
    calls = []
    backend = ProviderEmbeddingBatchBackend(
        lambda requests: (calls.append(requests) or [], 0),
        job_registry=factory,
        claim_lease_seconds=90,
    )
    backend._executor.shutdown(wait=True)
    assert calls == []
    assert factory.mapping("provider_embedding_states")["inflight"] == "queued"


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


def test_valkey_claim_uses_bounded_lease_and_wait_not_result_retention() -> None:
    """A crashed claimant cannot stall a request for the result lifetime."""
    client = FakeValkeyClient()
    claim = JobRegistryFactory(client).lock("shards", "one", lease_seconds=90.0)
    assert claim is not None
    assert client.locks == [
        (
            "batch_job_registry:shards:claim:one",
            {
                "timeout": 90.0,
                "blocking": True,
                "blocking_timeout": 90.0,
            },
        )
    ]


def test_valkey_claim_requires_an_explicit_positive_lease() -> None:
    """Durable claims cannot silently invent a lease duration."""
    factory = JobRegistryFactory(FakeValkeyClient())
    for lease in (None, 0, -1):
        try:
            factory.lock("shards", "one", lease_seconds=lease)
            raised = False
        except ValueError:
            raised = True
        assert raised


def test_embedding_claim_lease_uses_request_or_provider_timeout() -> None:
    """The caller deadline narrows, but never extends, the provider timeout."""
    client = ModelClient(timeout=90)
    coordinator = CostRoutingCoordinator(
        TaskOrchestrator([ModelAgent("mock_worker", "mock-model")], client=client)
    )
    assert coordinator._embedding_claim_lease_seconds() == 90
    with client.request_settings(request_deadline_monotonic=time.monotonic() + 10):
        lease = coordinator._embedding_claim_lease_seconds()
    assert lease is not None and 0 < lease <= 10


def test_idle_local_claim_locks_are_reclaimed() -> None:
    """Unique job and shard keys do not accumulate for the process lifetime."""
    factory = JobRegistryFactory()
    first = factory.lock("shards", "one")
    assert factory.lock("shards", "one") is first
    reference = weakref.ref(first)
    del first
    gc.collect()
    assert reference() is None
    assert len(factory._local_locks) == 0


if __name__ == "__main__":
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()
    print("test_batch_job_registry: all direct-run checks passed")
