"""Split embedding inputs into searchable meaning units.

Token-budget splitting in :mod:`contextual_orchestrator.cost_router` keeps a
provider call under a ceiling and then averages parts back into one vector.
That is the wrong grain for retrieval: a naruon invoice email then embeds the
greeting, the balance line, and the signature as one point.

This module cuts at linguistic meaning units — email parties, innermost HTML
leaves, RFC 2397 embedded images, paragraphs, and sentences — so a later
lexical or neural search can recover the invoice line without the greeting
(Zhao et al., 2024; Qu et al., 2025; Unicode Consortium, 2024; Masinter,
1998). Similarity-breakpoint “semantic chunking” is deliberately not used:
Qu et al. (2025) found that cost is not justified by consistent gains.
Sentence cuts follow the Unicode text segmentation intent in UAX #29 without
adding a Unicode dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

_EMAIL_HEADER = re.compile(
    r"^(From|To|Cc|Bcc|Subject|Reply-To|Date):\s*.+$",
    re.MULTILINE | re.IGNORECASE,
)
_IMAGE = re.compile(
    r"data:image/[A-Za-z0-9.+-]+(?:;[A-Za-z0-9!#$&^_.+-]+(?:=[^;,\s]+)?)*;base64,"
    r"[A-Za-z0-9+/_-]+(?:=[A-Za-z0-9+/_=-]*)*"
    r"(?:\r?\n[A-Za-z0-9+/_-]{16,}[ \t=]*)*",
    re.IGNORECASE,
)
_HTML_OPEN = re.compile(
    r"<(p|div|li|h[1-6]|tr|td|section|article|blockquote)\b",
    re.IGNORECASE,
)
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n+")
_SENTENCE_CUT = re.compile(r"(?<=[.!?。！？])(?=\s+(?:[A-Z\"'(가-힣]))")
_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*|[가-힣]+")
_ABBREVIATIONS = frozenset(
    {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "inc", "ltd", "vs", "etc"}
)
_EMAIL_KIND = {
    "from": "email_sender",
    "to": "email_recipient",
    "cc": "email_copy",
    "bcc": "email_copy",
    "subject": "email_subject",
    "reply-to": "email_header",
    "date": "email_header",
}


@dataclass(frozen=True)
class MeaningUnit:
    """One retrieval grain cut from a source document.

    ``chunk_text`` is always the exact source slice
    ``source[source_offset:source_offset + source_length]`` so a buyer can
    put the unit back into the original email, HTML, or image position.
    """

    chunk_kind: str
    source_offset: int
    source_length: int
    chunk_text: str
    input_index: int = 0
    chunk_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize the unit for the embeddings batch document."""
        return {
            "chunk_kind": self.chunk_kind,
            "source_offset": self.source_offset,
            "source_length": self.source_length,
            "chunk_text": self.chunk_text,
            "input_index": self.input_index,
            "chunk_index": self.chunk_index,
        }

    def with_index(self, input_index: int, chunk_index: int) -> MeaningUnit:
        """Return a copy stamped with batch input and unit indexes."""
        return MeaningUnit(
            self.chunk_kind,
            self.source_offset,
            self.source_length,
            self.chunk_text,
            input_index,
            chunk_index,
        )


def meaning_unit_chunks(
    text: str,
    *,
    input_index: int = 0,
    unit_grain: str = "body_paragraph",
) -> list[MeaningUnit]:
    """Cut ``text`` into non-overlapping meaning units in source order.

    Empty or whitespace-only input becomes a single ``source_document`` unit
    so a batch slot is never dropped. Image data-URLs keep their original
    offset so OCR or object tags added later can point at the same span.
    ``unit_grain`` is ``body_paragraph`` (default retrieval grain) or
    ``body_sentence`` (UAX #29-style sentence cuts inside leftover prose).
    """
    if not isinstance(text, str):
        text = str(text)
    if not text.strip():
        return [MeaningUnit("source_document", 0, len(text), text, input_index, 0)]

    reserved: list[tuple[int, int, str, str]] = []
    for match in _IMAGE.finditer(text):
        reserved.append((match.start(), match.end(), "embedded_image", match.group(0)))
    if _looks_like_email(text):
        for match in _EMAIL_HEADER.finditer(text):
            if _overlaps(reserved, match.start(), match.end()):
                continue
            kind = _EMAIL_KIND.get(match.group(1).lower(), "email_header")
            reserved.append((match.start(), match.end(), kind, match.group(0)))
    if "<" in text and ">" in text:
        for start, end, piece in _html_leaf_spans(text):
            if _overlaps(reserved, start, end):
                continue
            reserved.append((start, end, "html_block", piece))

    reserved.sort(key=lambda item: (item[0], item[1]))
    units: list[MeaningUnit] = []
    cursor = 0
    for start, end, kind, piece in reserved:
        if start > cursor:
            units.extend(_split_plain(text[cursor:start], cursor, input_index, unit_grain))
        units.append(MeaningUnit(kind, start, end - start, piece, input_index, 0))
        cursor = max(cursor, end)
    if cursor < len(text):
        units.extend(_split_plain(text[cursor:], cursor, input_index, unit_grain))
    units = [
        unit
        for unit in units
        if unit.chunk_text.strip() and not _is_tag_only(unit.chunk_text)
    ]
    if not units:
        return [MeaningUnit("source_document", 0, len(text), text, input_index, 0)]
    return [unit.with_index(input_index, index) for index, unit in enumerate(units)]


def expand_embedding_inputs(
    inputs: list[str],
    *,
    chunking_strategy: str | None,
) -> tuple[list[str], list[MeaningUnit]]:
    """Expand batch inputs according to ``chunking_strategy``.

    ``None`` / empty / ``source_document`` keeps one unit per input so the
    naruon contract (one vector per submitted string) does not change.
    ``meaning_units`` emits one embeddable string per meaning unit.
    """
    if chunking_strategy in (None, "", "source_document"):
        units = [
            MeaningUnit("source_document", 0, len(text), text, input_index, 0)
            for input_index, text in enumerate(inputs)
        ]
        return list(inputs), units
    if chunking_strategy != "meaning_units":
        raise ValueError("chunking_strategy must be omitted or meaning_units")
    units: list[MeaningUnit] = []
    for input_index, text in enumerate(inputs):
        parts = meaning_unit_chunks(text, input_index=input_index)
        if not parts:
            parts = [MeaningUnit("source_document", 0, len(text), text, input_index, 0)]
        for chunk_index, part in enumerate(parts):
            units.append(part.with_index(input_index, chunk_index))
    return [unit.chunk_text for unit in units], units


def rank_meaning_units(query: str, units: list[MeaningUnit]) -> list[MeaningUnit]:
    """Rank units by query-token overlap for retrieval-accuracy tests.

    The standalone embedding backend is a SHA-256 heuristic and is not
    semantically meaningful. Lexical overlap is the honest offline proof that
    isolating the invoice line makes that line retrievable.
    """
    query_tokens = _tokens(query)
    scored: list[tuple[float, int, MeaningUnit]] = []
    for unit in units:
        unit_tokens = _tokens(unit.chunk_text)
        overlap = (len(query_tokens & unit_tokens) / len(query_tokens)) if query_tokens else 0.0
        scored.append((overlap, -unit.source_offset, unit))
    scored.sort(reverse=True)
    matched = [unit for score, _offset, unit in scored if score > 0]
    return matched or [unit for _score, _offset, unit in scored]


def _tokens(text: str) -> set[str]:
    return {match.group(0).lower() for match in _TOKEN.finditer(text)}


def _looks_like_email(text: str) -> bool:
    headers = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if headers:
                break
            continue
        match = _EMAIL_HEADER.match(stripped)
        if match is None:
            break
        headers.append(match.group(1).lower())
        if len(headers) >= 8:
            break
    return bool({"from", "to", "subject"} & set(headers))


def _is_tag_only(text: str) -> bool:
    """Return True when ``text`` is only HTML tags and whitespace.

    A linear ``find`` replaces ``(?:\\s*</?[A-Za-z][^>]*>\\s*)+``. Overlapping
    ``\\s*`` on both sides of that group made ``<A> <A> <A>`` prefixes explode
    when leftover prose kept the match from succeeding; each ``>`` stays O(n).
    """
    index = 0
    length = len(text)
    saw_tag = False
    while index < length:
        while index < length and text[index].isspace():
            index += 1
        if index >= length:
            return saw_tag
        if text[index] != "<":
            return False
        name_at = index + 1
        if name_at < length and text[name_at] == "/":
            name_at += 1
        if name_at >= length:
            return False
        first = text[name_at]
        if not ("A" <= first <= "Z" or "a" <= first <= "z"):
            return False
        close_at = text.find(">", name_at + 1)
        if close_at < 0:
            return False
        index = close_at + 1
        saw_tag = True
    return saw_tag


def _html_block_span(
    text: str, lowered: str, opener_start: int, tag: str
) -> tuple[int, int] | None:
    """Return ``[opener_start, close_end)`` for the first matching close tag.

    A linear ``find`` replaces ``.*?`` plus a backreference. Nested
    ``<div> <div> <div>`` prefixes made that matcher explode; the first
    same-tag close is the previous non-greedy behavior and stays O(n).
    """
    gt = text.find(">", opener_start)
    if gt < 0:
        return None
    needle = f"</{tag}>"
    close_at = lowered.find(needle, gt + 1)
    if close_at < 0:
        return None
    return opener_start, close_at + len(needle)


def _html_leaf_spans(text: str) -> list[tuple[int, int, str]]:
    """Return innermost HTML blocks so a wrapper div does not hide inner ``<p>``.

    ``finditer`` on the wrapper tag consumes every nested paragraph. Gmail and
    naruon bodies arrive as ``<div><p>greeting</p><p>invoice</p></div>``. This
    walks each opener, then drops a match that strictly contains another.
    """
    found: list[tuple[int, int, str]] = []
    lowered = text.lower()
    for opener in _HTML_OPEN.finditer(text):
        span = _html_block_span(text, lowered, opener.start(), opener.group(1).lower())
        if span is None:
            continue
        start, end = span
        found.append((start, end, text[start:end]))
    leaves: list[tuple[int, int, str]] = []
    for start, end, piece in found:
        contained = any(
            start < other_start and other_end <= end and (other_start, other_end) != (start, end)
            for other_start, other_end, _ in found
        )
        if contained:
            continue
        leaves.append((start, end, piece))
    return leaves


def _overlaps(reserved: list[tuple[int, int, str, str]], start: int, end: int) -> bool:
    for existing_start, existing_end, _kind, _piece in reserved:
        if start < existing_end and end > existing_start:
            return True
    return False


def _split_plain(
    text: str,
    base_offset: int,
    input_index: int,
    unit_grain: str = "body_paragraph",
) -> list[MeaningUnit]:
    if not text.strip():
        return []
    units: list[MeaningUnit] = []
    cursor = 0
    breaks = list(_PARAGRAPH_BREAK.finditer(text))
    spans: list[tuple[int, int]] = []
    for match in breaks:
        if match.start() > cursor:
            spans.append((cursor, match.start()))
        cursor = match.end()
    if cursor < len(text):
        spans.append((cursor, len(text)))
    if not spans:
        spans = [(0, len(text))]
    for start, end in spans:
        piece = text[start:end]
        leading = len(piece) - len(piece.lstrip())
        trailing = len(piece) - len(piece.rstrip())
        inner_start = start + leading
        inner_end = end - trailing
        if inner_end <= inner_start:
            continue
        inner = text[inner_start:inner_end]
        if unit_grain == "body_sentence":
            units.extend(_split_sentences(inner, base_offset + inner_start, input_index))
            continue
        units.append(
            MeaningUnit(
                "body_paragraph",
                base_offset + inner_start,
                inner_end - inner_start,
                inner,
                input_index,
                0,
            )
        )
    return units


def _split_sentences(text: str, base_offset: int, input_index: int) -> list[MeaningUnit]:
    cuts = [0]
    for match in _SENTENCE_CUT.finditer(text):
        cuts.append(match.start())
    cuts.append(len(text))
    raw_spans = [
        (left, right) for left, right in zip(cuts, cuts[1:]) if right > left
    ]
    merged = _merge_abbreviations(text, raw_spans)
    units: list[MeaningUnit] = []
    for start, end in merged:
        piece = text[start:end]
        leading = len(piece) - len(piece.lstrip())
        trailing = len(piece) - len(piece.rstrip())
        inner_start = start + leading
        inner_end = end - trailing
        if inner_end <= inner_start:
            continue
        inner = text[inner_start:inner_end]
        kind = "body_sentence" if len(merged) > 1 else "body_paragraph"
        units.append(
            MeaningUnit(
                kind,
                base_offset + inner_start,
                inner_end - inner_start,
                inner,
                input_index,
                0,
            )
        )
    return units


def _merge_abbreviations(text: str, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if len(spans) < 2:
        return spans
    merged: list[tuple[int, int]] = [spans[0]]
    for start, end in spans[1:]:
        previous_start, previous_end = merged[-1]
        tail = text[previous_start:previous_end].rstrip()
        word = re.search(r"([A-Za-z]+)\.$", tail)
        if word and word.group(1).lower() in _ABBREVIATIONS:
            merged[-1] = (previous_start, end)
            continue
        merged.append((start, end))
    return merged
