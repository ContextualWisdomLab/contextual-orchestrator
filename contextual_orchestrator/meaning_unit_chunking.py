"""Meaning-unit chunking for embeddings search.

Token-midpoint splits mix unrelated facts (invoice due date vs SKU line vs
sender) into one vector. This module walks untrusted text in source order and
emits header blocks, paragraphs, sentences, and embedded ``data:image`` URIs
as separate units, falling back to word then character splits only when a
single unit exceeds the provider budget.

Grounding: passage-level retrieval (Karpukhin et al., 2020) and late chunking
(Günther et al., 2024). No new runtime dependency — stdlib scanning only.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, List

TokenCountFn = Callable[[str, str], int]

_HEADER_LINE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*:[ \t].+")
_IMAGE_RE = re.compile(r"data:image/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=]+")
_BLANK_LINE_RE = re.compile(r"\n[ \t]*\n")
_SENTENCE_RE = re.compile(r".+?(?:[.!?](?=\s|$)|$)", re.DOTALL)
_WORD_UNIT_RE = re.compile(r"\S+\s*|\s+", re.UNICODE)

_KIND_HEADER = "header_block"
_KIND_PARAGRAPH = "paragraph_unit"
_KIND_SENTENCE = "sentence_unit"
_KIND_IMAGE = "embedded_image"
_KIND_TOKEN = "token_fallback"


@dataclass(frozen=True)
class MeaningUnitChunk:
    """One searchable embedding part with its original source span.

    Attributes:
        chunk_text: Text forwarded to the embedding provider.
        source_start: Inclusive offset into the original input.
        source_end: Exclusive offset into the original input.
        unit_kind: Meaning-unit class (header, paragraph, sentence, image, or fallback).
        token_count: Token estimate used for the provider budget.
    """

    chunk_text: str
    source_start: int
    source_end: int
    unit_kind: str
    token_count: int


def split_meaning_units(
    text: str,
    *,
    model: str,
    max_tokens: int,
    max_chars: int,
    count_tokens: TokenCountFn,
) -> List[MeaningUnitChunk]:
    """Split ``text`` into meaning units that each fit the provider budget.

    Args:
        text: Original embedding input. May contain email headers, paragraphs,
            and ``data:image`` URIs.
        model: Embedding model name forwarded to ``count_tokens``.
        max_tokens: Inclusive token ceiling per emitted chunk.
        max_chars: Inclusive character ceiling per emitted chunk.
        count_tokens: ``(text, model) -> int`` token estimator.

    Returns:
        Source-ordered chunks. An empty input yields one empty paragraph unit
        so callers can keep a 1:1 source row.
    """
    if text == "":
        return [
            MeaningUnitChunk(
                chunk_text="",
                source_start=0,
                source_end=0,
                unit_kind=_KIND_PARAGRAPH,
                token_count=0,
            )
        ]
    safe_tokens = max(1, int(max_tokens))
    safe_chars = max(1, int(max_chars))
    chunks: List[MeaningUnitChunk] = []
    for start, end, kind in _scan_top_level_units(text):
        chunks.extend(
            _fit_unit(
                text,
                start,
                end,
                kind,
                model=model,
                max_tokens=safe_tokens,
                max_chars=safe_chars,
                count_tokens=count_tokens,
            )
        )
    return chunks or [
        MeaningUnitChunk(
            chunk_text=text,
            source_start=0,
            source_end=len(text),
            unit_kind=_KIND_PARAGRAPH,
            token_count=_safe_count(count_tokens, text, model),
        )
    ]


def _scan_top_level_units(text: str) -> List[tuple[int, int, str]]:
    """Return ``(start, end, kind)`` spans that cover ``text`` in order."""
    spans: List[tuple[int, int, str]] = []
    position = 0
    header_end = _leading_header_end(text)
    if header_end > 0:
        spans.append((0, header_end, _KIND_HEADER))
        position = header_end
    length = len(text)
    while position < length:
        while position < length and text[position] in "\r\n":
            position += 1
        if position >= length:
            break
        image = _IMAGE_RE.match(text, position)
        if image is not None:
            spans.append((image.start(), image.end(), _KIND_IMAGE))
            position = image.end()
            continue
        next_image = _IMAGE_RE.search(text, position)
        blank = _BLANK_LINE_RE.search(text, position)
        end = length
        if blank is not None:
            end = min(end, blank.start())
        if next_image is not None:
            end = min(end, next_image.start())
        if end <= position:
            end = min(length, position + 1)
        spans.append((position, end, _KIND_PARAGRAPH))
        position = end
    return spans


def _leading_header_end(text: str) -> int:
    """Return the exclusive end of a leading RFC822-style header block."""
    if not _HEADER_LINE_RE.match(text):
        return 0
    position = 0
    length = len(text)
    while position < length:
        line_end = text.find("\n", position)
        line = text[position:] if line_end < 0 else text[position:line_end]
        if line.endswith("\r"):
            line = line[:-1]
        if not _HEADER_LINE_RE.match(line):
            break
        position = length if line_end < 0 else line_end + 1
    return position


def _fit_unit(
    text: str,
    start: int,
    end: int,
    kind: str,
    *,
    model: str,
    max_tokens: int,
    max_chars: int,
    count_tokens: TokenCountFn,
) -> List[MeaningUnitChunk]:
    """Emit ``text[start:end]`` as one chunk or budget-safe children."""
    unit_text = text[start:end]
    if unit_text == "":
        return []
    token_count = _safe_count(count_tokens, unit_text, model)
    if token_count <= max_tokens and len(unit_text) <= max_chars:
        return [
            MeaningUnitChunk(
                chunk_text=unit_text,
                source_start=start,
                source_end=end,
                unit_kind=kind,
                token_count=token_count,
            )
        ]
    if kind in {_KIND_PARAGRAPH, _KIND_HEADER}:
        sentences = list(_sentence_spans(unit_text, start))
        if len(sentences) > 1:
            return _pack_spans(
                text,
                sentences,
                default_kind=_KIND_SENTENCE,
                model=model,
                max_tokens=max_tokens,
                max_chars=max_chars,
                count_tokens=count_tokens,
            )
    return _fallback_split(
        unit_text,
        start,
        model=model,
        max_tokens=max_tokens,
        max_chars=max_chars,
        count_tokens=count_tokens,
    )


def _sentence_spans(unit_text: str, origin: int) -> List[tuple[int, int]]:
    """Return sentence spans relative to the original document."""
    spans: List[tuple[int, int]] = []
    for match in _SENTENCE_RE.finditer(unit_text):
        piece = match.group(0)
        if not piece.strip():
            continue
        spans.append((origin + match.start(), origin + match.end()))
    return spans


def _pack_spans(
    text: str,
    spans: List[tuple[int, int]],
    *,
    default_kind: str,
    model: str,
    max_tokens: int,
    max_chars: int,
    count_tokens: TokenCountFn,
) -> List[MeaningUnitChunk]:
    """Pack adjacent spans until the next one would exceed the budget."""
    chunks: List[MeaningUnitChunk] = []
    pack_start: int | None = None
    pack_end: int | None = None
    for start, end in spans:
        candidate_start = start if pack_start is None else pack_start
        candidate = text[candidate_start:end]
        token_count = _safe_count(count_tokens, candidate, model)
        if pack_start is not None and (
            token_count > max_tokens or len(candidate) > max_chars
        ):
            packed = text[pack_start:pack_end]
            chunks.append(
                MeaningUnitChunk(
                    chunk_text=packed,
                    source_start=pack_start,
                    source_end=pack_end or pack_start,
                    unit_kind=default_kind,
                    token_count=_safe_count(count_tokens, packed, model),
                )
            )
            pack_start = None
            pack_end = None
            piece = text[start:end]
            if (
                _safe_count(count_tokens, piece, model) > max_tokens
                or len(piece) > max_chars
            ):
                chunks.extend(
                    _fallback_split(
                        piece,
                        start,
                        model=model,
                        max_tokens=max_tokens,
                        max_chars=max_chars,
                        count_tokens=count_tokens,
                    )
                )
                continue
        if pack_start is None:
            pack_start = start
        pack_end = end
    if pack_start is not None and pack_end is not None:
        packed = text[pack_start:pack_end]
        chunks.append(
            MeaningUnitChunk(
                chunk_text=packed,
                source_start=pack_start,
                source_end=pack_end,
                unit_kind=default_kind,
                token_count=_safe_count(count_tokens, packed, model),
            )
        )
    return chunks


def _fallback_split(
    unit_text: str,
    origin: int,
    *,
    model: str,
    max_tokens: int,
    max_chars: int,
    count_tokens: TokenCountFn,
) -> List[MeaningUnitChunk]:
    """Word-pack, then character-split, a single oversized meaning unit."""
    if len(unit_text) > max_chars:
        chunks: List[MeaningUnitChunk] = []
        for offset in range(0, len(unit_text), max_chars):
            piece = unit_text[offset : offset + max_chars]
            chunks.extend(
                _fallback_split(
                    piece,
                    origin + offset,
                    model=model,
                    max_tokens=max_tokens,
                    max_chars=max_chars,
                    count_tokens=count_tokens,
                )
            )
        return chunks
    token_count = _safe_count(count_tokens, unit_text, model)
    if token_count <= max_tokens or len(unit_text) <= 1:
        kind = _KIND_TOKEN if token_count > max_tokens else _KIND_SENTENCE
        return [
            MeaningUnitChunk(
                chunk_text=unit_text,
                source_start=origin,
                source_end=origin + len(unit_text),
                unit_kind=kind,
                token_count=token_count,
            )
        ]
    units = _WORD_UNIT_RE.findall(unit_text)
    if len(units) > 1:
        chunks = []
        current = ""
        current_origin = origin
        cursor = origin
        for unit in units:
            candidate = f"{current}{unit}"
            if current and (
                len(candidate) > max_chars
                or _safe_count(count_tokens, candidate, model) > max_tokens
            ):
                chunks.append(
                    MeaningUnitChunk(
                        chunk_text=current,
                        source_start=current_origin,
                        source_end=current_origin + len(current),
                        unit_kind=_KIND_TOKEN,
                        token_count=_safe_count(count_tokens, current, model),
                    )
                )
                current_origin = cursor
                current = unit
            else:
                current = candidate
            cursor += len(unit)
        if current:
            chunks.append(
                MeaningUnitChunk(
                    chunk_text=current,
                    source_start=current_origin,
                    source_end=current_origin + len(current),
                    unit_kind=_KIND_TOKEN,
                    token_count=_safe_count(count_tokens, current, model),
                )
            )
        if len(chunks) > 1 or (chunks and chunks[0].chunk_text != unit_text):
            return chunks
    midpoint = max(1, len(unit_text) // 2)
    left = unit_text[:midpoint]
    right = unit_text[midpoint:]
    return _fallback_split(
        left,
        origin,
        model=model,
        max_tokens=max_tokens,
        max_chars=max_chars,
        count_tokens=count_tokens,
    ) + _fallback_split(
        right,
        origin + midpoint,
        model=model,
        max_tokens=max_tokens,
        max_chars=max_chars,
        count_tokens=count_tokens,
    )


def _safe_count(count_tokens: TokenCountFn, text: str, model: str) -> int:
    """Count tokens, treating adapter failures as a whitespace word count."""
    try:
        value = int(count_tokens(text, model))
    except Exception:
        value = len(text.split())
    if text and value <= 0:
        return 1
    return max(0, value)
