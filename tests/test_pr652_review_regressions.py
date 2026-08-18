"""RED regressions for the unresolved review threads on PR #652.

These cases model the inputs that buyers actually submit: Gmail wrapper HTML,
RFC 2397 image data URLs emitted by MIME-aware clients, RFC 5322-like mail
bodies, and the public batch-embeddings contract.  The timing comparison locks
linear scanning rather than a machine-specific absolute duration.
"""

from __future__ import annotations

from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.semantic_chunking import meaning_unit_chunks  # noqa: E402
from tests.test_embeddings_meaning_units_http_honesty import _post, _serve  # noqa: E402


def _assert_exact_span(source: str, unit) -> None:
    assert unit.chunk_text == source[
        unit.source_offset : unit.source_offset + unit.source_length
    ]


def test_gmail_wrapper_html_emits_leaf_units() -> None:
    source = (
        '<div class="gmail_quote"><div class="gmail_default">'
        "<p>Good morning from support.</p>"
        "<p>Invoice INV-20260816 balance due is 1840.00 USD.</p>"
        "</div></div>"
    )
    units = meaning_unit_chunks(source)
    for unit in units:
        _assert_exact_span(source, unit)
    greeting = next(unit for unit in units if "Good morning" in unit.chunk_text)
    invoice = next(unit for unit in units if "INV-20260816" in unit.chunk_text)
    assert greeting is not invoice
    assert greeting.chunk_text.startswith("<p>")
    assert invoice.chunk_text.startswith("<p>")
    assert "INV-20260816" not in greeting.chunk_text
    assert "Good morning" not in invoice.chunk_text


def test_rfc2397_image_parameters_stay_in_one_exact_unit() -> None:
    data_url = (
        "data:image/png;charset=utf-8;name=invoice.png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8="
    )
    source = f"Scan follows.\n{data_url}\nInvoice INV-20260816 remains open."
    units = meaning_unit_chunks(source)
    image = next(unit for unit in units if unit.chunk_kind == "embedded_image")
    _assert_exact_span(source, image)
    assert image.chunk_text == data_url
    invoice = next(unit for unit in units if "INV-20260816" in unit.chunk_text)
    assert invoice.chunk_kind != "embedded_image"
    assert "data:image" not in invoice.chunk_text


def test_rfc2397_urlsafe_payload_is_not_truncated() -> None:
    data_url = "data:image/png;base64,QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo-_w=="
    source = f"{data_url}\nInvoice INV-20260816 remains open."
    units = meaning_unit_chunks(source)
    image = next(unit for unit in units if unit.chunk_kind == "embedded_image")
    _assert_exact_span(source, image)
    assert image.chunk_text == data_url
    assert image.chunk_text.endswith("-_w==")


def test_rfc2397_mime_wrapped_payload_is_one_exact_unit() -> None:
    payload = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8x8AAwMCAO"
        "ip1sAAAAASUVORK5CYII="
    )
    first, second = payload[:76], payload[76:]
    data_url = f"data:image/png;base64,{first}\r\n{second}"
    source = f"Scan follows.\r\n{data_url}\r\nInvoice INV-20260816 remains open."
    units = meaning_unit_chunks(source)
    image = next(unit for unit in units if unit.chunk_kind == "embedded_image")
    _assert_exact_span(source, image)
    assert image.chunk_text == data_url
    invoice = next(unit for unit in units if "INV-20260816" in unit.chunk_text)
    assert second not in invoice.chunk_text
    assert invoice.chunk_kind != "embedded_image"


def _median_unclosed_html_seconds(openers: int) -> float:
    source = "<div>" * openers + "Invoice INV-20260816 remains open."
    samples: list[float] = []
    for _ in range(3):
        started = time.perf_counter()
        meaning_unit_chunks(source)
        samples.append(time.perf_counter() - started)
    return statistics.median(samples)


def test_unclosed_html_scan_scales_near_linearly() -> None:
    small = _median_unclosed_html_seconds(1_500)
    large = _median_unclosed_html_seconds(3_000)
    assert large < small * 3.0, (
        "doubling unclosed wrapper input must not approach quadratic scanning: "
        f"small={small:.6f}s large={large:.6f}s ratio={large / small:.2f}"
    )


def test_subject_line_inside_body_is_not_an_email_header() -> None:
    source = (
        "From: alice.billing@acme.example\n"
        "To: ap@buyer.example\n"
        "Subject: Invoice INV-20260816 is due\n"
        "\n"
        "Subject: see attached SKU-77 packing list.\n"
        "\n"
        "Invoice INV-20260816 remains open."
    )
    units = meaning_unit_chunks(source)
    body_subject = next(unit for unit in units if "SKU-77" in unit.chunk_text)
    assert body_subject.chunk_kind == "body_paragraph"
    assert len([unit for unit in units if unit.chunk_kind == "email_subject"]) == 1


def test_http_source_document_strategy_is_omit_alias() -> None:
    server, thread, port = _serve()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-a",
                "inputs": ["one document"],
                "chunking_strategy": "source_document",
            },
        )
        assert status == 200, body
        assert "chunk_units" not in body
        assert len(body["embeddings"]) == 1
    finally:
        server.shutdown()
        thread.join(timeout=5)
