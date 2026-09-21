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
        (_mutated(**{"objects.0.head_text": base64.b64encode(HEAD_DOCX).decode()[:4000]}), 422, "inline_binary_content"),
        (_mutated(**{"objects.0.head_text": "api_key=sk-abcdefghijklmnop123456"}), 422, "secret_detected"),
        (_mutated(**{"objects.0.head_text": "participant 900101-1234567"}), 422, "participant_identifier_detected"),
        (_mutated(path="data/participants/transcript.docx"), 422, "participant_material"),
        (_mutated(participant_material=True), 422, "participant_material"),
        (_mutated(raw_document="UEsDBA=="), 400, "unknown_field"),
        (_mutated(**{"objects.0.object_hash_head": ENVELOPE["objects"][0]["object_hash_base"]}), 400, "inconsistent_change"),
        (_mutated(head_blob=ENVELOPE["base_blob"]), 400, "inconsistent_change"),
        (_mutated(path="manuscript/paper.txt"), 400, "unsupported_document"),
    ],
    ids=[
        "data_uri",
        "base64_docx",
        "secret",
        "resident_number",
        "participant_path",
        "participant_attestation",
        "unknown_field",
        "modified_same_hash",
        "same_blob",
        "text_file",
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
