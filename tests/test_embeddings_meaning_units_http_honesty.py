"""HTTP honesty: meaning-unit chunking on /v1/batch/embeddings.

Omit keeps the naruon one-vector-per-input contract. ``meaning_units`` embeds
each email/HTML/paragraph unit separately and returns ``chunk_units`` so a
buyer can map vectors back to the invoice line. Unknown strategies fail closed.
"""

from __future__ import annotations

import json
from pathlib import Path
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
    TaskOrchestrator,
)
from contextual_orchestrator.semantic_chunking import MeaningUnit, rank_meaning_units  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

INVOICE_EMAIL = """From: alice.billing@acme.example
To: ap@buyer.example
Subject: Invoice INV-20260816 is due

Good morning. Thank you for your continued partnership this quarter.

Please remit payment for invoice INV-20260816. The balance due is 1840.00 USD by 2026-08-30.

Kind regards,
Alice Billing
"""
INVOICE_WRAPPED_HTML = (
    "<div><p>Good morning from support.</p>"
    "<p>Invoice INV-20260816 balance due is 1840.00 USD.</p></div>"
)
_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+"
    "ip1sAAAAASUVORK5CYII="
)
INVOICE_IMAGE_RFC2045_WRAP = (
    "See the scanned invoice below.\n"
    f"data:image/png;base64,{_PNG_B64[:76]}\n"
    f"{_PNG_B64[76:]}\n"
    "The amount on that scan is 1840.00 USD for INV-20260816."
)
INVOICE_QUERY = "invoice INV-20260816 balance due 1840.00 USD"

_TEST_AUTH_TOKEN = "meaning_units_http_honesty_token"  # noqa: S105


def _serve():
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                id="mock_worker",
                model="mock-a",
                base_url="mock://a",
                provider_name="mock",
                tags=("reasoning", "writing"),
                priority=1,
            )
        ]
    )
    coordinator = CostRoutingCoordinator(
        orchestrator, InMemoryConfigStore(), price_book=PriceBook(InMemoryConfigStore())
    )
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN),
        coordinator=coordinator,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/batch/embeddings",
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


def test_http_omit_keeps_one_vector_per_input() -> None:
    server, thread, port = _serve()
    try:
        status, body = _post(
            port,
            {"model": "mock-a", "inputs": ["alpha body", "beta attachment"]},
        )
        assert status == 200, body
        assert "chunk_units" not in body
        assert len(body["embeddings"]) == 2
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_meaning_units_exposes_invoice_chunk_for_search() -> None:
    server, thread, port = _serve()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-a",
                "inputs": [INVOICE_EMAIL],
                "chunking_strategy": "meaning_units",
            },
        )
        assert status == 200, body
        units = [MeaningUnit(**item) for item in body["chunk_units"]]
        assert len(body["embeddings"]) == len(units)
        assert len(units) > 1
        ranked = rank_meaning_units(INVOICE_QUERY, units)
        assert "INV-20260816" in ranked[0].chunk_text
        assert "1840.00" in ranked[0].chunk_text
        assert "Good morning" not in ranked[0].chunk_text
        poll_status, poll_body = _get(port, body["batch_id"])
        assert poll_status == 200, poll_body
        assert poll_body["chunk_units"] == body["chunk_units"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _get(port: int, batch_id: str) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/batch/embeddings/{batch_id}",
        headers={"authorization": f"Bearer {_TEST_AUTH_TOKEN}", "connection": "close"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_http_wrapped_html_keeps_invoice_out_of_the_greeting() -> None:
    server, thread, port = _serve()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-a",
                "inputs": [INVOICE_WRAPPED_HTML],
                "chunking_strategy": "meaning_units",
            },
        )
        assert status == 200, body
        units = [MeaningUnit(**item) for item in body["chunk_units"]]
        greeting = next(unit for unit in units if "Good morning" in unit.chunk_text)
        invoice = next(unit for unit in units if "INV-20260816" in unit.chunk_text)
        assert greeting is not invoice
        assert "INV-20260816" not in greeting.chunk_text
        assert "Good morning" not in invoice.chunk_text
        ranked = rank_meaning_units(INVOICE_QUERY, units)
        assert "INV-20260816" in ranked[0].chunk_text
        assert "Good morning" not in ranked[0].chunk_text
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_rfc2045_wrap_keeps_leftover_base64_out_of_the_invoice() -> None:
    server, thread, port = _serve()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-a",
                "inputs": [INVOICE_IMAGE_RFC2045_WRAP],
                "chunking_strategy": "meaning_units",
            },
        )
        assert status == 200, body
        units = [MeaningUnit(**item) for item in body["chunk_units"]]
        image = next(unit for unit in units if unit.chunk_kind == "embedded_image")
        invoice = next(unit for unit in units if "INV-20260816" in unit.chunk_text)
        assert image.chunk_text.endswith("=")
        assert _PNG_B64[76:] in image.chunk_text
        assert "AAAASUVORK5CYII" not in invoice.chunk_text
        assert "data:image" not in invoice.chunk_text
        assert len(body["embeddings"]) == len(units)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_unknown_chunking_strategy_fails_closed() -> None:
    server, thread, port = _serve()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-a",
                "inputs": [INVOICE_EMAIL],
                "chunking_strategy": "tokens",
            },
        )
        assert status == 400, body
        assert body["error_code"] == "invalid_chunking_strategy"
        assert "meaning_units" in body["error_message"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_null_chunking_strategy_is_omit() -> None:
    server, thread, port = _serve()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-a",
                "inputs": ["one document"],
                "chunking_strategy": None,
            },
        )
        assert status == 200, body
        assert "chunk_units" not in body
        assert len(body["embeddings"]) == 1
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_non_string_chunking_strategy_fails_closed() -> None:
    server, thread, port = _serve()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-a",
                "inputs": ["one document"],
                "chunking_strategy": True,
            },
        )
        assert status == 400, body
        assert body["error_code"] == "invalid_chunking_strategy"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_omit_keeps_one_vector_per_input()
    test_http_meaning_units_exposes_invoice_chunk_for_search()
    test_http_wrapped_html_keeps_invoice_out_of_the_greeting()
    test_http_rfc2045_wrap_keeps_leftover_base64_out_of_the_invoice()
    test_http_unknown_chunking_strategy_fails_closed()
    test_http_null_chunking_strategy_is_omit()
    test_http_non_string_chunking_strategy_fails_closed()
    print("ok")
