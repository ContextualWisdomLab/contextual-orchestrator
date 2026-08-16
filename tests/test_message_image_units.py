"""Invoice figures stay searchable next to the text they illustrated.

Buyers send a receipt photo as an OpenAI ``image_url`` data URI beside
``approve invoice INV-4419``. A HTML or truncated PNG payload must fail
closed before the gateway bills a vision hop. A real raster stamp must
be accepted, and the persisted ``message_image_unit`` must keep the
figure's ``part_index`` next to that invoice line so operators can find
the picture that sat in the original message (Xu et al., 2020; Masinter,
1998).

Xu, Y., Li, M., Cui, L., Huang, S., Wei, F., & Zhou, M. (2020). LayoutLM:
Pre-training of text and layout for document image understanding. In
*Proceedings of the 26th ACM SIGKDD International Conference on Knowledge
Discovery & Data Mining* (pp. 1192–1200). Association for Computing
Machinery. https://doi.org/10.1145/3394486.3403172

Masinter, L. (1998). *The "data" URL scheme* (RFC 2397). Internet
Engineering Task Force. https://doi.org/10.17487/RFC2397
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "message_image_units_http_honesty_token"  # noqa: S105
_STAMP_PATH = Path(__file__).resolve().parent / "fixtures" / "invoice_stamp_1x1.png"


def _stamp_data_uri() -> str:
    payload = base64.b64encode(_STAMP_PATH.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{payload}"


def _orchestrator(state_db: str | None = None) -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))],
        state_db=state_db,
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server(orchestrator: TaskOrchestrator | None = None):
    server = build_server(
        orchestrator or _orchestrator(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def _invoice_parts(image_url: str) -> list[dict]:
    return [
        {"type": "text", "text": "approve invoice INV-4419"},
        {"type": "image_url", "image_url": {"url": image_url}},
    ]


def test_http_rejects_html_data_uri_image_url() -> None:
    """A HTML payload must not bill a vision hop as if it were a receipt photo."""
    html = base64.b64encode(b"<script>alert(1)</script>").decode("ascii")
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": _invoice_parts(f"data:text/html;base64,{html}")}],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message_content" in blob
        assert body.get("error", {}).get("detail", {}).get("part_index") == 1
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_rejects_javascript_image_url() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": _invoice_parts("javascript:alert(1)")}],
            },
        )
        assert status == 400, body
        assert "invalid_message_content" in json.dumps(body)
        assert body.get("error", {}).get("detail", {}).get("part_index") == 1
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_rejects_truncated_png_data_uri() -> None:
    """Truncated magic-only PNG is not a receipt the operator can reopen."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": _invoice_parts("data:image/png;base64,iVBORw0KGgo=")}
                ],
            },
        )
        assert status == 400, body
        assert "invalid_message_content" in json.dumps(body)
        assert body.get("error", {}).get("detail", {}).get("part_index") == 1
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_real_invoice_stamp_png() -> None:
    """Buyer next action: send a real raster data URI beside the invoice line."""
    assert _STAMP_PATH.is_file()
    assert _STAMP_PATH.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": _invoice_parts(_stamp_data_uri())}],
            },
        )
        assert status == 200, body
        assert body.get("object") == "chat.completion" or "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_run_persists_image_unit_part_index_beside_invoice_text() -> None:
    """Restart must still find the stamp that sat at part_index 1 next to INV-4419."""
    with tempfile.TemporaryDirectory() as directory:
        state_db = str(Path(directory) / "invoice_state.db")
        first = _orchestrator(state_db=state_db)
        record = first.run(
            [{"role": "user", "content": _invoice_parts(_stamp_data_uri())}],
            mode="route",
        )
        run_id = record["workflow_run_id"]
        first.close()
        restarted = _orchestrator(state_db=state_db)
        try:
            units = restarted.list_message_image_units(run_id)
            assert len(units) == 1
            unit = units[0]
            assert unit["workflow_run_id"] == run_id
            assert unit["message_index"] == 0
            assert unit["part_index"] == 1
            assert unit["image_mime_type"] == "image/png"
            assert unit["image_byte_length"] == _STAMP_PATH.stat().st_size
            assert "INV-4419" in unit["neighbor_text"]
        finally:
            restarted.close()


if __name__ == "__main__":
    test_http_rejects_html_data_uri_image_url()
    test_http_rejects_javascript_image_url()
    test_http_rejects_truncated_png_data_uri()
    test_http_accepts_real_invoice_stamp_png()
    test_run_persists_image_unit_part_index_beside_invoice_text()
    print("ok")
