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
def test_http_batch_origin_survives_distinct_retrieval_and_reload(tmp_path, monkeypatch, write_failure):
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
