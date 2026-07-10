from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator, classify_operational_alert  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


LITELLM_P2028_ALERT = {
    "alert_type": "db_exceptions",
    "level": "High",
    "timestamp": "01:15:03",
    "message": (
        'DB read/write call failed: 504: {"is_panic":false,"message":"Transaction API error: '
        'Unable to start a transaction in the given time.","meta":{"error":"Unable to start a '
        'transaction in the given time."},"error_code":"P2028"}'
        "[Non-Blocking]LiteLLM Prisma Client Exception - update spend logs"
    ),
    "traceback": "File /usr/lib/python3.13/site-packages/litellm/proxy/db/db_spend_update_writer.py",
    "proxy_url": "https://llm-gateway.hyosung.com",
}


def test_litellm_p2028_spend_log_alert_is_suppressed_from_incident_routing() -> None:
    classification = classify_operational_alert(LITELLM_P2028_ALERT)

    assert classification["classification_status"] == "suppressed"
    assert classification["incident_routing"] == "drop"
    assert classification["page_required"] is False
    assert classification["normalized_severity"] == "info"
    assert classification["reason_code"] == "non_blocking_spend_log_transaction_timeout"
    assert {
        "litellm_proxy",
        "prisma_client",
        "p2028_transaction_start_timeout",
        "transaction_start_timeout",
        "non_blocking_context",
        "spend_log_update",
        "db_exception_alert",
    }.issubset(set(classification["matched_signals"]))

    rendered = json.dumps(classification)
    assert "llm-gateway.hyosung.com" not in rendered
    assert "db_spend_update_writer.py" not in rendered


def test_p2028_without_non_blocking_spend_log_signature_is_not_suppressed() -> None:
    classification = classify_operational_alert(
        {
            "alert_type": "db_exceptions",
            "level": "High",
            "message": "LiteLLM Prisma failed with P2028 during key lookup before request authorization.",
        }
    )

    assert classification["classification_status"] == "escalate"
    assert classification["incident_routing"] == "normal_policy"
    assert classification["page_required"] is True
    assert classification["reason_code"] == "no_suppression_signature_match"


def test_unknown_low_signal_alert_stays_on_normal_policy_without_page() -> None:
    classification = classify_operational_alert({"level": "Info", "message": "background cache refresh skipped"})

    assert classification["classification_status"] == "escalate"
    assert classification["incident_routing"] == "normal_policy"
    assert classification["page_required"] is False
    assert classification["normalized_severity"] == "info"


def _post_json(url: str, payload: dict[str, object], token: str) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _serve() -> tuple[object, int]:
    orchestrator = TaskOrchestrator([ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))])
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(admin_token="admin_token", inference_token="inference_token"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


def test_operational_alert_classification_endpoint_is_admin_scoped() -> None:
    server, port = _serve()
    url = f"http://127.0.0.1:{port}/api/v1/operational_alert_classifications"
    try:
        denied_status, denied = _post_json(url, LITELLM_P2028_ALERT, "inference_token")
        status, body = _post_json(url, LITELLM_P2028_ALERT, "admin_token")
    finally:
        server.shutdown()

    assert denied_status == 401
    assert denied["error"]["code"] == "unauthorized"
    assert status == 201
    assert body["classification_status"] == "suppressed"
    assert body["incident_routing"] == "drop"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
