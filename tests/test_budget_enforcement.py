"""Budget enforcement — operator spend cap that refuses runs once exhausted.

Enterprise gateways gate spend. This reuses spend_analytics totals as the meter
(no separate accounting), refuses new runs when over the cap, surfaces the state,
and maps to a 429 over HTTP. Default (no cap) is unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import BudgetExceededError  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


def _agent() -> ModelAgent:
    return ModelAgent("general_agent", "test-model", tags=("reasoning",))


def test_default_no_budget_is_unchanged() -> None:
    orchestrator = TaskOrchestrator([_agent()])
    orchestrator.run([{"role": "user", "content": "one"}])
    orchestrator.run([{"role": "user", "content": "two"}])  # no cap, both allowed
    assert orchestrator.spend_analytics()["budget"]["enabled"] is False


def test_token_budget_allows_then_blocks() -> None:
    orchestrator = TaskOrchestrator([_agent()], budget_max_output_tokens=1)
    orchestrator.run([{"role": "user", "content": "first run is allowed"}])  # spent was 0 at entry

    raised = False
    try:
        orchestrator.run([{"role": "user", "content": "second run is blocked"}])
    except BudgetExceededError as exc:
        raised = True
        assert exc.detail["exceeded"] is True
        assert exc.detail["max_output_tokens"] == 1
    assert raised


def test_budget_block_reports_spent_and_remaining() -> None:
    orchestrator = TaskOrchestrator([_agent()], budget_max_output_tokens=1000)
    orchestrator.run([{"role": "user", "content": "measure the budget"}])
    budget = orchestrator.spend_analytics()["budget"]

    assert budget["enabled"] is True
    assert budget["max_output_tokens"] == 1000
    assert budget["spent_output_tokens"] > 0
    assert budget["remaining_output_tokens"] == 1000 - budget["spent_output_tokens"]
    assert budget["exceeded"] is False


def test_cost_budget_blocks() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "priced-model", tags=("reasoning",))],
        price_per_million={"priced-model": 1_000_000.0},  # $1 per token, so any run exceeds a tiny cap
        budget_max_cost_usd=0.001,
    )
    orchestrator.run([{"role": "user", "content": "spend some money"}])  # allowed (cost was 0 at entry)
    assert orchestrator.spend_analytics()["budget"]["exceeded"] is True

    raised = False
    try:
        orchestrator.run([{"role": "user", "content": "now blocked"}])
    except BudgetExceededError:
        raised = True
    assert raised


def test_http_over_budget_returns_429() -> None:
    token = "budget_token"
    orchestrator = TaskOrchestrator([_agent()], budget_max_output_tokens=1)
    orchestrator.run([{"role": "user", "content": "prime the budget over the cap"}])  # now exceeded

    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps({"messages": [{"role": "user", "content": "blocked"}]}).encode("utf-8"),
        headers={"content-type": "application/json", "authorization": f"Bearer {token}", "connection": "close"},
        method="POST",
    )
    try:
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                status, body = response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            status, body = exc.code, json.loads(exc.read().decode("utf-8"))
    finally:
        server.shutdown()

    assert status == 429
    assert body["error"]["code"] == "budget_exceeded"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
