"""Binary document diff review over HTTP: envelope in, located findings out.

The fixture starts from two DOCX binaries only. A test-side extractor (the
review leaf owns the production one) turns them into the
``document_diff_review.v1`` envelope. The gateway must reject leaks before any
provider call, keep the original binaries out of the provider payload, and
return findings that are located and quoted from the envelope.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import random
import re
import sys
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.document_diff_review import (  # noqa: E402
    DocumentDiffReviewError,
    _contains_data_uri,
    _scan_for_leaks,
    validate_document_diff_envelope,
    validate_document_diff_findings,
)
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TOKEN = "document_diff_review_test_token"  # noqa: S105
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx(sample_size: str, figure_pixels: bytes) -> bytes:
    """Build one minimal DOCX with a paragraph, a table cell, a caption, and an image."""
    body = (
        f'<w:document xmlns:w="{_W_NS}"><w:body>'
        f"<w:p><w:r><w:t>The sample included {sample_size} participants.</w:t></w:r></w:p>"
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>n = 120</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
        "<w:p><w:r><w:t>Figure 1. Recruitment flow (n = 120)</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", body)
        archive.writestr("word/media/image1.png", b"\x89PNG\r\n\x1a\n" + figure_pixels)
    return buffer.getvalue()


def _objects(raw: bytes) -> dict[str, tuple[str, str | None, str]]:
    """Extract locator -> (kind, text, sha256) from one fixture DOCX."""
    def digest(data: bytes) -> str:
        return "sha256:" + hashlib.sha256(data).hexdigest()

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
        image = archive.read("word/media/image1.png")
    found: dict[str, tuple[str, str | None, str]] = {}
    caption = None
    for index, child in enumerate(root.find(f"{_W}body")):
        text = "".join(node.text or "" for node in child.iter(f"{_W}t"))
        kind = "table" if child.tag == f"{_W}tbl" else "paragraph"
        found[f"body/{kind}[{index}]"] = (kind, text, digest(text.encode()))
        if text.startswith("Figure "):
            caption = text
    found["word/media/image1.png"] = ("figure", caption, digest(image))
    return found


def _envelope(base: bytes, head: bytes) -> dict:
    """Diff two fixture binaries into the v1 envelope, keeping unchanged context."""
    before, after = _objects(base), _objects(head)
    objects = []
    for locator, (kind, head_text, head_hash) in after.items():
        _, base_text, base_hash = before[locator]
        objects.append(
            {
                "page": 1,
                "object_kind": kind,
                "locator": locator,
                "change": "unchanged" if base_hash == head_hash else "modified",
                "object_hash_base": base_hash,
                "object_hash_head": head_hash,
                "base_text": base_text,
                "head_text": head_text,
            }
        )
    return {
        "contract_version": "document_diff_review.v1",
        "repo": "ContextualWisdomLab/example-paper",
        "path": "manuscript/paper.docx",
        "base_blob": hashlib.sha1(b"blob base").hexdigest(),  # noqa: S324
        "head_blob": hashlib.sha1(b"blob head").hexdigest(),  # noqa: S324
        "extractor_version": "test-docx-extractor/1",
        "participant_material": False,
        "objects": objects,
    }


BASE_DOCX = _docx("120", b"old-flow-diagram" * 64)
HEAD_DOCX = _docx("118", b"new-flow-diagram" * 64)
ENVELOPE = _envelope(BASE_DOCX, HEAD_DOCX)


_ZDR_REVIEWER = ModelAgent(
    "free_zdr_reviewer",
    "mock-free-zdr-reviewer",
    base_url="mock://reviewer",
    tags=("review", "cost:free", "privacy:zdr", "response_format", "input:text", "output:text"),
    priority=1,
)
_RETAINING_REVIEWER = ModelAgent(
    "free_retaining_reviewer",
    "mock-free-retaining-reviewer",
    base_url="mock://retaining",
    tags=("review", "cost:free", "response_format", "input:text", "output:text"),
    priority=2,
)


@pytest.fixture()
def gateway(monkeypatch, request):
    """Serve free reviewers (ZDR plus a preferred non-ZDR decoy) and capture provider calls."""
    captured: list[dict] = []
    called: list[str] = []
    answer: dict = {"findings": []}

    def fake_mock_raw(self, agent, endpoint, payload):
        called.append(agent.id)
        captured.append(copy.deepcopy(payload))
        content = json.dumps(answer)
        return {
            "id": "chatcmpl_document_review",
            "object": "chat.completion",
            "created": 0,
            "model": agent.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    monkeypatch.setattr(ModelClient, "_mock_raw", fake_mock_raw)
    agents = getattr(request, "param", [_ZDR_REVIEWER, _RETAINING_REVIEWER])
    server = build_server(TaskOrchestrator(list(agents)), port=0, security=SecurityConfig(auth_token=_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def post(body) -> tuple[int, dict]:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/v1/document_diff_reviews",
            data=json.dumps(body).encode(),
            headers={"content-type": "application/json", "authorization": f"Bearer {_TOKEN}", "connection": "close"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read())

    try:
        post.called = called
        yield post, captured, answer
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_binary_only_docx_pair_yields_located_quoted_findings(gateway) -> None:
    post, captured, answer = gateway
    kinds = [item["object_kind"] for item in ENVELOPE["objects"]]
    body_index, table_index = kinds.index("paragraph"), kinds.index("table")
    answer["findings"] = (
            [
                {
                    "category": "body",
                    "severity": "major",
                    "object_index": body_index,
                    "evidence_base": "120 participants",
                    "evidence_head": "118 participants",
                    "related_object_index": table_index,
                    "related_evidence": "n = 120",
                    "explanation": "The body now reports 118 participants but the table still reports 120.",
                }
            ]
    )

    status, body = post(ENVELOPE)

    assert status == 200, body
    by_source = {finding["source"]: finding for finding in body["findings"]}
    assert by_source["rule"]["locator"] == "word/media/image1.png"
    assert by_source["rule"]["evidence_head"] == "Figure 1. Recruitment flow (n = 120)"
    model = by_source["model"]
    assert (model["page"], model["locator"], model["related_locator"]) == (1, "body/paragraph[0]", "body/table[1]")
    assert (model["evidence_base"], model["evidence_head"], model["related_evidence"]) == (
        "120 participants",
        "118 participants",
        "n = 120",
    )
    assert body["base_blob"] == ENVELOPE["base_blob"] and body["head_blob"] == ENVELOPE["head_blob"]
    sent = json.dumps(captured, ensure_ascii=False).encode()
    for binary in (BASE_DOCX, HEAD_DOCX):
        assert binary not in sent and base64.b64encode(binary) not in sent
    assert b"PK\x03\x04" not in sent and b"flow-diagram" not in sent
    # Every provider call (review and the existing answer-judge verification) is binary-free.
    assert "document_diff_review_findings" in [
        payload["response_format"]["json_schema"]["name"] for payload in captured
    ]
    # Documents default to zero-data-retention routes: the preferred non-ZDR decoy is never called.
    assert set(post.called) == {"free_zdr_reviewer"}


def test_fabricated_evidence_is_rejected(gateway) -> None:
    post, _, answer = gateway
    answer["findings"] = (
            [
                {
                    "category": "citation",
                    "severity": "minor",
                    "object_index": 0,
                    "evidence_base": None,
                    "evidence_head": "Kim et al. (2019)",
                    "related_object_index": None,
                    "related_evidence": None,
                    "explanation": "Citation not in the reference list.",
                }
            ]
    )

    status, body = post(ENVELOPE)

    assert status == 502, body
    assert body["error"]["code"] == "unsupported_evidence"


def _mutated(**changes) -> dict:
    envelope = copy.deepcopy(ENVELOPE)
    for dotted, value in changes.items():
        target = envelope
        *parents, leaf = dotted.split(".")
        for key in parents:
            target = target[int(key)] if key.isdigit() else target[key]
        target[leaf] = value
    return envelope


@pytest.mark.parametrize(
    ("envelope", "status", "code"),
    [
        (_mutated(**{"objects.0.head_text": "data:image/png;base64,iVBORw0KGgo="}), 422, "inline_binary_content"),
        (_mutated(**{"objects.0.head_text": "data:image/png;name=" + "x" * 101 + ";base64,AAAA"}), 422, "inline_binary_content"),
        (_mutated(**{"objects.0.head_text": "DATA:,x"}), 422, "inline_binary_content"),
        (_mutated(**{"objects.0.head_text": base64.b64encode(HEAD_DOCX).decode()[:4000]}), 422, "inline_binary_content"),
        (
            _mutated(**{"objects.0.head_text": base64.urlsafe_b64encode(b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 8).decode()}),
            422,
            "inline_binary_content",
        ),
        (_mutated(**{"objects.0.head_text": "api_key=sk-abcdefghijklmnop123456"}), 422, "secret_detected"),
        (_mutated(**{"objects.0.head_text": "participant 900101-1234567"}), 422, "participant_identifier_detected"),
        (_mutated(path="data/participants/transcript.docx"), 422, "participant_material"),
        (_mutated(participant_material=True), 422, "participant_material"),
        (_mutated(raw_document="UEsDBA=="), 400, "unknown_field"),
        (_mutated(**{"objects.0.object_hash_head": ENVELOPE["objects"][0]["object_hash_base"]}), 400, "inconsistent_change"),
        (_mutated(**{"objects.0.object_kind": []}), 400, "invalid_object_kind"),
        (_mutated(**{"objects.0.change": {}}), 400, "invalid_change"),
        (_mutated(**{"objects.0.head_text": "\ud800"}), 400, "invalid_text"),
        (_mutated(head_blob=ENVELOPE["base_blob"]), 400, "inconsistent_change"),
        (_mutated(path="manuscript/paper.txt"), 400, "unsupported_document"),
        (_mutated(objects=[None]), 400, "invalid_object"),
        (_mutated(objects=[{"page": 1}]), 400, "missing_field"),
        (_mutated(extractor_version=None), 400, "invalid_reference"),
        (_mutated(extractor_version="extractor\nversion"), 400, "invalid_reference"),
        (_mutated(repo="not-a-repository"), 400, "invalid_reference"),
        (_mutated(path="/paper.docx"), 400, "invalid_reference"),
        (_mutated(path="../paper.docx"), 400, "invalid_reference"),
        (_mutated(path="folder\\paper.docx"), 400, "invalid_reference"),
        (_mutated(**{"objects.0.page": True}), 400, "invalid_page"),
        (_mutated(**{"objects.0.head_text": 123}), 400, "invalid_text"),
        (_mutated(**{"objects.0.head_text": "가" * 3000}), 400, "invalid_text"),
        (_mutated(**{"objects.0.object_hash_head": None}), 400, "inconsistent_change"),
        (_mutated(**{"objects.0.change": "added", "objects.0.object_hash_base": None}), 400, "inconsistent_change"),
        (_mutated(**{"objects.0.change": "unchanged"}), 400, "inconsistent_change"),
        (_mutated(base_blob=None, head_blob=None), 400, "invalid_reference"),
        (_mutated(contract_version="document_diff_review.v2"), 400, "unsupported_contract"),
        (_mutated(objects=[]), 400, "invalid_objects"),
        (_mutated(objects=[None] * 201), 400, "invalid_objects"),
        (_mutated(objects=[{**ENVELOPE["objects"][0], "base_text": "word " * 1600,
                           "head_text": "text " * 1600}] * 17), 413, "request_too_large"),
    ],
    ids=[
        "data_uri",
        "long_data_uri_header",
        "uppercase_empty_data_uri",
        "base64_docx",
        "urlsafe_base64_image",
        "secret",
        "resident_number",
        "participant_path",
        "participant_attestation",
        "unknown_field",
        "modified_same_hash",
        "non_string_object_kind",
        "non_string_change",
        "unpaired_surrogate",
        "same_blob",
        "text_file",
        "non_object", "missing_object_fields", "non_string_reference", "reference_control",
        "invalid_repo", "absolute_path", "traversal", "backslash_path", "boolean_page",
        "non_string_text", "utf8_text_budget", "missing_hash", "text_without_hash",
        "unchanged_different_hashes", "both_blobs_null", "unsupported_contract",
        "empty_objects", "object_count_budget", "envelope_text_budget",
    ],
)
def test_leaking_or_malformed_envelopes_fail_closed_before_any_provider_call(gateway, envelope, status, code) -> None:
    post, captured, _ = gateway

    response_status, body = post(envelope)

    assert (response_status, body["error"]["code"]) == (status, code), body
    assert captured == []


def test_figure_finding_without_any_quote_is_rejected(gateway) -> None:
    post, _, answer = gateway
    figure_index = [item["object_kind"] for item in ENVELOPE["objects"]].index("figure")
    answer["findings"] = [
        {
            "category": "figure",
            "severity": "minor",
            "object_index": figure_index,
            "evidence_base": None,
            "evidence_head": None,
            "related_object_index": None,
            "related_evidence": None,
            "explanation": "The figure looks different.",
        }
    ]

    status, body = post(ENVELOPE)

    assert (status, body["error"]["code"]) == (502, "unsupported_evidence"), body


@pytest.mark.parametrize(("field", "value"), [("category", []), ("severity", {})])
def test_non_string_model_finding_fields_are_rejected(field, value) -> None:
    finding = {
        "category": "body",
        "severity": "minor",
        "object_index": 0,
        "evidence_base": None,
        "evidence_head": "118 participants",
        "related_object_index": None,
        "related_evidence": None,
        "explanation": "Sample size changed.",
    }
    finding[field] = value

    with pytest.raises(DocumentDiffReviewError) as error:
        validate_document_diff_findings(json.dumps({"findings": [finding]}), ENVELOPE)

    assert (error.value.status, error.value.code) == (502, "invalid_structured_output")


@pytest.mark.parametrize("gateway", [[_RETAINING_REVIEWER]], indirect=True)
def test_documents_fail_closed_without_a_zero_retention_route(gateway) -> None:
    post, captured, _ = gateway

    status, body = post(ENVELOPE)

    assert status == 400, body
    assert captured == []


@pytest.mark.parametrize("gateway", [[_RETAINING_REVIEWER]], indirect=True)
def test_public_repository_may_opt_out_of_zero_retention(gateway) -> None:
    post, _, _ = gateway

    status, body = post({**ENVELOPE, "zdr_only": False})

    assert status == 200, body
    assert set(post.called) == {"free_retaining_reviewer"}


def test_non_boolean_zdr_only_is_rejected(gateway) -> None:
    post, captured, _ = gateway

    status, body = post({**ENVELOPE, "zdr_only": "yes"})

    assert (status, body["error"]["code"]) == (400, "invalid_zdr_only"), body
    assert captured == []


def test_decoy_is_preferred_once_zero_retention_is_waived(gateway) -> None:
    """Control: the non-ZDR decoy really is the preferred route, so the default test means something."""
    post, _, _ = gateway

    status, body = post({**ENVELOPE, "zdr_only": False})

    assert status == 200, body
    assert "free_retaining_reviewer" in post.called


@pytest.mark.parametrize("answer", [None, "not JSON", '{"findings":[],"findings":[]}',
                                  "[]", '{"findings":{}}',
                                  json.dumps({"findings": [{}] * 101}),
                                  json.dumps({"findings": [None]}),
                                  json.dumps({"findings": [{}]})])
def test_malformed_model_answer_has_no_findings(answer) -> None:
    with pytest.raises(DocumentDiffReviewError) as error:
        validate_document_diff_findings(answer, ENVELOPE)
    assert (error.value.status, error.value.code) == (502, "invalid_structured_output")


@pytest.mark.parametrize(("changes", "code"), [
    ({"category": "unknown"}, "invalid_structured_output"),
    ({"severity": "unknown"}, "invalid_structured_output"),
    ({"object_index": True}, "unsupported_evidence"),
    ({"object_index": 100}, "unsupported_evidence"),
    ({"related_object_index": True}, "unsupported_evidence"),
    ({"related_object_index": 100}, "unsupported_evidence"),
    ({"related_evidence": "n = 120"}, "unsupported_evidence"),
    ({"evidence_head": 118}, "unsupported_evidence"),
    ({"evidence_head": " "}, "unsupported_evidence"),
    ({"explanation": None}, "invalid_structured_output"),
    ({"explanation": " "}, "invalid_structured_output"),
    ({"explanation": "x" * 2001}, "invalid_structured_output"),
])
def test_invalid_finding_is_rejected_without_partial_results(changes, code) -> None:
    finding = {
        "category": "body", "severity": "minor", "object_index": 0,
        "evidence_base": None, "evidence_head": "118 participants",
        "related_object_index": None, "related_evidence": None,
        "explanation": "Sample size changed.",
    }
    invalid = {**finding, **changes}
    with pytest.raises(DocumentDiffReviewError) as error:
        validate_document_diff_findings(json.dumps({"findings": [finding, invalid]}), ENVELOPE)
    assert (error.value.status, error.value.code) == (502, code)


def test_added_and_removed_objects_keep_null_sides(gateway) -> None:
    post, _, _ = gateway
    envelope = _mutated(base_blob=None)
    envelope["objects"] = [
        {**ENVELOPE["objects"][0], "change": "added", "page": None,
         "object_hash_base": None, "base_text": None},
        {**ENVELOPE["objects"][0], "change": "removed",
         "object_hash_head": None, "head_text": None},
    ]
    status, body = post(envelope)
    assert status == 200, body
    assert body["base_blob"] is None
    assert body["findings"] == []


def test_total_extracted_text_budget_rejects_individually_bounded_objects() -> None:
    """The envelope validator enforces its own budget independently of HTTP size."""
    envelope = _mutated(objects=[
        {**ENVELOPE["objects"][0], "base_text": "word " * 1600, "head_text": "text " * 1600}
    ] * 17)
    with pytest.raises(DocumentDiffReviewError) as error:
        validate_document_diff_envelope(envelope)
    assert (error.value.status, error.value.code) == (413, "request_too_large")
    assert "envelope text" in str(error.value)


def test_data_uri_scan_handles_repeated_scheme_without_comma() -> None:
    """A repeated scheme without a comma is not inline media."""
    pathological = "data:" * 20_000
    assert not _contains_data_uri(pathological)
    _scan_for_leaks(pathological, "objects[0].head_text")


@pytest.mark.parametrize(
    "value",
    [
        "data:image/png;base64,iVBORw0KGgo=",
        "DATA:,x",
        "Data:text/plain;charset=utf-8,hello",
        "see data:,x inline",
        "data:" + "a;" * 128 + ",AAAA",
        "data:" + "a;" * 150 + ",AAAA",
    ],
    ids=[
        "png_base64",
        "uppercase_empty",
        "mixed_case_charset",
        "embedded",
        "header_at_256_bound",
        "header_over_256_bound",
    ],
)
def test_data_uri_is_rejected_as_inline_binary(value) -> None:
    with pytest.raises(DocumentDiffReviewError) as error:
        _scan_for_leaks(value, "objects[0].head_text")
    assert (error.value.status, error.value.code) == (422, "inline_binary_content")


@pytest.mark.parametrize(
    "value",
    [
        "data:" + "a;" * 150,
        "data: image/png, not a uri",
        "the data, as reported",
    ],
    ids=["long_header_without_comma", "whitespace_in_header", "no_scheme"],
)
def test_non_data_uri_text_is_not_flagged(value) -> None:
    """Whitespace or an absent comma prevents a data-URI match."""
    assert not _contains_data_uri(value)
    _scan_for_leaks(value, "objects[0].head_text")


def test_data_uri_scanner_matches_the_contract_on_varied_short_text() -> None:
    """The linear scanner preserves the original data-URI language."""
    unbounded = re.compile(r"data:[^,\s]*,", re.IGNORECASE)
    rng = random.Random(1262)
    alphabet = ["data:", "DATA:", "Data:", ",", ";", "/", " ", "\n", "a", "b64", "="]
    for _ in range(3000):
        value = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        assert _contains_data_uri(value) == bool(unbounded.search(value)), value
