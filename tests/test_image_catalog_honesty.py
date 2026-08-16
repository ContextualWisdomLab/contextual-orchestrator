"""Catalog honesty for invoice figures that real clients actually send.

#663 records a 3NF image catalog. Buyers still lose the figure when:

- the data URI scheme is ``DATA:`` (RFC 2397 is case-insensitive)
- the base64 payload is wrapped with whitespace (RFC 2397 §3)
- they stream (``stream: true``) and look for the catalog on the stop chunk
- they persist a streamed run to ``--state-db``
- an API key sat next to the pay line (credential shapes must not leak)

Operational emails and invoice numbers stay searchable. Masking those
paralyzes AP/AR retrieval; only credential shapes are redacted.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import threading
import urllib.error
import urllib.request
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import (  # noqa: E402
    chat_completion_chunks,
    chat_completion_response,
    collect_image_catalog,
)
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQ"
    "AAAABJRU5ErkJggg=="
)
_PNG_DIGEST = hashlib.sha256(base64.b64decode(_PNG_B64, validate=True)).hexdigest()
_TEST_AUTH_TOKEN = "image_catalog_honesty_http_token"  # noqa: S105


def _vision_message(url: str, text: str) -> dict[str, object]:
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": url}},
        ],
    }


def test_uppercase_data_uri_keeps_invoice_figure() -> None:
    """A client that emits DATA:IMAGE/PNG;BASE64 must still find invoice 1042."""
    url = f"DATA:IMAGE/PNG;BASE64,{_PNG_B64}"
    catalog = collect_image_catalog(
        [_vision_message(url, "Please pay invoice 1042 shown below.")]
    )
    assert catalog["image_payloads"][0]["payload_digest"] == _PNG_DIGEST
    assert catalog["image_placements"][0]["adjacent_text"].find("invoice 1042") >= 0
    assert catalog["image_placements"][0]["placement_id"] == "image_placement_0_1"


def test_rfc2397_whitespace_in_base64_keeps_invoice_figure() -> None:
    """Wrapped data URIs (mail clients, JSON pretty-print) must still hash."""
    wrapped = f"data:image/png;base64,{_PNG_B64[:40]}\n{_PNG_B64[40:]}"
    catalog = collect_image_catalog(
        [_vision_message(wrapped, "Please pay invoice 1042 shown below.")]
    )
    assert catalog["image_payloads"][0]["payload_digest"] == _PNG_DIGEST
    assert _PNG_B64 not in json.dumps(catalog)


def test_https_uppercase_scheme_is_placed() -> None:
    catalog = collect_image_catalog(
        [
            _vision_message(
                "HTTPS://example.com/packing-slip.png",
                "See the packing slip.",
            )
        ]
    )
    assert catalog["image_placements"][0]["source_kind"] == "remote_https"
    assert "packing slip" in catalog["image_placements"][0]["adjacent_text"]


def test_http_accepts_uppercase_https_and_data_schemes() -> None:
    """Validator and parser must agree so the figure is not silently dropped."""
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
                    "messages": [
                        _vision_message(
                            f"DATA:image/png;base64,{_PNG_B64}",
                            "Please pay invoice 1042 shown below.",
                        )
                    ],
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
            body = json.loads(response.read().decode("utf-8"))
        catalog = body["orchestration"]["image_content_catalog"]
        assert catalog["image_placements"][0]["adjacent_text"].find("invoice 1042") >= 0
        assert catalog["image_payloads"][0]["payload_digest"] == _PNG_DIGEST
    except urllib.error.HTTPError as exc:
        raise AssertionError(exc.read().decode("utf-8")) from exc
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_adjacent_text_redacts_credentials_keeps_invoice_and_email() -> None:
    """AP search needs the pay line and the AP mailbox; keys must not leak."""
    text = (
        "Please pay invoice 1042 to ap@acme.com "
        "api_key=sk-abcdefghijklmnopqrstuvwxyz"
    )
    result = {
        "mode": "route",
        "answer": "ok",
        "image_content_catalog": collect_image_catalog(
            [_vision_message(f"data:image/png;base64,{_PNG_B64}", text)]
        ),
    }
    catalog = chat_completion_response(result)["orchestration"]["image_content_catalog"]
    adjacent = catalog["image_placements"][0]["adjacent_text"]
    assert "invoice 1042" in adjacent
    assert "ap@acme.com" in adjacent
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in adjacent
    assert "[REDACTED]" in adjacent
    assert _PNG_B64 not in json.dumps(catalog)


def test_stream_stop_chunk_includes_searchable_catalog() -> None:
    """Framed SSE buyers read the catalog from the terminal stop chunk."""
    result = {
        "mode": "route",
        "answer": "ok",
        "workflow_run_id": "run_stream_catalog",
        "image_content_catalog": collect_image_catalog(
            [_vision_message(f"data:image/png;base64,{_PNG_B64}", "Please pay invoice 1042.")]
        ),
    }
    chunks = chat_completion_chunks(result)
    final = chunks[-1]
    assert final["choices"][0]["finish_reason"] == "stop"
    catalog = final["orchestration"]["image_content_catalog"]
    assert catalog["image_placements"][0]["adjacent_text"].find("invoice 1042") >= 0
    assert catalog["image_placements"][0]["placement_id"] == "image_placement_0_1"


def test_stream_route_persists_catalog_to_state_db() -> None:
    """A streamed invoice must survive restart the same way a JSON completion does."""
    messages = [
        _vision_message(f"data:image/png;base64,{_PNG_B64}", "Please pay invoice 1042 shown below.")
    ]
    with tempfile.TemporaryDirectory() as directory:
        db_path = os.path.join(directory, "state.db")
        first = TaskOrchestrator(
            [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))],
            state_db=db_path,
        )
        list(first.stream_route(messages, workflow_run_id="run_stream_invoice"))
        first.close()
        second = TaskOrchestrator(
            [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))],
            state_db=db_path,
        )
        try:
            record = second.get_workflow_run("run_stream_invoice")
            catalog = record["image_content_catalog"]
            assert catalog["image_placements"][0]["adjacent_text"].find("invoice 1042") >= 0
            assert catalog["image_payloads"][0]["payload_digest"] == _PNG_DIGEST
        finally:
            second.close()


def test_http_route_stream_stop_frame_has_invoice_catalog() -> None:
    """True-stream route path must still return the figure at the pay line."""
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
                    "messages": [
                        _vision_message(
                            f"data:image/png;base64,{_PNG_B64}",
                            "Please pay invoice 1042 shown below.",
                        )
                    ],
                    "mode": "route",
                    "stream": True,
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
            sse = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise AssertionError(exc.read().decode("utf-8")) from exc
    finally:
        server.shutdown()
        thread.join(timeout=5)
    stop_catalog = None
    for frame in sse.split("\n\n"):
        frame = frame.strip()
        if not frame.startswith("data: ") or frame == "data: [DONE]":
            continue
        chunk = json.loads(frame[len("data: ") :])
        if chunk["choices"][0].get("finish_reason") == "stop":
            stop_catalog = chunk.get("orchestration", {}).get("image_content_catalog")
    assert stop_catalog is not None
    assert stop_catalog["image_placements"][0]["adjacent_text"].find("invoice 1042") >= 0
    assert _PNG_B64 not in sse


if __name__ == "__main__":
    test_uppercase_data_uri_keeps_invoice_figure()
    test_rfc2397_whitespace_in_base64_keeps_invoice_figure()
    test_https_uppercase_scheme_is_placed()
    test_http_accepts_uppercase_https_and_data_schemes()
    test_adjacent_text_redacts_credentials_keeps_invoice_and_email()
    test_stream_stop_chunk_includes_searchable_catalog()
    test_stream_route_persists_catalog_to_state_db()
    test_http_route_stream_stop_frame_has_invoice_catalog()
    print("ok")
