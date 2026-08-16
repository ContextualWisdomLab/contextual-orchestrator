"""HTTP surface for reasoning_effort validation and mode="verify" (Fugu/Conductor/
TRINITY test-time-compute allocation): a request-level knob for per-call effort,
plus a cheaper adjudication mode between route() and the full conduct() workflow.
"""

from __future__ import annotations

from pathlib import Path
import json
import threading
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


def _serve():
    agents = [
        ModelAgent(id="mock_worker", model="mock-a", base_url="mock://a",
                   tags=("reasoning", "coding", "writing"), priority=1),
        ModelAgent(id="mock_verifier", model="mock-b", base_url="mock://b",
                   tags=("verification", "security", "review"), priority=1),
    ]
    orchestrator = TaskOrchestrator(agents)
    token = "verify_token"
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1], token


def _post(url, token, body):
    headers = {"content-type": "application/json", "authorization": f"Bearer {token}"}
    req = urllib.request.Request(url, method="POST", headers=headers, data=json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:  # pragma: no cover - surfaced in asserts
        return exc.code, json.loads(exc.read())


def test_verify_mode_returns_worker_and_verifier_trace_over_http() -> None:
    server, port, token = _serve()
    try:
        status, body = _post(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            token,
            {"messages": [{"role": "user", "content": "Does record B follow from record A?"}], "mode": "verify"},
        )
    finally:
        server.shutdown()
    assert status == 200
    assert body["orchestration"]["mode"] == "verify"


def test_invalid_reasoning_effort_is_rejected() -> None:
    server, port, token = _serve()
    try:
        status, body = _post(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            token,
            {"messages": [{"role": "user", "content": "hello"}], "reasoning_effort": "extreme"},
        )
    finally:
        server.shutdown()
    assert status == 400
    assert body["error"]["code"] == "invalid_reasoning_effort"


def test_valid_reasoning_effort_is_accepted() -> None:
    server, port, token = _serve()
    try:
        status, body = _post(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            token,
            {"messages": [{"role": "user", "content": "hello"}], "reasoning_effort": "high", "mode": "route"},
        )
    finally:
        server.shutdown()
    assert status == 200
    assert body["orchestration"]["mode"] == "route"
    assert body["orchestration"]["reasoning_effort"]["requested"] == "high"
    assert body["orchestration"]["reasoning_effort"]["status"] == "applied"


if __name__ == "__main__":
    test_verify_mode_returns_worker_and_verifier_trace_over_http()
    test_invalid_reasoning_effort_is_rejected()
    test_valid_reasoning_effort_is_accepted()
    print("ok")
