"""Meaning-unit chunking isolates searchable facts from real documents.

Buyers embed naruon-style email, HTML, and mixed image+text bodies. Token-budget
splits keep provider calls under a ceiling and then average parts back into one
vector, which hides the invoice line inside the greeting. These tests require
the chunker to emit linguistic meaning units so a lexical retriever can rank the
invoice unit first for an invoice query (Zhao et al., 2024; Unicode, 2024).
"""

from __future__ import annotations

from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.semantic_chunking import (  # noqa: E402
    expand_embedding_inputs,
    meaning_unit_chunks,
    rank_meaning_units,
)

INVOICE_EMAIL = """From: alice.billing@acme.example
To: ap@buyer.example
Subject: Invoice INV-20260816 is due

Good morning. Thank you for your continued partnership this quarter.

Please remit payment for invoice INV-20260816. The balance due is 1840.00 USD by 2026-08-30.

Kind regards,
Alice Billing
"""

INVOICE_HTML = (
    "<p>Good morning from support.</p>"
    "<p>Invoice INV-20260816 balance due is 1840.00 USD.</p>"
)

INVOICE_WITH_IMAGE = (
    "See the scanned invoice below.\n"
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=\n"
    "The amount on that scan is 1840.00 USD for INV-20260816."
)

INVOICE_WRAPPED_HTML = (
    "<div><p>Good morning from support.</p>"
    "<p>Invoice INV-20260816 balance due is 1840.00 USD.</p></div>"
)

INVOICE_IMAGE_CHARSET = (
    "See the scanned invoice below.\n"
    "data:image/png;charset=utf-8;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=\n"
    "The amount on that scan is 1840.00 USD for INV-20260816."
)

INVOICE_IMAGE_URLSAFE = (
    "See the scanned invoice below.\n"
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8_-8AAwMCAO-ip1s=\n"
    "The amount on that scan is 1840.00 USD for INV-20260816."
)

INVOICE_IMAGE_MIME_WRAP = (
    "See the scanned invoice below.\n"
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC\n"
    "AAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=\n"
    "The amount on that scan is 1840.00 USD for INV-20260816."
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

INVOICE_IMAGE_SHORT_LAST_LINE_4 = (
    "See the scanned invoice below.\n"
    f"data:image/png;base64,{_PNG_B64[:88]}\n"
    f"{_PNG_B64[88:]}\n"
    "The amount on that scan is 1840.00 USD for INV-20260816."
)

INVOICE_IMAGE_SHORT_LAST_LINE_8 = (
    "See the scanned invoice below.\n"
    f"data:image/png;base64,{_PNG_B64[:84]}\n"
    f"{_PNG_B64[84:]}\n"
    "The amount on that scan is 1840.00 USD for INV-20260816."
)

INVOICE_IMAGE_SAME_LINE_PROSE = (
    f"data:image/png;base64,{_PNG_B64}"
    "The amount on that scan is 1840.00 USD for INV-20260816."
)

INVOICE_IMAGE_FOLLOWING_ALNUM = (
    f"data:image/png;base64,{_PNG_B64}\n"
    "PleaseRemitInvoiceINV20260816Now\n"
)

INVOICE_BODY_SUBJECT_LINE = """From: alice.billing@acme.example
To: ap@buyer.example
Subject: Invoice INV-20260816 is due

Subject: see attached SKU-77 packing list.

Invoice INV-20260816 remains open.
"""

INVOICE_QUERY = "invoice INV-20260816 balance due 1840.00 USD"


def _assert_span(text: str, unit) -> None:
    assert unit.chunk_text == text[unit.source_offset : unit.source_offset + unit.source_length]
    assert unit.source_length == len(unit.chunk_text)
    assert unit.source_offset >= 0


def test_invoice_email_isolates_sender_subject_and_balance_line() -> None:
    units = meaning_unit_chunks(INVOICE_EMAIL)
    assert units, "an invoice email must produce at least one meaning unit"
    for unit in units:
        _assert_span(INVOICE_EMAIL, unit)

    kinds = {unit.chunk_kind for unit in units}
    assert "email_sender" in kinds
    assert "email_recipient" in kinds
    assert "email_subject" in kinds

    sender = next(unit for unit in units if unit.chunk_kind == "email_sender")
    assert "alice.billing@acme.example" in sender.chunk_text
    assert "INV-20260816" not in sender.chunk_text

    invoice_units = [unit for unit in units if "INV-20260816" in unit.chunk_text]
    assert invoice_units, "the invoice identifier must land in a dedicated unit"
    greeting_only = [
        unit
        for unit in units
        if "Good morning" in unit.chunk_text and "INV-20260816" not in unit.chunk_text
    ]
    assert greeting_only, "the greeting must not be glued to the invoice line"


def test_invoice_query_ranks_the_balance_unit_first() -> None:
    units = meaning_unit_chunks(INVOICE_EMAIL)
    ranked = rank_meaning_units(INVOICE_QUERY, units)
    assert ranked, "ranking must return the invoice units"
    top = ranked[0]
    assert "INV-20260816" in top.chunk_text
    assert "1840.00" in top.chunk_text
    assert "Good morning" not in top.chunk_text


def test_html_blocks_keep_invoice_out_of_the_greeting() -> None:
    units = meaning_unit_chunks(INVOICE_HTML)
    for unit in units:
        _assert_span(INVOICE_HTML, unit)
    greeting = next(unit for unit in units if "Good morning" in unit.chunk_text)
    invoice = next(unit for unit in units if "INV-20260816" in unit.chunk_text)
    assert greeting is not invoice
    assert "INV-20260816" not in greeting.chunk_text
    assert "Good morning" not in invoice.chunk_text


def test_truncated_html_opener_does_not_claim_the_invoice() -> None:
    text = "<div Invoice INV-20260816 remains open."
    units = meaning_unit_chunks(text)
    for unit in units:
        _assert_span(text, unit)
    invoice = next(unit for unit in units if "INV-20260816" in unit.chunk_text)
    assert invoice.chunk_kind != "html_block"


def test_unclosed_wrapper_divs_do_not_hide_the_invoice() -> None:
    text = "<div>" * 40 + "<p>Invoice INV-20260816 balance due is 1840.00 USD.</p>"
    units = meaning_unit_chunks(text)
    for unit in units:
        _assert_span(text, unit)
    invoice = next(unit for unit in units if "INV-20260816" in unit.chunk_text)
    assert invoice.chunk_kind == "html_block"
    assert invoice.chunk_text.startswith("<p>")


def test_case_insensitive_html_close_still_isolates_the_invoice() -> None:
    text = "<DIV><P>Good morning from support.</P><P>Invoice INV-20260816.</P></DIV>"
    units = meaning_unit_chunks(text)
    greeting = next(unit for unit in units if "Good morning" in unit.chunk_text)
    invoice = next(unit for unit in units if "INV-20260816" in unit.chunk_text)
    assert greeting is not invoice
    assert "INV-20260816" not in greeting.chunk_text


def test_deeply_nested_unclosed_html_stays_linear_and_keeps_the_invoice() -> None:
    text = "<div>" * 8000 + "<p>Invoice INV-20260816 balance due is 1840.00 USD.</p>"
    started = time.perf_counter()
    units = meaning_unit_chunks(text)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.25, f"nested unclosed HTML scan stalled ({elapsed:.3f}s)"
    for unit in units:
        _assert_span(text, unit)
    invoice = next(unit for unit in units if "INV-20260816" in unit.chunk_text)
    assert invoice.chunk_kind == "html_block"
    assert invoice.chunk_text.startswith("<p>")


def test_dotted_capital_i_does_not_shift_html_source_offsets() -> None:
    text = "<DIV>İnvoice INV-20260816</DIV> leftover İ still here"
    units = meaning_unit_chunks(text)
    for unit in units:
        _assert_span(text, unit)
        assert text[unit.source_offset : unit.source_offset + unit.source_length] == unit.chunk_text
    invoice = next(unit for unit in units if "INV-20260816" in unit.chunk_text)
    assert invoice.chunk_kind == "html_block"
    assert invoice.chunk_text.startswith("<DIV>")
    assert invoice.chunk_text.endswith("</DIV>")
    leftover = next(unit for unit in units if "leftover" in unit.chunk_text)
    assert leftover.chunk_kind == "body_paragraph"
    assert "INV-20260816" not in leftover.chunk_text


def test_repeated_empty_anchor_tags_do_not_stall_invoice_isolation() -> None:
    text = "<A>" + " <A>" * 32 + " Invoice INV-20260816 remains open."
    started = time.perf_counter()
    units = meaning_unit_chunks(text)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.25, f"tag-only leftover scan stalled ({elapsed:.3f}s)"
    for unit in units:
        _assert_span(text, unit)
    invoice = next(unit for unit in units if "INV-20260816" in unit.chunk_text)
    assert invoice.chunk_kind == "body_paragraph"
    assert "INV-20260816" in invoice.chunk_text


def test_tag_only_document_falls_back_to_source_document() -> None:
    text = "<A>" + " <A>" * 8
    units = meaning_unit_chunks(text)
    assert len(units) == 1
    assert units[0].chunk_kind == "source_document"
    assert units[0].chunk_text == text


def test_wrapped_div_keeps_invoice_out_of_the_greeting() -> None:
    units = meaning_unit_chunks(INVOICE_WRAPPED_HTML)
    for unit in units:
        _assert_span(INVOICE_WRAPPED_HTML, unit)
    greeting = next(unit for unit in units if "Good morning" in unit.chunk_text)
    invoice = next(unit for unit in units if "INV-20260816" in unit.chunk_text)
    assert greeting is not invoice
    assert "INV-20260816" not in greeting.chunk_text
    assert "Good morning" not in invoice.chunk_text
    assert not any(unit.chunk_text.strip() in {"<div>", "</div>"} for unit in units)
    ranked = rank_meaning_units(INVOICE_QUERY, units)
    assert "INV-20260816" in ranked[0].chunk_text
    assert "Good morning" not in ranked[0].chunk_text


def test_embedded_image_keeps_source_offset_and_neighbors() -> None:
    units = meaning_unit_chunks(INVOICE_WITH_IMAGE)
    image = next(unit for unit in units if unit.chunk_kind == "embedded_image")
    _assert_span(INVOICE_WITH_IMAGE, image)
    assert INVOICE_WITH_IMAGE[image.source_offset :].startswith("data:image/png;base64,")
    invoice = next(unit for unit in units if "INV-20260816" in unit.chunk_text)
    assert invoice.chunk_kind != "embedded_image"
    assert image.source_offset < invoice.source_offset


def _assert_image_isolated(source: str, prefix: str) -> None:
    units = meaning_unit_chunks(source)
    for unit in units:
        _assert_span(source, unit)
    image = next(unit for unit in units if unit.chunk_kind == "embedded_image")
    assert source[image.source_offset :].startswith(prefix)
    assert "INV-20260816" not in image.chunk_text
    invoice = next(unit for unit in units if "INV-20260816" in unit.chunk_text)
    assert invoice.chunk_kind != "embedded_image"
    assert "data:image" not in invoice.chunk_text
    assert image.source_offset < invoice.source_offset


def test_charset_data_image_is_its_own_unit() -> None:
    _assert_image_isolated(INVOICE_IMAGE_CHARSET, "data:image/png;charset=utf-8;base64,")


def test_urlsafe_data_image_keeps_full_payload() -> None:
    _assert_image_isolated(INVOICE_IMAGE_URLSAFE, "data:image/png;base64,")
    image = next(
        unit
        for unit in meaning_unit_chunks(INVOICE_IMAGE_URLSAFE)
        if unit.chunk_kind == "embedded_image"
    )
    assert "_-" in image.chunk_text
    assert image.chunk_text.endswith("=")


def test_mime_wrapped_data_image_keeps_full_payload() -> None:
    _assert_image_isolated(INVOICE_IMAGE_MIME_WRAP, "data:image/png;base64,")
    image = next(
        unit
        for unit in meaning_unit_chunks(INVOICE_IMAGE_MIME_WRAP)
        if unit.chunk_kind == "embedded_image"
    )
    assert "\n" in image.chunk_text
    assert image.chunk_text.endswith("=")


def test_rfc2045_column_76_wrap_keeps_invoice_out_of_the_image() -> None:
    _assert_image_isolated(INVOICE_IMAGE_RFC2045_WRAP, "data:image/png;base64,")
    image = next(
        unit
        for unit in meaning_unit_chunks(INVOICE_IMAGE_RFC2045_WRAP)
        if unit.chunk_kind == "embedded_image"
    )
    assert _PNG_B64[76:] in image.chunk_text
    invoice = next(
        unit
        for unit in meaning_unit_chunks(INVOICE_IMAGE_RFC2045_WRAP)
        if "INV-20260816" in unit.chunk_text
    )
    assert "AAAASUVORK5CYII" not in invoice.chunk_text
    assert "SUVORK5CYII" not in invoice.chunk_text


def test_short_padded_last_line_of_four_stays_in_the_image() -> None:
    _assert_image_isolated(INVOICE_IMAGE_SHORT_LAST_LINE_4, "data:image/png;base64,")
    image = next(
        unit
        for unit in meaning_unit_chunks(INVOICE_IMAGE_SHORT_LAST_LINE_4)
        if unit.chunk_kind == "embedded_image"
    )
    assert image.chunk_text.endswith(_PNG_B64[88:])
    assert len(_PNG_B64[88:]) == 4


def test_short_padded_last_line_of_eight_stays_in_the_image() -> None:
    _assert_image_isolated(INVOICE_IMAGE_SHORT_LAST_LINE_8, "data:image/png;base64,")
    image = next(
        unit
        for unit in meaning_unit_chunks(INVOICE_IMAGE_SHORT_LAST_LINE_8)
        if unit.chunk_kind == "embedded_image"
    )
    assert image.chunk_text.endswith(_PNG_B64[84:])
    assert len(_PNG_B64[84:]) == 8


def test_same_line_prose_after_padding_is_not_in_the_image() -> None:
    units = meaning_unit_chunks(INVOICE_IMAGE_SAME_LINE_PROSE)
    image = next(unit for unit in units if unit.chunk_kind == "embedded_image")
    invoice = next(unit for unit in units if "INV-20260816" in unit.chunk_text)
    assert image.chunk_text.endswith("=")
    assert "The amount" not in image.chunk_text
    assert "data:image" not in invoice.chunk_text


def test_following_alnum_line_is_not_swallowed_by_the_image() -> None:
    units = meaning_unit_chunks(INVOICE_IMAGE_FOLLOWING_ALNUM)
    image = next(unit for unit in units if unit.chunk_kind == "embedded_image")
    follow = next(unit for unit in units if "INV20260816" in unit.chunk_text)
    assert image.chunk_text.endswith("=")
    assert "PleaseRemit" not in image.chunk_text
    assert follow.chunk_kind != "embedded_image"


def test_body_subject_line_is_not_a_second_email_header() -> None:
    units = meaning_unit_chunks(INVOICE_BODY_SUBJECT_LINE)
    for unit in units:
        _assert_span(INVOICE_BODY_SUBJECT_LINE, unit)
    subjects = [unit for unit in units if unit.chunk_kind == "email_subject"]
    assert len(subjects) == 1
    assert "INV-20260816" in subjects[0].chunk_text
    sku = next(unit for unit in units if "SKU-77" in unit.chunk_text)
    assert sku.chunk_kind == "body_paragraph"
    assert sku.chunk_kind != "email_subject"


def test_chunk_units_serialize_position_and_chunk_text_only() -> None:
    unit = meaning_unit_chunks(INVOICE_WITH_IMAGE)[0]
    payload = unit.to_dict()
    assert set(payload) == {
        "chunk_kind",
        "source_offset",
        "source_length",
        "chunk_text",
        "input_index",
        "chunk_index",
    }
    assert "media_type" not in payload


def test_sentence_grain_keeps_exact_source_spans() -> None:
    units = meaning_unit_chunks(INVOICE_EMAIL, unit_grain="body_sentence")
    assert units
    for unit in units:
        _assert_span(INVOICE_EMAIL, unit)
    spans = sorted((unit.source_offset, unit.source_offset + unit.source_length) for unit in units)
    for previous, current in zip(spans, spans[1:]):
        assert previous[1] <= current[0]


def test_expand_embedding_inputs_preserves_input_index() -> None:
    texts, units = expand_embedding_inputs(
        [INVOICE_EMAIL, "single note"],
        chunking_strategy="meaning_units",
    )
    assert len(texts) == len(units)
    assert texts == [unit.chunk_text for unit in units]
    assert {unit.input_index for unit in units} == {0, 1}
    assert any(unit.input_index == 1 and unit.chunk_text == "single note" for unit in units)


def test_expand_omitted_strategy_keeps_one_document_unit() -> None:
    texts, units = expand_embedding_inputs([INVOICE_EMAIL], chunking_strategy=None)
    assert texts == [INVOICE_EMAIL]
    assert len(units) == 1
    assert units[0].chunk_kind == "source_document"


def test_units_do_not_overlap() -> None:
    units = meaning_unit_chunks(INVOICE_EMAIL)
    spans = sorted((unit.source_offset, unit.source_offset + unit.source_length) for unit in units)
    for previous, current in zip(spans, spans[1:]):
        assert previous[1] <= current[0]


def test_korean_invoice_sentence_is_its_own_unit() -> None:
    body = (
        "안녕하세요. 이번 분기 정산 안내입니다.\n\n"
        "청구서 INV-20260816의 미납 잔액은 1,840.00 USD입니다."
    )
    units = meaning_unit_chunks(body)
    invoice = next(unit for unit in units if "INV-20260816" in unit.chunk_text)
    assert "안녕하세요" not in invoice.chunk_text
    ranked = rank_meaning_units("INV-20260816 미납 잔액", units)
    assert "INV-20260816" in ranked[0].chunk_text


def test_sentence_grain_keeps_greeting_as_its_own_unit() -> None:
    units = meaning_unit_chunks(INVOICE_EMAIL, unit_grain="body_sentence")
    greeting = next(unit for unit in units if unit.chunk_text == "Good morning.")
    assert greeting.chunk_kind == "body_sentence"
    assert "INV-20260816" not in greeting.chunk_text


def test_copy_and_reply_headers_are_their_own_units() -> None:
    text = (
        "From: alice.billing@acme.example\n"
        "To: ap@buyer.example\n"
        "Cc: audit@acme.example\n"
        "Reply-To: alice.billing@acme.example\n"
        "Subject: Invoice INV-20260816 is due\n\n"
        "Please remit payment for invoice INV-20260816."
    )
    units = meaning_unit_chunks(text)
    kinds = {unit.chunk_kind for unit in units}
    assert "email_copy" in kinds
    assert "email_header" in kinds


def test_source_document_strategy_is_omit_equivalent() -> None:
    texts, units = expand_embedding_inputs(["note"], chunking_strategy="source_document")
    assert texts == ["note"]
    assert units[0].chunk_kind == "source_document"


def test_whitespace_input_is_one_source_document() -> None:
    units = meaning_unit_chunks("   ")
    assert len(units) == 1
    assert units[0].chunk_kind == "source_document"
    assert units[0].chunk_text == "   "


def test_unknown_chunking_strategy_is_rejected() -> None:
    try:
        expand_embedding_inputs(["note"], chunking_strategy="tokens")
    except ValueError:
        return
    raise AssertionError("expected ValueError for an unknown chunking_strategy")


def test_sentence_grain_keeps_title_abbreviation_with_the_invoice() -> None:
    text = "Dr. Smith paid invoice INV-20260816. Goodbye later."
    units = meaning_unit_chunks(text, unit_grain="body_sentence")
    invoice = next(unit for unit in units if "INV-20260816" in unit.chunk_text)
    assert "Dr. Smith" in invoice.chunk_text


def test_token_overlap_ignores_punctuation() -> None:
    score = rank_meaning_units("INV-20260816", meaning_unit_chunks("Pay INV-20260816."))
    assert score[0].chunk_text
    assert re.search(r"INV-20260816", score[0].chunk_text)


if __name__ == "__main__":
    test_invoice_email_isolates_sender_subject_and_balance_line()
    test_invoice_query_ranks_the_balance_unit_first()
    test_html_blocks_keep_invoice_out_of_the_greeting()
    test_truncated_html_opener_does_not_claim_the_invoice()
    test_unclosed_wrapper_divs_do_not_hide_the_invoice()
    test_deeply_nested_unclosed_html_stays_linear_and_keeps_the_invoice()
    test_dotted_capital_i_does_not_shift_html_source_offsets()
    test_case_insensitive_html_close_still_isolates_the_invoice()
    test_repeated_empty_anchor_tags_do_not_stall_invoice_isolation()
    test_tag_only_document_falls_back_to_source_document()
    test_wrapped_div_keeps_invoice_out_of_the_greeting()
    test_embedded_image_keeps_source_offset_and_neighbors()
    test_charset_data_image_is_its_own_unit()
    test_urlsafe_data_image_keeps_full_payload()
    test_mime_wrapped_data_image_keeps_full_payload()
    test_rfc2045_column_76_wrap_keeps_invoice_out_of_the_image()
    test_short_padded_last_line_of_four_stays_in_the_image()
    test_short_padded_last_line_of_eight_stays_in_the_image()
    test_same_line_prose_after_padding_is_not_in_the_image()
    test_following_alnum_line_is_not_swallowed_by_the_image()
    test_body_subject_line_is_not_a_second_email_header()
    test_chunk_units_serialize_position_and_chunk_text_only()
    test_sentence_grain_keeps_exact_source_spans()
    test_expand_embedding_inputs_preserves_input_index()
    test_expand_omitted_strategy_keeps_one_document_unit()
    test_units_do_not_overlap()
    test_korean_invoice_sentence_is_its_own_unit()
    test_sentence_grain_keeps_greeting_as_its_own_unit()
    test_copy_and_reply_headers_are_their_own_units()
    test_source_document_strategy_is_omit_equivalent()
    test_whitespace_input_is_one_source_document()
    test_unknown_chunking_strategy_is_rejected()
    test_sentence_grain_keeps_title_abbreviation_with_the_invoice()
    test_token_overlap_ignores_punctuation()
    print("ok")
