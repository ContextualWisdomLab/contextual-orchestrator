"""OpenAI ``user`` maps into cost-ledger account attribution for multi-tenant billing."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    SecurityConfig,
    _merge_openai_user_attribution,
    build_server,
)

_TEST_AUTH_TOKEN = "user_attr_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_merge_openai_user_fills_account_when_missing() -> None:
    assert _merge_openai_user_attribution({"user": "tenant-a"}, None) == {"account": "tenant-a"}
    assert _merge_openai_user_attribution({"user": "tenant-a"}, {"team": "ops"}) == {
        "team": "ops",
        "account": "tenant-a",
    }


def test_merge_openai_user_does_not_override_explicit_account() -> None:
    merged = _merge_openai_user_attribution(
        {"user": "sdk-user"},
        {"account": "billing-account", "team": "ops"},
    )
    assert merged == {"account": "billing-account", "team": "ops"}


def test_coordinator_path_user_via_http_usage_record_id() -> None:
    """End-to-end: OpenAI user becomes cost-ledger account when attribution.account is unset."""
    from contextual_orchestrator import (  # noqa: E402
        CostRoutingCoordinator,
        InMemoryConfigStore,
        PriceBook,
        PriceEntry,
    )
    from contextual_orchestrator.server import _validate_attribution

    orchestrator = build()
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(
        PriceEntry("mock", "mock-generalist", prompt_price_per_1k=1.0, completion_price_per_1k=2.0)
    )
    coordinator = CostRoutingCoordinator(orchestrator, config, price_book=price_book)

    body = {
        "messages": [{"role": "user", "content": "attribute me"}],
        "user": "end-user-9",
        "attribution": {"team": "platform"},
    }
    attribution = _merge_openai_user_attribution(body, _validate_attribution(body.get("attribution")))
    result = coordinator.complete(
        body["messages"],
        mode="route",
        attribution=attribution,
        model_name="mock-generalist",
    )
    assert result.get("usage_record_id")
    rows = coordinator.ledger.records()
    assert rows
    assert rows[-1]["account_name"] == "end-user-9"
    assert rows[-1]["team_name"] == "platform"


def test_empty_user_rejected_over_http() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "messages": [{"role": "user", "content": "hi"}],
                    "user": "   ",
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
            raise AssertionError("expected HTTPError")
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 400
            assert payload["error"]["code"] == "invalid_user"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_merge_openai_user_fills_account_when_missing()
    test_merge_openai_user_does_not_override_explicit_account()
    test_coordinator_path_user_via_http_usage_record_id()
    test_empty_user_rejected_over_http()
    print("ok")
