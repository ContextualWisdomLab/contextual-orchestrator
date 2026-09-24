"""Review locally extracted base/head document diffs without sending binaries.

GitHub shows no patch for DOCX, HWPX, PDF, or image changes. The review leaf
extracts both blobs on its own runner and sends only page/object records: kind,
locator, content hashes, and bounded text (a figure contributes its hash and
caption, never pixels). This module is the gateway-side boundary for that
envelope. It fails closed before any provider call when the envelope is
malformed, carries inline binary or media, matches a credential shape or a
resident registration number, or declares participant material. It then
requires every returned finding to point at an envelope object and to quote
only text that the envelope actually contains.

Scope limits: the gateway cannot fetch blobs, so ``base_blob``/``head_blob``
are format-checked identifiers, not verified content. The participant checks
are an attestation plus path and identifier heuristics; they catch declared or
obvious leaks, not every possible disclosure. Pixel-level figure review needs a
multimodal-capable route and is not part of this contract version.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import PurePosixPath
from typing import Any, Mapping

from .orchestrator import SECRET_PATTERNS

CONTRACT_VERSION = "document_diff_review.v1"
MAX_DIFF_OBJECTS = 200
MAX_OBJECT_TEXT_BYTES = 8 * 1024
MAX_ENVELOPE_TEXT_BYTES = 256 * 1024
MAX_REFERENCE_LENGTH = 256
MAX_FINDINGS = 100
MAX_EXPLANATION_LENGTH = 2000

# "page" is a blob-level object for a PDF or image the leaf cannot split further.
OBJECT_KINDS = frozenset({"paragraph", "table", "figure", "citation", "style", "page"})
CHANGE_KINDS = frozenset({"added", "removed", "modified", "unchanged"})
FINDING_CATEGORIES = frozenset({"body", "table", "figure", "citation", "format"})
FINDING_SEVERITIES = frozenset({"blocker", "major", "minor"})
REVIEW_DOCUMENT_SUFFIXES = frozenset(
    {".docx", ".hwp", ".hwpx", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff"}
)
# ponytail: path-segment heuristic; a repository-declared data map would be the upgrade.
PARTICIPANT_PATH_SEGMENTS = frozenset(
    {"participants", "participant_data", "raw_data", "subjects", "interviews", "consent", "consents", "pii"}
)

_ENVELOPE_FIELDS = frozenset(
    {
        "contract_version",
        "repo",
        "path",
        "base_blob",
        "head_blob",
        "extractor_version",
        "participant_material",
        "objects",
        "zdr_only",
    }
)
_REQUIRED_ENVELOPE_FIELDS = _ENVELOPE_FIELDS - {"zdr_only"}
_OBJECT_FIELDS = frozenset(
    {
        "page",
        "object_kind",
        "locator",
        "change",
        "object_hash_base",
        "object_hash_head",
        "base_text",
        "head_text",
    }
)
_FINDING_FIELDS = frozenset(
    {
        "category",
        "severity",
        "object_index",
        "evidence_base",
        "evidence_head",
        "related_object_index",
        "related_evidence",
        "explanation",
    }
)
_REPO = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")
_BLOB = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_OBJECT_HASH = re.compile(r"sha256:[0-9a-f]{64}")
_DATA_URI = re.compile(r"data:[^,\s]{0,100},", re.IGNORECASE)
_BASE64_RUN = re.compile(r"[A-Za-z0-9+/_-]{200,}={0,2}")
_RESIDENT_REGISTRATION_NUMBER = re.compile(r"(?<!\d)\d{6}-[1-4]\d{6}(?!\d)")
# ZIP (DOCX/HWPX), PDF, PNG, JPEG, GIF, and OLE (HWP) signatures as decoded text.
_BINARY_SIGNATURES = ("PK\x03\x04", "%PDF-", "\x89PNG", "\xff\xd8\xff", "GIF8", "\xd0\xcf\x11\xe0")


class DocumentDiffReviewError(ValueError):
    """Raised when an envelope or model answer cannot cross this boundary."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        """Retain a stable machine-readable code and the HTTP status to surface."""
        self.code = code
        self.status = status
        super().__init__(message)


def _reject(code: str, message: str, status: int = 400) -> DocumentDiffReviewError:
    """Build one boundary rejection."""
    return DocumentDiffReviewError(code, message, status)


def _exact_object(value: Any, allowed: frozenset[str], field: str, *, required: frozenset[str]) -> dict[str, Any]:
    """Require a JSON object whose keys are known and whose required keys exist."""
    if type(value) is not dict:
        raise _reject("invalid_object", f"{field} must be an object")
    unknown = set(value) - allowed
    if unknown:
        raise _reject("unknown_field", f"{field} has unknown fields: {', '.join(sorted(unknown))}")
    missing = required - set(value)
    if missing:
        raise _reject("missing_field", f"{field} is missing: {', '.join(sorted(missing))}")
    return value


def _scan_for_leaks(value: str, field: str) -> None:
    """Reject inline binary/media, credentials, and resident identifiers."""
    if any(signature in value for signature in _BINARY_SIGNATURES) or _DATA_URI.search(value) or _BASE64_RUN.search(value):
        raise _reject("inline_binary_content", f"{field} must not carry inline binary or media data", 422)
    if any(pattern.search(value) for pattern in SECRET_PATTERNS):
        raise _reject("secret_detected", f"{field} matches a credential pattern", 422)
    if _RESIDENT_REGISTRATION_NUMBER.search(value):
        raise _reject("participant_identifier_detected", f"{field} contains a resident registration number", 422)


def _reference(value: Any, field: str, pattern: re.Pattern[str] | None = None) -> str:
    """Validate one bounded single-line reference string."""
    if type(value) is not str or not value or len(value) > MAX_REFERENCE_LENGTH or value != value.strip():
        raise _reject("invalid_reference", f"{field} must be a bounded non-empty string")
    if any(unicodedata.category(character) in {"Cc", "Cs"} for character in value):
        raise _reject("invalid_reference", f"{field} must not contain control characters")
    if pattern is not None and not pattern.fullmatch(value):
        raise _reject("invalid_reference", f"{field} has an invalid format")
    _scan_for_leaks(value, field)
    return value


def _optional_hash(value: Any, field: str) -> str | None:
    """Validate one optional ``sha256:<hex>`` object hash."""
    if value is None:
        return None
    return _reference(value, field, _OBJECT_HASH)


def _optional_text(value: Any, field: str) -> str | None:
    """Validate one optional bounded extracted text."""
    if value is None:
        return None
    if type(value) is not str or len(value.encode("utf-8")) > MAX_OBJECT_TEXT_BYTES:
        raise _reject("invalid_text", f"{field} must be text of at most {MAX_OBJECT_TEXT_BYTES} bytes")
    if any(
        unicodedata.category(character) in {"Cc", "Cs"} and character not in "\n\t"
        for character in value
    ):
        raise _reject("invalid_text", f"{field} must not contain control characters")
    _scan_for_leaks(value, field)
    return value


def _validate_path(value: Any) -> str:
    """Accept only a repository-relative binary document path outside participant data."""
    path = _reference(value, "path")
    parts = PurePosixPath(path).parts
    if path.startswith("/") or ".." in parts or "\\" in path:
        raise _reject("invalid_reference", "path must be repository-relative")
    if PurePosixPath(path).suffix.lower() not in REVIEW_DOCUMENT_SUFFIXES:
        raise _reject("unsupported_document", "path is not a supported binary document type")
    if PARTICIPANT_PATH_SEGMENTS.intersection(part.lower() for part in parts[:-1]):
        raise _reject("participant_material", "path is inside a participant-data directory", 422)
    return path


def _validate_object(value: Any, index: int) -> dict[str, Any]:
    """Validate one diff object and its change/hash consistency."""
    field = f"objects[{index}]"
    item = _exact_object(value, _OBJECT_FIELDS, field, required=_OBJECT_FIELDS)
    page = item["page"]
    if page is not None and (type(page) is not int or page < 1):
        raise _reject("invalid_page", f"{field}.page must be a positive integer or null")
    kind = item["object_kind"]
    if kind not in OBJECT_KINDS:
        raise _reject("invalid_object_kind", f"{field}.object_kind is not supported")
    change = item["change"]
    if change not in CHANGE_KINDS:
        raise _reject("invalid_change", f"{field}.change must be added, removed, modified, or unchanged")
    base_hash = _optional_hash(item["object_hash_base"], f"{field}.object_hash_base")
    head_hash = _optional_hash(item["object_hash_head"], f"{field}.object_hash_head")
    base_text = _optional_text(item["base_text"], f"{field}.base_text")
    head_text = _optional_text(item["head_text"], f"{field}.head_text")
    expected = {
        "added": (False, True),
        "removed": (True, False),
        "modified": (True, True),
        "unchanged": (True, True),
    }[change]
    if (base_hash is not None, head_hash is not None) != expected:
        raise _reject("inconsistent_change", f"{field} hashes do not match change={change}")
    if (base_text is not None and base_hash is None) or (head_text is not None and head_hash is None):
        raise _reject("inconsistent_change", f"{field} text is present without its hash")
    if change == "modified" and base_hash == head_hash:
        raise _reject("inconsistent_change", f"{field} is modified but its hashes are identical")
    if change == "unchanged" and base_hash != head_hash:
        raise _reject("inconsistent_change", f"{field} is unchanged but its hashes differ")
    return {
        "page": page,
        "object_kind": kind,
        "locator": _reference(item["locator"], f"{field}.locator"),
        "change": change,
        "object_hash_base": base_hash,
        "object_hash_head": head_hash,
        "base_text": base_text,
        "head_text": head_text,
    }


def validate_document_diff_envelope(body: Any) -> dict[str, Any]:
    """Return a normalized envelope or raise before any provider can see it."""
    envelope = _exact_object(body, _ENVELOPE_FIELDS, "envelope", required=_REQUIRED_ENVELOPE_FIELDS)
    if envelope["contract_version"] != CONTRACT_VERSION:
        raise _reject("unsupported_contract", f"contract_version must be {CONTRACT_VERSION}")
    # Documents default to zero-data-retention routes; a public repository may opt out.
    zdr_only = envelope.get("zdr_only", True)
    if type(zdr_only) is not bool:
        raise _reject("invalid_zdr_only", "zdr_only must be a boolean")
    if envelope["participant_material"] is not False:
        raise _reject("participant_material", "the extractor must attest participant_material=false", 422)
    base_blob = envelope["base_blob"]
    head_blob = envelope["head_blob"]
    for name, blob in (("base_blob", base_blob), ("head_blob", head_blob)):
        if blob is not None:
            _reference(blob, name, _BLOB)
    if base_blob is None and head_blob is None:
        raise _reject("invalid_reference", "base_blob and head_blob cannot both be null")
    if base_blob == head_blob:
        raise _reject("inconsistent_change", "base_blob and head_blob are identical")
    objects = envelope["objects"]
    if type(objects) is not list or not objects or len(objects) > MAX_DIFF_OBJECTS:
        raise _reject("invalid_objects", f"objects must contain 1 to {MAX_DIFF_OBJECTS} entries")
    normalized = [_validate_object(item, index) for index, item in enumerate(objects)]
    total = sum(
        len(text.encode("utf-8"))
        for item in normalized
        for text in (item["base_text"], item["head_text"])
        if text is not None
    )
    if total > MAX_ENVELOPE_TEXT_BYTES:
        raise _reject("request_too_large", "envelope text exceeds the review budget", 413)
    return {
        "contract_version": CONTRACT_VERSION,
        "repo": _reference(envelope["repo"], "repo", _REPO),
        "path": _validate_path(envelope["path"]),
        "base_blob": base_blob,
        "head_blob": head_blob,
        "extractor_version": _reference(envelope["extractor_version"], "extractor_version"),
        "participant_material": False,
        "zdr_only": zdr_only,
        "objects": normalized,
    }


_NULLABLE_STRING = {"type": ["string", "null"]}
_NULLABLE_INDEX = {"type": ["integer", "null"], "minimum": 0}
DOCUMENT_DIFF_REVIEW_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "document_diff_review_findings",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["findings"],
            "properties": {
                "findings": {
                    "type": "array",
                    "maxItems": MAX_FINDINGS,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": sorted(_FINDING_FIELDS),
                        "properties": {
                            "category": {"type": "string", "enum": sorted(FINDING_CATEGORIES)},
                            "severity": {"type": "string", "enum": sorted(FINDING_SEVERITIES)},
                            "object_index": {"type": "integer", "minimum": 0},
                            "evidence_base": _NULLABLE_STRING,
                            "evidence_head": _NULLABLE_STRING,
                            "related_object_index": _NULLABLE_INDEX,
                            "related_evidence": _NULLABLE_STRING,
                            "explanation": {"type": "string", "maxLength": MAX_EXPLANATION_LENGTH},
                        },
                    },
                }
            },
        },
    },
}

_REVIEW_INSTRUCTIONS = (
    "You review a change to a binary document. You receive only locally extracted "
    "objects (paragraphs, tables, figure hashes with captions, citations, style runs) "
    "for the base and head revisions, indexed by object_index; unchanged objects are "
    "context. Report inconsistencies "
    "the change introduces or leaves: body text versus tables, figures versus captions "
    "or body, citations versus references, numbering, and formatting. Every finding "
    "must name the object_index it concerns. evidence_base and evidence_head must be "
    "exact substrings of that object's base_text and head_text (or null); "
    "related_evidence must be an exact substring of the related object's text. A "
    "figure or page has no pixels here: judge it only from its hashes and text. Do not "
    "invent content, numbers, or citations. Return an empty findings list when the "
    "change is consistent."
)


def document_diff_review_messages(envelope: Mapping[str, Any]) -> list[dict[str, str]]:
    """Build the text-only review conversation for one validated envelope."""
    document = {
        "repo": envelope["repo"],
        "path": envelope["path"],
        "extractor_version": envelope["extractor_version"],
        "objects": [
            {"object_index": index, **item} for index, item in enumerate(envelope["objects"])
        ],
    }
    return [
        {"role": "system", "content": _REVIEW_INSTRUCTIONS},
        {"role": "user", "content": json.dumps(document, ensure_ascii=False, sort_keys=True)},
    ]


def _object_texts(item: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the non-null extracted texts of one object."""
    return tuple(text for text in (item["base_text"], item["head_text"]) if text is not None)


def _quoted(value: Any, sources: tuple[str, ...], field: str) -> str | None:
    """Accept a null or an exact quote from ``sources`` only."""
    if value is None:
        return None
    if type(value) is not str or not value.strip() or not any(value in source for source in sources):
        raise _reject("unsupported_evidence", f"{field} is not quoted from the envelope", 502)
    return value


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build one JSON object while rejecting duplicate member names."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _reject("invalid_structured_output", "model answer repeats a member name", 502)
        result[key] = value
    return result


def validate_document_diff_findings(answer: Any, envelope: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return located findings whose evidence is quoted from the envelope."""
    if type(answer) is not str:
        raise _reject("invalid_structured_output", "model answer is not text", 502)
    try:
        parsed = json.loads(answer, object_pairs_hook=_unique_pairs)
    except json.JSONDecodeError as exc:
        raise _reject("invalid_structured_output", "model answer is not JSON", 502) from exc
    if type(parsed) is not dict or set(parsed) != {"findings"} or type(parsed["findings"]) is not list:
        raise _reject("invalid_structured_output", "model answer must be {findings: [...]}", 502)
    if len(parsed["findings"]) > MAX_FINDINGS:
        raise _reject("invalid_structured_output", "model answer has too many findings", 502)
    objects = envelope["objects"]
    findings = []
    for position, raw in enumerate(parsed["findings"]):
        field = f"findings[{position}]"
        if type(raw) is not dict or set(raw) != _FINDING_FIELDS:
            raise _reject("invalid_structured_output", f"{field} has the wrong fields", 502)
        if raw["category"] not in FINDING_CATEGORIES or raw["severity"] not in FINDING_SEVERITIES:
            raise _reject("invalid_structured_output", f"{field} has an unknown category or severity", 502)
        index = raw["object_index"]
        if type(index) is not int or not 0 <= index < len(objects):
            raise _reject("unsupported_evidence", f"{field}.object_index is not an envelope object", 502)
        item = objects[index]
        evidence_base = _quoted(raw["evidence_base"], (item["base_text"] or "",), f"{field}.evidence_base")
        evidence_head = _quoted(raw["evidence_head"], (item["head_text"] or "",), f"{field}.evidence_head")
        related_index = raw["related_object_index"]
        related_evidence = None
        if related_index is not None:
            if type(related_index) is not int or not 0 <= related_index < len(objects):
                raise _reject("unsupported_evidence", f"{field}.related_object_index is not an envelope object", 502)
            related_evidence = _quoted(
                raw["related_evidence"], _object_texts(objects[related_index]), f"{field}.related_evidence"
            )
        elif raw["related_evidence"] is not None:
            raise _reject("unsupported_evidence", f"{field}.related_evidence needs related_object_index", 502)
        if evidence_base is None and evidence_head is None and related_evidence is None:
            raise _reject("unsupported_evidence", f"{field} quotes no evidence", 502)
        explanation = raw["explanation"]
        if type(explanation) is not str or not explanation.strip() or len(explanation) > MAX_EXPLANATION_LENGTH:
            raise _reject("invalid_structured_output", f"{field}.explanation must be bounded text", 502)
        findings.append(
            {
                "source": "model",
                "category": raw["category"],
                "severity": raw["severity"],
                "page": item["page"],
                "locator": item["locator"],
                "object_kind": item["object_kind"],
                "object_hash_base": item["object_hash_base"],
                "object_hash_head": item["object_hash_head"],
                "evidence_base": evidence_base,
                "evidence_head": evidence_head,
                "related_locator": objects[related_index]["locator"] if related_index is not None else None,
                "related_evidence": related_evidence,
                "explanation": explanation,
            }
        )
    return findings


def rule_findings(envelope: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return findings that follow from the envelope alone, without a model.

    A figure whose image hash changed while its extracted caption stayed
    identical is flagged: the caption may no longer describe the new figure.
    """
    return [
        {
            "source": "rule",
            "category": "figure",
            "severity": "minor",
            "page": item["page"],
            "locator": item["locator"],
            "object_kind": "figure",
            "object_hash_base": item["object_hash_base"],
            "object_hash_head": item["object_hash_head"],
            "evidence_base": item["base_text"],
            "evidence_head": item["head_text"],
            "related_locator": None,
            "related_evidence": None,
            "explanation": "The figure image changed but its caption did not; confirm the caption still describes it.",
        }
        for item in envelope["objects"]
        if item["object_kind"] == "figure"
        and item["change"] == "modified"
        and item["base_text"] is not None
        and item["base_text"] == item["head_text"]
    ]
