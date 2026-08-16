"""Invoice figures stay searchable at the text they sat next to.

Buyers paste a PNG under ``Please pay invoice 1042``. Text-only chunking
drops the figure, so retrieval cannot find the picture that belongs to that
line. ColPali (Faysse et al., 2024) and LayoutLM (Xu et al., 2020) treat
page layout as retrieval signal: the image must keep its source offset.

3NF split: one ``image_payload`` (digest identity), many ``image_placement``
rows (the same bytes can appear on a reminder thread), and time-varying
``image_recognition_event`` rows (OCR/tags arrive later).
"""

from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import collect_image_catalog  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

# 1x1 PNG (real raster, not a stub string).
_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQ"
    "AAAABJRU5ErkJggg=="
)
_PNG_DATA_URI = f"data:image/png;base64,{_PNG_B64}"
_PNG_DIGEST = hashlib.sha256(
    __import__("base64").b64decode(_PNG_B64, validate=True)
).hexdigest()
_TEST_AUTH_TOKEN = "image_placement_catalog_http_honesty_token"  # noqa: S105


def _invoice_messages() -> list[dict]:
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Please pay invoice 1042 shown below."},
                {"type": "image_url", "image_url": {"url": _PNG_DATA_URI}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Same figure attached to the reminder thread."},
                {"type": "image_url", "image_url": {"url": _PNG_DATA_URI}},
            ],
        },
    ]


def test_invoice_png_keeps_one_payload_and_two_placements() -> None:
    """The same invoice PNG on a reminder thread is one payload, two placements."""
    catalog = collect_image_catalog(_invoice_messages())
    payloads = catalog["image_payloads"]
    placements = catalog["image_placements"]
    assert len(payloads) == 1
    assert payloads[0]["payload_digest"] == _PNG_DIGEST
    assert payloads[0]["mime_type"] == "image/png"
    assert payloads[0]["byte_length"] == 70
    assert len(placements) == 2
    assert placements[0]["payload_digest"] == _PNG_DIGEST
    assert placements[0]["message_index"] == 0
    assert placements[0]["part_index"] == 1
    assert placements[0]["source_kind"] == "inline_data_uri"
    assert "invoice 1042" in placements[0]["adjacent_text"]
    assert placements[1]["message_index"] == 1
    assert "reminder thread" in placements[1]["adjacent_text"]
    blob = json.dumps(catalog)
    assert _PNG_B64 not in blob
    assert "image_recognition_events" in catalog
    assert catalog["image_recognition_events"] == []


def test_remote_https_image_is_placed_without_fetching_bytes() -> None:
    catalog = collect_image_catalog(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "See the packing slip."},
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://example.com/packing-slip.png"},
                    },
                ],
            }
        ]
    )
    assert catalog["image_payloads"][0]["byte_length"] == 0
    assert catalog["image_placements"][0]["source_kind"] == "remote_https"
    assert "packing slip" in catalog["image_placements"][0]["adjacent_text"]


def test_http_chat_returns_invoice_figure_next_to_pay_line() -> None:
    """A buyer sending a vision invoice must get the figure back at that line."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "model": "mock-planner",
                    "messages": _invoice_messages()[:1],
                    "include_orchestration_trace": True,
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            status = response.status
            body = json.loads(response.read().decode("utf-8"))
        assert status == 200, body
        catalog = body["orchestration"]["image_content_catalog"]
        assert catalog["image_placements"][0]["adjacent_text"].find("invoice 1042") >= 0
        assert _PNG_B64 not in json.dumps(body)
    except urllib.error.HTTPError as exc:
        raise AssertionError(exc.read().decode("utf-8")) from exc
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_docs_cite_colpali_and_layoutlm() -> None:
    root = Path(__file__).resolve().parents[1]
    papers = (root / "docs" / "papers" / "README.md").read_text(encoding="utf-8")
    architecture = (root / "docs" / "architecture.md").read_text(encoding="utf-8")
    assert "ColPali" in papers and "2407.01449" in papers
    assert "LayoutLM" in papers
    assert "collect_image_catalog" in architecture
    assert (root / "docs" / "papers" / "colpali-2407.01449.pdf").is_file()


if __name__ == "__main__":
    test_invoice_png_keeps_one_payload_and_two_placements()
    test_remote_https_image_is_placed_without_fetching_bytes()
    test_http_chat_returns_invoice_figure_next_to_pay_line()
    test_docs_cite_colpali_and_layoutlm()
    print("ok")
