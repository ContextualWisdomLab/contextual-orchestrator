"""End-to-end contract test for the batch embeddings endpoint.

This is a *real* contract test, not a mock: it drives the actual HTTP server
(``build_server``) over a live loopback socket, submits the shared contract
request through the in-process ``LocalEmbeddingBatchBackend``, and asserts the
response matches the ``{batch_id, status, embeddings, cost_micro_usd,
token_counts}`` shape naruon's ``batch_embedding_service`` parses.

The request and the response keys are loaded from
``tests/fixtures/batch_embeddings_contract.json`` — the same fixture naruon
keeps a byte-identical copy of and asserts its client against — so the two
services cannot drift out of contract.
"""

from __future__ import annotations

from pathlib import Path
import json
import sys
import threading
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import (  # noqa: E402
    CostRoutingCoordinator,
    InMemoryConfigStore,
    ModelAgent,
    PriceBook,
    PriceEntry,
    TaskOrchestrator,
)
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


CONTRACT = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "batch_embeddings_contract.json").read_text(
        encoding="utf-8"
    )
)


def _serve():
    agents = [
        ModelAgent(
            id="mock_worker",
            model="mock-a",
            base_url="mock://a",
            provider_name="mock",
            tags=("reasoning", "coding", "writing"),
            priority=1,
        )
    ]
    orchestrator = TaskOrchestrator(agents)
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    # Price the embeddings provider so cost is a real, non-zero number.
    price_book.set_price(
        PriceEntry("acme-provider", "text-embedding-test", prompt_price_per_1k=0.13, completion_price_per_1k=0.0)
    )
    coordinator = CostRoutingCoordinator(orchestrator, config, price_book=price_book)
    token = "cost_token"
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=token), coordinator=coordinator
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1], token, coordinator


def _request(method, url, token=None, body=None):
    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:  # pragma: no cover - surfaced in asserts
        return exc.code, json.loads(exc.read())


def test_batch_embeddings_endpoint_matches_naruon_contract() -> None:
    server, port, token, coordinator = _serve()
    base = f"http://127.0.0.1:{port}"
    request = CONTRACT["request"]
    submit_path = CONTRACT["endpoint"]["submit_path"]
    response_keys = CONTRACT["response"]["required_keys"]
    item_keys = CONTRACT["response"]["embedding_item_keys"]
    try:
        # Submit through the real endpoint with a provider dimension so the
        # ledger prices the priced provider/model above (non-zero cost).
        payload = {
            "model": request["model"],
            "endpoint": request["endpoint"],
            "inputs": request["inputs"],
            "metadata": {**request["metadata"], "provider": "acme-provider"},
        }
        status, document = _request("POST", f"{base}{submit_path}", token, payload)
        assert status == 200, document

        # Exact response shape naruon parses.
        for key in response_keys:
            assert key in document, f"missing contract key: {key}"
        assert document["status"] == CONTRACT["response"]["status_completed"]

        embeddings = document["embeddings"]
        assert isinstance(embeddings, list)
        assert len(embeddings) == len(request["inputs"])
        for position, item in enumerate(embeddings):
            for key in item_keys:
                assert key in item
            assert item["index"] == position
            assert isinstance(item["embedding"], list) and item["embedding"]

        token_counts = document["token_counts"]
        assert len(token_counts) == len(request["inputs"])
        assert all(count > 0 for count in token_counts)
        assert document["total_tokens"] == sum(token_counts)

        # Cost was actually computed and recorded in micro-USD.
        assert isinstance(document["cost_micro_usd"], int)
        assert document["cost_micro_usd"] > 0

        batch_id = document["batch_id"]

        # Polling the batch id returns the same completed document (idempotent),
        # and does NOT double-record usage in the ledger.
        records_after_submit = len(coordinator.ledger.records())
        poll_path = CONTRACT["endpoint"]["poll_path_template"].format(batch_id=batch_id)
        status, polled = _request("GET", f"{base}{poll_path}", token)
        assert status == 200
        assert polled["batch_id"] == batch_id
        assert polled["status"] == "completed"
        assert polled["embeddings"] == embeddings
        assert len(coordinator.ledger.records()) == records_after_submit

        # Cost is attributed across every dimension naruon sends in metadata.
        for dimension in CONTRACT["attribution_dimensions_in_metadata"]:
            status, report = _request(
                "GET", f"{base}/api/v1/cost_reports/rollup?dimension={dimension}", token
            )
            assert status == 200, report
            values = {item["dimension_value"] for item in report["items"]}
            expected = request["metadata"][dimension]
            assert expected in values, f"dimension {dimension} not attributed to {expected}"
    finally:
        server.shutdown()


def test_batch_embeddings_accepts_openai_style_input_field() -> None:
    """The endpoint also accepts the OpenAI-style ``input`` (string or list)."""
    server, port, token, _coordinator = _serve()
    base = f"http://127.0.0.1:{port}"
    try:
        status, document = _request(
            "POST",
            f"{base}/v1/batch/embeddings",
            token,
            {"model": "text-embedding-test", "input": "single string input"},
        )
        assert status == 200, document
        assert len(document["embeddings"]) == 1
        assert document["status"] == "completed"
    finally:
        server.shutdown()
