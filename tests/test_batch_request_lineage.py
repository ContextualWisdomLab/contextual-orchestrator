"""Deferred batch outcomes retain their original trusted HTTP admission."""

import copy
import threading
import pytest

from contextual_orchestrator import CostRoutingCoordinator, ModelAgent, TaskOrchestrator
from contextual_orchestrator.batch_routing import PgLlmBatchBackend
from contextual_orchestrator.server import SecurityConfig, build_server
from contextual_orchestrator.telemetry import current_request_id
from test_batch_routing import _FakeBatchApiClient
from test_cost_review_server import _request


@pytest.mark.parametrize("write_failure", [False, True])
@pytest.mark.parametrize("registry_failure", [None, "hset", "expire"])
def test_http_batch_origin_survives_distinct_retrieval_and_reload(tmp_path, monkeypatch, write_failure, registry_failure):
    """One submission joins two item outcomes without trusting their custom IDs."""
    class ObservedBatchClient(_FakeBatchApiClient):
        """Reuse the existing offline provider contract with passive identity capture."""

        async def create_batch_job(self, *args, **kwargs):
            self.submission_request_id = current_request_id()
            return await super().create_batch_job(*args, **kwargs)

        async def download_results(self, *args, **kwargs):
            self.retrieval_request_id = current_request_id()
            payload = await super().download_results(*args, **kwargs)
            second_result = copy.deepcopy(payload["responses"][0])
            second_result["custom_id"] = "b"
            payload["responses"].append(second_result)
            return payload

    state_path = tmp_path / "state.db"
    agents = [ModelAgent("worker_one", "mock/worker")]
    orchestrator = TaskOrchestrator(agents, state_db=state_path)
    if write_failure:
        original_save = orchestrator._store.save

        def reject_link(kind, *args, **kwargs):
            if kind == "batch_request_link":
                raise RuntimeError("private-store-secret")
            return original_save(kind, *args, **kwargs)

        monkeypatch.setattr(orchestrator._store, "save", reject_link)
    batch_client = ObservedBatchClient()
    coordinator = CostRoutingCoordinator(
        orchestrator, batch_backend=PgLlmBatchBackend(batch_client)
    )
    if registry_failure:
        from contextual_orchestrator.batch_job_registry import ValkeyJsonMapping
        from contextual_orchestrator.batch_routing import BatchJob
        from test_batch_job_registry import FakeValkeyClient

        class RejectingClient(FakeValkeyClient):
            """Distinguish no registry write from partial HSET-before-expiry."""

            def hset(self, *args, **kwargs):
                if registry_failure == "hset":
                    raise RuntimeError("private-registry-secret")
                return super().hset(*args, **kwargs)

            def expire(self, *args, **kwargs):
                raise RuntimeError("private-registry-secret")

        registry_client = RejectingClient()
        coordinator._batch_jobs = ValkeyJsonMapping(
            registry_client, "jobs", decode=lambda raw: BatchJob(**raw)
        )
    server = build_server(orchestrator, port=0, coordinator=coordinator,
                          security=SecurityConfig(auth_token="unit-token"))
    worker_thread = threading.Thread(target=server.serve_forever, daemon=True)
    worker_thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, submitted = _request("POST", f"{base_url}/api/v1/batch_routing_jobs",
                                     "unit-token", {"requests": [
            {"custom_id": item_id, "model": "mock/worker", "mode": "route",
             "messages": [{"role": "user", "content": "Offline contract fixture."}]}
            for item_id in ("a", "b")
        ]})
        assert status == 201, submitted
        assert submitted["request_link_status"] == ("write_failed" if write_failure else "durable")
        assert "private-store-secret" not in str(submitted)
        assert submitted["recovery_status"] == "unavailable"
        assert submitted["registry_persistence_status"] == ("write_failed" if registry_failure else "stored")
        assert "private-registry-secret" not in str(submitted)
        if registry_failure:
            assert submitted["job_id"] == "batch-789"
            assert batch_client.calls.count("create_batch_job") == 1
            stored_handles = registry_client.hashes.get("batch_job_registry:jobs", {})
            assert bool(stored_handles) == (registry_failure == "expire")
            denied_status, _ = _request(
                "POST", f"{base_url}/api/v1/batch_routing_jobs/{submitted['job_id']}/results",
                "other-owner-token",
            )
            assert denied_status in {401, 403}
            assert "download_results" not in batch_client.calls
            links = orchestrator._store.load("batch_request_link")
            assert len(links) == (0 if write_failure else 1)
            if links:
                assert links[0]["request_id"] == batch_client.submission_request_id
            return
        status, retrieved = _request(
            "POST", f"{base_url}/api/v1/batch_routing_jobs/{submitted['job_id']}/results",
            "unit-token",
        )
        assert status == 200, retrieved
        assert {item["custom_id"] for item in retrieved["results"]} == {"a", "b"}
        assert batch_client.submission_request_id
        assert batch_client.retrieval_request_id
        assert batch_client.submission_request_id != batch_client.retrieval_request_id
        assert batch_client.submission_request_id not in {"a", "b"}
        repeated_status, repeated = _request(
            "POST", f"{base_url}/api/v1/batch_routing_jobs/{submitted['job_id']}/results",
            "unit-token",
        )
        assert repeated_status == 200
        assert {item["custom_id"] for item in repeated["results"]} == {"a", "b"}
        assert batch_client.calls.count("create_batch_job") == 1
        assert coordinator._batch_jobs[submitted["job_id"]].job_id == submitted["job_id"]
    finally:
        server.shutdown()
        worker_thread.join()
        server.server_close()
        orchestrator.close()

    restored = TaskOrchestrator(agents, state_db=state_path)
    try:
        # Proposed CO-owned association contract: one row per submission/job/item,
        # not a replacement of provider custom_id or one origin per eventual job.
        links = restored._store.load("batch_request_link")
        actual_links = {
            (row["request_id"], row["batch_job_id"], custom_id)
            for row in links for custom_id in row["custom_ids"]
        }
        if write_failure:
            assert not actual_links
            return
        assert actual_links == {
            (batch_client.submission_request_id, submitted["job_id"], item["custom_id"])
            for item in retrieved["results"]
        }
    finally:
        restored.close()


def test_batch_submission_links_keep_job_scoped_item_ids(tmp_path):
    """Repeated item identifiers across submissions retain every origin association."""
    from contextual_orchestrator.batch_routing import BatchRequest

    agents = [ModelAgent("worker_one", "mock/worker")]
    orchestrator = TaskOrchestrator(agents, state_db=tmp_path / "state.db")
    coordinator = CostRoutingCoordinator(
        orchestrator, batch_backend=PgLlmBatchBackend(_FakeBatchApiClient())
    )
    try:
        for request_id in ("trusted_origin_one", "trusted_origin_two"):
            coordinator.submit_batch([
                BatchRequest(messages=[{"role": "user", "content": "Fixture"}], custom_id="a")
            ], owner_id="owner_one", request_id=request_id)
        links = orchestrator._store.load("batch_request_link")
        assert {row["request_id"] for row in links} == {"trusted_origin_one", "trusted_origin_two"}
        assert [row["custom_ids"] for row in links] == [["a"], ["a"]]
    finally:
        orchestrator.close()


def test_library_batch_without_state_store_keeps_legacy_submission():
    """Standalone calls explicitly report unavailable durable request lineage."""
    from contextual_orchestrator.batch_routing import BatchRequest

    orchestrator = TaskOrchestrator([ModelAgent("worker_one", "mock/worker")])
    coordinator = CostRoutingCoordinator(
        orchestrator, batch_backend=PgLlmBatchBackend(_FakeBatchApiClient())
    )
    try:
        job = coordinator.submit_batch([BatchRequest(
            messages=[{"role": "user", "content": "Fixture"}], custom_id="a"
        )])
        assert job.request_link_status == "unavailable"
        assert job.job_id == "batch-789"
        # Legacy metadata without a deployment binding remains usable only
        # while the injected backend also has no recovery identity configured.
        coordinator.batch_backend._jobs[job.job_id].pop("recovery_identity")
        assert coordinator.poll_batch(job.job_id)["is_complete"] is True
    finally:
        orchestrator.close()


def test_batch_link_does_not_rewrite_submitted_registry_handle(tmp_path):
    """Lineage status must not add another failure-prone registry assignment."""
    from contextual_orchestrator.batch_routing import BatchRequest

    class SingleWriteRegistry(dict):
        """Reject a redundant second remote-registry assignment."""

        def __setitem__(self, key, value):
            if key in self:
                raise RuntimeError("second registry write failed")
            super().__setitem__(key, value)

    orchestrator = TaskOrchestrator([ModelAgent("worker_one", "mock/worker")],
                                  state_db=tmp_path / "state.db")
    coordinator = CostRoutingCoordinator(
        orchestrator, batch_backend=PgLlmBatchBackend(_FakeBatchApiClient())
    )
    coordinator._batch_jobs = SingleWriteRegistry()
    try:
        job = coordinator.submit_batch([BatchRequest(
            messages=[{"role": "user", "content": "Fixture"}], custom_id="a"
        )], request_id="trusted_origin_one")
        assert job.request_link_status == "durable"
    finally:
        orchestrator.close()


def test_valkey_job_snapshot_does_not_prove_lineage_commit(tmp_path):
    """Decoded registry status is non-authoritative; committed events supply proof."""
    from contextual_orchestrator.batch_job_registry import ValkeyJsonMapping
    from contextual_orchestrator.batch_routing import BatchJob, BatchRequest
    from test_batch_job_registry import FakeValkeyClient

    orchestrator = TaskOrchestrator([ModelAgent("worker_one", "mock/worker")],
                                  state_db=tmp_path / "state.db")
    coordinator = CostRoutingCoordinator(
        orchestrator, batch_backend=PgLlmBatchBackend(_FakeBatchApiClient())
    )
    coordinator._batch_jobs = ValkeyJsonMapping(
        FakeValkeyClient(), "jobs", decode=lambda raw: BatchJob(**raw)
    )
    try:
        response_job = coordinator.submit_batch([BatchRequest(
            messages=[{"role": "user", "content": "Fixture"}], custom_id="a"
        )], owner_id="owner_one", request_id="trusted_origin_one")
        decoded_job = coordinator._batch_jobs[response_job.job_id]
        assert decoded_job is not response_job
        assert decoded_job.request_link_status == "durable"
        assert decoded_job.registry_persistence_status == "unavailable"
        assert response_job.registry_persistence_status == "stored"
        assert decoded_job.owner_id == "owner_one"
        assert response_job.request_link_status == "durable"
        assert orchestrator._store.load("batch_request_link")[0]["request_id"] == "trusted_origin_one"
    finally:
        orchestrator.close()


@pytest.mark.parametrize("recovery_case", ["valid", "expired", "malformed", "backend_mismatch", "unexpected_item", "missing_usage", "registry_outage", "item_mismatch", "estimate_mismatch", "null_estimates", "boolean_count", "deployment_mismatch", "missing_identity", "coordinator_hit", "duplicate_ids", "backend_write_outage", "healthy_expired", "healthy_deployment_mismatch", "healthy_endpoint_mismatch"])
def test_http_batch_failed_registry_recovers_authorized_job_after_restart(tmp_path, recovery_case):
    """SQLite recovery binds the original owner without another remote submission."""
    class MissingRegistry(dict):
        """Lose the registry assignment, retaining only committed SQLite evidence."""

        def __setitem__(self, key, value):
            raise RuntimeError("registry unavailable")

    state_path = tmp_path / "state.db"
    agents = [ModelAgent("worker_one", "mock/worker")]
    security = SecurityConfig(bearer_verifier=lambda token, scope:
                              token in {"owner-one", "owner-two"})
    clients = []
    for restarted in (False, True):
        orchestrator = TaskOrchestrator(agents, state_db=state_path)
        class RecoveryClient(_FakeBatchApiClient):
            """Return controlled result variants without changing routing execution."""

            async def download_results(self, *args, **kwargs):
                result = await super().download_results(*args, **kwargs)
                if recovery_case == "unexpected_item":
                    result["responses"][0]["custom_id"] = "unsubmitted-item"
                if recovery_case == "missing_usage":
                    result["responses"][0]["response"]["body"].pop("usage")
                return result

        client = RecoveryClient()
        clients.append(client)
        coordinator = CostRoutingCoordinator(orchestrator,
            batch_backend=PgLlmBatchBackend(client, endpoint_alias=(
                "changed-endpoint" if restarted and recovery_case == "backend_mismatch"
                else "original-endpoint"), endpoint=(
                    "/v1/completions" if restarted and recovery_case == "healthy_endpoint_mismatch"
                    else "/v1/chat/completions"), recovery_identity=(
                    None if restarted and recovery_case == "missing_identity" else
                    "different-deployment" if restarted and recovery_case in {"deployment_mismatch", "healthy_deployment_mismatch"}
                    else "unit-deployment-account")))
        if not restarted:
            if recovery_case == "backend_write_outage":
                coordinator.batch_backend._jobs = MissingRegistry()
            else:
                coordinator._batch_jobs = MissingRegistry()
        elif recovery_case in {"coordinator_hit", "healthy_expired", "healthy_deployment_mismatch", "healthy_endpoint_mismatch"}:
            from contextual_orchestrator.batch_routing import BatchJob
            coordinator._batch_jobs[submitted["job_id"]] = BatchJob(**record["recovery_descriptor"]["job"])
            if recovery_case in {"healthy_expired", "healthy_deployment_mismatch", "healthy_endpoint_mismatch"}:
                coordinator.batch_backend._jobs = retained_backend_metadata
        elif recovery_case == "registry_outage":
            class UnavailableRegistry(MissingRegistry):
                """All reads and writes remain unavailable during recovery."""

                def get(self, *args, **kwargs):
                    raise RuntimeError("registry still unavailable")

            coordinator._batch_jobs = UnavailableRegistry()
            coordinator.batch_backend._jobs = UnavailableRegistry()
        server = build_server(orchestrator, port=0, coordinator=coordinator, security=security)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            if not restarted:
                status, submitted = _request("POST", f"{base_url}/api/v1/batch_routing_jobs",
                    "owner-one", {"requests": [{"custom_id": "a", "model": "mock/worker",
                    "messages": [{"role": "user", "content": "Never persist this prompt."}]}]})
                assert status == 201
                assert submitted["registry_persistence_status"] == (
                    "stored" if recovery_case == "backend_write_outage" else "write_failed")
                if recovery_case == "backend_write_outage":
                    assert submitted["backend_registry_persistence_status"] == "write_failed"
                assert submitted["recovery_status"] == "durable_descriptor"
                record = orchestrator._store.load("batch_request_link")[0]
                assert "Never persist this prompt." not in str(record)
                retained_backend_metadata = coordinator.batch_backend._jobs
                if recovery_case in {"expired", "healthy_expired"}:
                    record["recovery_descriptor"]["expires_at"] = 0
                if recovery_case == "malformed":
                    record["recovery_descriptor"]["backend"] = []
                if recovery_case == "item_mismatch":
                    record["custom_ids"] = ["different-original-item"]
                if recovery_case == "estimate_mismatch":
                    record["recovery_descriptor"]["job"]["prompt_token_estimates"] = {"different-item": 99}
                if recovery_case == "null_estimates":
                    record["recovery_descriptor"]["job"]["prompt_token_estimates"] = None
                if recovery_case == "boolean_count":
                    record["recovery_descriptor"]["job"]["request_count"] = True
                if recovery_case == "duplicate_ids":
                    record["custom_ids"] = ["a", "a"]
                if recovery_case in {"expired", "healthy_expired", "malformed", "item_mismatch", "estimate_mismatch", "null_estimates", "boolean_count", "duplicate_ids"}:
                    orchestrator._store.save("batch_request_link", submitted["job_id"], record, durable=True)
                continue
            result_url = f"{base_url}/api/v1/batch_routing_jobs/{submitted['job_id']}/results"
            denied_status, _ = _request("POST", result_url, "owner-two")
            assert denied_status == 404
            assert "download_results" not in client.calls
            status, retrieved = _request("POST", result_url, "owner-one")
            if recovery_case in {"expired", "malformed", "backend_mismatch", "item_mismatch", "estimate_mismatch", "null_estimates", "boolean_count", "deployment_mismatch", "missing_identity", "duplicate_ids", "healthy_deployment_mismatch", "healthy_endpoint_mismatch"}:
                assert status == 404, retrieved
                assert "download_results" not in client.calls
                continue
            if recovery_case == "unexpected_item":
                assert status != 200
                continue
            assert status == 200, retrieved
            poll_status, _ = _request("GET", result_url.removesuffix("/results"), "owner-one")
            assert poll_status == 200
            assert retrieved["results"][0]["custom_id"] == "a"
            if recovery_case == "missing_usage":
                assert retrieved["results"][0]["measurement_status"] != "measured"
            assert sum(item.calls.count("create_batch_job") for item in clients) == 1
        finally:
            server.shutdown()
            worker.join()
            server.server_close()
            orchestrator.close()
