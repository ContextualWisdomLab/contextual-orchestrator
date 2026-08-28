from typing import Any
"""Ecosystem consumer contract tests for Naruon DOM-decomposition."""

import threading
import urllib.request
import urllib.error
import json
import pytest
from typing import Iterator

from contextual_orchestrator.orchestrator import TaskOrchestrator, ModelAgent
from contextual_orchestrator.server import SecurityConfig
from http.server import HTTPServer

@pytest.fixture
def test_server() -> Iterator[tuple[HTTPServer, int, str]]:
    token = "naruon_consumer_token_123"
    agents = [ModelAgent("extractor_1", "naruon-extractor-model-v1")]
    orchestrator = TaskOrchestrator(agents)

    from contextual_orchestrator.server import build_server
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield server, server.server_address[1], token
    finally:
        server.shutdown()
        t.join(timeout=2.0)

def test_naruon_structured_dom_decomposition_payload(test_server: tuple[HTTPServer, int, str]) -> None:
    """Naruon uses function calling and structured outputs to decompose emails."""
    server, port, token = test_server

    payload = {
        "model": "orchestrator/auto",
        "messages": [
            {"role": "system", "content": "Extract DOM entities from the email."},
            {"role": "user", "content": "From: Alice. Subject: Project Update. We are launching tomorrow."}
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "dom_extraction",
                "schema": {
                    "type": "object",
                    "properties": {
                        "sender": {"type": "string"},
                        "subject": {"type": "string"},
                        "entities": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["sender", "subject", "entities"],
                    "additionalProperties": False,
                },
                "strict": True
            }
        },
        "temperature": 0.0
    }

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST"
    )

    try:
        # Since we use fake mock providers (or nothing) in this simple test server without real providers configured,
        # we expect the orchestrator to fail to route or mock a response. We just want to ensure it parses the payload correctly.
        with urllib.request.urlopen(req) as response:
            body = json.loads(response.read().decode("utf-8"))
            assert "choices" in body
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode("utf-8"))
        # The structured payload passed request validation, but this isolated
        # server has no runnable provider-backed agent for the capability.
        assert e.code == 503
        assert body["error"]["code"] == "no_viable_agent"
