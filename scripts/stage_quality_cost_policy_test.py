#!/usr/bin/env python3
"""Stage failing regressions for the adaptive quality-first cost-aware policy."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_PATH = ROOT / "tests" / "test_quality_cost_adaptive_default.py"

if TEST_PATH.exists():
    raise SystemExit(f"refusing to replace existing test: {TEST_PATH}")

TEST_PATH.write_text(
    '''"""Regression contract for quality-first, cost-aware adaptive defaults."""

from __future__ import annotations

import json
import threading
import urllib.request

from contextual_orchestrator.orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.server import SecurityConfig, build_server


class _RecordingClient:
    """Deterministic provider seam that records route, verify, and proxy calls."""

    def __init__(self) -> None:
        self.chat_calls: list[tuple[str, list[dict[str, str]], str | None]] = []
        self.proxy_calls: list[tuple[str, str, dict[str, object]]] = []

    def chat(
        self,
        agent: ModelAgent,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        reasoning_effort: str | None = None,
    ) -> str:
        del temperature
        self.chat_calls.append((agent.id, messages, reasoning_effort))
        system = next(
            (message.get("content", "") for message in messages if message.get("role") == "system"),
            "",
        ).lower()
        if "role: verifier" in system or "verification judge" in system:
            return "verified"
        if "role: synthesizer" in system:
            return '{"decision":"accepted"}'
        return '{"decision":"accepted"}'

    def proxy_send(
        self, agent: ModelAgent, endpoint: str, payload: dict[str, object]
    ) -> dict[str, object]:
        self.proxy_calls.append((agent.id, endpoint, payload))
        return {
            "id": "proxied_completion",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": '{"decision":"accepted"}',
                    },
                }
            ],
        }

    def take_usage(self) -> None:
        return None


def _agent(agent_id: str, model: str, *, priority: int = 0) -> ModelAgent:
    return ModelAgent(
        id=agent_id,
        model=model,
        tags=("reasoning", "verification", "planning", "writing"),
        priority=priority,
    )


def _messages(text: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": text}]


def test_auto_uses_route_verify_and_conduct_by_quality_need() -> None:
    client = _RecordingClient()
    orchestrator = TaskOrchestrator([_agent("adaptive_worker", "model_alpha")], client=client)

    assert orchestrator.complete(_messages("Translate hello."), mode="auto")["mode"] == "route"
    verified = orchestrator.complete(
        _messages("Evaluate whether this answer is factually supported."), mode="auto"
    )
    assert verified["mode"] == "verify"
    assert [step["role"] for step in verified["trace"]] == ["worker", "verifier"]
    conducted = orchestrator.complete(
        _messages("Analyze and verify this multi-step architecture and implementation plan."),
        mode="auto",
    )
    assert conducted["mode"] == "conduct"


def test_equal_capability_prefers_known_lower_cost_and_never_treats_unknown_as_free() -> None:
    client = _RecordingClient()
    orchestrator = TaskOrchestrator(
        [
            _agent("expensive_worker", "model_expensive"),
            _agent("unknown_worker", "model_unknown"),
            _agent("economical_worker", "model_economical"),
        ],
        client=client,
        price_per_million={"model_expensive": 12.0, "model_economical": 1.0},
    )

    selected = orchestrator._select_agent("ordinary reasoning task", "worker")
    assert selected.id == "economical_worker"


def test_capability_priority_precedes_cost() -> None:
    client = _RecordingClient()
    orchestrator = TaskOrchestrator(
        [
            _agent("strong_worker", "model_strong", priority=10),
            _agent("cheap_worker", "model_cheap", priority=0),
        ],
        client=client,
        price_per_million={"model_strong": 20.0, "model_cheap": 0.1},
    )

    selected = orchestrator._select_agent("ordinary reasoning task", "worker")
    assert selected.id == "strong_worker"


def _post_json(url: str, token: str, payload: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_explicit_auto_structured_output_uses_adaptive_path_while_implicit_mode_keeps_compatibility() -> None:
    client = _RecordingClient()
    orchestrator = TaskOrchestrator([_agent("adaptive_worker", "model_alpha")], client=client)
    token = "adaptive_policy_test_token_32_bytes"
    server = build_server(
        orchestrator,
        host="127.0.0.1",
        port=0,
        security=SecurityConfig(auth_token=token),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
        common = {
            "model": "contextual-orchestrator",
            "messages": [
                {
                    "role": "user",
                    "content": "Evaluate this record and return exactly one JSON object.",
                }
            ],
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "decision_record",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["decision"],
                        "properties": {"decision": {"type": "string"}},
                    },
                },
            },
        }
        _post_json(url, token, {**common, "orchestration_mode": "auto"})
        assert client.proxy_calls == []
        assert len(client.chat_calls) >= 2

        client.chat_calls.clear()
        _post_json(url, token, common)
        assert len(client.proxy_calls) == 1
        assert client.chat_calls == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
''',
    encoding="utf-8",
)
